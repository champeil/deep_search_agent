# Retrieval routing (0.3.0)

Inspect `research_providers` with no arguments before retrieval; it performs no network request and never prints keys. The backend cannot execute host-native tools: the host makes those calls. Default `research_search`/`research_extract` returns `needs_native` until the host reports `native_status: unavailable`, `failed` or `insufficient` from actual tool availability/results. Native host search/read → Perplexity Search → remaining configured providers for search. Extraction uses only actual extraction-capable providers; Perplexity Search/SerpApi/SerpSearch do not extract article bodies.

## Task policy

These orders are editable routing defaults, not empirical quality rankings or assertions of lowest prices. All lists skip missing keys, disabled providers and providers cooling down after errors. Search always puts configured Perplexity first, unless the user explicitly pins another provider or disables Perplexity.

| Task | Remaining providers, before filtering |
|---|---|
| general / balanced | Tavily, Exa, Parallel, Linkup, AnySearch, SerpApi, SerpSearch, Keenable, Firecrawl |
| academic | Exa, SerpApi (Google Scholar), Parallel, Tavily, Linkup, Keenable, AnySearch, SerpSearch, Firecrawl |
| exact | SerpApi, SerpSearch, Tavily, Exa, Parallel, AnySearch, Linkup, Keenable, Firecrawl |
| news | SerpApi (Google News), SerpSearch news, Tavily news, Parallel, Exa, AnySearch, Linkup, Keenable, Firecrawl |
| chinese | AnySearch (cn zone), SerpApi, Tavily, SerpSearch, Exa, Linkup, Parallel, Keenable, Firecrawl |
| technical | Exa, Tavily, Firecrawl developer category, Parallel, SerpApi, Linkup, AnySearch, SerpSearch, Keenable |
| economy | Tavily, Keenable, AnySearch, Parallel, Exa, SerpSearch, SerpApi, Linkup, Firecrawl |
| quality, general | Exa, Parallel, Linkup, Tavily, SerpApi, SerpSearch, AnySearch, Keenable, Firecrawl |

Economy changes the remote tail and uses Perplexity fast / Tavily basic / Exa lite / Parallel turbo. Quality uses Tavily advanced / Parallel advanced. Other quality tasks keep their specialty order. Linkup uses standard searchResults in all profiles; no sourcedAnswer, agent/research generation or wallet billing endpoints are used. No provider is contacted just because its key exists. Successful nonempty results stop the fallback; the host assesses relevance and chooses a new targeted query if necessary.

Extraction balanced/quality: Firecrawl → Tavily → Exa → Parallel → Linkup → Keenable → AnySearch. Economy: Tavily → Keenable → AnySearch → Exa → Parallel → Linkup → Firecrawl. Host/direct readers precede these. PDF support is conditional on the retrieval path, accessibility and parser; no guaranteed paid-PDF access.

## Configuration

Set keys in your private research.env. Recognized names: PERPLEXITY_API_KEY, TAVILY_API_KEY, EXA_API_KEY, FIRECRAWL_API_KEY, LINKUP_API_KEY, PARALLEL_API_KEY, SERPSEARCH_API_KEY, KEENABLE_API_KEY, ANYSEARCH_API_KEY, SERPAPI_API_KEY. Only the keys you want to use are necessary. `RESEARCH_SEARCH_PROVIDER=auto` enables routing; an old explicit `perplexity` or `tavily` setting pins search. Explicit `provider` pins a single remote provider for that call, still guarded by native status.

Optional variables:

- RESEARCH_STRATEGY=balanced (or quality/economy)
- RESEARCH_PROVIDER_ORDER=exa,tavily (custom remote tail, other defaults follow; Perplexity stays first in auto search)
- RESEARCH_DISABLED_PROVIDERS=linkup,firecrawl (comma-separated names)
- RESEARCH_MAX_ATTEMPTS=3 (1–5 attempts per operation, across different providers; no retry of the same provider in that call)
- RESEARCH_MAX_API_REQUESTS left blank (1–500 when specified; shared search+extraction attempt ceiling per research run; default quick 12 / research 60; an explicit value overrides both)
- RESEARCH_CACHE_TTL=3600 (0 disables; maximum 86400 seconds; set 0 for live freshness verification)
- RESEARCH_ALLOW_KEYLESS_KEENABLE=false (only exact true opts into documented public search/fetch endpoints; shared IP limits, queries/URLs logged by service)

REST Parallel requires a key. Keenable has documented public endpoints with X-Keenable-Title, but is disabled without a key unless opted in. Do not infer free tiers/renewal dates from screenshots or assume OAuth-managed MCP sessions are REST keys. SerpSearch and SerpApi are distinct services. AnySearch here means anysearch.com; similarly named services are not interchangeable.

## Accounting and failures

`research_status.retrieval_usage` and exported audit.json include attempt events, provider, operation, status, duration, cache hits and numeric provider-reported usage when present. Units differ (credits, currency, tokens); never sum unlike units. Native hidden HTTP calls, host model tokens and total charges are null rather than fabricated. Pending attempts after interruption remain conservatively counted. Authentication/credit errors cool down that provider for an hour within this run; other failures for 60 seconds. A nonempty low-quality result is not silently treated as failure: the host must identify the gap. Failed/empty requests can still be billable.

Only fixed official HTTPS API origins are used. Credentials stay in local env; do not print requests or raw error bodies. SerpApi authenticates by a URL query parameter, which is not saved in logs. Cache holds normalized retrieved text locally and is separated by credential fingerprint. Research folders may contain private questions or copyrighted text; do not publish the run database/cache with the repository.

## Official contracts checked 2026-11-11

- Perplexity: https://docs.perplexity.ai/api-reference/search-post
- Tavily: https://docs.tavily.com/documentation/api-reference/endpoint/search and /extract
- Exa: https://exa.ai/docs/reference/search and /get-contents
- Firecrawl: https://docs.firecrawl.dev/api-reference/endpoint/search and /scrape
- Linkup: https://docs.linkup.so/pages/documentation/endpoints/search/reference and /fetch/reference
- Parallel V1: https://docs.parallel.ai/api-reference/search/search and https://docs.parallel.ai/api-reference/extract/extract (full_content belongs inside advanced_settings)
- SerpSearch: https://serpsearch.com/docs
- Keenable: https://docs.keenable.ai/api-reference/search.md and /fetch.md and https://docs.keenable.ai/authentication.md
- AnySearch: https://www.anysearch.com/docs/api-endpoints/v1-search and /v1-extract
- SerpApi: https://serpapi.com/search-api and https://serpapi.com/google-scholar-api and https://serpapi.com/google-news-api

Contract tests are offline mocks, not evidence that a configured key/account can currently call a provider. Doctor never probes accounts or spends credits. Before claiming real integration success, require an actual authorized call and inspect its returned provenance.
