"""Documented retrieval adapters. No language-model API calls or automatic billing setup.

Only fixed official HTTPS API origins are allowed. Never expose raw error bodies,
headers or request URLs: some providers return credentials inside error responses.
"""
import hashlib
import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

KEYS = {p: p.upper() + '_API_KEY' for p in (
    'perplexity', 'tavily', 'exa', 'firecrawl', 'linkup', 'parallel',
    'serpsearch', 'keenable', 'anysearch', 'serpapi')}
EXTRACT = {'tavily', 'exa', 'firecrawl', 'linkup', 'parallel', 'keenable', 'anysearch'}
ORIGINS = {
    'perplexity': 'https://api.perplexity.ai', 'tavily': 'https://api.tavily.com',
    'exa': 'https://api.exa.ai', 'firecrawl': 'https://api.firecrawl.dev',
    'linkup': 'https://api.linkup.so', 'parallel': 'https://api.parallel.ai',
    'serpsearch': 'https://api.serpsearch.com', 'keenable': 'https://api.keenable.ai',
    'anysearch': 'https://api.anysearch.com', 'serpapi': 'https://serpapi.com'}
TASKS = {
    'general': ['tavily','exa','parallel','linkup','anysearch','serpapi','serpsearch','keenable','firecrawl'],
    'academic': ['exa','serpapi','parallel','tavily','linkup','keenable','anysearch','serpsearch','firecrawl'],
    'exact': ['serpapi','serpsearch','tavily','exa','parallel','anysearch','linkup','keenable','firecrawl'],
    'news': ['serpapi','serpsearch','tavily','parallel','exa','anysearch','linkup','keenable','firecrawl'],
    'chinese': ['anysearch','serpapi','tavily','serpsearch','exa','linkup','parallel','keenable','firecrawl'],
    'technical': ['exa','tavily','firecrawl','parallel','serpapi','linkup','anysearch','serpsearch','keenable'],
}
ECONOMY = ['tavily','keenable','anysearch','parallel','exa','serpsearch','serpapi','linkup','firecrawl']
QUALITY = ['exa','parallel','linkup','tavily','serpapi','serpsearch','anysearch','keenable','firecrawl']
EXTRACTION = ['firecrawl','tavily','exa','parallel','linkup','keenable','anysearch']
CONFIG = set(KEYS.values()) | {
    'RESEARCH_SEARCH_PROVIDER','RESEARCH_STRATEGY','RESEARCH_PROVIDER_ORDER',
    'RESEARCH_DISABLED_PROVIDERS','RESEARCH_MAX_ATTEMPTS','RESEARCH_MAX_API_REQUESTS',
    'RESEARCH_CACHE_TTL','RESEARCH_ALLOW_KEYLESS_KEENABLE'}


class ProviderError(ValueError):
    def __init__(self, code, http_status=None):
        # code is chosen by our code, never from a remote response body.
        self.code, self.http_status = code, http_status
        super().__init__(code + (f' (HTTP {http_status})' if http_status else ''))


def integer_setting(name, default, low, high):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError('Invalid integer configuration: ' + name) from None
    if not low <= value <= high:
        raise ValueError('Configuration outside allowed range: ' + name)
    return value


def names_setting(name):
    names = [v.strip().lower() for v in os.getenv(name, '').split(',') if v.strip()]
    if any(n not in KEYS for n in names) or len(names) != len(set(names)):
        raise ValueError('Invalid provider list: ' + name)
    return names


def keyless(provider):
    return provider == 'keenable' and not os.getenv(KEYS[provider], '').strip() and os.getenv('RESEARCH_ALLOW_KEYLESS_KEENABLE') == 'true'


def configured(provider):
    return bool(os.getenv(KEYS[provider], '').strip()) or keyless(provider)


