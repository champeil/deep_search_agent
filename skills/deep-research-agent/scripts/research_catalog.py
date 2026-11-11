"""Source-aware planning and three public database adapters. No model API calls."""
import copy
from datetime import datetime,timezone
from html import unescape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlencode, quote
import xml.etree.ElementTree as ET
import research_providers as providers


def now():return datetime.now(timezone.utc).isoformat()


def registry():
    # Runtime installer keeps a sibling references directory; skills use ../references.
    here=Path(__file__).resolve().parent
    paths=[here/'references/source-registry.json',here.parent/'references/source-registry.json']
    return json.loads(next(p for p in paths if p.is_file()).read_text(encoding='utf-8'))


def sources(state):return {**registry()['sources'],**state.get('custom_sources',{})}


def source_matches(source,url):
    u=urlsplit(url)
    if not u.hostname:return False
    for prefix in source['match_urls']:
        v=urlsplit(prefix)
        host=u.hostname.lower().rstrip('.')
        if host!=v.hostname and not host.endswith('.'+v.hostname):continue
        path=v.path.rstrip('/')
        if not path or u.path.rstrip('/')==path or u.path.startswith(path+'/'):return True
    return False


def choose_domains(question):
    matches=[]
    for ident,d in registry()['domains'].items():
        if ident=='general':continue
        hits=[]
        for word in d['triggers']:
            pattern=re.escape(word)
            if word.isascii():pattern=r'(?<![a-z])'+pattern+r'(?![a-z])'
            if re.search(pattern,question,re.I):hits.append(word)
        if hits:matches.append({'id':ident,'matched_terms':hits})
    matches.sort(key=lambda x:-len(x['matched_terms']))
    return matches[:5] or [{'id':'general','matched_terms':[]}]


def make_plan(state,args=None):
    args=args or {}
    r=registry();old=state.get('source_plan',{})
    suggested=choose_domains(state['question'])
    domains=args.get('domains',old.get('domains',[x['id'] for x in suggested]))
    if not 1<=len(domains)<=6 or len(set(domains))!=len(domains) or any(d not in r['domains'] for d in domains):raise ValueError('Use 1..6 known domain IDs; inspect research_catalog')
    available=sources(state)
    selected=args.get('source_ids',old.get('source_ids'))
    if selected is None:
        # Round robin across domains: avoid one category filling the entire small plan.
        selected=[]
        for rank in range(4):
            for d in domains:
                pool=r['domains'][d]['sources']
                if rank<len(pool) and pool[rank] not in selected:selected.append(pool[rank])
        selected=selected[:8]
    if len(selected)>20 or len(set(selected))!=len(selected) or any(s not in available for s in selected):raise ValueError('Use <=20 registered sources without duplicates')
    policy=args.get('policy',old.get('policy','preferred'))
    if policy not in {'preferred','strict_domains'} or (policy=='strict_domains' and not selected):raise ValueError('Invalid source policy')
    required=args.get('required_source_ids',old.get('required_source_ids',[]))
    if len(set(required))!=len(required) or not set(required)<=set(selected):raise ValueError('Required sources must be selected sources')
    concepts=args.get('concepts',old.get('concepts',[]))
    if len(concepts)>6:raise ValueError('At most six query concept groups')
    for concept in concepts:
        if not 1<=len(concept.get('terms',[]))<=8 or any(not isinstance(t,str) or not 1<=len(t.strip())<=100 for t in concept['terms']):raise ValueError('Each concept needs 1..8 actual terms, <=100 characters each')
    reason=args.get('reason','')
    if len(reason)>1500:raise ValueError('Plan reason too long')
    text=' AND '.join('('+' OR '.join('"'+t.replace('"',' ').strip()+'"' for t in c['terms'])+')' for c in concepts) or state['question'][:500]
    if len(text)>850:raise ValueError('Query plan too long; reduce concepts or synonyms')
    task=args.get('task',old.get('task')) or ('academic' if any(x in domains for x in ('biomed','omics','clinical','social','humanities')) else 'technical' if 'computing' in domains else 'general')
    if task not in providers.TASKS:raise ValueError('Unknown retrieval task')
    plan={'registry_version':r['version'],'revision':old.get('revision',0)+1,'domains':domains,'suggested_domains':suggested,
          'domain_selection':'host_supplied' if 'domains' in args else old.get('domain_selection','keyword_suggestion'),
          'needs_host_review':False if 'domains' in args else old.get('needs_host_review',True),
          'concepts':copy.deepcopy(concepts),'query':text,'source_ids':list(selected),'required_source_ids':list(required),
          'policy':policy,'task':task,'reason':reason or old.get('reason',''),'updated_at':now(),
          'open_web_fallback':policy=='preferred',
          'warning':'Starting points only; source selection is not actual coverage. Database syntax, jurisdiction, species and language require host review.'}
    if len(state.get('plan_history',[]))>=20:raise ValueError('Plan revision budget exhausted')
    state['source_plan']=plan
    state.setdefault('plan_history',[]).append(copy.deepcopy(plan))
    return plan_view(state)


