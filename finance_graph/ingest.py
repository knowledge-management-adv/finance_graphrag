from __future__ import annotations
import re
from pathlib import Path
from html.parser import HTMLParser
from .common import *

class TableParser(HTMLParser):
 def __init__(self):super().__init__();self.rows=[];self.row=[];self.cell=None
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='tr':self.row=[]
  elif tag in ('td','th'):self.cell={'text':'','rowspan':max(1,int(a.get('rowspan','1'))),'colspan':max(1,int(a.get('colspan','1')))}
  elif tag in ('br','p','div') and self.cell is not None:self.cell['text']+=' '
 def handle_data(self,data):
  if self.cell is not None:self.cell['text']+=data
 def handle_endtag(self,tag):
  if tag in ('td','th') and self.cell is not None:self.row.append(self.cell);self.cell=None
  elif tag=='tr' and self.row:self.rows.append(self.row);self.row=[]
 def expanded(self):
  pending={};out=[]
  for row in self.rows:
   vals={c:v[0] for c,v in pending.items()};next_pending={c:(v,n-1) for c,(v,n) in pending.items() if n>1};col=0
   for cell in row:
    while col in vals:col+=1
    value=normalize(cell['text'])
    for k in range(cell['colspan']):
     vals[col+k]=value
     if cell['rowspan']>1:next_pending[col+k]=(value,cell['rowspan']-1)
    col+=cell['colspan']
   pending=next_pending;out.append([vals[c] for c in sorted(vals)])
  return out

def split_text(text,limit):
 while len(text)>limit:
  choices=[text.rfind(sep,limit//2,limit) for sep in ('\n','。','. ','; ',' ')]
  cut=max(choices)
  if cut<=0:cut=limit
  else:cut+=1
  yield text[:cut].strip();text=text[cut:].strip()
 if text.strip():yield text.strip()

def units_from_document(doc,cfg):
 text=doc['text'];units=[];heading=doc['title'];page=1
 def add(value,start,end,row=None):
  for part in split_text(value,cfg['unit_max_chars']):
   if not part.strip():continue
   n=len(units);u={'id':ident('u',doc['id'],n),'document_id':doc['id'],'ordinal':n,'text':part,'heading':heading,'page':page,'raw_start':start,'raw_end':end}
   if row is not None:u['table_row']=row
   units.append(u)
 # A single scanner preserves raw offsets and avoids treating HTML rows as paragraphs.
 pattern=re.compile(r'<table\b.*?</table>|<!--\s*page:\s*\d+\s*-->|[^\n]+(?:\n(?!\s*\n|#|<!--|<table)[^\n]+)*',re.S|re.I)
 # Split at tables/page markers first; process remaining Markdown paragraphs linearly.
 cursor=0
 special=re.compile(r'<table\b.*?</table>|<!--\s*page:\s*(\d+)\s*-->',re.S|re.I)
 def plain(seg,offset):
  nonlocal heading
  for m in re.finditer(r'[^\n]+(?:\n(?!\s*\n|#)[^\n]+)*',seg):
   raw=m.group();s=raw.strip()
   if not s:continue
   if s.startswith('#') and '\n' not in s:heading=re.sub(r'^#+\s*','',s);continue
   add(s,offset+m.start(),offset+m.end())
 for m in special.finditer(text):
  plain(text[cursor:m.start()],cursor)
  if m.group(1):page=int(m.group(1))
  else:
   p=TableParser();p.feed(m.group());rows=p.expanded();header=' | '.join(dict.fromkeys(rows[0])) if rows else ''
   for i,row in enumerate(rows):
    rowtext=' | '.join(v for j,v in enumerate(row) if j==0 or v!=row[j-1])
    if i and header and len(header)<200:rowtext='[표 머리글: '+header+'] '+rowtext
    add(rowtext,m.start(),m.end(),i)
  cursor=m.end()
 plain(text[cursor:],cursor)
 return units

def make_chunks(doc,units,cfg):
 chunks=[];group=[];size=0
 def flush():
  nonlocal group,size
  if not group:return
  n=len(chunks);chunks.append({'id':ident('c',doc['id'],[u['id'] for u in group]),'document_id':doc['id'],'ordinal':n,'unit_ids':[u['id'] for u in group],'pages':sorted({u['page'] for u in group}),'headings':list(dict.fromkeys(u['heading'] for u in group)),'text':'\n\n'.join('['+u['heading']+']\n'+u['text'] for u in group)})
  group=[];size=0
 for u in units:
  extra=len(u['text'])+len(u['heading'])+5
  boundary=bool(group) and u['heading']!=group[-1]['heading']
  if group and (size+extra>cfg['chunk_max_chars'] or size>=cfg['chunk_target_chars'] or (boundary and size>cfg['chunk_target_chars']*.7)):flush()
  group.append(u);size+=extra
 flush();return chunks

def ingest(cfg):
 root=Path(cfg['dataset_root']);out=Path(cfg['artifact_dir']);out.mkdir(parents=True,exist_ok=True)
 paths=sorted(root.rglob('document.md'),key=lambda p:str(p.relative_to(root)))
 if not paths:raise ValueError('No document.md files')
 docs={};sources=[];products={}
 for p in paths:
  raw=p.read_text(encoding='utf-8');sha=digest(raw);did=ident('d',sha);rel=str(p.relative_to(root));name=p.relative_to(root).parts[0];pid=ident('p',name)
  products[pid]={'id':pid,'name':name,'aliases':[key(name)]}
  source={'id':ident('s',rel),'path':str(p),'relative_path':rel,'sha256':sha,'product_id':pid,'product_name':name,'document_id':did,'file_mtime':p.stat().st_mtime};sources.append(source)
  if did not in docs:
   title=next((re.sub(r'^#+\s*','',l).strip() for l in raw.splitlines() if l.startswith('#')),p.parent.name)
   docs[did]={'id':did,'sha256':sha,'title':title,'text':raw,'source_count':0,'date_mentions':sorted(set(re.findall(r'20\d{2}[.년/-]\s*\d{1,2}[.월/-]\s*\d{1,2}일?',raw)))}
  docs[did]['source_count']+=1
 units=[];chunks=[]
 for doc in docs.values():
  us=units_from_document(doc,cfg);units.extend(us);chunks.extend(make_chunks(doc,us,cfg))
 manifest={'created_at':now(),'dataset_root':str(root),'schema_version':cfg['schema_version'],'products':len(products),'source_documents':len(sources),'unique_documents':len(docs),'units':len(units),'chunks':len(chunks),'raw_chars':sum(len(d['text']) for d in docs.values()),'dataset_hash':digest([(s['relative_path'],s['sha256']) for s in sources]),'chunking':{k:cfg[k] for k in ('chunk_target_chars','chunk_max_chars','unit_max_chars')}}
 for name,items in [('sources',sources),('documents',docs.values()),('products',products.values()),('units',units),('chunks',chunks)]:write_jsonl(out/'corpus'/f'{name}.jsonl',items)
 write_json(out/'corpus/manifest.json',manifest);print(json.dumps(manifest,ensure_ascii=False),flush=True);return manifest
