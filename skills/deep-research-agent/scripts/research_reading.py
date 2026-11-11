"""Full-text-first reading plans and host-attested section coverage. No LLM calls."""
import hashlib
import re
from datetime import datetime,timezone
import research_providers as providers

PROFILES={
 'paper':{'primary':['introduction','results','methods','abstract'],'extra':['figures_tables','discussion','limitations','supplement'],'fallback':'abstract','order':['fulltext_html','fulltext_xml','fulltext_pdf','abstract']},
 'technical':{'primary':['version','reference','parameters','limitations'],'extra':['examples','errors'],'fallback':'summary','order':['primary','summary']},
 'policy':{'primary':['scope','provisions','effective_date','exceptions'],'extra':['definitions','amendments'],'fallback':'summary','order':['primary','summary']},
 'dataset':{'primary':['provenance','variables','methods','limitations'],'extra':['data','version'],'fallback':'summary','order':['primary','summary']},
 'news':{'primary':['primary_evidence','date','context','limitations'],'extra':['corroboration'],'fallback':'summary','order':['primary','summary']},
 'business':{'primary':['period','statements','notes','risks'],'extra':['methods'],'fallback':'summary','order':['primary','summary']},
 'general':{'primary':['primary_evidence','methods','limitations','summary'],'extra':[],'fallback':'summary','order':['primary','summary']}}
ALIASES={
 'introduction':['introduction','background','引言','前言','研究背景'],
 'results':['results','findings','results and discussion','results & discussion','结果','研究结果','结果与讨论'],
 'methods':['methods','materials and methods','materials & methods','methodology','experimental procedures','方法','材料与方法'],
 'abstract':['abstract','summary','摘要'],
 'discussion':['discussion','讨论'], 'limitations':['limitations','局限性','局限'],
 'figures_tables':['figure legends','figures','tables','图注','表格'],
 'supplement':['supplementary material','supplementary information','supplementary materials','supporting information','补充材料']}


def now():return datetime.now(timezone.utc).isoformat()


def get_document(state,did):
    doc=state.get('documents',{}).get(did)
    if not doc:raise ValueError('Unknown document_id')
    return doc


def normalized_url(value):return providers.public_url(value)


def register(state,args):
    kind=args['kind']
    if kind not in PROFILES:raise ValueError('Unknown document kind')
    title=args['title'].strip()
    if not 3<=len(title)<=500:raise ValueError('Document title must contain 3..500 characters')
    identifier=args.get('identifier',title.casefold()).strip()
    if not 1<=len(identifier)<=500:raise ValueError('Invalid document identifier')
    did='d_'+hashlib.sha256((kind+'\0'+identifier).encode()).hexdigest()[:16]
    entries=[]
    if kind=='paper':
        for url in args.get('fulltext_urls',[]):
            u=normalized_url(url)
            role='fulltext_pdf' if re.search(r'\.pdf(?:\?|$)',u,re.I) else 'fulltext_xml' if 'fullTextXML' in u or re.search(r'\.xml(?:\?|$)',u,re.I) else 'fulltext_html'
            entries.append({'url':u,'role':role})
        entries += [{'url':normalized_url(u),'role':'abstract'} for u in args.get('summary_urls',[])]
    else:
        entries += [{'url':normalized_url(u),'role':'primary'} for u in args.get('fulltext_urls',[])]
        entries += [{'url':normalized_url(u),'role':'summary'} for u in args.get('summary_urls',[])]
    unique=list({(e['url'],e['role']):e for e in entries}.values())
    if len(unique)>8:raise ValueError('At most eight candidate URLs per document')
    docs=state.setdefault('documents',{})
    if did not in docs:
        if len(docs)>=60:raise ValueError('Document budget exhausted')
        docs[did]={'id':did,'kind':kind,'title':title,'identifier':identifier,'candidates':[],
                   'captures':{},'attempts':[],'sections':[],'not_present':[], 'created_at':now()}
    doc=docs[did]
    for entry in unique:
        if entry not in doc['candidates']:doc['candidates'].append(entry)
    if len(doc['candidates'])>8:raise ValueError('At most eight candidate URLs per document')
    for sid in args.get('source_ids',[]):capture(state,did,sid)
    return plan(state,did)


def candidate(doc,url):
    u=normalized_url(url)
    return next((c for c in doc['candidates'] if c['url']==u),None)


def capture(state,did,sid,requested_url=None):
    doc=get_document(state,did);s=state['sources'].get(sid)
    if not s:raise ValueError('Unknown source_id')
    entry=candidate(doc,requested_url or s['url'])
    if not entry:raise ValueError('Register the actual page URL as a document candidate before attaching it')
    role=entry['role']
    if s['read_scope']=='abstract':role='abstract' if doc['kind']=='paper' else 'summary'
    doc['captures'][sid]={'source_id':sid,'url':s['url'],'requested_url':entry['url'],'role':role,'text_sha256':s['text_sha256'],'captured_at':now()}
    return {'document_id':did,'source_id':sid,'role':role,'note':'Captured text is not proof the host read the sections or verified article identity.'}