def plan_view(state):
    plan=state.get('source_plan')
    if not plan:return None
    available=sources(state)
    queries=[]
    for sid in plan['source_ids']:
        source=available[sid]
        restrictions=['site:'+urlsplit(x).netloc+urlsplit(x).path.rstrip('/') for x in source['match_urls']]
        queries.append({'source_id':sid,'database_query':plan['query'] if source['adapter'] else None,
                        'site_query':'('+' OR '.join(restrictions)+') '+plan['query'],
                        'available_adapter':source['adapter'],'note':'site_query is web-index search, not a database-native search'})
    return {**plan,'query_suggestions':queries,'coverage':coverage(state)}


def enforce_url(state,url):
    plan=state.get('source_plan',{})
    if plan.get('policy')=='strict_domains':
        available=sources(state)
        if not any(source_matches(available[sid],url) for sid in plan['source_ids']):raise ValueError('URL outside strict_domains plan; no source saved. Change scope only with user authorization')


def restrict_query(state,query,source_id=None):
    available=sources(state)
    plan=state.get('source_plan',{})
    if source_id and source_id not in available:raise ValueError('Unknown catalog source_id')
    selected=([source_id] if source_id else plan.get('source_ids',[])) if plan.get('policy')=='strict_domains' or source_id else []
    if plan.get('policy')=='strict_domains' and source_id and source_id not in plan['source_ids']:raise ValueError('Source outside strict plan')
    if not selected:return query
    prefixes=list(dict.fromkeys('site:'+urlsplit(u).netloc+urlsplit(u).path.rstrip('/') for sid in selected for u in available[sid]['match_urls']))
    scoped='('+' OR '.join(prefixes)+') '+query
    if len(scoped)>1000:raise ValueError('Scoped query exceeds budget; target a single catalog_source_id or shorten the query')
    return scoped


def filter_results(state,results,source_id=None):
    kept=[]
    for result in results:
        try:enforce_url(state,result['url'])
        except ValueError:continue
        if source_id and not source_matches(sources(state)[source_id],result['url']):continue
        kept.append(result)
    return kept


def record_attempt(state,source_id,method,outcome,query='',reference='',reason='',verification='host_attested'):
    if source_id not in sources(state):raise ValueError('Unknown source ID')
    if method not in {'site_search','native_database','database_api','availability'}:raise ValueError('Invalid source access method')
    if outcome not in {'searched','empty','failed','unavailable','skipped'}:raise ValueError('Invalid source outcome')
    if outcome in {'searched','empty'} and not reference:raise ValueError('Actual successful search needs a tool reference')
    if outcome in {'unavailable','skipped','failed'} and len(reason.strip())<5:raise ValueError('Record a concrete access failure/skip reason')
    entries=state.setdefault('source_attempts',[])
    if len(entries)>=200:raise ValueError('Source attempt budget exhausted')
    event={'source_id':source_id,'method':method,'outcome':outcome,'query':query[:1000],
           'tool_reference':reference[:1000],'reason':reason[:1500],'verification':verification,'time':now()}
    entries.append(event)
    return event


