from __future__ import annotations
import os,sqlite3
from pathlib import Path
from .common import *
SIGNATURES={'HAS_VERSION':({'Source'},{'Document'}),'DESCRIBES':({'Source'},{'Product'}),'HAS_CHUNK':({'Document'},{'Chunk'}),'NEXT_CHUNK':({'Chunk'},{'Chunk'}),'ASSERTS':({'Document'},FACT_TYPES),'SUPPORTED_BY':(FACT_TYPES,{'Chunk'}),'MENTIONS':(FACT_TYPES,ENTITY_TYPES)}

def connect(path,readonly=False):
 conn=sqlite3.connect(f'file:{path}?mode=ro' if readonly else path,uri=readonly);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON');return conn

def build_graph(cfg):
 out=Path(cfg['artifact_dir']);status=load_json(out/'extraction/status.json');manifest=load_json(out/'corpus/manifest.json')
 if status['failed_chunks'] or status['partial_run'] or status['completed_chunks']!=manifest['chunks']:raise ValueError('Cannot publish an incomplete extraction as a complete graph')
 tables={k:read_jsonl(out/'corpus'/f'{k}.jsonl') for k in ('sources','documents','products','units','chunks')};facts=read_jsonl(out/'extraction/facts.jsonl')
 nodes={};edges={}
 def node(typ,obj,name=None):nodes[obj['id']]={'id':obj['id'],'type':typ,'name':name or obj.get('name') or obj.get('title') or obj['id'],'properties':obj}
 def edge(typ,src,dst,props=None):
  e={'id':ident('e',typ,src,dst),'source':src,'target':dst,'type':typ,'properties':props or {}};edges[e['id']]=e
 for d in tables['documents']:node('Document',d)
 for p in tables['products']:node('Product',p)
 for s in tables['sources']:
  node('Source',s,s['relative_path']);edge('HAS_VERSION',s['id'],s['document_id']);edge('DESCRIBES',s['id'],s['product_id'])
 previous={}
 for c in tables['chunks']:
  node('Chunk',c);edge('HAS_CHUNK',c['document_id'],c['id'],{'ordinal':c['ordinal']})
  if c['document_id'] in previous:edge('NEXT_CHUNK',previous[c['document_id']],c['id'])
  previous[c['document_id']]=c['id']
 for f in facts:
  node(f['type'],f);edge('ASSERTS',f['document_id'],f['id']);edge('SUPPORTED_BY',f['id'],f['chunk_id'],{'unit_ids':f['unit_ids']})
  for e in f['entities']:
   eid=ident('entity',e['type'],normalize(e['name']));node(e['type'],{'id':eid,'name':e['name']});edge('MENTIONS',f['id'],eid,{'unit_ids':f['unit_ids']})
 for e in edges.values():
  allowed=SIGNATURES[e['type']]
  if nodes[e['source']]['type'] not in allowed[0] or nodes[e['target']]['type'] not in allowed[1]:raise ValueError('Edge type signature violation')
 db=out/'graph.sqlite';tmp=out/'graph.building.sqlite'
 if tmp.exists():tmp.unlink()
 conn=connect(tmp)
 conn.executescript('CREATE TABLE nodes(id TEXT PRIMARY KEY,type TEXT NOT NULL,name TEXT NOT NULL,properties TEXT NOT NULL);CREATE TABLE edges(id TEXT PRIMARY KEY,source TEXT NOT NULL REFERENCES nodes(id),target TEXT NOT NULL REFERENCES nodes(id),type TEXT NOT NULL,properties TEXT NOT NULL);CREATE INDEX edges_source ON edges(source,type);CREATE INDEX edges_target ON edges(target,type);CREATE INDEX node_type ON nodes(type);CREATE TABLE units(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES nodes(id),properties TEXT NOT NULL);CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);')
 with conn:
  conn.executemany('INSERT INTO nodes VALUES (?,?,?,?)',[(n['id'],n['type'],n['name'],json.dumps(n['properties'],ensure_ascii=False)) for n in nodes.values()])
  conn.executemany('INSERT INTO edges VALUES (?,?,?,?,?)',[(e['id'],e['source'],e['target'],e['type'],json.dumps(e['properties'],ensure_ascii=False)) for e in edges.values()])
  conn.executemany('INSERT INTO units VALUES (?,?,?)',[(u['id'],u['document_id'],json.dumps(u,ensure_ascii=False)) for u in tables['units']])
  conn.executemany('INSERT INTO metadata VALUES (?,?)',[(k,json.dumps(v,ensure_ascii=False)) for k,v in {'created_at':now(),'manifest':manifest,'configuration':cfg,'ontology_hash':digest((ROOT/'docs/ontology.md').read_text()),'extraction_prompt_hash':digest((ROOT/'prompts/extract.txt').read_text())}.items()])
 if conn.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Foreign key failure')
 conn.close();os.replace(tmp,db)
 write_jsonl(out/'graph_export/nodes.jsonl',nodes.values());write_jsonl(out/'graph_export/edges.jsonl',edges.values())
 result=validate_graph(cfg);write_json(out/'graph_validation.json',result);print('GRAPH '+json.dumps(result,ensure_ascii=False),flush=True);return result

