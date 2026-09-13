"""The only pre-evaluation benchmark operation is an explicit question-only projection."""
from pathlib import Path
from .common import *

def prepare_questions(cfg):
 raw=load_json(cfg['benchmark_path'])
 if not isinstance(raw,list):raise ValueError('Benchmark must be a JSON list')
 rows=[{'id':r['id'],'question':r['question']} for r in raw]
 if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate question IDs')
 if any(not isinstance(r['question'],str) or not r['question'].strip() for r in rows):raise ValueError('Invalid question')
 out=Path(cfg['artifact_dir']);write_jsonl(out/'questions/questions.jsonl',rows)
 write_json(out/'questions/manifest.json',{'count':len(rows),'allowed_fields':['id','question'],'question_hash':digest(rows),'source_file_sha256':digest(Path(cfg['benchmark_path']).read_text()),'created_at':now()})
 print('QUESTION_PROJECTION count='+str(len(rows)),flush=True);return rows

def read_questions(cfg):
 rows=read_jsonl(Path(cfg['artifact_dir'])/'questions/questions.jsonl')
 if any(set(r)!={'id','question'} for r in rows):raise ValueError('Question input contains forbidden extra fields')
 return rows