def coverage(state):
    plan=state.get('source_plan',{});available=sources(state)
    ordered=list(dict.fromkeys(plan.get('source_ids',[])+[e['source_id'] for e in state.get('source_attempts',[])]))
    rows=[]
    for sid in ordered:
        source=available[sid];events=[e for e in state.get('source_attempts',[]) if e['source_id']==sid]
        native=any(e['outcome'] in {'searched','empty'} and e['method'] in {'database_api','native_database'} for e in events)
        site=any(e['outcome'] in {'searched','empty'} and e['method']=='site_search' for e in events)
        reads=[s for s in state['sources'].values() if source_matches(source,s['url'])]
        scopes={scope:sum(s['read_scope']==scope for s in reads) for scope in ('abstract','partial_text','page_text','test_fixture','user_supplied')}
        rows.append({'source_id':sid,'name':source['name'],'planned':sid in plan.get('source_ids',[]),'required':sid in plan.get('required_source_ids',[]),
                     'database_searched':native,'site_searched':site,'read_count':len(reads),'read_scopes':scopes,
                     'last_outcome':events[-1]['outcome'] if events else 'planned','attempt_count':len(events),'last_reason':events[-1]['reason'] if events else '',
                     'access_note':source['note']})
    return {'sources':rows,'required_missing':[r['source_id'] for r in rows if r['required'] and not r['database_searched']],
            'unattempted':[r['source_id'] for r in rows if r['planned'] and not r['attempt_count']],
            'complete_database_coverage':False,'note':'A successful query is not exhaustive database coverage. Reading a page does not prove a database was searched.'}


def add_custom(state,args):
    ident=args['source_id']
    if not re.fullmatch(r'custom_[a-z0-9_]{1,50}',ident) or ident in sources(state):raise ValueError('Use a new custom_ source ID')
    if len(state.get('custom_sources',{}))>=20:raise ValueError('Custom source budget exhausted')
    homepage=providers.public_url(args['homepage'])
    proof=state['sources'].get(args['verification_source_id'])
    if not proof or proof['read_scope'] in {'test_fixture','user_supplied'}:raise ValueError('Read and save an actual public source page before registering a new source')
    source={'id':ident,'name':args['name'][:120],'kind':'custom','homepage':homepage,'match_urls':[homepage],
            'adapter':None,'note':args['reason'][:1500],'registration':'host_attested','verification_source_id':proof['id'],'live_access':'host_read'}
    if not source_matches(source,proof['url']):raise ValueError('Verification page must belong to the declared source URL prefix')
    if len(args['reason'].strip())<5:raise ValueError('Explain the evidence gap this source addresses')
    state.setdefault('custom_sources',{})[ident]=source
    return {'registered':source,'next':'Add its ID with research_plan if relevant. Registration does not claim a database query occurred; it creates no API endpoint.'}


def clean_markup(text):return unescape(re.sub(r'<[^>]+>',' ',str(text)))