class Graph:
 def __init__(self,path):
  self.path=Path(path);self.conn=connect(self.path,True)
  self.nodes={r['id']:{'id':r['id'],'type':r['type'],'name':r['name'],'properties':json.loads(r['properties'])} for r in self.conn.execute('SELECT * FROM nodes')}
  self.edges=[{'id':r['id'],'source':r['source'],'target':r['target'],'type':r['type'],'properties':json.loads(r['properties'])} for r in self.conn.execute('SELECT * FROM edges')]
  self.units={r['id']:json.loads(r['properties']) for r in self.conn.execute('SELECT * FROM units')}
  self.outgoing={};self.incoming={}
  for e in self.edges:self.outgoing.setdefault(e['source'],[]).append(e);self.incoming.setdefault(e['target'],[]).append(e)
  self.product_docs={};self.doc_products={};self.doc_sources={}
  for n in self.typed('Source'):
   versions=self.targets(n['id'],'HAS_VERSION');products=self.targets(n['id'],'DESCRIBES')
   for d in versions:
    self.doc_sources.setdefault(d,[]).append(n['id'])
    for p in products:self.product_docs.setdefault(p,set()).add(d);self.doc_products.setdefault(d,set()).add(p)
 def typed(self,typ):return [n for n in self.nodes.values() if n['type']==typ]
 def targets(self,node,edge_type):return [e['target'] for e in self.outgoing.get(node,[]) if e['type']==edge_type]
 def predecessors(self,node,edge_type):return [e['source'] for e in self.incoming.get(node,[]) if e['type']==edge_type]
 def facts(self):return [n for n in self.nodes.values() if n['type'] in FACT_TYPES]
 def props(self,node):return self.nodes[node]['properties']
 def close(self):self.conn.close()

def validate_graph(cfg):
 g=Graph(Path(cfg['artifact_dir'])/'graph.sqlite');errors=[]
 for n in g.typed('Document'):
  p=n['properties']
  if digest(p['text'])!=p['sha256']:errors.append('Document hash mismatch '+n['id'])
 for f in g.facts():
  p=f['properties'];cs=g.targets(f['id'],'SUPPORTED_BY')
  if not cs or not p['unit_ids']:errors.append('Missing fact provenance '+f['id']);continue
  if any(u not in g.units for u in p['unit_ids']):errors.append('Unknown unit '+f['id']);continue
  if '\n'.join(g.units[u]['text'] for u in p['unit_ids'])!=p['statement']:errors.append('Statement mismatch '+f['id'])
  if not all(any(u in g.props(c)['unit_ids'] for c in cs) for u in p['unit_ids']):errors.append('Chunk evidence mismatch '+f['id'])
  if any(g.units[u]['document_id']!=p['document_id'] for u in p['unit_ids']):errors.append('Wrong source document '+f['id'])
 for e in g.edges:
  a,b=SIGNATURES[e['type']]
  if g.nodes[e['source']]['type'] not in a or g.nodes[e['target']]['type'] not in b:errors.append('Invalid edge '+e['id'])
 for u in g.units.values():
  raw=g.props(u['document_id'])['text']
  if not 0<=u['raw_start']<u['raw_end']<=len(raw):errors.append('Invalid raw span '+u['id'])
 facts=g.facts();res={'valid':not errors,'errors':errors,'nodes':len(g.nodes),'edges':len(g.edges),'facts':len(facts),'units':len(g.units),'node_counts':{t:sum(n['type']==t for n in g.nodes.values()) for t in sorted({n['type'] for n in g.nodes.values()})},'edge_counts':{t:sum(e['type']==t for e in g.edges) for t in sorted(SIGNATURES)},'fact_provenance_coverage':sum(bool(g.targets(f['id'],'SUPPORTED_BY')) for f in facts)/max(1,len(facts))};g.close()
 if errors:raise ValueError(res)
 return res
