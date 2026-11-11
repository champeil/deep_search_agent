import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'deep-research-agent'
SCRIPT = SKILL/'scripts/research.py'
sys.path.insert(0, str(SCRIPT.parent))
import research as module


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tools = module.ResearchTools(self.temp.name)
        self.run = self.tools.call('research_begin', {'question':'Compare supplied methods', 'subquestions':[{'id':'Q1','question':'What is supported?'}]})['run_id']

    def tearDown(self):
        self.temp.cleanup()

    def source(self, **kwargs):
        args = {'run_id':self.run, 'url':'https://example.org/paper','title':'Test source',
                'text':'The supplied study reports an association in twenty samples, but it does not demonstrate a causal effect.',
                'read_scope':'test_fixture','provenance':{'provider':'test-fixture'}}
        args.update(kwargs)
        return self.tools.call('research_source', args)['source_id']

    def supported(self):
        sid = self.source()
        eid = self.tools.call('research_quote', {'run_id':self.run,'source_id':sid,
            'quote':'The supplied study reports an association in twenty samples'})['evidence_id']
        cid = self.tools.call('research_claim', {'run_id':self.run,'question_id':'Q1',
            'text':'The study reports association in twenty samples.', 'evidence_ids':[eid]})['claim_id']
        self.tools.call('research_review', {'run_id':self.run,'claim_id':cid,'verdict':'supported',
            'reason':'The exact original context supports this limited association statement.', 'supporting_evidence_ids':[eid]})
        return sid,eid,cid

    def log(self, query='actual first search', round=1, purpose='discovery'):
        return self.tools.call('research_log_search', {'run_id':self.run,'query':query,'round':round,
            'purpose':purpose,'provider':'test-provider','result_count':2,'tool_reference':'fixture'})

    def publish(self, ids):
        return self.tools.call('research_publish', {'run_id':self.run,'claim_ids':ids,
            'limitations':[], 'stop_reason':'coverage_sufficient'})

    def test_begin_is_host_driven(self):
        state = self.tools.store.get(self.run)
        self.assertEqual(state['claims'],{})
        self.assertEqual(state['budgets']['searches'],18)

    def test_quote_rejects_fabrication(self):
        sid=self.source()
        with self.assertRaises(ValueError):
            self.tools.call('research_quote', {'run_id':self.run,'source_id':sid,'quote':'This is a fabricated exact quote not found anywhere.'})

    def test_offsets_preserve_whitespace_and_unicode(self):
        text='  中文原始段落中的证据必须精确定位，不能修改文字。  '
        sid=self.source(text=text)
        quote='中文原始段落中的证据必须精确定位'
        e=self.tools.call('research_quote', {'run_id':self.run,'source_id':sid,'quote':quote})
        self.assertEqual(text[e['start']:e['end']],quote)
        self.assertEqual(e['start'],2)

    def test_unreviewed_claim_rejected(self):
        _,eid,_=self.supported()
        cid=self.tools.call('research_claim', {'run_id':self.run,'question_id':'Q1','text':'Another atomic candidate claim.', 'evidence_ids':[eid]})['claim_id']
        with self.assertRaises(ValueError):self.publish([cid])

    def test_unknown_evidence_rejected(self):
        with self.assertRaises(ValueError):
            self.tools.call('research_claim', {'run_id':self.run,'question_id':'Q1','text':'This fact has a fake source.', 'evidence_ids':['e_fake']})

    def test_missing_citation_relation_rejected(self):
        _,eid,cid=self.supported()
        with self.assertRaises(ValueError):
            self.tools.call('research_review', {'run_id':self.run,'claim_id':cid,'verdict':'supported',
                'reason':'Unsupported relation is missing.', 'supporting_evidence_ids':[]})

    def test_contradicted_claim_rejected(self):
        _,eid,cid=self.supported()
        self.tools.call('research_review', {'run_id':self.run,'claim_id':cid,'verdict':'contradicted',
            'reason':'Later full context contradicts the initial reading.', 'supporting_evidence_ids':[]})
        with self.assertRaises(ValueError):self.publish([cid])

    def test_tampering_blocks_publication(self):
        sid,_,cid=self.supported()
        self.tools.store.update(self.run, lambda state:state['sources'][sid].update(text='tampered'))
        with self.assertRaises(ValueError):self.publish([cid])

    def test_fixture_is_always_labelled(self):
        _,_,cid=self.supported()
        self.log();self.log('actual counter query',2,'counter')
        result=self.publish([cid])
        self.assertEqual(result['status'],'demonstration')
        self.assertIn('演示材料',Path(result['report_path']).read_text(encoding='utf-8'))
        self.assertNotIn('研究由当前宿主模型执行',Path(result['report_path']).read_text(encoding='utf-8'))

    def test_no_search_returns_partial_not_fake_web_report(self):
        _,_,cid=self.supported()
        self.tools.store.update(self.run,lambda state:state.update(demo=False))
        self.assertEqual(self.publish([cid])['status'],'partial')

    def test_two_rounds_counter_and_coverage_required(self):
        _,_,cid=self.supported()
        self.tools.store.update(self.run,lambda state:state.update(demo=False))
        self.log()
        self.assertEqual(self.publish([cid])['status'],'partial')
        self.log('actual counter query',2,'counter')
        self.assertEqual(self.publish([cid])['status'],'audited')

    def test_same_round_counter_does_not_complete_research(self):
        _,_,cid=self.supported()
        self.tools.store.update(self.run,lambda state:state.update(demo=False))
        self.log();self.log('counter at seed stage',1,'counter')
        self.assertEqual(self.publish([cid])['status'],'partial')

    def test_duplicate_query_does_not_inflate_count(self):
        self.log()
        with self.assertRaises(ValueError):self.log('ACTUAL FIRST SEARCH')
        self.assertEqual(len(self.tools.store.get(self.run)['searches']),1)

    def test_unknown_fields_and_wrong_types_rejected(self):
        for args in [{'run_id':self.run,'extra':True},{'run_id':123}]:
            with self.assertRaises(ValueError):self.tools.call('research_status',args)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):self.tools.call('research_status',{'run_id':'../../secret'})

    def test_native_import_needs_reader_provenance(self):
        with self.assertRaises(ValueError):self.source(provenance={})

    def test_search_key_missing_fails_visibly_without_network(self):
        with patch.dict(os.environ, {'PERPLEXITY_API_KEY':'','TAVILY_API_KEY':''}):
            with patch('urllib.request.build_opener', side_effect=AssertionError('no network')):
                with self.assertRaises(ValueError):self.tools.call('research_search',{'run_id':self.run,'query':'real query','round':1,'purpose':'discovery','native_status':'unavailable'})
        self.assertEqual(self.tools.store.get(self.run)['searches'],[])

    def test_no_model_key_is_required(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'','LLM_API_KEY':'','ANTHROPIC_API_KEY':''}):
            self.supported()

    def test_html_is_escaped(self):
        _,_,cid=self.supported()
        self.tools.store.update(self.run,lambda state:state.update(question='<script>alert(1)</script>'))
        result=self.publish([cid])
        html=Path(result['html_path']).read_text(encoding='utf-8')
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)

    def test_deterministic_reference_mapping(self):
        _,_,cid=self.supported()
        result=self.publish([cid])
        text=Path(result['report_path']).read_text(encoding='utf-8')
        self.assertIn('[1]',text)
        self.assertNotIn('[2]',text)
        self.assertIn('https://example.org/paper',text)

    def test_persistent_state_across_process_instances(self):
        self.supported()
        tools=module.ResearchTools(self.temp.name)
        self.assertEqual(tools.call('research_status',{'run_id':self.run})['coverage'],1)

    def test_cli_roundtrip(self):
        p=Path(self.temp.name)/'input.json';p.write_text(json.dumps({'run_id':self.run}))
        result=subprocess.run([sys.executable,str(SCRIPT),'call','research_status','--root',self.temp.name,'--input',str(p)],capture_output=True,text=True,check=True)
        self.assertTrue(json.loads(result.stdout)['ok'])

    def test_stdio_protocol_has_no_non_protocol_stdout(self):
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'research_status','arguments':{'run_id':self.run}}}]
        result=subprocess.run([sys.executable,str(SCRIPT),'serve','--root',self.temp.name],
            input='\n'.join(json.dumps(x) for x in messages)+'\n',capture_output=True,text=True,check=True)
        rows=[json.loads(x) for x in result.stdout.splitlines()]
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['result']['serverInfo']['name'],'deep-research-agent')
        self.assertEqual(len(rows[1]['result']['tools']),23)
        self.assertFalse(rows[2]['result']['isError'])

    def test_optional_direct_read_rejects_local_addresses(self):
        from research_reader import public_addresses, ReadError
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ReadError):public_addresses('attacker.example',443)


if __name__=='__main__':unittest.main()