def database_search(source_id,query,request):
    """request(url, params, format) is supplied by the backend and meters each HTTP call."""
    if source_id=='europepmc':
        raw=request('https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':query,'format':'json','resultType':'core','pageSize':6},'json')
        if 'hitCount' not in raw or not isinstance(raw.get('resultList',{}).get('result'),list):raise providers.ProviderError('invalid_database_response')
        results=[]
        for r in raw['resultList']['result'][:6]:
            source=str(r.get('source',''));ident=str(r.get('id',''))
            if not re.fullmatch(r'[A-Z]+',source) or not re.fullmatch(r'[A-Za-z0-9_.-]+',ident):continue
            abstract=clean_markup(r.get('abstractText',''))
            results.append({'url':'https://europepmc.org/article/'+source+'/'+ident,'title':str(r.get('title',''))[:500],
                'snippet':abstract[:3000],'abstract':abstract[:100000],'read_scope':'abstract' if abstract else 'metadata',
                'doi':r.get('doi'),'pmid':r.get('pmid'),'pmcid':r.get('pmcid'),
                'publication_types':r.get('pubTypeList',{}).get('pubType',[]),
                'fulltext_urls':[x['url'] for x in r.get('fullTextUrlList',{}).get('fullTextUrl',[]) if isinstance(x,dict) and isinstance(x.get('url'),str)]})
        return {'results':results,'total_hits':int(raw['hitCount']),'query_translation':None}
    if source_id=='crossref':
        raw=request('https://api.crossref.org/works',{'query.bibliographic':query,'rows':6},'json')
        if not isinstance(raw.get('message',{}).get('items'),list):raise providers.ProviderError('invalid_database_response')
        results=[]
        for r in raw['message']['items'][:6]:
            doi=r.get('DOI')
            if not isinstance(doi,str) or not doi.startswith('10.'):continue
            title=r.get('title',[])
            abstract=clean_markup(r.get('abstract',''))
            results.append({'url':'https://doi.org/'+quote(doi,safe='/'),'title':str(title[0] if title else doi)[:500],
                'snippet':abstract[:3000],'abstract':abstract[:100000],'read_scope':'abstract' if abstract else 'metadata',
                'doi':doi,'publication_types':[r.get('type','')],'fulltext_urls':[x['URL'] for x in r.get('link',[]) if isinstance(x,dict) and isinstance(x.get('URL'),str)]})
        return {'results':results,'total_hits':int(raw['message'].get('total-results',0)),'query_translation':None}
    if source_id=='pubmed':
        base='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
        raw=request(base+'esearch.fcgi',{'db':'pubmed','term':query,'retmode':'json','retmax':6,'sort':'relevance','tool':'deep_research_agent'},'json')
        data=raw.get('esearchresult',{})
        ids=data.get('idlist')
        if not isinstance(ids,list) or any(not isinstance(i,str) or not i.isdigit() for i in ids):raise providers.ProviderError('invalid_database_response')
        result={'results':[],'total_hits':int(data.get('count',0)),'query_translation':data.get('querytranslation'),'search_warnings':data.get('warninglist',{})}
        if not ids:return result
        xml=request(base+'efetch.fcgi',{'db':'pubmed','id':','.join(ids),'retmode':'xml','tool':'deep_research_agent'},'xml')
        if b'<!ENTITY' in xml.upper():raise providers.ProviderError('unsafe_database_xml')
        try:root=ET.fromstring(xml)
        except ET.ParseError:raise providers.ProviderError('invalid_database_xml') from None
        for article in root.findall('.//PubmedArticle'):
            pmid=article.findtext('./MedlineCitation/PMID')
            if not pmid or pmid not in ids:continue
            title=''.join(article.find('./MedlineCitation/Article/ArticleTitle').itertext()) if article.find('./MedlineCitation/Article/ArticleTitle') is not None else pmid
            abstract='\n'.join((x.attrib.get('Label','')+': ' if x.attrib.get('Label') else '')+''.join(x.itertext()) for x in article.findall('./MedlineCitation/Article/Abstract/AbstractText'))
            ident={x.attrib.get('IdType'):x.text for x in article.findall('./PubmedData/ArticleIdList/ArticleId')}
            result['results'].append({'url':'https://pubmed.ncbi.nlm.nih.gov/'+pmid+'/','title':title[:500],
                'snippet':abstract[:3000],'abstract':abstract[:100000],'read_scope':'abstract' if abstract else 'metadata',
                'pmid':pmid,'doi':ident.get('doi'),'pmcid':ident.get('pmc'),
                'publication_types':[''.join(x.itertext()) for x in article.findall('./MedlineCitation/Article/PublicationTypeList/PublicationType')],
                'fulltext_urls':['https://pmc.ncbi.nlm.nih.gov/articles/'+ident['pmc']+'/'] if ident.get('pmc') else []})
        return result
    raise ValueError('No bundled native adapter for this source; use host database tools or site search and label the method honestly')
