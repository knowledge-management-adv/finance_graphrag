from __future__ import annotations
import math,re,collections
from pathlib import Path
from .common import *
from .graph import Graph

# Deterministic Korean-friendly lexical retrieval: no trained embedding model.
def terms(s):
 words=re.findall(r'[가-힣A-Za-z0-9%]+',s.lower());out=[]
 for word in words:
  if len(word)>1:out.append('w:'+word)
  for n in (2,3):out.extend('g:'+word[i:i+n] for i in range(len(word)-n+1))
 return out
class BM25:
 def __init__(self,texts):
  self.length={};self.postings=collections.defaultdict(list);self.n=len(texts)
  for id,text in texts.items():
   counts=collections.Counter(terms(text));self.length[id]=sum(counts.values())
   for term,tf in counts.items():self.postings[term].append((id,tf))
  self.avg=sum(self.length.values())/max(1,self.n)
 def scores(self,q,allowed=None):
  scores=collections.defaultdict(float)
  for term in set(terms(q)):
   postings=self.postings.get(term,[]);idf=math.log(1+(self.n-len(postings)+.5)/(len(postings)+.5))
   for id,tf in postings:
    if allowed is not None and id not in allowed:continue
    denom=tf+1.2*(.25+.75*self.length[id]/max(1,self.avg));scores[id]+=idf*(tf*2.2)/denom
  return dict(scores)

