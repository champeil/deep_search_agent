"""Offline contract/routing/accounting tests. These do not assert live provider quality."""
import io
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/deep-research-agent/scripts'))
import research as backend
import research_providers as p

URL='https://example.org/paper'
TEXT='This public article provides methods and results with enough actual text for an evidence import.'
RESULT={'url':URL,'title':'Original paper','snippet':'Actual snippet','content':'Actual content','name':'Original paper','description':'Actual description'}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{key:'fixture-'+name for name,key in p.KEYS.items()},clear=True)
        self.env.start();self.addCleanup(self.env.stop)

    def test_all_ten_search_contracts(self):
        shapes={name:{'results':[RESULT]} for name in p.KEYS}
        shapes.update(firecrawl={'success':True,'data':{'web':[RESULT]}},anysearch={'data':{'results':[RESULT]}},
                      serpapi={'organic_results':[{'link':URL,'title':'Paper','snippet':'Actual snippet'}]},
                      serpsearch={'organic_results':[{'url':URL,'title':'Paper','description':'Actual description'}]})
        for name in p.KEYS:
            with self.subTest(provider=name):
                req=p.build_request(name,'search','endothelial cancer','academic')
                self.assertTrue(req.full_url.startswith(p.ORIGINS[name]+'/'))
                self.assertEqual(req.get_method(),'GET' if name in {'serpapi','serpsearch'} else 'POST')
                out=p.normalize(name,'search',shapes[name],'endothelial cancer')
                self.assertEqual(out[0]['url'],URL)
                self.assertEqual(out[0]['read_scope'],'search_snippet')
        self.assertIn('google_scholar',p.build_request('serpapi','search','x','academic').full_url)
        self.assertIn('/v1/search',p.build_request('parallel','search','x').full_url)
        body=json.loads(p.build_request('linkup','search','x').data)
        self.assertEqual(body['outputType'],'searchResults')

    def test_all_seven_extraction_contracts_and_conservative_scope(self):
        shapes={'tavily':{'results':[{'url':URL,'raw_content':TEXT}]},
                'exa':{'results':[{'url':URL,'text':TEXT}]},
                'parallel':{'results':[{'url':URL,'full_content':TEXT}]},
                'firecrawl':{'success':True,'data':{'markdown':TEXT,'metadata':{'title':'Paper'}}},
                'linkup':{'markdown':TEXT},'keenable':{'url':URL,'content':TEXT},
                'anysearch':{'data':{'url':URL,'title':'Paper','content':TEXT}}}
        for name in p.EXTRACT:
            with self.subTest(provider=name):
                req=p.build_request(name,'extract',URL)
                text=p.normalize(name,'extract',shapes[name],URL)
                self.assertEqual(text['text'],TEXT)
                self.assertEqual(text['read_scope'],'partial_text')
        body=json.loads(p.build_request('parallel','extract',URL).data)
        self.assertEqual(body['advanced_settings'],{'full_content':True})
        self.assertNotIn('full_content',body)

    def test_specialty_and_prefix(self):
        for task in p.TASKS:
            plan=p.route(task)
            self.assertEqual(plan['remote_order'][0],'perplexity')
        self.assertEqual(p.route('academic')['remote_order'][1],'exa')
        self.assertEqual(p.route('exact')['remote_order'][1],'serpapi')
        self.assertEqual(p.route('chinese')['remote_order'][1],'anysearch')
        self.assertEqual(p.route(operation='extract')['remote_order'][0],'firecrawl')
        self.assertNotIn('perplexity',p.route(operation='extract')['remote_order'])

    def test_economy_avoids_deeper_modes(self):
        self.assertEqual(json.loads(p.build_request('perplexity','search','x',strategy='economy').data)['search_type'],'fast')
        self.assertEqual(json.loads(p.build_request('tavily','search','x',strategy='economy').data)['search_depth'],'basic')
        self.assertEqual(json.loads(p.build_request('parallel','search','x',strategy='economy').data)['mode'],'turbo')
        self.assertEqual(json.loads(p.build_request('exa','search','x',strategy='economy').data)['type'],'lite')

    def test_missing_disabled_and_custom_order(self):
        with patch.dict(os.environ,{'PERPLEXITY_API_KEY':'','RESEARCH_DISABLED_PROVIDERS':'tavily','RESEARCH_PROVIDER_ORDER':'serpapi,exa'}):
            self.assertEqual(p.route()['remote_order'][:2],['serpapi','exa'])
            self.assertNotIn('tavily',p.route()['remote_order'])
        self.assertEqual(p.route(provider='tavily')['remote_order'],['tavily'])
        with patch.dict(os.environ,{'RESEARCH_PROVIDER_ORDER':'unknown'}):
            with self.assertRaises(ValueError):p.route()

    def test_keyless_is_opt_in_and_named(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(p.route()['remote_order'],[])
            with patch.dict(os.environ,{'RESEARCH_ALLOW_KEYLESS_KEENABLE':'true'}):
                self.assertEqual(p.route()['remote_order'],['keenable'])
                req=p.build_request('keenable','search','x')
                self.assertTrue(req.full_url.endswith('/v1/search/public'))
                self.assertEqual(req.get_header('X-keenable-title'),'Deep Research Agent')
                self.assertIsNone(req.get_header('X-api-key'))
                self.assertFalse(p.configured('parallel'))

    def test_no_credentials_in_normalized_output(self):
        secret=os.environ['ANYSEARCH_API_KEY']
        out=p.normalize('anysearch','search',{'data':{'results':[{**RESULT,'content':secret}]}},'x')
        self.assertNotIn(secret,json.dumps(out))
        out=p.numeric_usage({'usage':{'credits':2,'key':secret},'credentials':secret})
        self.assertEqual(out,{'usage':{'credits':2}})

    def test_raw_http_errors_are_redacted(self):
        secret='new-generated-secret-never-print'
        err=urllib.error.HTTPError('https://serpapi.com/search.json?api_key='+secret,402,secret,{},io.BytesIO(secret.encode()))
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=err
            with self.assertRaises(p.ProviderError) as ctx:p.raw_request(p.build_request('serpapi','search','x'))
        self.assertNotIn(secret,str(ctx.exception))
        self.assertEqual(ctx.exception.http_status,402)

    def test_unexpected_or_blocked_content_is_not_evidence(self):
        for raw in ({'data':{'content':'Access denied: please verify your identity'}},{'data':{}},{'error':'private-secret'}):
            with self.subTest(raw=raw):
                with self.assertRaises(p.ProviderError):p.normalize('anysearch','extract',raw,URL)
        with self.assertRaises(p.ProviderError):p.normalize('exa','search',{'unrecognized':True},'x')

    def test_private_targets_and_credentials_rejected(self):
        for url in ('http://127.0.0.1/','http://169.254.169.254/latest','http://localhost/','http://internal/','https://u:p@example.org/'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):p.build_request('tavily','extract',url)

    def test_legacy_search_preference_does_not_pin_extraction(self):
        with patch.dict(os.environ,{'RESEARCH_SEARCH_PROVIDER':'tavily'}):
            self.assertEqual(p.route()['remote_order'],['tavily'])
            self.assertEqual(p.route(operation='extract')['remote_order'][0],'firecrawl')
            self.assertEqual(p.route(operation='extract',provider='exa')['remote_order'],['exa'])

    def test_heading_does_not_hide_login_gate(self):
        text='# Publisher\n\nSign in to continue. Your institution may provide access to this article.'
        with self.assertRaises(p.ProviderError):p.normalize('firecrawl','extract',{'data':{'markdown':text}},URL)

    def test_parallel_does_not_truncate_long_intent(self):
        q='alpha '*150
        req=p.build_request('parallel','search',q)
        body=json.loads(req.data)
        self.assertEqual(body['objective'],q.strip())
        self.assertTrue(all(len(x)<=200 for x in body['search_queries']))


class RoutingIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'PERPLEXITY_API_KEY':'pp-fixture','TAVILY_API_KEY':'tv-fixture'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        self.tools=backend.ResearchTools(self.temp.name)
        self.run=self.begin()

    def begin(self):
        return self.tools.call('research_begin',{'question':'A retrieval test','subquestions':[{'id':'Q1','question':'Evidence?'}]})['run_id']

    def search(self,**overrides):
        return self.tools.call('research_search',{'run_id':self.run,'query':'real gap query','round':1,'purpose':'gap','native_status':'unavailable',**overrides})

    def status(self):return self.tools.call('research_status',{'run_id':self.run})['retrieval_usage']

    def test_native_guard_never_calls_remote(self):
        with patch.object(p,'retrieve',side_effect=AssertionError('network must not happen')):
            self.assertEqual(self.search(native_status='unknown')['status'],'needs_native')
            self.assertEqual(self.search(native_status='available')['status'],'needs_native')
            self.assertEqual(self.tools.call('research_providers',{})['remote_order'],['perplexity','tavily'])
        self.assertEqual(self.status()['remote_api_attempts'],0)

    def test_failure_fallback_accounts_all_attempts(self):
        payload={'data':[RESULT],'usage_reported':{'usage':{'credits':1}}}
        with patch.object(p,'retrieve',side_effect=[p.ProviderError('http_error',429),payload]) as call:
            result=self.search()
        self.assertEqual(result['provider'],'tavily')
        self.assertEqual(call.call_count,2)
        usage=self.status()
        self.assertEqual(usage['remote_api_attempts'],2)
        self.assertEqual(usage['by_provider']['perplexity']['failed'],1)
        self.assertEqual(usage['by_provider']['tavily']['succeeded'],1)
        self.assertIsNone(usage['host_model_tokens'])
        self.assertEqual(len(self.tools.store.get(self.run)['searches']),1)

    def test_cross_run_cache_does_not_double_count_requests_or_usage(self):
        with patch.object(p,'retrieve',return_value={'data':[RESULT],'usage_reported':{'usage':{'credits':1}}}) as call:
            self.search();self.run=self.begin();result=self.search()
            self.assertEqual(call.call_count,1)
        self.assertTrue(result['cache_hit'])
        self.assertEqual(self.status()['remote_api_attempts'],0)
        self.assertEqual(self.status()['events'][0]['usage_reported'],{})

    def test_request_budget_counts_failure_and_blocks_before_network(self):
        with patch.dict(os.environ,{'RESEARCH_MAX_API_REQUESTS':'1'}),patch.object(p,'retrieve',side_effect=p.ProviderError('http_error',500)) as call:
            with self.assertRaises(ValueError):self.search()
            self.assertEqual(call.call_count,1)
        self.assertEqual(self.status()['remote_api_attempts'],1)
        self.assertEqual(self.tools.store.get(self.run)['retrieval_pending'],{})

    def test_max_fallback_and_cooldown(self):
        with patch.dict(os.environ,{'RESEARCH_MAX_ATTEMPTS':'1'}),patch.object(p,'retrieve',side_effect=p.ProviderError('http_error',401)) as call:
            self.assertEqual(self.search()['status'],'unavailable')
            self.assertEqual(call.call_count,1)
        with patch.object(p,'retrieve',return_value={'data':[RESULT],'usage_reported':{}}) as call:
            self.assertEqual(self.search(query='another gap query')['provider'],'tavily')
            self.assertEqual(call.call_args.args[0],'tavily')

    def test_duplicate_query_does_not_make_a_paid_call(self):
        with patch.object(p,'retrieve',return_value={'data':[RESULT],'usage_reported':{}}) as call:
            self.search()
            with self.assertRaises(ValueError):self.search()
            self.assertEqual(call.call_count,1)

    def test_extract_imports_real_text_without_claiming_full_article(self):
        page={'url':URL,'title':'Paper','text':TEXT,'note':'Inspect actual scope'}
        with patch.object(p,'retrieve',return_value={'data':page,'usage_reported':{}}):
            result=self.tools.call('research_extract',{'run_id':self.run,'url':URL,'native_status':'failed'})
        self.assertEqual(result['read_scope'],'partial_text')
        saved=self.tools.store.get(self.run)['sources'][result['source_id']]
        self.assertEqual(saved['text'],TEXT)
        self.assertEqual(saved['provenance']['provider'],'tavily')
        self.assertEqual(self.status()['remote_api_attempts'],1)

    def test_normalization_error_retains_reported_usage(self):
        raw={'success':True,'usage':{'credits':2},'data':{'markdown':'# Publisher\nSign in to continue. Your institution may provide access to this article.'}}
        with patch.object(p,'raw_request',return_value=raw):
            self.tools.call('research_extract',{'run_id':self.run,'url':URL,'provider':'tavily','native_status':'failed'})
        # Tavily uses a different raw shape but the same malformed response is rejected after usage collection.
        self.assertEqual(self.status()['events'][0]['usage_reported'],{'usage':{'credits':2}})
        self.assertEqual(self.status()['remote_api_attempts'],1)

    def test_scope_correction_is_persisted_and_invalidates_review(self):
        args={'run_id':self.run,'url':URL,'title':'Paper','text':TEXT,'read_scope':'partial_text','provenance':{'provider':'test'}}
        sid=self.tools.call('research_source',args)['source_id']
        eid=self.tools.call('research_quote',{'run_id':self.run,'source_id':sid,'quote':TEXT[:60]})['evidence_id']
        cid=self.tools.call('research_claim',{'run_id':self.run,'question_id':'Q1','text':'A narrow supported claim','evidence_ids':[eid]})['claim_id']
        self.tools.call('research_review',{'run_id':self.run,'claim_id':cid,'verdict':'supported','reason':'Actual surrounding context considered','supporting_evidence_ids':[eid]})
        corrected=self.tools.call('research_source',{**args,'read_scope':'abstract'})
        self.assertEqual(corrected['read_scope'],'abstract')
        inspected=self.tools.call('research_inspect_source',{'run_id':self.run,'source_id':sid})
        self.assertEqual(inspected['read_scope'],'abstract')
        self.assertNotIn('review',self.tools.store.get(self.run)['claims'][cid])
        with self.assertRaises(ValueError):self.tools.call('research_source',args)

    def test_direct_pdf_page_locations_survive_import(self):
        page={'url':URL,'title':'PDF paper','text':TEXT,'read_scope':'parsed_text','extraction':'pdf_text','raw_sha256':'fixture',
              'passages':[{'id':'P0001','start':0,'end':len(TEXT),'page':3,'text':TEXT}]}
        with patch('research_reader.Reader.read',return_value=page):
            result=self.tools.call('research_read',{'run_id':self.run,'url':URL})
        source=self.tools.call('research_inspect_source',{'run_id':self.run,'source_id':result['source_id']})
        self.assertEqual(source['page_locations'][0]['page'],3)
        self.assertEqual(source['read_scope'],'partial_text')
        quote=self.tools.call('research_quote',{'run_id':self.run,'source_id':result['source_id'],'quote':TEXT[:50]})
        self.assertEqual(quote['pages'],[3])

    def test_malformed_response_retains_reported_credits(self):
        with patch.dict(os.environ,{'EXA_API_KEY':'exa-fixture'}),patch.object(p,'raw_request',return_value={'usage':{'credits':3},'results':123}):
            self.tools.call('research_extract',{'run_id':self.run,'url':URL,'provider':'exa','native_status':'failed'})
        self.assertEqual(self.status()['events'][0]['usage_reported'],{'usage':{'credits':3}})
        self.assertEqual(self.status()['events'][0]['error'],'invalid_response_shape')

    def test_existing_abstract_can_gain_pdf_locations_without_scope_upgrade(self):
        sid=self.tools.call('research_source',{'run_id':self.run,'url':URL,'title':'Paper','text':TEXT,'read_scope':'abstract','provenance':{'provider':'fixture'}})['source_id']
        page={'url':URL,'title':'PDF paper','text':TEXT,'read_scope':'parsed_text','extraction':'pdf_text','raw_sha256':'fixture',
              'passages':[{'id':'P0001','start':0,'end':len(TEXT),'page':2,'text':TEXT}]}
        with patch('research_reader.Reader.read',return_value=page):self.tools.call('research_read',{'run_id':self.run,'url':URL})
        source=self.tools.call('research_inspect_source',{'run_id':self.run,'source_id':sid})
        self.assertEqual(source['page_locations'][0]['page'],2)
        self.assertEqual(source['reader_extraction'],'pdf_text')
        self.assertEqual(source['read_scope'],'abstract')

    def test_terminal_fallback_discovers_project_env_without_exposing_key(self):
        root=Path(self.temp.name)/'project'
        envdir=root/'.deep-research';envdir.mkdir(parents=True)
        (envdir/'research.env').write_text('RESEARCH_SEARCH_PROVIDER=auto\nEXA_API_KEY=never-echo-this-fixture\n')
        child=root/'nested';child.mkdir()
        env={k:v for k,v in os.environ.items() if k not in p.CONFIG}
        result=subprocess.run([sys.executable,str(Path(backend.__file__)),'doctor'],cwd=child,env=env,capture_output=True,text=True,check=True)
        data=json.loads(result.stdout)
        self.assertEqual(data['routing']['remote_order'],['exa'])
        self.assertNotIn('never-echo-this-fixture',result.stdout)

    def test_no_keys_does_not_make_a_request(self):
        with patch.dict(os.environ,{},clear=True),patch.object(p,'retrieve',side_effect=AssertionError('network')):
            with self.assertRaises(ValueError):self.search()
        self.assertEqual(self.status()['remote_api_attempts'],0)


if __name__=='__main__':unittest.main()
