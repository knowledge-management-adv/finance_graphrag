from __future__ import annotations
import argparse,json
from pathlib import Path
from .common import config,ROOT,load_json,digest
from .llm import create_llm

def main():
 p=argparse.ArgumentParser(description='Korean finance GraphRAG pipeline (local MLX or Upstage API)');p.add_argument('--config',default=str(ROOT/'config.json'));p.add_argument('--backend',choices=['local_mlx','upstage']);p.add_argument('--artifact-dir');sub=p.add_subparsers(dest='command',required=True)
 for name in ('ingest','extract','build-graph','questions','freeze','qa','evaluate','diagnose','report','validate','all'):sub.add_parser(name)
 sub.add_parser('llm-test')
 ask=sub.add_parser('ask');ask.add_argument('question');ret=sub.add_parser('retrieve');ret.add_argument('question')
 a=p.parse_args();c=config(a.config,backend=a.backend,artifact_dir=a.artifact_dir);llm=create_llm(c);out=Path(c['artifact_dir'])
 if a.command=='llm-test':
  prompt='An $80 item gets a 20% discount, then 10% tax is added. What is the final price? Answer with only the dollar amount.'
  kwargs={'use_cache':False} if c['backend']=='upstage' else {}
  try:
   rec=llm.generate_many('smoke_test',[('smoke_test',prompt)],4096,**kwargs)['smoke_test']
   print(json.dumps({'backend':c['backend'],'model':c['model_id'],'answer':rec['raw_text'],'possibly_truncated':rec['possibly_truncated']},ensure_ascii=False,indent=2))
   if rec['possibly_truncated'] or not rec['raw_text'].strip():raise RuntimeError('Smoke test did not return a complete answer')
  finally:llm.unload()
  return
 from .ingest import ingest
 from .extract import extract
 from .graph import build_graph,validate_graph
 from .benchmark import prepare_questions
 from .qa import freeze,answer_questions,answer_one
 from .evaluate import evaluate,diagnose
 from .report import report
 if a.command=='all':
  if (out/'run_freeze.json').exists():
   # Resume the immutable published graph; rebuilding it would alter timestamps/hashes.
   manifest=load_json(out/'corpus/manifest.json')
   sources=__import__('finance_graph.common',fromlist=['read_jsonl']).read_jsonl(out/'corpus/sources.jsonl')
   if any(digest(Path(s['path']).read_text())!=s['sha256'] for s in sources):raise ValueError('Source corpus changed; choose a new artifact_dir')
   validate_graph(c);freeze(c)
  else:
   ingest(c);extract(c,llm);build_graph(c);prepare_questions(c);freeze(c)
  answer_questions(c,llm);evaluate(c,llm);diagnose(c,llm);report(c)
 elif a.command=='ingest':
  if (out/'run_freeze.json').exists():raise ValueError('Frozen run; use a new artifact_dir')
  ingest(c)
 elif a.command=='extract':
  if (out/'run_freeze.json').exists():raise ValueError('Frozen run; use a new artifact_dir')
  extract(c,llm)
 elif a.command=='build-graph':
  if (out/'run_freeze.json').exists():raise ValueError('Frozen run; use a new artifact_dir')
  build_graph(c)
 elif a.command=='questions':prepare_questions(c)
 elif a.command=='freeze':freeze(c)
 elif a.command=='qa':answer_questions(c,llm)
 elif a.command=='evaluate':evaluate(c,llm)
 elif a.command=='diagnose':diagnose(c,llm)
 elif a.command=='report':report(c)
 elif a.command=='validate':print(json.dumps(validate_graph(c),ensure_ascii=False,indent=2))
 elif a.command=='ask':print(json.dumps(answer_one(c,llm,a.question),ensure_ascii=False,indent=2))
 elif a.command=='retrieve':
  from .retrieve import Retriever
  r=Retriever(c);print(json.dumps(r.retrieve(a.question),ensure_ascii=False,indent=2));r.g.close()

if __name__=='__main__':main()
