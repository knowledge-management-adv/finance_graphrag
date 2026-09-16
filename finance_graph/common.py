from __future__ import annotations
import hashlib,json,os,re,unicodedata
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
FACT_TYPES={'Rule','Condition','Requirement','Benefit','Restriction'}
ENTITY_TYPES={'Organization','Concept'}
def normalize(s): return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s)).strip()
def key(s): return re.sub(r'[^가-힣a-z0-9]','',unicodedata.normalize('NFKC',s).lower())
def digest(x):
 if not isinstance(x,str):x=json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
 return hashlib.sha256(x.encode()).hexdigest()
def ident(prefix,*parts):return prefix+'_'+digest(list(parts))[:20]
def now():return datetime.now(timezone.utc).isoformat()
def load_json(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write_json(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
 tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,p)
def write_jsonl(p,items):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
 with tmp.open('w',encoding='utf-8') as f:
  for x in items:f.write(json.dumps(x,ensure_ascii=False)+'\n')
 os.replace(tmp,p)
def read_jsonl(p):
 with Path(p).open(encoding='utf-8') as f:return [json.loads(l) for l in f if l.strip()]
def config(path=None,backend=None,artifact_dir=None):
 c=load_json(path or ROOT/'config.json')
 if backend:c['backend']=backend
 if c['backend'] not in ('local_mlx','upstage'):raise ValueError('backend must be local_mlx or upstage')
 if c['backend']=='upstage':
  c['model_id']=c['api']['model'];c['model_revision']='provider-managed'
  c['local_extraction_fallback']=None
  # Keep API runs away from the default published local run.
  c['artifact_dir']=c.get('api_artifact_dir',c['artifact_dir']+'_upstage')
 if artifact_dir:c['artifact_dir']=artifact_dir
 for field in ('artifact_dir','dataset_root','benchmark_path','model_path'):
  if c.get(field):c[field]=str((ROOT/Path(c[field]).expanduser()).resolve())
 if c.get('local_extraction_fallback'):
  fallback=c['local_extraction_fallback']
  fallback['model_path']=str((ROOT/Path(fallback['model_path']).expanduser()).resolve())
 if c.get('api'):
  c['api']['key_file']=str((ROOT/Path(c['api']['key_file']).expanduser()).resolve())
 return c
def parse_json(s):
 s=re.sub(r'<think>.*?</think>','',s,flags=re.S).strip()
 s=re.sub(r'^```(?:json)?\s*|\s*```$','',s).strip()
 start=s.find('{');end=s.rfind('}')
 if start<0 or end<start:raise ValueError('No JSON object')
 x=json.loads(s[start:end+1])
 if not isinstance(x,dict):raise ValueError('Expected JSON object')
 return x
