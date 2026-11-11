# Evidence tool inputs

Use the MCP tool when available. Otherwise save the JSON arguments and run:

```text
python /absolute/skill/scripts/research.py call TOOL_NAME --root /project/deep-research-runs --input /path/arguments.json
```

The helper returns `ok` plus `result` or `error`. Use the returned IDs verbatim. A failed call is not valid evidence. Do not edit the database directly.

## Operations

- `research_begin`: `{question,subquestions:[{id:"Q1",question,weight:1}],mode:"research"}`. Returns run_id. Mode may be quick.
- `research_log_search`: `{run_id,query,round:1,purpose:"discovery",provider:"host-web-search",result_count:5,tool_reference:"actual tool reference"}`. Purpose may be gap or counter. Log only successful calls. References are host-supplied provenance, not server-side proof.
- `research_search`: `{run_id,query,round:1,purpose:"discovery"}`. Ten-provider optional search backend. Omitted native_status returns needs_native; after actual native absence/failure/insufficiency pass native_status and optional task/strategy. Returns candidates and logs a successful nonempty query; individual errors and empty responses remain in retrieval usage. No LLM call.
- `research_source`: `{run_id,url,title,text,read_scope:"page_text",provenance:{provider:"host-reader",tool_reference:"actual reader reference"}}`. Import only text actually read. Allowed scopes: page_text, partial_text, abstract, user_supplied, test_fixture. For supplied files without a public URL use `urn:user-document:NAME` with user_supplied; synthetic documents can use that identifier with test_fixture. Fixture sources force demonstration labelling. Keep per-page sources separately when needed to retain PDF locators.
- `research_read`: `{run_id,url}`. Optional direct public-URL reader; no JavaScript execution. Failure means use a host reader or record a gap.
- `research_inspect_source`: `{run_id,source_id,offset:0,limit:4000}`. Retrieve a text window after compaction.
- `research_quote`: `{run_id,source_id,quote:"exact contiguous substring",locator:"actually verified page or section"}`. Returns evidence_id and computed Unicode offsets. Locator is host-attested metadata, not independently verified by the tool.
- `research_claim`: `{run_id,question_id:"Q1",text:"atomic statement without citation markers or URLs",evidence_ids:["returned evidence ID"],kind:"fact"}`. Kind may be inference. Returns claim_id, initially pending.
- `research_review`: `{run_id,claim_id,verdict:"supported",reason:"concrete short reason",supporting_evidence_ids:["returned evidence ID"]}`. Other verdicts: partially_supported, contradicted, insufficient. Supported review must name exactly the contributing cited evidence IDs. This is a HOST-MODEL review, not server-side semantic validation. Review every claim separately.
- `research_status`: `{run_id}`. Returns coverage, missing questions, claims and query history.
- `research_publish`: `{run_id,claim_ids:["approved claim ID"],limitations:["unresolved issue"],stop_reason:"coverage_sufficient"}`. Returns report paths, Markdown, audited/partial status. Research mode needs successful searches in at least two rounds and a counter query for audited status. Supplied-document-only work may return a partial report with this limitation. Unreviewed claims, altered evidence or unsupported references are refused.
- `research_get_report`: `{run_id}`. Returns saved Markdown after publication.

## Minimal order

Begin → native search → log successful search → native read → import source → register exact quote → candidate claim → context review → coverage check → new gap/counter searches → review revised claims → publish.

Reserve search and reading budgets for later rounds. Native search may batch variants, but log each actual query honestly. Search snippets are discovery metadata; do not import them as page_text. Never change abstract scope to full text.


## Multi-provider retrieval (0.3.0)

`research_providers` accepts optional task, strategy, operation (search/extract), provider and needs no run_id. It is a network-free configuration/route inspector.

`research_search` retains run_id/query/round/purpose and adds optional task, strategy, provider, native_status. Default native_status unknown returns needs_native without network. After actual native absence/failure/insufficiency, use unavailable/failed/insufficient. A successful operation logs its logical query automatically; never also call research_log_search for it. Each fallback attempt is counted separately. A new gap query is needed after an already logged native query.

`research_extract` takes run_id/url plus the same optional routing fields. It saves returned page text as partial_text with provider provenance and returns a preview; inspect_source pages through the rest. It does not guarantee article full text or extract visual figures. If only an abstract is present, label this evidence accordingly in the report.

CLI example arguments for API search after actual native unavailability:

```json
{"run_id":"<returned run_id>","query":"tumor endothelial cells angiocrine signaling original study","round":1,"purpose":"discovery","task":"academic","strategy":"balanced","native_status":"unavailable"}
```

See providers.md for configuration, task priorities, budgets, failure handling and accounting.

For a saved API/direct source found to contain only an abstract, re-import the identical actual URL+text with read_scope abstract. Conservative scope downgrade persists and invalidates related claim reviews; inspect then re-review. Silent scope upgrades of identical content are refused. Direct PDF passage page numbers survive in research_inspect_source.page_locations and research_quote.pages.

The CLI accepts --env /absolute/private/research.env. Without it, terminal fallback discovers the installed runtime sibling file, then nearest cwd ancestor .deep-research/research.env, then ~/.local/share/deep-research-agent/research.env. Process environment values still take precedence. MCP always passes its installation-specific file explicitly.


## Source-aware planning (0.4.0)

Read sources.md for research_catalog, research_plan, research_add_source, research_source_attempt and research_database_search. research_begin returns compact domain/source suggestions; research_status returns source_coverage. Optional research_log_search fields catalog_source_id/access_method explicitly distinguish native_database vs site_search. Optional research_search catalog_source_id targets one site prefix and labels the method. Successful new backend calls log themselves. Audit and report export include the selected plan and actual coverage; required native database searches left incomplete force partial status.


## Reading priorities (0.5.0)

Read reading.md for research_document, research_reading_plan, research_document_attempt and research_document_read. Optional document_id on research_read/research_extract/research_source attaches real captured text. Capturing or inspecting a preview does not mark priority sections read. Use saved-source offsets for actually inspected spans and record primary-text failures before an abstract-only fallback; publishing cited documents with unresolved section reading is partial.
