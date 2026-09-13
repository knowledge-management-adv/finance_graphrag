import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from finance_graph.common import config,write_json,write_jsonl,read_jsonl,digest,parse_json,ident
from finance_graph.ingest import TableParser,units_from_document,make_chunks,ingest
from finance_graph.benchmark import prepare_questions,read_questions
from finance_graph.graph import build_graph,validate_graph,Graph
from finance_graph.retrieve import Retriever
from finance_graph.llm import validated_generations,LocalLLM

class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cfg=config();self.cfg['artifact_dir']=str(self.root/'out');self.cfg['dataset_root']=str(self.root/'sources');self.cfg['benchmark_path']=str(self.root/'benchmark.json')
 def tearDown(self):self.tmp.cleanup()
 def source(self,product,title,text):
  p=Path(self.cfg['dataset_root'])/product/title/'document.md';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
 def test_table_rowspan_keeps_qualification(self):
  p=TableParser();p.feed('<table><tr><td rowspan="3">우대금리</td><td>조건</td></tr><tr><td>급여 6개월</td></tr><tr><td>중도해지 제외</td></tr></table>')
  self.assertEqual(p.expanded(),[['우대금리','조건'],['우대금리','급여 6개월'],['우대금리','중도해지 제외']])
 def test_deterministic_offsets_and_all_unit_membership(self):
  text='# 상품\n\n<!-- page: 2 -->\n\n# 가입조건\n\n월 10만원 이하.\n\n<table><tr><td>기간</td><td>12개월</td></tr></table>\n\n# 해지\n\n중도해지시 우대 제외.'
  doc={'id':'d_test','title':'상품','text':text};units=units_from_document(doc,self.cfg);chunks=make_chunks(doc,units,self.cfg)
  self.assertEqual(units,units_from_document(doc,self.cfg));self.assertEqual({u['id'] for u in units},{u for c in chunks for u in c['unit_ids']})
  self.assertTrue(all(u['page']==2 for u in units))
  table=next(u for u in units if 'table_row' in u);self.assertTrue(text[table['raw_start']:table['raw_end']].startswith('<table>'))
  self.assertTrue(all(len(c['text'])<=self.cfg['chunk_max_chars'] for c in chunks))
 def test_duplicate_sources_keep_distinct_product_scope(self):
  self.source('가 적금','약관','# 공통\n\n매월 저축한다.');self.source('나 적금','약관','# 공통\n\n매월 저축한다.');m=ingest(self.cfg)
  self.assertEqual(m['source_documents'],2);self.assertEqual(m['unique_documents'],1);self.assertEqual(m['products'],2)
 def test_gold_projection_is_strict_and_inference_rejects_extra_fields(self):
  sentinel='FORBIDDEN_GOLD_SECRET';write_json(self.cfg['benchmark_path'],[{'id':'q1','question':'조건은?','answer':sentinel,'rationale':sentinel,'sources':[sentinel]}]);prepare_questions(self.cfg)
  p=Path(self.cfg['artifact_dir'])/'questions/questions.jsonl';self.assertNotIn(sentinel,p.read_text());self.assertEqual(read_questions(self.cfg),[{'id':'q1','question':'조건은?'}])
  write_jsonl(p,[{'id':'q1','question':'조건은?','answer':sentinel}])
  with self.assertRaises(ValueError):read_questions(self.cfg)
 def make_graph(self):
  self.source('가 적금','특약','# 가 적금\n\n# 계약기간\n\n계약기간은 12개월입니다.\n\n# 예외\n\n중도해지 시 우대금리는 적용하지 않습니다.')
  self.source('나 적금','특약','# 나 적금\n\n# 계약기간\n\n계약기간은 24개월입니다.')
  m=ingest(self.cfg);out=Path(self.cfg['artifact_dir']);chunks=read_jsonl(out/'corpus/chunks.jsonl');units={u['id']:u for u in read_jsonl(out/'corpus/units.jsonl')};facts=[]
  for c in chunks:
   for uid in c['unit_ids']:
    u=units[uid];facts.append({'id':ident('f',uid),'type':'Rule','name':u['heading'],'statement':u['text'],'unit_ids':[uid],'document_id':c['document_id'],'chunk_id':c['id'],'entities':[],'rejected_entities':[],'extraction_run':'synthetic-fixture'})
  write_jsonl(out/'extraction/facts.jsonl',facts);write_json(out/'extraction/status.json',{'failed_chunks':{},'partial_run':False,'completed_chunks':m['chunks']});return build_graph(self.cfg)
 def test_graph_roundtrip_and_source_scoped_traversal(self):
  stats=self.make_graph();self.assertTrue(stats['valid']);self.assertEqual(stats['fact_provenance_coverage'],1)
  r=Retriever(self.cfg);trace=r.retrieve('가 적금의 계약기간은?');self.assertEqual(trace['matched_products'],['가 적금']);self.assertIn('12개월',trace['context']);self.assertNotIn('24개월',trace['context']);self.assertTrue(trace['fact_ids']);self.assertTrue(trace['chunk_ids']);r.g.close()
 def test_incomplete_graph_is_not_published(self):
  out=Path(self.cfg['artifact_dir']);write_json(out/'corpus/manifest.json',{'chunks':2});write_json(out/'extraction/status.json',{'failed_chunks':{},'partial_run':True,'completed_chunks':1})
  with self.assertRaises(ValueError):build_graph(self.cfg)
  self.assertFalse((out/'graph.sqlite').exists())
 def test_invalid_json_retry_is_bounded(self):
  class Bad:
   calls=0
   def generate_many(self,stage,requests,max_tokens):
    self.calls+=1;return {i:{'raw_text':'not json','possibly_truncated':False} for i,p in requests}
  bad=Bad();good,errors=validated_generations(bad,'test',[('q','prompt')],100,lambda i,x:x);self.assertEqual(bad.calls,3);self.assertFalse(good);self.assertIn('q',errors)
 def test_external_api_never_enabled_implicitly(self):
  self.cfg['backend']='upstage'
  with self.assertRaises(ValueError):LocalLLM(self.cfg)
 def test_json_fences_and_boolean_type(self):
  self.assertEqual(parse_json('```json\n{"correct": false}\n```'),{'correct':False})

if __name__=='__main__':unittest.main()