def record_attempt(state,args,verification='host_attested'):
    doc=get_document(state,args['document_id'])
    reason=args['reason'].strip()
    if not 5<=len(reason)<=1500:raise ValueError('Give a concrete reading/fallback reason')
    outcome=args['outcome']
    if outcome not in {'failed','unavailable','not_primary','skipped','not_found'}:raise ValueError('Successful captures must come from an actual saved source')
    method=args['method']
    reference=args.get('tool_reference','')
    url=args.get('url')
    if method=='discovery':
        if outcome!='not_found':raise ValueError('Discovery may only record not_found with an actual search reference')
        if not reference or not any(reference==q.get('tool_reference') or reference==q['query'] for q in state['searches']):raise ValueError('Full-text discovery needs an existing actual search reference')
    elif method in {'native_reader','direct_reader','api_extract','scope','budget'}:
        if url and not candidate(doc,url):raise ValueError('Attempt URL must be registered for this document')
        if not url and method not in {'scope','budget'}:raise ValueError('Reader failures need the actual candidate URL')
        if method in {'native_reader','api_extract'} and not reference:raise ValueError('Host reader attempt needs its actual tool reference')
        if outcome=='not_found':raise ValueError('Use actual discovery search evidence for not_found')
    else:raise ValueError('Unknown reading attempt method')
    if len(doc['attempts'])>=30:raise ValueError('Document attempt budget exhausted')
    event={'method':method,'outcome':outcome,'url':normalized_url(url) if url else None,'reason':reason,
           'tool_reference':reference[:1000],'verification':verification,'time':now()}
    doc['attempts'].append(event)
    return plan(state,doc['id'])


def annotate(state,args):
    doc=get_document(state,args['document_id']);profile=PROFILES[doc['kind']]
    identity=args['identity_note'].strip()
    if not 10<=len(identity)<=1500:raise ValueError('Record how title/DOI/version identity was checked against the actual text')
    entries=args.get('sections',[]);missing=args.get('not_present',[])
    if not entries and not missing:raise ValueError('Provide actually read spans or observed absent sections')
    if len(entries)+len(missing)>20:raise ValueError('At most twenty reading records per call')
    allowed=set(profile['primary']+profile['extra']+[profile['fallback']])
    for item in entries:
        sid=item['source_id'];s=state['sources'].get(sid);part=item['section']
        if part not in allowed or sid not in doc['captures'] or not s:raise ValueError('Use a known section and a source attached to this document')
        start,end=item['start'],item['end']
        if not 0<=start<end<=len(s['text']) or not 20<=end-start<=12000:raise ValueError('Each read span must address 20..12000 exact source characters')
        is_summary=doc['captures'][sid]['role'] in {'abstract','summary'} or s['read_scope']=='abstract'
        if is_summary and part!=profile['fallback']:raise ValueError('Abstract/summary text cannot satisfy body or primary-document sections')
        if len(doc['sections'])>=100:raise ValueError('Document section record budget exhausted')
        doc['sections'].append({**item,'text_sha256':s['text_sha256'],'identity_note':identity,'method':'host_attested','time':now()})
    for item in missing:
        sid=item['source_id'];s=state['sources'].get(sid);part=item['section']
        if part not in allowed or sid not in doc['captures'] or not s or s['read_scope']=='abstract' or doc['captures'][sid]['role'] in {'abstract','summary'}:raise ValueError('Only an inspected primary/body source can justify an absent non-summary section')
        if len(item['reason'].strip())<10:raise ValueError('Explain article type, integrated section or actual absence; do not guess')
        if len(doc['not_present'])>=20:raise ValueError('Absent-section record budget exhausted')
        doc['not_present'].append({**item,'text_sha256':s['text_sha256'],'identity_note':identity,'method':'host_attested','time':now()})
    return plan(state,doc['id'])