def route(task='general', strategy=None, operation='search', provider=None):
    strategy = strategy or os.getenv('RESEARCH_STRATEGY', 'balanced')
    if task not in TASKS or strategy not in {'balanced','quality','economy'} or operation not in {'search','extract'}:
        raise ValueError('Unknown task, strategy or operation')
    forced = provider or (os.getenv('RESEARCH_SEARCH_PROVIDER', 'auto') if operation == 'search' else 'auto')
    if forced not in {'auto', *KEYS}:
        raise ValueError('Unknown search provider')
    disabled = names_setting('RESEARCH_DISABLED_PROVIDERS')
    if forced != 'auto':
        if operation == 'extract' and forced not in EXTRACT:
            # A legacy search preference is not an extraction capability.
            if provider:
                raise ValueError('Provider does not support extraction')
            forced = 'auto'
    if forced != 'auto':
        order = [forced]
    else:
        custom = names_setting('RESEARCH_PROVIDER_ORDER')
        if operation == 'extract':
            tail = (['tavily','keenable','anysearch','exa','parallel','linkup','firecrawl']
                    if strategy == 'economy' else EXTRACTION)
            order = list(dict.fromkeys(custom + tail))
        else:
            tail = ECONOMY if strategy == 'economy' else QUALITY if strategy == 'quality' and task == 'general' else TASKS[task]
            order = ['perplexity'] + [p for p in dict.fromkeys(custom + tail) if p != 'perplexity']
    eligible = [p for p in order if p not in disabled and configured(p) and (operation != 'extract' or p in EXTRACT)]
    return {'task':task, 'strategy':strategy, 'operation':operation, 'remote_order':eligible,
            'native_first':True, 'policy_order':order,
            'providers': [{'name':p,'configured':configured(p),'enabled':p not in disabled,
                           'search':True,'extract':p in EXTRACT,'keyless':keyless(p)} for p in KEYS],
            'note':'Policy defaults, not measured quality rankings. Native tools are called by the host, never by this Python server.'}


def build_request(provider, operation, value, task='general', strategy='balanced'):
    if provider not in KEYS or (operation == 'extract' and provider not in EXTRACT):
        raise ValueError('Unsupported provider operation')
    key = os.getenv(KEYS[provider], '').strip()
    if not key and not keyless(provider):
        raise ValueError('No configured retrieval key; use host-native tools')
    headers = {'Content-Type':'application/json','Accept':'application/json','User-Agent':'deep-research-agent/0.6.0'}
    if provider in {'exa','parallel','keenable'}:
        if key: headers['X-API-Key'] = key
    elif provider != 'serpapi':
        headers['Authorization'] = 'Bearer ' + key
    path, payload, params = '', None, None
    if operation == 'search':
        if not isinstance(value,str) or not 1 <= len(value.strip()) <= 1000:
            raise ValueError('Query must contain 1..1000 characters')
        q = value.strip()
        if provider == 'perplexity':
            path,payload = '/search', {'query':q,'max_results':6}
            if strategy == 'economy': payload['search_type'] = 'fast'
        elif provider == 'tavily':
            path,payload = '/search', {'query':q,'max_results':6,'search_depth':'advanced' if strategy == 'quality' else 'basic','include_answer':False,'include_usage':True}
            if task == 'news': payload['topic'] = 'news'
        elif provider == 'exa':
            path,payload = '/search', {'query':q,'numResults':6,'type':'lite' if strategy == 'economy' else 'auto'}
            if task == 'academic': payload['category'] = 'publication'
        elif provider == 'firecrawl':
            if len(q)>500: raise ValueError('Firecrawl query limit is 500 characters')
            path,payload = '/v2/search', {'query':q,'limit':6,'sources':['web'],'timeout':15000}
            if task == 'academic': payload['categories'] = ['research']
            elif task == 'technical': payload['categories'] = ['developer']
            elif task == 'news': payload['sources'] = ['news']
        elif provider == 'linkup': path,payload = '/v1/search', {'q':q,'depth':'standard','outputType':'searchResults','maxResults':6}
        elif provider == 'parallel':
            # V1 supports <=200 chars/probe; objective preserves full intent without truncation.
            probes = [q[i:i+200] for i in range(0,len(q),200)]
            path,payload = '/v1/search', {'objective':q,'search_queries':probes,'mode':'turbo' if strategy == 'economy' else 'advanced' if strategy == 'quality' else 'basic','max_chars_total':18000}
        elif provider == 'serpsearch': path,params = '/api/v1/news' if task == 'news' else '/api/v1/search', {'query':q}
        elif provider == 'keenable':
            path,payload = '/v1/search' + ('/public' if keyless(provider) else ''), {'query':q,'max_results':6,'snippet_max_length':2500}
        elif provider == 'anysearch':
            path,payload = '/v1/search', {'query':q,'max_results':6,'format':'json','zone':'cn' if task=='chinese' else 'intl'}
        elif provider == 'serpapi':
            path,params = '/search.json', {'engine':'google_scholar' if task=='academic' else 'google_news' if task=='news' else 'google','q':q,'api_key':key}
            if task == 'chinese': params['hl'] = 'zh-cn'
    else:
        value = public_url(value)
        if provider == 'tavily': path,payload = '/extract', {'urls':[value],'extract_depth':'advanced' if strategy=='quality' else 'basic','format':'markdown','include_usage':True}
        elif provider == 'exa': path,payload = '/contents', {'urls':[value],'text':True}
        elif provider == 'firecrawl': path,payload = '/v2/scrape', {'url':value,'formats':['markdown'],'timeout':20000}
        elif provider == 'linkup': path,payload = '/v1/fetch', {'url':value,'renderJs':True,'mode':'standard'}
        elif provider == 'parallel': path,payload = '/v1/extract', {'urls':[value],'advanced_settings':{'full_content':True}}
        elif provider == 'keenable': path,params = '/v1/fetch' + ('/public' if keyless(provider) else ''), {'url':value,'max_chars':50000}
        elif provider == 'anysearch': path,payload = '/v1/extract', {'url':value}
    if keyless(provider): headers['X-Keenable-Title'] = 'Deep Research Agent'
    endpoint = ORIGINS[provider] + path
    if params is not None: endpoint += '?' + urllib.parse.urlencode(params)
    return urllib.request.Request(endpoint, json.dumps(payload).encode('utf-8') if payload is not None else None,
                                  headers, method='POST' if payload is not None else 'GET')


