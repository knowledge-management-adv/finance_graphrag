"""Post-evaluation reporting only. Does not call an LLM or modify graph/answers/judgments."""
from pathlib import Path
import sys,re,html,json,collections,hashlib
from finance_graph.common import ROOT,config,load_json,read_jsonl,write_json,write_jsonl,key,digest,now
from finance_graph.graph import Graph

def plain(s):
 return html.unescape(re.sub(r'</?[A-Za-z][^>]*>',' ',s))
def quote_text(value):
 if isinstance(value,str):return value
 if isinstance(value,list):return '\n'.join(quote_text(v) for v in value)
 if isinstance(value,dict):
  if 'quote' in value:return quote_text(value['quote'])
  if 'text' in value:return quote_text(value['text'])
  return ''
 return ''
def grams(text):
 s=key(plain(text));return {s[i:i+2] for i in range(len(s)-1)}
def main():
 cfg=config(sys.argv[1] if len(sys.argv)>1 else None);out=Path(cfg['artifact_dir']);report=out/'reports/evaluation_report.md'
 if not report.exists():raise SystemExit('Complete the benchmark evaluation/report first.')
 frozen_files=[out/'graph.sqlite',out/'qa/answers.jsonl',out/'evaluation/results.jsonl'];before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen_files}
 summary=load_json(out/'evaluation/summary.json');results=read_jsonl(out/'evaluation/results.jsonl');gold={q['id']:q for q in load_json(cfg['benchmark_path'])};metrics=read_jsonl(out/'evaluation/retrieval_metrics.jsonl');byid={m['id']:m for m in metrics};g=Graph(out/'graph.sqlite');rows=[]
 for r in results:
  trace=load_json(out/'retrieval'/f'{r["id"]}.json');docids=byid[r['id']]['gold_document_ids'];refs=[grams(quote_text(s.get('evidence',''))) for s in gold[r['id']]['sources']];refs=[x for x in refs if x]
  texts={'context':trace['context'],'source_chunks':'\n'.join(g.props(c)['text'] for c in trace['chunk_ids']),'retrieved_fact_nodes':'\n'.join(g.props(f)['statement'] for f in trace['fact_ids']),'all_annotated_document_fact_nodes':'\n'.join(f['properties']['statement'] for f in g.facts() if f['properties']['document_id'] in docids)}
  coverage={name:sum(len(ref&grams(text))/len(ref) for ref in refs)/len(refs) if refs else None for name,text in texts.items()};rows.append({'id':r['id'],'correct':r['correct'],'quote_only_plain_text_bigram_coverage':coverage})
 write_jsonl(out/'evaluation/normalized_evidence_metrics.jsonl',rows)
 means={name:sum(r['quote_only_plain_text_bigram_coverage'][name] for r in rows)/len(rows) for name in texts}
 statements=collections.Counter(digest(f['properties']['statement']) for f in g.facts());duplicates=sum(v-1 for v in statements.values());review=load_json(ROOT/'docs/manual_error_review.json') if summary['answers_hash']=='28b622482458e3a9cee55bd0ab9dd4c9358e2d3f453fb9684c89fd2d85adc6be' else [];manual=[]
 for case in review:
  trace=load_json(out/'retrieval'/f'{case["id"]}.json');normalized=key(trace['context']);checks={term:key(term) in normalized for term in case['evidence_terms']};manual.append({**case,'literal_context_checks':checks})
 write_jsonl(out/'evaluation/manual_error_review.jsonl',manual)
 qavalid=load_json(out/'qa/validation.json') if (out/'qa/validation.json').exists() else None
 generation_records={}
 for stage in ('extraction','extraction_fallback','qa','evaluation','diagnosis'):
  records=[load_json(p) for p in (out/'llm'/stage).glob('*.json')];batches={digest(r['batch_stats']):r['batch_stats'] for r in records};generation_records[stage]={'stored_calls_including_pilots_and_repairs':len(records),'output_tokens':sum(r['generated_tokens'] for r in records),'unique_batch_compute_seconds':sum(v['prompt_time']+v['generation_time'] for v in batches.values()),'peak_memory_gb':max([v['peak_memory'] for v in batches.values()],default=0)}
 write_json(out/'evaluation/operational_audit.json',{'created_at':now(),'normalized_evidence_coverage':means,'identical_statement_occurrences_beyond_first':duplicates,'qa_validation':qavalid,'generation_records':generation_records,'notes':'Batch compute sums exclude interrupted/unsaved batches, orchestration, and most model-loading time; they are not wall-clock elapsed time. Stored call counts include pilots and repair attempts.'})
 lines=['# Post-evaluation audit','', f'This audit reads frozen predictions and judgments. It does not change the {summary["correct"]}/{summary["total"]} ({100*summary["accuracy"]:.1f}%) binary result and performs no new model generation.','', '## Evidence metric interpretation','', 'The baseline diagnostic serialized structured evidence annotations (including quote dictionaries, line metadata, and HTML). Its original bigram coverage values are retained for transparency. The supplemental metric below extracts only `quote` text, removes HTML tags, and measures character-bigram coverage in the actual context and stored graph text. This remains a lexical proxy, not semantic entailment or a grading rule. An annotated quote may cover a whole table with more information than the question requires.','', '| Context source | Quote-only plain-text bigram coverage |','|---|---:|']
 for name,v in means.items():lines.append(f'| {name} | {100*v:.1f}% |')
 lines += ['', f'There are {duplicates} stored fact occurrences beyond the first occurrence of an identical full statement. Different labels can legitimately share evidence, but repeating that evidence in the answer context is a V2 efficiency and reasoning concern.','', f'## Preserved V1 manual review ({len(manual)} matching cases)','', 'The local model diagnoses are preserved separately. The review below checks concrete examples against the delivered context; it does not constitute a causal ablation or a human-certified benchmark regrade.','']
 for c in manual:
  lines += [f'### {c["id"]}: {c["subtype"]}','',c['finding'],'', 'Literal context checks: '+json.dumps(c['literal_context_checks'],ensure_ascii=False)+'.','']
 lines += ['## Implications for V2','', 'Prioritize evidence-linked calculators, explicit temporal/conditional scope, and special-term exception handling. Then reduce repeated context. Add an independent judge or human-adjudicated sample before claiming a reliable deployment accuracy.','', '[Bounded V2 proposal](../../../docs/v2_proposal.md) · [Execution and parser amendment record](../../../docs/v1_implementation_notes.md)','', 'In the original V1 run, the same-model diagnostic for QA036 contains a partially mistaken explanation of the referral-rate components. The source gives 0.5 percentage point for entering another referral number and 1.0 for two others entering the account’s number. The question excludes the former. This illustrates why generated diagnostic prose also needs evidence review.','']
 (out/'reports/post_evaluation_audit.md').write_text('\n'.join(lines),encoding='utf-8')
 marker='\n## Post-evaluation audit and execution notes\n'
 body=report.read_text();body=body.split(marker)[0]
 freeze_note='Two pre-evaluation response-parser amendments are recorded in the execution notes; they preserved the graph, retrieval, model prompts, and raw generations. No answer or grade was edited by Codex.'
 if freeze_note not in body:body=body.replace('## Benchmark isolation and methodology\n','## Benchmark isolation and methodology\n\n'+freeze_note+'\n')
 metric_note=f'The four original bigram values below include serialized annotation metadata/HTML. For quote-only plain-text metrics, see the [post-evaluation audit](post_evaluation_audit.md): final-context coverage is {100*means["context"]:.1f}%. Neither metric changes the binary score.'
 if metric_note not in body:body=body.replace('## Retrieval diagnostics\n','## Retrieval diagnostics\n\n'+metric_note+'\n')
 extra_title='### Additional source-reviewed failures'
 if manual and extra_title not in body:
  lookup={r['id']:r for r in results};extra=[extra_title,'']
  for case in manual:
   if case['id'] in ('QA048','QA073','QA112'):
    r=lookup[case['id']];extra += [f'- [{case["id"]}](questions/{case["id"]}.md): '+case['finding'],'']
  body=body.replace('## Proposed V2 — bounded follow-up','\n'.join(extra)+'\n## Proposed V2 — bounded follow-up')
 body+=marker+'\nRead the [post-evaluation audit](post_evaluation_audit.md) for quote-only evidence metrics, the preserved V1 manual review, and a correction to one local diagnostic explanation. The original score is unchanged. The [execution notes](../../../docs/v1_implementation_notes.md) document the two pre-evaluation parser amendments, and the [V2 proposal](../../../docs/v2_proposal.md) gives a bounded improvement plan.\n';report.write_text(body,encoding='utf-8')
 after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen_files};assert before==after;write_json(out/'evaluation/post_audit_integrity.json',{'created_at':now(),'core_artifacts_unchanged':True,'sha256':after});g.close();print(json.dumps({'report':str(report),'normalized_coverage':means,'unchanged_score':summary['accuracy'],'identical_statement_duplicates':duplicates},ensure_ascii=False))
if __name__=='__main__':main()