def progress(state,doc):
    profile=PROFILES[doc['kind']];valid=[];errors=[]
    for entry in doc['sections']:
        s=state['sources'].get(entry['source_id'])
        if not s or s['text_sha256']!=entry['text_sha256'] or entry['end']>len(s['text']):
            errors.append((entry['section'],'Source changed or missing for '+entry['section']));continue
        if s['read_scope']=='abstract' and entry['section']!=profile['fallback']:
            errors.append((entry['section'],'Scope downgraded to abstract for '+entry['section']));continue
        valid.append(entry)
    covered={e['section'] for e in valid}
    absent=set()
    for entry in doc['not_present']:
        s=state['sources'].get(entry['source_id'])
        if s and s['text_sha256']==entry['text_sha256'] and s['read_scope']!='abstract':absent.add(entry['section'])
    body=any(e['section']!=profile['fallback'] for e in valid)
    primary=[x for x in doc['candidates'] if x['role'] not in {'abstract','summary'}]
    resolved={e['url'] for e in doc['attempts'] if e['url'] and e['outcome'] in {'failed','unavailable','not_primary'}}
    untried=[x for x in primary if x['url'] not in resolved and not any(a['requested_url']==x['url'] for a in doc['captures'].values())]
    captured_primary=[a for a in doc['captures'].values() if a['role'] not in {'abstract','summary'} and state['sources'][a['source_id']]['read_scope']!='abstract' and a['requested_url'] not in {e['url'] for e in doc['attempts'] if e['outcome']=='not_primary'}]
    discovery=any(x['method']=='discovery' and x['outcome']=='not_found' for x in doc['attempts'])
    limited=any(x['method'] in {'budget','scope'} or x['outcome']=='skipped' for x in doc['attempts'])
    primary_resolved=bool(primary) and all(x['url'] in resolved for x in primary)
    fallback_ready=not untried and not captured_primary and (primary_resolved or (not primary and discovery))
    fallback_read=profile['fallback'] in covered
    missing=[x for x in profile['primary'] if x not in covered|absent]
    if body:level='primary_sections' if not missing else 'partial_primary'
    elif fallback_read and captured_primary:level='summary_with_primary_unread'
    elif fallback_read and fallback_ready:level='abstract_only' if doc['kind']=='paper' else 'summary_only'
    elif fallback_read and limited:level='abstract_only_limited' if doc['kind']=='paper' else 'summary_only_limited'
    elif fallback_read:level='fallback_unresolved'
    else:level='not_read'
    return {'document_id':doc['id'],'title':doc['title'],'kind':doc['kind'],'level':level,'covered_sections':sorted(covered),'observed_absent_sections':sorted(absent-covered),
            'missing_priority_sections':missing,'fallback_ready':fallback_ready,'untried_primary_urls':[x['url'] for x in untried],
            'captured_primary_unread':bool(captured_primary and not body),'reading_integrity_errors':[message for section,message in errors if section not in covered|absent],
            'superseded_reading_records':sum(section in covered|absent for section,message in errors),
            'fallback_reasons':list(dict.fromkeys(e['reason'] for e in doc['attempts'])),
            'verification':'host_attested_sections; exact offsets and saved scope checked, semantic section identity is not independently verified'}


def plan(state,did):
    doc=get_document(state,did);profile=PROFILES[doc['kind']];status=progress(state,doc)
    order=profile['order']
    candidates=sorted(doc['candidates'],key=lambda x:order.index(x['role']) if x['role'] in order else 99)
    return {**status,'priority_sections':profile['primary'],'conditional_sections':profile['extra'],'candidates':candidates,
            'next':'Read available primary/full text and annotate actual priority-section spans. Only fall back after recorded access/discovery failures, or explicitly label a budget/scope-limited fallback.',
            'note':'HTML/XML/PDF availability is separate from section reading. A preview or Abstract alone does not count as reading full text. Use visual readers for figures when needed.'}


def summary(state):return [progress(state,d) for d in state.get('documents',{}).values()]


def publication_gaps(state,source_ids):
    levels={'primary_sections','abstract_only','summary_only','abstract_only_limited','summary_only_limited'}
    gaps=[]
    for doc in state.get('documents',{}).values():
        if set(doc['captures']).intersection(source_ids):
            item=progress(state,doc)
            if item['level'] not in levels or item['reading_integrity_errors']:gaps.append(doc['id']+': '+item['level'])
    return gaps


def section_hints(text):
    found=[]
    for match in re.finditer(r'(?m)^[ \t]{0,3}(?:#{1,6}[ \t]*)?(?:\d+(?:\.\d+)*[.)]?[ \t]*)?([^\n]{2,80})[ \t]*$',text):
        heading=match.group(1).strip().rstrip(':：').casefold()
        for part,aliases in ALIASES.items():
            if heading in aliases:found.append({'section':part,'heading':match.group(1).strip(),'start':match.start()});break
    for i,item in enumerate(found):item['end']=found[i+1]['start'] if i+1<len(found) else len(text)
    return found[:60]


def candidate_arguments(result):
    urls=[]
    pmcid=result.get('pmcid')
    if isinstance(pmcid,str) and re.fullmatch(r'PMC[0-9]+',pmcid):
        urls += ['https://pmc.ncbi.nlm.nih.gov/articles/'+pmcid+'/', 'https://www.ebi.ac.uk/europepmc/webservices/rest/'+pmcid+'/fullTextXML']
    for url in result.get('fulltext_urls',[]):
        try:url=normalized_url(url)
        except ValueError:continue
        if url!=result['url'] and url not in urls:urls.append(url)
    identifier=('doi:'+result['doi']) if result.get('doi') else ('pmid:'+result['pmid']) if result.get('pmid') else result['url']
    return {'kind':'paper','title':result['title'],'identifier':identifier,'fulltext_urls':urls[:6],'summary_urls':[result['url']],
            'note':'Candidate links only, not verified full-text availability. Register selected papers with research_document; no automatic fetch occurred.'}