def public_url(url):
    if not isinstance(url,str) or len(url)>4000:
        raise ValueError('Invalid source URL')
    u = urllib.parse.urlsplit(url)
    if u.scheme not in {'https','http'} or not u.hostname or u.username or u.password:
        raise ValueError('Only public HTTP(S) source URLs are supported')
    host = u.hostname.lower().rstrip('.')
    if host == 'localhost' or '.' not in host or host.endswith(('.localhost','.local','.internal')):
        raise ValueError('Private source URLs are not supported')
    try: address = ipaddress.ip_address(host)
    except ValueError: address = None
    if address is not None and not address.is_global:
        raise ValueError('Private source URLs are not supported')
    return urllib.parse.urlunsplit((u.scheme,u.netloc,u.path or '/',u.query,''))


def redact(text):
    for name in KEYS.values():
        secret = os.getenv(name, '').strip()
        if secret:
            text = text.replace(secret, '[REDACTED]').replace(urllib.parse.quote(secret,safe=''), '[REDACTED]')
    return text


def raw_request(request, timeout=20):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=timeout) as response:
            body = response.read(4_000_001)
        if len(body)>4_000_000: raise ProviderError('response_too_large')
        data = json.loads(body)
        if not isinstance(data,dict): raise ProviderError('invalid_response')
        return data
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ProviderError('http_error',exc.code) from None
    except (OSError,ValueError) as exc:
        if isinstance(exc,ProviderError): raise
        raise ProviderError('connection_or_json_error') from None


def numeric_usage(raw):
    # Retain ONLY numeric accounting values. Do not expose arbitrary metadata/credentials.
    def clean(value, depth=0):
        if depth>3: return None
        if type(value) in {int,float}: return value
        if isinstance(value,dict): return {str(k)[:60]:clean(v,depth+1) for k,v in value.items() if type(v) in {int,float,dict}}
        return None
    return {k:clean(raw[k]) for k in ('usage','costDollars','creditsUsed') if k in raw and type(raw[k]) in {int,float,dict}}


