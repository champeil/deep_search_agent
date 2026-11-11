"""Full-text-first policy, section offsets and honest fallback regressions."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/deep-research-agent/scripts'))
import research as b
import research_reading as r
from research_reader import parse_article_xml,ReadError

FULL='https://example.org/paper/full'
ABS='https://example.org/paper/abstract'
PARTS={
 'introduction':'This study asks how endothelial phenotypes relate to the tumor microenvironment.',
 'results':'The measured association differs across the supplied sample groups; no intervention was performed.',
 'methods':'Samples were measured with a specified observational procedure and prespecified analysis.',
 'abstract':'The supplied report describes an association and identifies important design limitations.'}
TEXT='\n\n'.join('## '+k.title()+'\n\n'+v for k,v in PARTS.items())
XML=b'<article><front><article-meta><title-group><article-title>Supplied article</article-title></title-group><abstract><p>An observational association was described in the supplied abstract.</p></abstract></article-meta></front><body><sec><title>Introduction</title><p>Original introduction with sufficient text to inspect actual context.</p></sec><sec><title>Results</title><p>Measured results do not establish a causal intervention effect.</p></sec><sec><title>Methods</title><p>The study used observational samples with a clearly described procedure.</p></sec></body></article>'

class ReadingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.env=patch.dict(os.environ,{},clear=True);self.env.start();self.addCleanup(self.env.stop)
  self.t=b.ResearchTools(self.tmp.name)
  self.run=self.t.call('research_begin',{'question':'Supplied reading policy exercise','subquestions':[{'id':'Q1','question':'What is supported?'}]})['run_id']
  self.doc=self.register()['document_id']
 def register(self,**kwargs):return self.t.call('research_document',{'run_id':self.run,'kind':'paper','title':'Supplied paper','identifier':'doi:10.1234/test','fulltext_urls':[FULL],'summary_urls':[ABS],**kwargs})
 def source(self,url=FULL,text=TEXT,scope='partial_text'):
  return self.t.call('research_source',{'run_id':self.run,'document_id':self.doc,'url':url,'title':'Supplied paper','text':text,'read_scope':scope,'provenance':{'provider':'offline-unit-test'}})['source_id']
 def plan(self):return self.t.call('research_reading_plan',{'run_id':self.run,'document_id':self.doc})
 def annotate(self,sid,sections=None,**kwargs):
  if sections is None:sections=[{'source_id':sid,'section':k,'start':TEXT.index(v),'end':TEXT.index(v)+len(v)} for k,v in PARTS.items()]
  return self.t.call('research_document_read',{'run_id':self.run,'document_id':self.doc,'identity_note':'Title and declared article identifier checked against the supplied source context.','sections':sections,**kwargs})
 def fail(self,**kwargs):return self.t.call('research_document_attempt',{'run_id':self.run,'document_id':self.doc,'method':'native_reader','outcome':'failed','url':FULL,'reason':'Full text could not be retrieved through the actual reader path.','tool_reference':'actual-fixture-reader-reference',**kwargs})

 def test_registration_and_capture_do_not_claim_reading(self):
  self.assertEqual(self.plan()['level'],'not_read')
  self.source()
  self.assertEqual(self.plan()['level'],'not_read')
  self.assertEqual(self.plan()['priority_sections'],['introduction','results','methods','abstract'])

 def test_recorded_priority_spans_satisfy_section_reading(self):
  sid=self.source();result=self.annotate(sid)
  self.assertEqual(result['level'],'primary_sections')
  self.assertEqual(set(result['covered_sections']),set(PARTS))
  self.assertEqual(result['missing_priority_sections'],[])

 def test_abstract_cannot_satisfy_methods_or_results(self):
  sid=self.source(ABS,PARTS['abstract'],scope='abstract')
  for part in ('methods','results','introduction'):
   with self.assertRaises(ValueError):self.annotate(sid,[{'source_id':sid,'section':part,'start':0,'end':len(PARTS['abstract'])}])

 def test_abstract_with_untried_primary_is_unresolved(self):
  sid=self.source(ABS,PARTS['abstract'],scope='abstract')
  result=self.annotate(sid,[{'source_id':sid,'section':'abstract','start':0,'end':len(PARTS['abstract'])}])
  self.assertEqual(result['level'],'fallback_unresolved')
  self.assertFalse(result['fallback_ready'])

 def test_actual_failure_allows_explicit_abstract_only(self):
  self.fail();sid=self.source(ABS,PARTS['abstract'],scope='abstract')
  result=self.annotate(sid,[{'source_id':sid,'section':'abstract','start':0,'end':len(PARTS['abstract'])}])
  self.assertEqual(result['level'],'abstract_only')
  self.assertTrue(result['fallback_reasons'])

 def test_captured_primary_cannot_be_ignored_after_abstract(self):
  self.source();sid=self.source(ABS,PARTS['abstract'],scope='abstract')
  result=self.annotate(sid,[{'source_id':sid,'section':'abstract','start':0,'end':len(PARTS['abstract'])}])
  self.assertEqual(result['level'],'summary_with_primary_unread')
  self.assertFalse(result['fallback_ready'])

 def test_budget_fallback_is_limited_not_claimed_unavailable(self):
  self.t.call('research_document_attempt',{'run_id':self.run,'document_id':self.doc,'method':'budget','outcome':'skipped','reason':'Run budget exhausted before the full-text path could be tried.'})
  sid=self.source(ABS,PARTS['abstract'],scope='abstract')
  result=self.annotate(sid,[{'source_id':sid,'section':'abstract','start':0,'end':len(PARTS['abstract'])}])
  self.assertEqual(result['level'],'abstract_only_limited')
  self.assertFalse(result['fallback_ready'])

 def test_missing_links_need_a_real_discovery_record(self):
  self.doc=self.register(identifier='no-fulltext-link',fulltext_urls=[])['document_id']
  with self.assertRaises(ValueError):self.fail(method='discovery',outcome='not_found',tool_reference='made-up-search')
  self.t.call('research_log_search',{'run_id':self.run,'query':'actual DOI full text query','round':1,'purpose':'gap','provider':'fixture-host','result_count':0,'tool_reference':'real-search-reference'})
  self.t.call('research_document_attempt',{'run_id':self.run,'document_id':self.doc,'method':'discovery','outcome':'not_found','reason':'No usable full text was located in the actually returned search results.','tool_reference':'real-search-reference'})
  sid=self.source(ABS,PARTS['abstract'],scope='abstract')
  self.assertEqual(self.annotate(sid,[{'source_id':sid,'section':'abstract','start':0,'end':len(PARTS['abstract'])}])['level'],'abstract_only')

 def test_observed_absent_section_needs_primary_context(self):
  sid=self.source();spans=[{'source_id':sid,'section':k,'start':TEXT.index(v),'end':TEXT.index(v)+len(v)} for k,v in PARTS.items() if k!='methods']
  result=self.annotate(sid,spans,not_present=[{'source_id':sid,'section':'methods','reason':'Supplied demonstration of an article type with methods integrated into the results.'}])
  self.assertEqual(result['level'],'primary_sections')
  absid=self.source(ABS,PARTS['abstract'],scope='abstract')
  with self.assertRaises(ValueError):self.annotate(absid,[],not_present=[{'source_id':absid,'section':'methods','reason':'Not visible in the abstract alone, which cannot establish absence.'}])

 def test_wrong_offsets_or_unlinked_sources_rejected(self):
  sid=self.source()
  with self.assertRaises(ValueError):self.annotate(sid,[{'source_id':sid,'section':'methods','start':0,'end':len(TEXT)+1}])
  with self.assertRaises(ValueError):self.annotate(sid,[{'source_id':'s_fake','section':'methods','start':0,'end':60}])

 def test_scope_downgrade_invalidates_body_reading(self):
  sid=self.source();self.annotate(sid)
  self.source(scope='abstract')
  result=self.plan()
  self.assertTrue(result['reading_integrity_errors'])
  self.assertNotEqual(result['level'],'primary_sections')

 def test_primary_not_actually_primary_needs_a_failure_reason(self):
  sid=self.source(FULL,PARTS['abstract'],scope='abstract')
  self.annotate(sid,[{'source_id':sid,'section':'abstract','start':0,'end':len(PARTS['abstract'])}])
  self.assertEqual(self.plan()['level'],'fallback_unresolved')
  self.fail(outcome='not_primary',reason='The actual returned page contains only an abstract, not the article body.')
  self.assertEqual(self.plan()['level'],'abstract_only')

 def test_direct_reader_failure_is_recorded_and_no_capture_fabricated(self):
  with patch('research_reader.Reader.read',side_effect=ReadError('reader unavailable')):
   with self.assertRaises(ReadError):self.t.call('research_read',{'run_id':self.run,'document_id':self.doc,'url':FULL})
  doc=self.t.store.get(self.run)['documents'][self.doc]
  self.assertEqual(doc['captures'],{})
  self.assertEqual(doc['attempts'][0]['verification'],'backend_attempt')

 def test_invalid_document_extraction_is_rejected_before_api(self):
  with patch.dict(os.environ,{'TAVILY_API_KEY':'fixture'}),patch('research_providers.retrieve',side_effect=AssertionError('no paid call')):
   with self.assertRaises(ValueError):self.t.call('research_extract',{'run_id':self.run,'document_id':self.doc,'url':'https://different.example.org/','native_status':'unavailable'})
  self.assertEqual(self.t.store.get(self.run).get('retrieval_events',[]),[])

 def test_identity_note_and_section_hints_are_not_reading(self):
  hints=r.section_hints(TEXT)
  self.assertEqual({x['section'] for x in hints},set(PARTS))
  sid=self.source()
  with self.assertRaises(ValueError):self.t.call('research_document_read',{'run_id':self.run,'document_id':self.doc,'identity_note':'guess','sections':[{'source_id':sid,'section':'methods','start':0,'end':50}]})
  self.assertEqual(self.plan()['level'],'not_read')

 def test_non_paper_profiles_prioritize_primary_contracts(self):
  for kind in ('technical','policy','dataset','news','business','general'):
   result=self.register(kind=kind,identifier='supplied-'+kind)
   self.assertEqual(result['candidates'][0]['role'],'primary')
   self.assertIn('summary',[x['role'] for x in result['candidates']])
   self.assertTrue(result['priority_sections'])

 def test_jats_xml_preserves_main_section_headings(self):
  title,text=parse_article_xml(XML)
  self.assertEqual(title,'Supplied article')
  self.assertTrue({'abstract','introduction','results','methods'}<={h['section'] for h in r.section_hints(text)})
  self.assertIn('causal intervention effect',text)

 def test_xml_rejects_entity_expansion_and_malformed_input(self):
  for xml in (b'<!DOCTYPE x [<!ENTITY y "abc">]><x>&y;</x>',b'<broken>'):
   with self.subTest(xml=xml):
    with self.assertRaises(ReadError):parse_article_xml(xml)

 def test_priority_reading_gap_for_cited_document(self):
  sid=self.source();self.assertTrue(r.publication_gaps(self.t.store.get(self.run),[sid]))
  self.annotate(sid);self.assertEqual(r.publication_gaps(self.t.store.get(self.run),[sid]),[])
  self.assertEqual(r.publication_gaps(self.t.store.get(self.run),['s_unrelated']),[])

 def test_later_failed_reader_does_not_erase_available_primary_text(self):
  self.source();self.fail()
  sid=self.source(ABS,PARTS['abstract'],scope='abstract')
  result=self.annotate(sid,[{'source_id':sid,'section':'abstract','start':0,'end':len(PARTS['abstract'])}])
  self.assertEqual(result['level'],'summary_with_primary_unread')
  self.assertFalse(result['fallback_ready'])

 def test_publishing_cited_unread_primary_is_partial_then_resolves(self):
  sid=self.source()
  eid=self.t.call('research_quote',{'run_id':self.run,'source_id':sid,'quote':'The measured association differs across the supplied sample groups'})['evidence_id']
  cid=self.t.call('research_claim',{'run_id':self.run,'question_id':'Q1','text':'An association differs across the supplied sample groups.','evidence_ids':[eid]})['claim_id']
  self.t.call('research_review',{'run_id':self.run,'claim_id':cid,'verdict':'supported','reason':'The narrow association statement matches the supplied source context.','supporting_evidence_ids':[eid]})
  for query,round,purpose in [('actual fixture search',1,'discovery'),('actual fixture counter',2,'counter')]:self.t.call('research_log_search',{'run_id':self.run,'query':query,'round':round,'purpose':purpose,'provider':'offline-test','result_count':1})
  args={'run_id':self.run,'claim_ids':[cid],'limitations':[],'stop_reason':'coverage_sufficient'}
  report=self.t.call('research_publish',args)
  self.assertEqual(report['status'],'partial')
  self.assertIn('资料阅读范围',Path(report['report_path']).read_text(encoding='utf-8'))
  self.assertEqual(json.loads(Path(report['audit_path']).read_text(encoding='utf-8'))['reading_coverage'][0]['level'],'not_read')
  self.annotate(sid)
  self.assertEqual(self.t.call('research_publish',args)['status'],'audited')

 def test_separate_numeric_xml_labels_do_not_hide_body_headings(self):
  text='1. \n\n## Introduction\n\nSome actual context here.\n\n2. \n\n## Results and Discussion\n\nActual findings here.\n\n3. \n\n## Materials & Methods\n\nActual procedure here.'
  self.assertEqual({x['section'] for x in r.section_hints(text)},{'introduction','results','methods'})

 def test_new_primary_reading_can_resolve_stale_scope_records(self):
  sid=self.source();self.annotate(sid);self.source(scope='abstract')
  self.assertTrue(self.plan()['reading_integrity_errors'])
  alternate='https://example.org/paper/actual-fulltext'
  self.register(fulltext_urls=[alternate])
  new_sid=self.source(alternate)
  result=self.annotate(new_sid)
  self.assertEqual(result['level'],'primary_sections')
  self.assertEqual(result['reading_integrity_errors'],[])
  self.assertGreater(result['superseded_reading_records'],0)

 def test_database_link_hints_are_not_a_fetch_or_a_read(self):
  args=r.candidate_arguments({'url':'https://pubmed.ncbi.nlm.nih.gov/123/','title':'A test article','pmcid':'PMC123','pmid':'123','fulltext_urls':[]})
  self.assertEqual(len(args['fulltext_urls']),2)
  self.assertTrue(any('fullTextXML' in u for u in args['fulltext_urls']))
  self.assertEqual(args['summary_urls'],['https://pubmed.ncbi.nlm.nih.gov/123/'])
  self.assertEqual(self.plan()['level'],'not_read')

if __name__=='__main__':unittest.main()
