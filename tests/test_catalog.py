"""Domain/source planning, honest coverage and public API contract regressions."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/deep-research-agent/scripts'))
import research as backend
import research_catalog as c
import research_providers as p

EPMC={'hitCount':1,'resultList':{'result':[{'id':'123','source':'MED','title':'Test paper','abstractText':'An actual supplied abstract reports an association, not a causal result.','pmid':'123','doi':'10.1234/test','pubTypeList':{'pubType':['Journal Article']}}]}}
CROSSREF={'message':{'total-results':1,'items':[{'DOI':'10.1234/test','title':['Test paper'],'type':'journal-article'}]}}
XML=b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Supplied test paper</ArticleTitle><Abstract><AbstractText Label="RESULTS">An association was reported but no causal effect was established.</AbstractText></Abstract><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'


class SourcePlanning(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{},clear=True);self.env.start();self.addCleanup(self.env.stop)
        self.tools=backend.ResearchTools(self.temp.name)
        self.run=self.begin('肿瘤内皮细胞的单细胞异质性与治疗反应')

    def begin(self,question):return self.tools.call('research_begin',{'question':question,'subquestions':[{'id':'Q1','question':'What does the evidence support?'}]})['run_id']
    def plan(self,**args):return self.tools.call('research_plan',{'run_id':self.run,**args})
    def state(self):return self.tools.store.get(self.run)
    def cov(self):return self.tools.call('research_status',{'run_id':self.run})['source_coverage']
    def db(self,sid='europepmc',**args):return self.tools.call('research_database_search',{'run_id':self.run,'catalog_source_id':sid,'query':'endothelial tumor','round':1,'purpose':'discovery','native_status':'unavailable',**args})
    def source(self,url='https://pubmed.ncbi.nlm.nih.gov/123/',scope='abstract'):
        return self.tools.call('research_source',{'run_id':self.run,'url':url,'title':'Supplied offline test text','text':'This supplied passage describes association and does not establish causality.','read_scope':scope,'provenance':{'provider':'offline-test-reader'}})['source_id']

    def test_multi_domain_small_initial_plan_needs_host_review(self):
        plan=self.state()['source_plan']
        self.assertTrue({'biomed','omics','clinical'}<=set(plan['domains']))
        self.assertTrue(plan['needs_host_review'])
        self.assertEqual(plan['policy'],'preferred')
        self.assertLessEqual(len(plan['source_ids']),8)
        self.assertFalse(any(row['database_searched'] for row in self.cov()['sources']))

    def test_unknown_domain_falls_back_without_forcing_classification(self):
        rid=self.begin('ZXQ 123 question')
        plan=self.tools.store.get(rid)['source_plan']
        self.assertEqual(plan['domains'],['general'])
        self.assertTrue(plan['open_web_fallback'])
        self.assertNotIn('computing',[x['id'] for x in c.choose_domains('capital of Spain')])

    def test_host_confirms_domains_and_actual_synonyms(self):
        plan=self.plan(domains=['biomed','omics'],concepts=[{'terms':['tumor','cancer']},{'terms':['endothelial cells']}],source_ids=['pubmed','geo'])
        self.assertFalse(plan['needs_host_review'])
        self.assertIn('("tumor" OR "cancer") AND ("endothelial cells")',plan['query'])
        self.assertEqual(plan['query_suggestions'][0]['available_adapter'],'pubmed')
        self.assertIsNone(plan['query_suggestions'][1]['available_adapter'])
        self.assertEqual(len(self.state()['plan_history']),2)

    def test_invalid_domains_and_requirements_rejected(self):
        for args in ({'domains':['fictional']},{'source_ids':['unknown']},{'source_ids':['pmc'],'required_source_ids':['pubmed']},{'concepts':[{'terms':[]}]},{'policy':'strict_domains','source_ids':[]}):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):self.plan(**args)

    def test_reading_page_does_not_claim_database_search(self):
        self.source()
        row=next(x for x in self.cov()['sources'] if x['source_id']=='pubmed')
        self.assertEqual(row['read_scopes']['abstract'],1)
        self.assertFalse(row['database_searched'])
        self.assertFalse(row['site_searched'])

    def test_site_search_cannot_satisfy_required_native_database(self):
        self.plan(source_ids=['pubmed'],required_source_ids=['pubmed'])
        self.tools.call('research_log_search',{'run_id':self.run,'query':'site:pubmed.ncbi.nlm.nih.gov tumor endothelial','round':1,'purpose':'discovery','provider':'host-web','result_count':3,'catalog_source_id':'pubmed','access_method':'site_search','tool_reference':'actual-host-reference'})
        row=self.cov()['sources'][0]
        self.assertTrue(row['site_searched']);self.assertFalse(row['database_searched'])
        self.assertEqual(self.cov()['required_missing'],['pubmed'])

    def test_host_native_database_is_explicitly_attested(self):
        self.plan(source_ids=['pubmed'],required_source_ids=['pubmed'])
        self.tools.call('research_log_search',{'run_id':self.run,'query':'endothelial tumor','round':1,'purpose':'discovery','provider':'host-pubmed','result_count':0,'catalog_source_id':'pubmed','access_method':'native_database','tool_reference':'actual-host-reference'})
        self.assertEqual(self.cov()['required_missing'],[])
        self.assertEqual(self.state()['source_attempts'][0]['verification'],'host_attested')
        self.assertEqual(self.state()['source_attempts'][0]['outcome'],'empty')
        self.assertFalse(self.cov()['complete_database_coverage'])

    def test_failure_log_cannot_invent_success(self):
        with self.assertRaises(ValueError):self.tools.call('research_source_attempt',{'run_id':self.run,'catalog_source_id':'pubmed','outcome':'searched','reason':'Not actually searched'})
        self.tools.call('research_source_attempt',{'run_id':self.run,'catalog_source_id':'pubmed','outcome':'unavailable','reason':'Native tool absent and HTTP path unavailable'})
        self.assertEqual(next(r for r in self.cov()['sources'] if r['source_id']=='pubmed')['last_outcome'],'unavailable')

    def test_missing_required_database_forces_partial_and_exports_coverage(self):
        self.plan(source_ids=['pubmed'],required_source_ids=['pubmed'])
        sid=self.source()
        quote=self.tools.call('research_quote',{'run_id':self.run,'source_id':sid,'quote':'This supplied passage describes association'})['evidence_id']
        cid=self.tools.call('research_claim',{'run_id':self.run,'question_id':'Q1','text':'The supplied material describes association.','evidence_ids':[quote]})['claim_id']
        self.tools.call('research_review',{'run_id':self.run,'claim_id':cid,'verdict':'supported','reason':'This limited statement is supported by the supplied context','supporting_evidence_ids':[quote]})
        for query,round,purpose in [('first query',1,'discovery'),('counter query',2,'counter')]:self.tools.call('research_log_search',{'run_id':self.run,'query':query,'round':round,'purpose':purpose,'provider':'fixture-host','result_count':1})
        result=self.tools.call('research_publish',{'run_id':self.run,'claim_ids':[cid],'limitations':[],'stop_reason':'coverage_sufficient'})
        self.assertEqual(result['status'],'partial')
        audit=json.loads(Path(result['audit_path']).read_text(encoding='utf-8'))
        self.assertEqual(audit['source_coverage']['required_missing'],['pubmed'])
        self.assertIn('必须原生检索但尚未完成',Path(result['report_path']).read_text(encoding='utf-8'))

    def test_dynamic_source_needs_actual_matching_saved_page(self):
        sid=self.source('https://official.example.org/docs/')
        result=self.tools.call('research_add_source',{'run_id':self.run,'source_id':'custom_docs','name':'Extra official docs','homepage':'https://official.example.org/docs/','verification_source_id':sid,'reason':'Needed version-specific primary documentation'})
        self.assertIsNone(result['registered']['adapter'])
        self.plan(source_ids=['pubmed','custom_docs'])
        self.assertFalse(self.cov()['sources'][-1]['database_searched'])
        with self.assertRaises(ValueError):self.tools.call('research_add_source',{'run_id':self.run,'source_id':'custom_false','name':'Wrong','homepage':'https://different.example.org/','verification_source_id':sid,'reason':'Needs another verified source'})
        self.assertNotIn('custom_false',self.state().get('custom_sources',{}))

    def test_fixture_cannot_verify_a_new_registry_source(self):
        sid=self.source('https://example.org/test',scope='test_fixture')
        with self.assertRaises(ValueError):self.tools.call('research_add_source',{'run_id':self.run,'source_id':'custom_test','name':'Test','homepage':'https://example.org/','verification_source_id':sid,'reason':'Attempt to register a fixture source'})

    def test_strict_url_prefixes_reject_deceptive_hosts_and_wrong_paths(self):
        self.plan(source_ids=['geo'],policy='strict_domains')
        for url in ('https://www.ncbi.nlm.nih.gov.evil.example/geo/','https://www.ncbi.nlm.nih.gov/sra/','https://example.org/'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):self.source(url)
        self.source('https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE1')
        self.assertEqual(len(self.state()['sources']),1)

    def test_native_guard_and_unsupported_adapter_make_no_calls(self):
        with patch.object(p,'raw_request',side_effect=AssertionError('no network')):
            self.assertEqual(self.db(native_status='unknown')['status'],'needs_native')
            with self.assertRaises(ValueError):self.db('geo')
        self.assertEqual(self.state().get('retrieval_events',[]),[])

    def test_europepmc_native_query_metered_one_request_and_abstract_only(self):
        with patch.object(p,'raw_request',return_value=EPMC) as call:
            result=self.db()
        self.assertEqual(call.call_count,1)
        self.assertEqual(result['results'][0]['read_scope'],'abstract')
        self.assertEqual(self.state()['source_attempts'][0]['method'],'database_api')
        self.assertEqual(self.tools.call('research_status',{'run_id':self.run})['retrieval_usage']['remote_api_attempts'],1)
        self.assertEqual(len(self.state()['sources']),0)

    def test_pubmed_two_http_requests_preserve_abstract_and_fulltext_link(self):
        response=io.BytesIO(XML)
        with patch.object(p,'raw_request',return_value={'esearchresult':{'idlist':['123'],'count':'1','querytranslation':'translated query'}}),patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value=response
            result=self.db('pubmed')
        self.assertEqual(len(self.state()['retrieval_events']),2)
        self.assertEqual(result['query_translation'],'translated query')
        self.assertEqual(result['results'][0]['read_scope'],'abstract')
        self.assertIn('PMC123',result['results'][0]['fulltext_urls'][0])

    def test_pubmed_second_request_cap_prevents_network_and_records_gap(self):
        with patch.dict(os.environ,{'RESEARCH_MAX_API_REQUESTS':'1'}),patch.object(p,'raw_request',return_value={'esearchresult':{'idlist':['123'],'count':'1'}}),patch('urllib.request.build_opener',side_effect=AssertionError('second request must not happen')):
            with self.assertRaises(ValueError):self.db('pubmed')
        self.assertEqual(len(self.state()['retrieval_events']),1)
        self.assertEqual(self.state()['source_attempts'][0]['outcome'],'failed')
        self.assertEqual(self.state()['retrieval_pending'],{})

    def test_same_query_allowed_across_databases_not_repeated_within_one(self):
        with patch.object(p,'raw_request',side_effect=[EPMC,CROSSREF]):
            self.db('europepmc');self.db('crossref')
        self.assertEqual(len(self.state()['searches']),2)
        with patch.object(p,'raw_request',side_effect=AssertionError('duplicate')):
            with self.assertRaises(ValueError):self.db('europepmc')

    def test_crossref_metadata_is_not_mislabeled_as_abstract_or_fulltext(self):
        with patch.object(p,'raw_request',return_value=CROSSREF):result=self.db('crossref')
        self.assertEqual(result['results'][0]['read_scope'],'metadata')
        self.assertEqual(result['results'][0]['abstract'],'')

    def test_malformed_database_response_does_not_mark_successful_coverage(self):
        with patch.object(p,'raw_request',return_value={'unexpected':'shape'}):
            with self.assertRaises(ValueError):self.db()
        self.assertEqual(self.state()['source_attempts'][0]['outcome'],'failed')
        self.assertFalse(next(r for r in self.cov()['sources'] if r['source_id']=='europepmc')['database_searched'])

    def test_site_scoping_filters_results_ignored_by_provider(self):
        self.plan(source_ids=['pubmed'],task='academic')
        with patch.dict(os.environ,{'PERPLEXITY_API_KEY':'offline-fixture','TAVILY_API_KEY':'offline-fixture','RESEARCH_MAX_ATTEMPTS':'2'}),patch.object(p,'retrieve',return_value={'data':[{'url':'https://outside.example.org/','title':'Outside','snippet':'Not in selected prefix'}],'usage_reported':{}}) as request:
            result=self.tools.call('research_search',{'run_id':self.run,'query':'new targeted query','round':1,'purpose':'discovery','catalog_source_id':'pubmed','native_status':'unavailable'})
        self.assertEqual(request.call_count,2)
        self.assertEqual(result['status'],'unavailable')
        self.assertIn('site:pubmed.ncbi.nlm.nih.gov',request.call_args.args[2])
        self.assertFalse(next(r for r in self.cov()['sources'] if r['source_id']=='pubmed')['database_searched'])


if __name__=='__main__':unittest.main()