def looks_blocked(text):
    # Heuristic only. The host still checks source identity and actual reading scope.
    lead=re.sub(r'[#*_>`]+',' ',text[:1600]).strip()
    gate=r'(access denied|verify (?:that )?you are human|just a moment|sign in to continue|log in to (?:continue|access)|sign in to access|purchase (?:this|the) article|checking your browser)'
    return bool(re.match(gate,lead,re.I) or (len(text)<6000 and re.search(gate,lead,re.I)))


def normalize(provider, operation, raw, value):
    if raw.get('success') is False or raw.get('error'):
        raise ProviderError('provider_rejected_request')
    data = raw.get('data',raw)
    rows = raw.get('results')
    if operation == 'search':
        if provider == 'firecrawl': rows = data.get('web',data.get('news')) if isinstance(data,dict) else data
        elif provider == 'anysearch': rows = data.get('results') if isinstance(data,dict) else None
        elif provider == 'serpapi': rows = raw.get('organic_results',raw.get('news_results'))
        elif provider == 'serpsearch': rows = raw.get('organic_results',raw.get('news_results',raw.get('news')))
        if not isinstance(rows,list):
            # Empty SERPs can omit an organic block; preserve as empty, never invent snippets.
            if provider in {'serpapi','serpsearch'} and any(k in raw for k in ('search_metadata','search_info','search_information')): rows=[]
            else: raise ProviderError('invalid_response_shape')
        results,seen = [],set()
        for r in rows:
            if not isinstance(r,dict): continue
            url = r.get('url',r.get('link'))
            try: url=public_url(url)
            except ValueError: continue
            if url in seen: continue
            seen.add(url)
            snippet = r.get('snippet') or r.get('description') or r.get('content') or r.get('text')
            if not snippet: snippet='\n'.join(x for x in r.get('excerpts',r.get('highlights',[])) if isinstance(x,str))
            results.append({'url':redact(url),'title':redact(str(r.get('title') or r.get('name') or url))[:500],
                'snippet':redact(str(snippet or ''))[:3000], 'read_scope':'search_snippet'})
            if len(results)>=6: break
        return results
    if provider == 'firecrawl': r = data if isinstance(data,dict) else {}
    elif provider in {'linkup','keenable','anysearch'}: r = data if isinstance(data,dict) else {}
    else:
        r = next((r for r in rows or [] if isinstance(r,dict) and r.get('url')==value),None)
        if r is None: raise ProviderError('missing_extracted_page')
    text = r.get('raw_content') or r.get('full_content') or r.get('text') or r.get('markdown') or r.get('content')
    if provider == 'tavily':
        r = next((r for r in raw.get('results',[]) if isinstance(r,dict) and r.get('url')==value),{})
        text = r.get('raw_content')
    if not isinstance(text,str) or len(text.strip())<20: raise ProviderError('empty_extracted_page')
    if looks_blocked(text):
        raise ProviderError('blocked_or_login_page')
    metadata=r.get('metadata') if isinstance(r.get('metadata'),dict) else {}
    return {'url':value,'title':redact(str(r.get('title') or metadata.get('title') or value))[:500],
            'text':redact(text[:100000]),'read_scope':'partial_text',
            'truncated':len(text)>100000,'note':'Provider-returned page text; host must check identity, completeness and whether only an abstract was retrieved.'}


def retrieve(provider, operation, value, task, strategy):
    request=build_request(provider,operation,value,task,strategy)
    raw=raw_request(request)
    usage=numeric_usage(raw)
    try:
        data=normalize(provider,operation,raw,value)
    except Exception as exc:
        error=exc if isinstance(exc,ProviderError) else ProviderError('invalid_response_shape')
        error.usage_reported=usage
        raise error from None
    return {'data':data,'usage_reported':usage}


def cache_key(provider, operation, value, task, strategy):
    # Separate caches between accounts without saving the key itself.
    identity=os.getenv(KEYS[provider],'') or ('public' if keyless(provider) else '')
    data=[provider,operation,value,task,strategy,hashlib.sha256(identity.encode()).hexdigest()]
    return hashlib.sha256(json.dumps(data,ensure_ascii=False).encode()).hexdigest()
