"""Gold access is restricted to this post-generation evaluation module."""
from __future__ import annotations
import math,collections,re
from pathlib import Path
from .common import *
from .graph import Graph
from .llm import validated_generations
CATEGORIES={'ontology_design','information_extraction','graph_construction','retrieval','source_document_retrieval','answer_generation','evaluation_issue','unknown'}

def evaluate(cfg,llm):
 out=Path(cfg['artifact_dir']);am=load_json(out/'qa/manifest.json')
 if am['partial_run']:raise ValueError('Cannot evaluate a partial run as the full benchmark')
 answers=read_jsonl(out/'qa/answers.jsonl')
 if digest(answers)!=am['answers_hash']:raise ValueError('Frozen answers have changed')
 question_manifest=load_json(out/'questions/manifest.json')
 if digest(Path(cfg['benchmark_path']).read_text())!=question_manifest['source_file_sha256']:raise ValueError('Benchmark file changed after question projection')
 gold=load_json(cfg['benchmark_path']);byid={q['id']:q for q in gold};answer_ids={a['id'] for a in answers}
 if answer_ids!=set(byid) or len(answers)!=len(gold):raise ValueError('Answer and benchmark IDs must match exactly')
 instruction=(ROOT/'prompts/evaluate.txt').read_text();requests=[]
 for a in answers:
  q=byid[a['id']]
  if a['question']!=q['question']:raise ValueError('Question mismatch')
  payload={'question':q['question'],'ground_truth_answer':q['answer'],'answer_aliases':q.get('answer_aliases',[]),'ground_truth_rationale':q['rationale'],'model_answer':a['answer']}
  requests.append((a['id'],instruction+'\n\n'+json.dumps(payload,ensure_ascii=False)))
 def validate(qid,obj):
  if type(obj.get('correct')) is not bool or not isinstance(obj.get('reason'),str):raise ValueError('Evaluator must return binary correct and textual reason')
  return {'correct':obj['correct'],'reason':obj['reason']}
 good,errors=validated_generations(llm,'evaluation',requests,cfg['evaluation_max_tokens'],validate)
 if errors:
  write_json(out/'evaluation/errors.json',errors);raise RuntimeError('Evaluator did not return all binary judgments; no accuracy is published')
 results=[]
 for a in answers:
  q=byid[a['id']];rec=good[a['id']]
  results.append({**a,'ground_truth_answer':q['answer'],'ground_truth_rationale':q['rationale'],'qa_type':q.get('qa_type'),'difficulty':q.get('difficulty'),'reasoning_type':q.get('reasoning_type'),**rec['value'],'evaluation_request_hash':rec['request_hash']})
 correct=sum(r['correct'] for r in results);n=len(results);p=correct/n;z=1.96;denom=1+z*z/n;center=(p+z*z/(2*n))/denom;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denom
 groups={}
 for field in ('qa_type','difficulty','reasoning_type'):
  items=collections.defaultdict(list)
  for r in results:items[str(r[field])].append(r['correct'])
  groups[field]={k:{'correct':sum(v),'total':len(v),'accuracy':sum(v)/len(v)} for k,v in sorted(items.items())}
 summary={'created_at':now(),'total':n,'correct':correct,'incorrect':n-correct,'accuracy':p,'wilson_95_interval':[center-half,center+half],'by_group':groups,'judge_backend':cfg['backend'],'judge_model':cfg['model_id'],'same_model_as_answerer':True,'answers_hash':am['answers_hash'],'all_judgments_binary':True}
 write_jsonl(out/'evaluation/results.jsonl',results);write_json(out/'evaluation/summary.json',summary);print('EVALUATION_SUMMARY '+json.dumps(summary,ensure_ascii=False),flush=True);return results

