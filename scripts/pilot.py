import os,json,time
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
from mlx_lm import load,batch_generate
import mlx.core as mx
cfg=json.loads(Path('config.json').read_text());t=time.time()
model,tok=load(cfg['model_path']);print('LOADED',round(time.time()-t,2),flush=True)
prompts=[
'한국어 금융 문서에서 정보를 추출합니다. JSON만 출력하세요. 입력: [u1] 이 적금은 매월 1천원 이상 50만원 이하로 저축할 수 있습니다. [u2] 이 적금의 계약기간은 12개월입니다. [u3] 공동명의 가입은 불가합니다. 출력 형식: {"facts":[{"type":"Rule 또는 Restriction","name":"짧은 한국어 이름","units":["u1"]}]} 모든 사실을 추출하고 출처 units를 포함하세요.',
'주어진 근거만 사용해 한국어로 답하세요. 근거: 실제 만기 해지 거래일로부터 3개월이 되는 해당일까지 재가입하면 우대금리가 제공된다. 해당일이 없는 경우 3개월 해당월의 마지막일까지이다. 질문: 실제 만기해지를 2025년 1월 31일에 한 경우 재가입 마지막 날짜는? JSON만 출력: {"answer":"답과 간단한 근거"}'
]
encoded=[tok.apply_chat_template([{'role':'user','content':p}],add_generation_prompt=True,enable_thinking=False) for p in prompts]
r=batch_generate(model,tok,encoded,max_tokens=1000,completion_batch_size=2,prefill_batch_size=1,prefill_step_size=1024,verbose=True)
Path('artifacts/pilot.json').write_text(json.dumps({'texts':r.texts,'stats':vars(r.stats),'model':cfg['model_id']},ensure_ascii=False,indent=2))
for text in r.texts: print(text,flush=True)