class Retriever:
 def __init__(self,cfg):
  self.cfg=cfg;self.g=Graph(Path(cfg['artifact_dir'])/'graph.sqlite');self.facts={n['id']:n['properties'] for n in self.g.facts()};self.chunks={n['id']:n['properties'] for n in self.g.typed('Chunk')};self.products={n['id']:n['properties'] for n in self.g.typed('Product')}
  self.fi=BM25({fid:f['name']+' '+f['statement'] for fid,f in self.facts.items()});self.ci=BM25({cid:' '.join(c['headings'])+' '+c['text'] for cid,c in self.chunks.items()})
 def retrieve(self,question):
  if not isinstance(question,str):raise TypeError('Retrieval accepts a question string only')
  qkey=key(question);matches=[p for p in self.products if key(self.products[p]['name']) in qkey]
  matches=[p for p in matches if not any(p!=other and key(self.products[p]['name']) in key(self.products[other]['name']) for other in matches)]
  docs=set().union(*(self.g.product_docs[p] for p in matches)) if matches else None
  allowed_f={f for f,p in self.facts.items() if docs is None or p['document_id'] in docs};allowed_c={c for c,p in self.chunks.items() if docs is None or p['document_id'] in docs}
  fs=self.fi.scores(question,allowed_f);cs=self.ci.scores(question,allowed_c)
  ranked_f=sorted(fs,key=lambda f:(-fs[f],f));ranked_c=sorted(cs,key=lambda c:(-cs[c],c))
  selected_f=[]
  # Explicitly named products get coverage before the global score fills the budget.
  if matches:
   quota=max(2,min(8,self.cfg['retrieval_facts']//len(matches)))
   for p in matches:
    selected_f.extend([f for f in ranked_f if self.facts[f]['document_id'] in self.g.product_docs[p]][:quota])
  selected_f=list(dict.fromkeys(selected_f+ranked_f))[:self.cfg['retrieval_facts']]
  # Expand one semantic hop through an explicitly shared organization/concept.
  neighbor_scores={}
  for fid in selected_f[:8]:
   for entity in self.g.targets(fid,'MENTIONS'):
    for neighbor in self.g.predecessors(entity,'MENTIONS'):
     if neighbor in allowed_f and neighbor not in selected_f and neighbor in fs:neighbor_scores[neighbor]=max(neighbor_scores.get(neighbor,0),fs[neighbor])
  for fid in sorted(neighbor_scores,key=neighbor_scores.get,reverse=True)[:4]:
   if fid not in selected_f:selected_f.append(fid)
  score_c=collections.defaultdict(float);reasons=collections.defaultdict(list)
  for rank,fid in enumerate(selected_f):
   for cid in self.g.targets(fid,'SUPPORTED_BY'):
    score_c[cid]+=1/(20+rank);reasons[cid].append({'via':'SUPPORTED_BY','fact_id':fid})
  # Chunk lexical matches are graph-node seeds and bring their asserted facts with them.
  for rank,cid in enumerate(ranked_c[:30]):score_c[cid]+=.8/(20+rank);reasons[cid].append({'via':'chunk_lexical','rank':rank+1})
  ranking=sorted(score_c,key=lambda c:(-score_c[c],c));selected_c=[]
  if matches:
   quota=max(1,min(3,self.cfg['retrieval_chunks']//len(matches)))
   for p in matches:selected_c.extend([c for c in ranking if self.chunks[c]['document_id'] in self.g.product_docs[p]][:quota])
  selected_c=list(dict.fromkeys(selected_c+ranking))[:self.cfg['retrieval_chunks']]
  for cid in list(selected_c):
   # Two-way adjacent-chunk expansion preserves footnotes and table continuations.
   ns=self.g.targets(cid,'NEXT_CHUNK')+self.g.predecessors(cid,'NEXT_CHUNK')
   for adjacent in ns:
    if adjacent not in selected_c and len(selected_c)<self.cfg['retrieval_chunks']+3:
     selected_c.append(adjacent);reasons[adjacent].append({'via':'NEXT_CHUNK','from_chunk':cid})
  # Prioritize graph facts whose evidence is among the selected source chunks.
  for cid in selected_c:
   candidates=sorted(self.g.predecessors(cid,'SUPPORTED_BY'),key=lambda f:fs.get(f,0),reverse=True)
   for fid in candidates[:3]:
    if fid not in selected_f:selected_f.append(fid)
  selected_f=selected_f[:self.cfg['retrieval_facts']+12]
  parts=['검색된 지식그래프 사실'];kept_f=[];kept_c=[];budget=self.cfg['context_max_chars'];used=len(parts[0])
  # Facts supply compact typed labels and source links; full statements are in chunks.
  for fid in selected_f:
   f=self.facts[fid];names=[self.products[p]['name'] for p in sorted(self.g.doc_products.get(f['document_id'],set()))]
   scope=', '.join(names) if len(names)<=4 else '공통 약관 ('+str(len(names))+'개 상품 연결)'
   line=f'[F:{fid}] {f["type"]}: {f["name"]}; 상품 범위: {scope}; 근거: '+','.join('C:'+c for c in self.g.targets(fid,'SUPPORTED_BY'))+'\n'+f['statement'][:650]
   if used+len(line)>budget*.32:break
   parts.append(line);used+=len(line);kept_f.append(fid)
  parts.append('\n연결된 원문 청크')
  for cid in selected_c:
   c=self.chunks[cid];doc=self.g.props(c['document_id']);names=[self.products[p]['name'] for p in sorted(self.g.doc_products.get(c['document_id'],set()))];scope=', '.join(names) if len(names)<=4 else '공통 약관 ('+str(len(names))+'개 상품 연결)'
   block=f'[C:{cid}] 문서: {doc["title"]}; 상품: {scope}; 페이지: {c["pages"]}\n'+c['text']
   if used+len(block)>budget:continue
   parts.append(block);used+=len(block);kept_c.append(cid)
  # Only label graph edges as returned when both endpoints are in the context subgraph.
  context='\n\n'.join(parts)
  # Short context-local citations reduce copying errors; canonical graph IDs remain in the trace.
  citation_map={**{f'F:{i+1}':'F:'+fid for i,fid in enumerate(kept_f)},**{f'C:{i+1}':'C:'+cid for i,cid in enumerate(kept_c)}}
  for alias,canonical in citation_map.items():context=context.replace(canonical,alias)
  # A fact can be quoted without loading its full chunk; do not expose uncitable chunk IDs.
  context=re.sub(r'C:c_[0-9a-f]+','(연결 원문 청크 미포함)',context)
  trace={'question':question,'matched_products':[self.products[p]['name'] for p in matches],'matched_product_ids':matches,'fact_ids':kept_f,'chunk_ids':kept_c,'selected_chunk_ids_before_budget':selected_c,'document_ids':sorted({self.chunks[c]['document_id'] for c in kept_c}),'chunk_routes':{c:reasons[c] for c in kept_c},'fact_scores':{f:fs.get(f,0) for f in kept_f},'context_chars':len(context),'context':context,'citation_map':citation_map,'retrieval_config':{k:self.cfg[k] for k in ('retrieval_chunks','retrieval_facts','context_max_chars')}}
  return trace
