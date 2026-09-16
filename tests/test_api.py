import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from finance_graph.common import config
from finance_graph.llm import APILLM, LocalLLM, create_llm


class APITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.cfg=config(backend='upstage',artifact_dir=str(self.root/'out'))
  self.key=self.root/'key';self.key.write_text('test-secret-not-a-real-key\n')
  self.cfg['api']['key_file']=str(self.key)
 def response(self,reason='stop'):
  return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer":"ok"}'),finish_reason=reason)],usage=SimpleNamespace(completion_tokens=12,model_dump=lambda:{'completion_tokens':12}),model='solar-pro4')
 def test_selection_and_isolation(self):
  local=config();api=config(backend='upstage')
  self.assertIsInstance(create_llm(local),LocalLLM)
  self.assertIsInstance(create_llm(api),APILLM)
  self.assertNotEqual(local['artifact_dir'],api['artifact_dir'])
  self.assertIsNone(api['local_extraction_fallback'])
  self.assertEqual(api['model_id'],'solar-pro4')
  with self.assertRaises(ValueError):config(backend='unknown')
 def test_portable_config_paths_ignore_working_directory(self):
  import os
  from finance_graph.common import ROOT
  cwd=Path.cwd()
  try:
   os.chdir(self.root)
   c=config(ROOT/'config.api.example.json')
   self.assertEqual(c['dataset_root'],str(ROOT/'data/documents'))
   self.assertEqual(c['benchmark_path'],str(ROOT/'data/benchmark.json'))
   self.assertEqual(c['api']['key_file'],str(ROOT/'.secrets/upstage_api_key'))
   local=config(ROOT/'config.api.example.json',backend='local_mlx')
   self.assertEqual(local['model_path'],str(ROOT/'models/gemma'))
   self.assertEqual(local['local_extraction_fallback']['model_path'],str(ROOT/'models/qwen'))
  finally:os.chdir(cwd)
 def test_absolute_and_home_paths(self):
  from finance_graph.common import write_json
  c=config();c['dataset_root']=str(self.root);c['benchmark_path']='~/benchmark.json'
  path=self.root/'config.json';write_json(path,c);resolved=config(path)
  self.assertEqual(resolved['dataset_root'],str(self.root.resolve()))
  self.assertEqual(resolved['benchmark_path'],str((Path.home()/'benchmark.json').resolve()))
 def test_request_cache_and_secret_exclusion(self):
  with patch('openai.OpenAI') as sdk:
   client=sdk.return_value;client.chat.completions.create.return_value=self.response()
   llm=APILLM(self.cfg)
   first=llm.generate_many('test',[('a','hello')],100)['a']
   second=llm.generate_many('test',[('b','hello')],100)['b']
   self.assertEqual(second['request_id'],'b');self.assertEqual(first['request_hash'],second['request_hash'])
   self.assertEqual(client.chat.completions.create.call_count,1)
   client.chat.completions.create.assert_called_with(model='solar-pro4',messages=[{'role':'user','content':'hello'}],reasoning_effort='medium',max_tokens=100)
   self.assertEqual(sdk.call_args.kwargs['api_key'],'test-secret-not-a-real-key')
   self.assertNotIn('test-secret-not-a-real-key',json.dumps(self.cfg))
   for p in (self.root/'out').rglob('*.json'):self.assertNotIn('test-secret-not-a-real-key',p.read_text())
   llm.generate_many('test',[('a','hello')],100,use_cache=False)
   self.assertEqual(client.chat.completions.create.call_count,2)
   self.cfg['api']['reasoning_effort']='low';llm.generate_many('test',[('a','hello')],100)
   self.assertEqual(client.chat.completions.create.call_count,3)
   llm.unload();client.close.assert_called_once()
 def test_missing_key_and_length(self):
  self.key.write_text('')
  with self.assertRaisesRegex(ValueError,'Paste your Upstage API key'):APILLM(self.cfg).load()
  self.key.write_text('test-key')
  with patch('openai.OpenAI') as sdk:
   sdk.return_value.chat.completions.create.return_value=self.response('length')
   self.assertTrue(APILLM(self.cfg).generate_many('test',[('a','hello')],100)['a']['possibly_truncated'])
 def test_error_does_not_expose_response_body(self):
  import httpx
  from openai import AuthenticationError
  with patch('openai.OpenAI') as sdk:
   sdk.return_value.chat.completions.create.side_effect=AuthenticationError('test-secret-not-a-real-key',response=httpx.Response(401,request=httpx.Request('POST','https://api.upstage.ai/v1/chat/completions')),body=None)
   with self.assertRaises(RuntimeError) as caught:APILLM(self.cfg).generate_many('test',[('a','hello')],100)
   self.assertNotIn('test-secret',str(caught.exception));self.assertIn('401',str(caught.exception))

if __name__=='__main__':unittest.main()
