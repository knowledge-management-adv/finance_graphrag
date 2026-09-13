from __future__ import annotations
from pathlib import Path
from .common import *
from .benchmark import read_questions
from .retrieve import Retriever
from .llm import validated_generations

def freeze(cfg):
 out=Path(cfg['artifact_dir']);graph=out/'graph.sqlite'
 if not graph.exists():raise ValueError('Build graph first')
 paths=sorted(list((ROOT/'finance_graph').glob('*.py'))+list((ROOT/'prompts').glob('*.txt'))+[ROOT/'config.json',ROOT/'docs/ontology.md'])
 record={'created_at':now(),'files':{str(p.relative_to(ROOT)):digest(p.read_text()) for p in paths},'configuration':cfg,'graph_sha256':__import__('hashlib').sha256(graph.read_bytes()).hexdigest(),'dataset_hash':load_json(out/'corpus/manifest.json')['dataset_hash'],'questions_hash':load_json(out/'questions/manifest.json')['question_hash'],'policy':'Ground-truth answers, rationales, evidence, and benchmark product/source metadata are excluded from extraction, retrieval, and generation.'}
 existing=out/'run_freeze.json'
 if existing.exists():
  old=load_json(existing)
  if old['graph_sha256']!=record['graph_sha256'] or old['files']!=record['files'] or old['questions_hash']!=record['questions_hash']:raise ValueError('Frozen V1 changed. Use a new artifact_dir for a different system version.')
 else:write_json(existing,record)
 return record

def answer_questions(cfg,llm,limit=None):
 freeze(cfg);questions=read_questions(cfg)
 if limit:questions=questions[:limit]
 out=Path(cfg['artifact_dir']);retriever=Retriever(cfg);instruction=(ROOT/'prompts/answer.txt').read_text();traces={};requests=[]
 for row in questions:
  trace=retriever.retrieve(row['question']);traces[row['id']]=trace;write_json(out/'retrieval'/f'{row["id"]}.json',trace)
  requests.append((row['id'],instruction+'\n\n질문:\n'+row['question']+'\n\n'+trace['context']))
 def validate(qid,obj):
  if not isinstance(obj.get('answer'),str) or not obj['answer'].strip():raise ValueError('answer must be a nonempty Korean string')
  citations=obj.get('citations');insufficient=obj.get('insufficient_evidence')
  if not isinstance(citations,list) or any(not isinstance(c,str) for c in citations):raise ValueError('citations must be a list of evidence IDs')
  if type(insufficient) is not bool:raise ValueError('insufficient_evidence must be boolean')
  allowed={'C:'+i for i in traces[qid]['chunk_ids']}|{'F:'+i for i in traces[qid]['fact_ids']}
  if any(c not in allowed for c in citations):raise ValueError('Only cite IDs that were provided in the context')
  if not citations and not insufficient:raise ValueError('Provide at least one supporting citation or explicitly mark insufficient_evidence')
  return {'answer':obj['answer'],'citations':list(dict.fromkeys(citations)),'insufficient_evidence':insufficient}
 good,errors=validated_generations(llm,'qa',requests,cfg['qa_max_tokens'],validate)
 answers=[]
 for q in questions:
  rec=good.get(q['id']);value=rec['value'] if rec else {'answer':'','citations':[],'insufficient_evidence':True}
  answers.append({**q,**value,'generation_error':errors.get(q['id']),'request_hash':rec['request_hash'] if rec else None,'graph_fact_count':len(traces[q['id']]['fact_ids']),'source_chunk_count':len(traces[q['id']]['chunk_ids'])})
 write_jsonl(out/'qa/answers.jsonl',answers);write_json(out/'qa/manifest.json',{'count':len(answers),'errors':errors,'answers_hash':digest(answers),'created_at':now(),'partial_run':bool(limit)})
 retriever.g.close();print('QA_SUMMARY '+json.dumps({'count':len(answers),'errors':errors},ensure_ascii=False),flush=True);return answers

def answer_one(cfg,llm,question):
 ret=Retriever(cfg);trace=ret.retrieve(question);prompt=(ROOT/'prompts/answer.txt').read_text()+'\n\n질문:\n'+question+'\n\n'+trace['context']
 rec=llm.generate_many('interactive',[('interactive',prompt)],cfg['qa_max_tokens'])['interactive'];obj=parse_json(rec['raw_text']);ret.g.close();return {'response':obj,'trace':trace,'request_hash':rec['request_hash']}
