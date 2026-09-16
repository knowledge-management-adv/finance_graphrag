from __future__ import annotations
from pathlib import Path
from .common import *
from .benchmark import read_questions
from .retrieve import Retriever
from .llm import validated_generations

def parse_answer_json(text):
 """Read the last complete answer object; retain the unmodified model response in cache."""
 decoder=json.JSONDecoder();offset=0;candidates=[]
 while offset<len(text):
  start=text.find('{',offset)
  if start<0:break
  try:obj,end=decoder.raw_decode(text,start)
  except ValueError:offset=start+1;continue
  if isinstance(obj,dict) and isinstance(obj.get('answer'),str) and isinstance(obj.get('citations'),list):candidates.append(obj)
  offset=end
 if not candidates:return parse_json(text)
 return candidates[-1]

def freeze(cfg):
 out=Path(cfg['artifact_dir']);graph=out/'graph.sqlite'
 if not graph.exists():raise ValueError('Build graph first')
 paths=sorted(list((ROOT/'finance_graph').glob('*.py'))+list((ROOT/'prompts').glob('*.txt'))+[ROOT/'config.json',ROOT/'docs/ontology.md'])
 record={'created_at':now(),'files':{str(p.relative_to(ROOT)):digest(p.read_text()) for p in paths},'configuration':cfg,'graph_sha256':__import__('hashlib').sha256(graph.read_bytes()).hexdigest(),'dataset_hash':load_json(out/'corpus/manifest.json')['dataset_hash'],'questions_hash':load_json(out/'questions/manifest.json')['question_hash'],'policy':'Ground-truth answers, rationales, evidence, and benchmark product/source metadata are excluded from extraction, retrieval, and generation.'}
 existing=out/'run_freeze.json'
 if existing.exists():
  old=load_json(existing)
  if old['graph_sha256']!=record['graph_sha256'] or old['files']!=record['files'] or old['questions_hash']!=record['questions_hash'] or old['configuration']!=record['configuration']:raise ValueError('Frozen V1 changed. Use a new artifact_dir for a different system version.')
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
  if insufficient is not None and type(insufficient) is not bool:raise ValueError('insufficient_evidence must be boolean if reported')
  citations=[c.strip().removeprefix('[').removesuffix(']').strip() for c in citations]
  allowed=set(traces[qid]['citation_map'])
  if any(c not in allowed for c in citations):raise ValueError('Only cite IDs that were provided in the context')
  if not citations and not insufficient:raise ValueError('Provide at least one supporting citation or explicitly mark insufficient_evidence')
  return {'answer':obj['answer'],'citations':list(dict.fromkeys(traces[qid]['citation_map'][c] for c in citations)),'insufficient_evidence':insufficient}
 good,errors=validated_generations(llm,'qa',requests,cfg['qa_max_tokens'],validate,parser=parse_answer_json)
 answers=[]
 for q in questions:
  rec=good.get(q['id']);value=rec['value'] if rec else {'answer':'','citations':[],'insufficient_evidence':True}
  answers.append({**q,**value,'generation_error':errors.get(q['id']),'request_hash':rec['request_hash'] if rec else None,'graph_fact_count':len(traces[q['id']]['fact_ids']),'source_chunk_count':len(traces[q['id']]['chunk_ids'])})
 write_jsonl(out/'qa/answers.jsonl',answers);write_json(out/'qa/manifest.json',{'count':len(answers),'errors':errors,'answers_hash':digest(answers),'created_at':now(),'partial_run':bool(limit)})
 retriever.g.close();print('QA_SUMMARY '+json.dumps({'count':len(answers),'errors':errors},ensure_ascii=False),flush=True);return answers

def answer_one(cfg,llm,question):
 ret=Retriever(cfg);trace=ret.retrieve(question);prompt=(ROOT/'prompts/answer.txt').read_text()+'\n\n질문:\n'+question+'\n\n'+trace['context']
 def validate(_,obj):
  if not isinstance(obj.get('answer'),str) or not obj['answer'].strip():raise ValueError('A nonempty answer is required')
  if obj.get('insufficient_evidence') is not None and type(obj['insufficient_evidence']) is not bool:raise ValueError('insufficient_evidence must be boolean if reported')
  citations=obj.get('citations');allowed=set(trace['citation_map'])
  if isinstance(citations,list) and all(isinstance(c,str) for c in citations):citations=[c.strip().removeprefix('[').removesuffix(']').strip() for c in citations]
  if not isinstance(citations,list) or any(c not in allowed for c in citations):raise ValueError('Cite only provided evidence IDs')
  if not citations and not obj.get('insufficient_evidence'):raise ValueError('Cite supporting evidence or mark insufficiency')
  obj['citations']=[trace['citation_map'][c] for c in citations]
  obj.setdefault('insufficient_evidence',None)
  return obj
 good,errors=validated_generations(llm,'interactive',[('interactive',prompt)],cfg['qa_max_tokens'],validate,parser=parse_answer_json)
 ret.g.close()
 if errors:raise ValueError(errors)
 rec=good['interactive'];return {'response':rec['value'],'trace':trace,'request_hash':rec['request_hash']}
