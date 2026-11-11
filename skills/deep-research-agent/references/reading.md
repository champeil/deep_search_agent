# Full-text-first reading (0.5.0)

## Policy

For selected literature, use accessible article full text before abstract-only evidence. HTML, structured article XML and PDF are alternate full-text carriers, not quality tiers. Prefer accessible structured text when equivalent versions exist, while checking DOI/title/version identity. Screening an abstract first is allowed; it does not satisfy deep reading when the body is available. Main paper sections are Introduction → Results → Methods → Abstract. Check figures/tables and legends, Discussion/limitations and supplements when relevant to the claim, even though they are not the four default section requirements.

If one path fails, try a reasonable alternative (e.g. publisher/PMC HTML, public XML or PDF) within budget, usually no more than three full-text routes for one selected paper before reassessing priority. Do not spend the entire run on one inaccessible article. Locate candidates by actual DOI/PMID/title searches if links are missing. Different paths can have the same paper/version; do not count them as independent studies. Abstract only is an explicit fallback after recorded primary-access/discovery failures. Budget exhaustion, source scope, OCR needs or a temporary network failure are distinct reasons and do not establish nonexistence of full text. If full text is captured but priority sections remain unread, preserve partial status rather than claiming an abstract-only fallback. No abstract means no content-based claim from metadata alone.

## Tools

1. `research_document` registers run_id, kind (paper|technical|policy|dataset|news|business|general), title, optional stable identifier (prefer DOI/PMID plus version), fulltext_urls, summary_urls, source_ids. For paper, summary_urls means actual abstract landing pages; non-papers use source summaries. It returns document_id (d_...) and a reading plan. Re-registering the same kind/identifier merges new URLs without discarding prior reading. At most 60 documents/run and eight candidates/document. Select useful papers first; do not automatically register/read every search hit.
2. Native database results return reading_candidates: actual result metadata plus suggested PMC HTML/XML links when PMCID exists. These are hints only; a link can fail or require appropriate availability. They are not automatically fetched, registered, or counted as read.
3. `research_reading_plan` takes run_id, optional document_id. With a document, returns ordered candidates, priority and conditional sections, current reading level, missing sections and fallback reasons. Without it, returns compact document progress and profiles. It makes no network call. Section hints from read/inspect_source are locators, not a reading record.
4. When reading/importing actual text, pass document_id to research_read, research_extract or research_source. The requested/imported URL must already be registered. A direct-reader redirect is attached using the original candidate and actual final URL. Captures do not prove reading. Native source imports keep actual read_scope and provenance; abstract-only text must be tagged abstract. API/direct extraction still conservatively uses partial_text, independently of document section progress.
5. `research_document_attempt` takes run_id, document_id, method, outcome, reason, optional url/tool_reference. Methods: native_reader|direct_reader|api_extract|discovery|scope|budget. Outcomes: failed|unavailable|not_primary|skipped|not_found. Reader attempts use registered URLs. Host native/API attempts need an actual tool_reference. Discovery not_found requires an existing logged search query/reference; this remains a host assessment of that search. No supplied success flag can manufacture a capture. Backend direct-reader/extraction failures with document_id are logged automatically. Explicit scope/budget limits can be recorded without inventing a failed request. A successful URL returning just an abstract/login/metadata page should not be treated as article full text; correct its actual scope and record not_primary/failure with the real reason.
6. `research_document_read` takes run_id, document_id, identity_note, sections:[{source_id,section,start,end}], optional not_present:[{source_id,section,reason}]. Read substantive section content, not merely a heading or one quotable sentence. Record windows ACTUALLY inspected; offsets address saved normalized source text, with each span 20–12000 characters. Batch up to twenty spans/absence entries per call; long sections can use multiple windows. Identity note describes title/DOI/version checks against retrieved content. Abstract/summary capture cannot satisfy body sections. Observed absence requires a captured primary source plus a concrete reason; integrated sections can be mapped from their actual spans. Do not guess absence from truncation. Section labels and reading remain HOST-ATTESTED; the backend validates source IDs, exact offsets/digests and scope, not whether a model truly understood the section.
7. Inspect reading_coverage before publish. Source downgrades/changes invalidate incompatible reading records. Unresolved reading for documents linked to report citations forces partial; unrelated unselected documents do not block publication. Legacy sources without a document record remain supported but have no document-section verification. They cannot be advertised as following this policy solely from read_scope=page_text.

## Material profiles

| Kind | Primary/detail reading | Fallback |
|---|---|---|
| paper | Introduction, Results, Methods, Abstract; conditional figures/tables, Discussion/limitations, supplements | actual abstract |
| technical | version, reference/contract, parameters, limitations; add examples/errors | official summary/README, labelled limited |
| policy | scope/jurisdiction, operative provisions, effective date, exceptions; definitions/amendments | official summary/interpretation, labelled limited |
| dataset | provenance, variable dictionary, collection/processing methods, limitations; data/version as relevant | actual dataset summary |
| news | primary evidence, date, context, limitations; corroborating original sources | news summary, with missing original evidence stated |
| business | reporting period, statements, notes, risks; methodology as needed | official summary, with missing filings stated |
| general | original evidence, methods, limitations, summary | actual summary |

Source preference is separate from content quality. An original source can still contain errors; the host reviews what each claim supports. Methods/figure-level or causal claims should not be inferred from an abstract that omits those details. Do not copy authors' causal language without checking the actual design.

## Levels

- primary_sections: at least one actual body/detail section read and every profile priority section read or observed genuinely absent. This is not a claim of word-for-word full-article reading or complete access to supplements/figures.
- partial_primary: some body/detail reading, priority sections incomplete.
- summary_with_primary_unread: summary read although primary text is captured and unread. Does not qualify as an abstract-only fallback.
- abstract_only / summary_only: actual fallback text read, recorded primary routes resolved as unavailable/not-primary, or logged discovery found no primary candidate. No claim that all possible full texts were exhausted.
- abstract_only_limited / summary_only_limited: fallback due to explicit budget/scope/skip constraint. This does not assert primary text is unavailable in general.
- fallback_unresolved: only summary read while primary retrieval/discovery remains unresolved.
- not_read: no actual section span registered, even if text was downloaded.

Reports and audit.json include reading levels, covered/absent sections and fallback reasons. Limited fallback is allowed as evidence with explicit limitations; it does not waive claim support requirements. Exact source/section identity and model review still require judgment.

## XML reader

The direct reader can parse public article XML/JATS into normalized text with headings. Custom XML entities are rejected; no external entity fetching is enabled. Size, public-address, robots and existing parser limits remain. XML tables/figures may lose visual structure, so use native visual/table tools when relevant. Reader extraction format and section hints do not automatically mark full-text reading.
