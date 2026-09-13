from __future__ import annotations
import os,time
from pathlib import Path
from .common import *

class LocalLLM:
 """Local inference only. No automatic remote fallback or credential handling."""
 def __init__(self,cfg):
  if cfg['backend']!='local_mlx':raise ValueError('Only authorized local_mlx backend is enabled. Remote API requires explicit user approval.')
  self.cfg=cfg;self.model=None;self.tokenizer=None
  os.environ['HF_HUB_OFFLINE']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
 def load(self):
  if self.model is not None:return
  from mlx_lm import load
  import mlx.core as mx
  mx.random.seed(self.cfg['seed']);t=time.time()
  self.model,self.tokenizer=load(self.cfg['model_path']);print(f'LOCAL_MODEL_LOADED seconds={time.time()-t:.1f}',flush=True)
 def unload(self):
  self.model=None;self.tokenizer=None
  import gc
  gc.collect()
  import mlx.core as mx
  mx.clear_cache()
 def generate_many(self,stage,requests,max_tokens):
  out=Path(self.cfg['artifact_dir'])/'llm'/stage;out.mkdir(parents=True,exist_ok=True)
  result={};pending=[]
  batch_size=self.cfg.get('stage_batch_sizes',{}).get(stage,self.cfg['batch_size'])
  for rid,prompt in requests:
   fingerprint={'stage':stage,'prompt':prompt,'model_id':self.cfg['model_id'],'revision':self.cfg['model_revision'],'max_tokens':max_tokens,'seed':self.cfg['seed'],'thinking':False,'temperature':0,'batch_size':batch_size}
   h=digest(fingerprint);path=out/(h+'.json')
   if path.exists():result[rid]=load_json(path)
   else:pending.append((rid,prompt,path,h,fingerprint))
  if pending:self.load()
  from mlx_lm import batch_generate
  for start in range(0,len(pending),batch_size):
   batch=pending[start:start+batch_size]
   prompts=[self.tokenizer.apply_chat_template([{'role':'user','content':p}],add_generation_prompt=True,enable_thinking=False) for _,p,_,_,_ in batch]
   if max(map(len,prompts))>30000:raise ValueError('Prompt exceeds conservative local context budget')
   t=time.time();response=batch_generate(self.model,self.tokenizer,prompts,max_tokens=max_tokens,completion_batch_size=batch_size,prefill_batch_size=1,prefill_step_size=1024,return_token_ids=True,verbose=False)
   for (rid,p,path,h,fp),text,tokens in zip(batch,response.texts,response.token_ids):
    rec={'request_id':rid,'request_hash':h,'created_at':now(),'backend':'local_mlx','configuration':fp,'raw_text':text,'generated_tokens':len(tokens),'possibly_truncated':len(tokens)>=max_tokens,'batch_seconds':round(time.time()-t,3),'batch_stats':vars(response.stats)}
    write_json(path,rec);result[rid]=rec
   print(f'{stage.upper()} {min(start+len(batch),len(pending))}/{len(pending)} new requests; batch_seconds={time.time()-t:.1f}; tokens_per_second={response.stats.generation_tps:.1f}',flush=True)
  return result

def validated_generations(llm,stage,requests,max_tokens,validator,max_retries=2,parser=parse_json):
 """Persist raw attempts; bounded retries never accept a fabricated fallback."""
 original=dict(requests);pending=list(requests);good={};errors={}
 for attempt in range(max_retries+1):
  if not pending:break
  generated=llm.generate_many(stage,pending,max_tokens)
  retry=[]
  for rid,prompt in pending:
   rec=generated[rid]
   try:
    if rec['possibly_truncated']:raise ValueError('Output reached token limit')
    value=validator(rid,parser(rec['raw_text']))
    good[rid]={'value':value,'request_hash':rec['request_hash'],'attempt':attempt,'generated_tokens':rec['generated_tokens']};errors.pop(rid,None)
   except (ValueError,KeyError,TypeError) as e:
    errors[rid]=str(e)
    retry.append((rid,original[rid]+'\n\nYour prior output was invalid: '+str(e)+'. Return one complete concise JSON object with correct types and references. Do not use markdown. Reduce redundant entries if needed. Retry number '+str(attempt+1)+'.'))
  pending=retry
 if errors:print(stage.upper()+'_ERRORS '+json.dumps(errors,ensure_ascii=False),flush=True)
 return good,errors
