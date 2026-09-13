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
def config(path=None):
 c=load_json(path or ROOT/'config.json');c['artifact_dir']=str((ROOT/c['artifact_dir']).resolve());return c
def parse_json(s):
 s=re.sub(r'<think>.*?</think>','',s,flags=re.S).strip()
 s=re.sub(r'^```(?:json)?\s*|\s*```$','',s).strip()
 start=s.find('{');end=s.rfind('}')
 if start<0 or end<start:raise ValueError('No JSON object')
 x=json.loads(s[start:end+1])
 if not isinstance(x,dict):raise ValueError('Expected JSON object')
 return x