def evidence_metrics(cfg):
 out=Path(cfg['artifact_dir']);g=Graph(out/'graph.sqlite');gold={q['id']:q for q in load_json(cfg['benchmark_path'])};results=read_jsonl(out/'evaluation/results.jsonl');bysha={n['properties']['sha256']:n['id'] for n in g.typed('Document')};bypath={n['properties']['path']:n['properties']['document_id'] for n in g.typed('Source')};byrel={n['properties']['relative_path']:n['properties']['document_id'] for n in g.typed('Source')};metrics=[]
 for result in results:
  q=gold[result['id']];trace=load_json(out/'retrieval'/f'{q["id"]}.json');docs=set();evidences=[];unresolved=[]
  for source in q.get('sources',[]):
   did=bysha.get(source.get('sha256')) or bypath.get(source.get('document_path')) or byrel.get(source.get('relative_path'))
   if not did:
    rel=source.get('relative_path','');did=next((v for k,v in byrel.items() if rel.endswith(k)),None)
   if did:docs.add(did)
   else:unresolved.append({k:source.get(k) for k in ('document_path','relative_path','sha256')})
   evidence=source.get('evidence','')
   if isinstance(evidence,list):evidence='\n'.join(map(str,evidence))
   if isinstance(evidence,dict):evidence=json.dumps(evidence,ensure_ascii=False)
   evidences.append({'document_id':did,'evidence':str(evidence)})
  relevant_facts=[f for f in g.facts() if f['properties']['document_id'] in docs]
  extracted_units={uid for f in relevant_facts for uid in f['properties']['unit_ids']}
  source_text='\n'.join(g.props(c)['text'] for c in trace['chunk_ids']);fact_text='\n'.join(g.props(f)['statement'] for f in trace['fact_ids']);all_fact_text='\n'.join(f['properties']['statement'] for f in relevant_facts)
  # Character-bigram overlap is a diagnostic proxy, not semantic recall or a grading signal.
  def grams(s):
   s=key(s);return {s[i:i+2] for i in range(len(s)-1)}
  def coverage(text):
   t=grams(text);vals=[]
   for ev in evidences:
    e=grams(ev['evidence']);vals.append(len(e&t)/len(e) if e else None)
   vals=[v for v in vals if v is not None];return sum(vals)/len(vals) if vals else None
  found=docs&set(trace['document_ids']);item={'id':q['id'],'correct':result['correct'],'gold_document_ids':sorted(docs),'retrieved_gold_document_ids':sorted(found),'gold_document_recall':len(found)/len(docs) if docs else None,'all_gold_documents_retrieved':docs.issubset(set(trace['document_ids'])) if docs else None,'unresolved_gold_sources':unresolved,'evidence_bigram_coverage_in_context':coverage(trace['context']),'evidence_bigram_coverage_in_source_chunks':coverage(source_text),'evidence_bigram_coverage_in_retrieved_facts':coverage(fact_text),'evidence_bigram_coverage_in_all_gold_document_facts':coverage(all_fact_text),'gold_document_fact_count':len(relevant_facts),'evidences':evidences}
  metrics.append(item)
 write_jsonl(out/'evaluation/retrieval_metrics.jsonl',metrics);g.close();return metrics

def diagnose(cfg,llm):
 out=Path(cfg['artifact_dir']);metrics={m['id']:m for m in evidence_metrics(cfg)};results=read_jsonl(out/'evaluation/results.jsonl');g=Graph(out/'graph.sqlite');instruction=(ROOT/'prompts/diagnose.txt').read_text();requests=[]
 for r in results:
  if r['correct']:continue
  trace=load_json(out/'retrieval'/f'{r["id"]}.json');m=metrics[r['id']]
  # Rank evidence-related facts only for post-hoc diagnosis, never for answer generation.
  ev_key=key(' '.join(e['evidence'] for e in m['evidences']))
  def similarity(f):
   k=key(f['properties']['statement']);a={k[i:i+3] for i in range(len(k)-2)};return sum(x in ev_key for x in a)
  facts=sorted([f for f in g.facts() if f['properties']['document_id'] in m['gold_document_ids']],key=similarity,reverse=True)[:10]
  fact_summary=[{'id':f['id'],'type':f['type'],'name':f['name'],'statement':f['properties']['statement'][:2200],'retrieved':f['id'] in trace['fact_ids']} for f in facts]
  payload={'question':r['question'],'ground_truth_answer':r['ground_truth_answer'],'rationale':r['ground_truth_rationale'],'model_answer':r['answer'],'judge_reason':r['reason'],'retrieval_metrics':m,'graph_validation':load_json(out/'graph_validation.json'),'related_facts_in_persisted_graph':fact_summary,'retrieved_context':trace['context']}
  requests.append((r['id'],instruction+'\n\n'+json.dumps(payload,ensure_ascii=False)))
 def validate(qid,obj):
  if obj.get('primary_category') not in CATEGORIES or obj.get('confidence') not in ('high','medium','low') or not isinstance(obj.get('reason'),str):raise ValueError('Invalid diagnostic category/confidence/reason')
  obj['secondary_categories']=[c for c in obj.get('secondary_categories',[]) if c in CATEGORIES];return obj
 good,errors=validated_generations(llm,'diagnosis',requests,1100,validate)
 rows=[]
 for rid,_ in requests:
  rec=good.get(rid);rows.append({'id':rid,**(rec['value'] if rec else {'primary_category':'unknown','confidence':'low','reason':'Diagnosis generation failed: '+errors[rid],'secondary_categories':[]}), 'diagnosis_request_hash':rec['request_hash'] if rec else None})
 write_jsonl(out/'evaluation/error_analysis.jsonl',rows);write_json(out/'evaluation/error_categories.json',dict(collections.Counter(r['primary_category'] for r in rows)));g.close();print('DIAGNOSIS_SUMMARY '+json.dumps(dict(collections.Counter(r['primary_category'] for r in rows))),flush=True);return rows
