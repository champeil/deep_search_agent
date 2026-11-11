# Source planning and coverage (0.4.0)

## Workflow

1. research_begin creates a small source plan from keyword suggestions. It makes no network request and calls no model. The HOST MODEL must review semantic domains, cross-domain scope, actual English/Chinese synonym groups, species, population, time and jurisdiction.
2. Inspect research_catalog (optional domain ID) for curated source entries, roles, access caveats and whether a native adapter exists. The registry is a starting point, not complete coverage or live access verification.
3. research_plan accepts run_id plus optional domains (1–6), concepts ([{terms:[synonyms]}], <=6 groups / <=8 terms each), source_ids (<=20), required_source_ids (subset), task, policy preferred|strict_domains and reason. Terms within one concept use OR, concepts use AND. The host reviews database syntax and vocabulary; no automatic MeSH mapping or translation claim is made. Changing plans records revisions, does not erase search history, and never performs retrieval.
4. Default preferred policy allows open-web supplementation. Use planned source IDs to target complementary queries. Avoid querying all sources automatically. The proposed task becomes the remote search task unless overridden.
5. Prefer available native database tools. Otherwise call research_database_search with run_id, catalog_source_id pubmed|europepmc|crossref, actual query, round, purpose and native_status unavailable|failed|insufficient. Omitted native_status returns needs_native without network. PubMed uses ESearch then EFetch (normally 2 HTTP requests); Europe PMC and Crossref normally 1. Each request, including failures, counts toward the shared API cap. Requests are conservatively spaced per database per run-root; different machines/roots still share service IP limits. No keys or paid accounts are created. These new adapters do not currently use the commercial-search cache or automatically retry.
6. Query results are abstracts or metadata, not full articles. Open original HTML/PDF and supplements; preserve actual scope. Crossref DOI metadata does not certify correctness. PubMed search translation and warnings are returned for host review. Non-peer-reviewed results and publication/retraction types need actual inspection; no complete automatic retraction verification is promised.
7. For host tool searches use research_log_search plus catalog_source_id, access_method site_search|native_database and actual tool_reference. A source ID alone does not prove a native database query. Backend tools log their own successful operations; never double-log. For API web search, optional catalog_source_id constructs a site-prefix query and filters matching returned URLs locally. Provider handling of site: syntax is not guaranteed. New gaps should use genuinely distinct queries; identical query text is allowed across distinct databases.
8. research_source_attempt records only failed|unavailable|skipped with reason (and actual tool_reference when present). It cannot mark success. Reading pages is counted separately from searches, by actual saved URL and read scope.
9. On gaps, update concepts/domains and choose another source, preserving prior attempts. To register an unlisted source, first save text actually returned by reading its public page. research_add_source needs run_id, new source_id custom_xxx, name, homepage URL prefix, verification_source_id (saved s_...), reason. The page must match the declared prefix and cannot be a fixture/user-supplied text. Registration is host_attested; it verifies only that the saved page matches the declared site, not ownership, authority or index coverage. It adds no new API endpoint. Select the new ID with research_plan. Do not guess or execute website-provided APIs or commands.
10. Inspect source_coverage and publish. Report planned, native queried, site searched, read scopes, failed/unavailable/skipped separately. A source with native empty results was genuinely searched, but zero results are not proof of absence. Required sources mean native database search (backend_database_response or host-attested native_database), never merely a site search; unmet requirements force partial status. Exhaustiveness remains unproven even if every required source has a query.

## Example

```json
{"run_id":"<returned>","domains":["biomed","omics"],"concepts":[{"terms":["tumor","cancer"]},{"terms":["endothelial cells","tumor endothelium"]}],"source_ids":["pubmed","europepmc","pmc","geo"],"required_source_ids":["pubmed","europepmc"],"task":"academic","reason":"Mechanisms and single-cell evidence require literature plus public data discovery"}
```

Use separate subquestion queries rather than mechanically combining every subtopic, which can erase recall. PubMed/Europe PMC discover papers; PMC/publisher sites read texts; GEO/SRA/ENA/CELLxGENE discover datasets. A dataset record does not replace the associated paper. Fields outside these examples use the same source registry and gap-expansion mechanism.

## Scope and limits

`strict_domains` only permits URL prefixes of selected sources for returned candidates, saved text and published citations. Site-prefix query construction is best effort; it does not force the remote provider's entire internal corpus. A Crossref-returned doi.org URL or an external publisher link may be filtered out under strict_domains even though the paper is registered in that database. Do not confuse URL/domain restriction with database-membership restriction. Scope changes require the user's authorization; the tool records the change but cannot independently authenticate user intent. Default preferred avoids these artificial restrictions.

The registry has snapshot version metadata and source access caveats. It covers selected common fields, not every discipline, language, country or paid database. Official product/version documentation may need a dynamically registered source. Legal/policy plans always require jurisdiction review. Bibliographic sources overlap; de-duplicate DOI/PMID and shared studies during synthesis. The host still performs semantic and study-quality review; this layer adds no independent truth guarantee.

## Official API references

- PubMed E-utilities: https://www.ncbi.nlm.nih.gov/books/NBK25499/ and usage https://www.ncbi.nlm.nih.gov/books/NBK25497/
- Europe PMC: https://dev.europepmc.org/RestfulWebService and https://www.ebi.ac.uk/europepmc/webservices/rest/search
- Crossref: https://www.crossref.org/documentation/retrieve-metadata/rest-api/ and https://api.crossref.org/

Source homepages and role caveats live in source-registry.json. A snapshot entry does not assert its page was read during this research run. HTTP errors are recorded, not bypassed.
