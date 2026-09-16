from __future__ import annotations
from pathlib import Path
from .common import *
from .llm import validated_generations,LocalLLM

def extract(cfg,llm,limit=None):
 out=Path(cfg['artifact_dir']);chunks=read_jsonl(out/'corpus/chunks.jsonl');units={u['id']:u for u in read_jsonl(out/'corpus/units.jsonl')};docs={d['id']:d for d in read_jsonl(out/'corpus/documents.jsonl')}
 if limit:chunks=chunks[:limit]
 byid={c['id']:c for c in chunks};aliases={};requests=[];instruction=(ROOT/'prompts/extract.txt').read_text()
 for c in chunks:
  aliases[c['id']]={f'U{i+1}':uid for i,uid in enumerate(c['unit_ids'])}
  body='\n\n'.join(f'[{alias}] [페이지 {units[uid]["page"]}; {units[uid]["heading"]}]\n{units[uid]["text"]}' for alias,uid in aliases[c['id']].items())
  requests.append((c['id'],instruction+'\n\nDocument title: '+docs[c['document_id']]['title']+'\nSource units:\n'+body))
 def validate(cid,obj):
  facts=obj.get('facts')
  if not isinstance(facts,list):raise ValueError('facts must be a list')
  valid=[]
  for f in facts:
   if not isinstance(f,dict) or f.get('type') not in FACT_TYPES:raise ValueError('Invalid fact type')
   if not isinstance(f.get('name'),str) or not f['name'].strip():raise ValueError('Fact needs name')
   refs=f.get('units')
   if not isinstance(refs,list) or not refs or any(u not in aliases[cid] for u in refs):raise ValueError('Unknown or missing unit reference; use only provided U identifiers')
   uids=list(dict.fromkeys(aliases[cid][u] for u in refs));statement='\n'.join(units[u]['text'] for u in uids)
   entities=f.get('entities',[])
   if not isinstance(entities,list):raise ValueError('entities must be a list')
   accepted=[];rejected=[]
   for e in entities:
    if isinstance(e,dict) and e.get('type') in ENTITY_TYPES and isinstance(e.get('name'),str) and normalize(e['name']) and key(e['name']) in key(statement):accepted.append({'type':e['type'],'name':normalize(e['name'])})
    else:rejected.append(e)
   valid.append({'id':ident('f',byid[cid]['document_id'],f['type'],normalize(f['name']),sorted(uids)),'type':f['type'],'name':normalize(f['name']),'statement':statement,'unit_ids':uids,'document_id':byid[cid]['document_id'],'chunk_id':cid,'entities':accepted,'rejected_entities':rejected})
  if not valid and len(byid[cid]['text'])>250:raise ValueError('Empty extraction for a substantive source chunk')
  return valid
 good,errors=validated_generations(llm,'extraction',requests,cfg['extraction_max_tokens'],validate)
 fallback_successes=0
 if errors and cfg['backend']=='local_mlx' and cfg.get('local_extraction_fallback'):
  # One bounded alternate-local-model pass (plus at most one format repair).
  # Only failed chunks are sent; successful primary extractions stay unchanged.
  fallback_cfg={**cfg,**cfg['local_extraction_fallback']}
  llm.unload();alternate=LocalLLM(fallback_cfg)
  selected=[(cid,prompt) for cid,prompt in requests if cid in errors]
  alt_good,alt_errors=validated_generations(alternate,'extraction_fallback',selected,cfg['extraction_max_tokens'],validate,max_retries=1)
  for cid,rec in alt_good.items():
   rec['attempt']+=3;rec['fallback_model']=fallback_cfg['model_id'];good[cid]=rec;errors.pop(cid,None)
  errors.update(alt_errors);fallback_successes=len(alt_good);alternate.unload()
 facts=[]
 for cid,rec in good.items():
  write_json(out/'extraction/chunks'/f'{cid}.json',rec)
  for fact in rec['value']:fact['extraction_run']=rec['request_hash'];facts.append(fact)
 covered={uid for f in facts for uid in f['unit_ids']};allunits={uid for c in chunks for uid in c['unit_ids']}
 stats={'requested_chunks':len(chunks),'completed_chunks':len(good),'failed_chunks':errors,'facts':len(facts),'covered_units':len(covered),'total_units':len(allunits),'unit_coverage':len(covered)/max(1,len(allunits)),'rejected_entities':sum(len(f['rejected_entities']) for f in facts),'partial_run':bool(limit),'fallback_successes':fallback_successes,'created_at':now()}
 write_jsonl(out/'extraction/facts.jsonl',facts);write_json(out/'extraction/status.json',stats)
 print('EXTRACTION_SUMMARY '+json.dumps(stats,ensure_ascii=False),flush=True)
 if errors:raise RuntimeError(f'{len(errors)} chunks failed extraction; inspect logs and resume')
 return stats
