# Coder brief: Block-4 systematic-search pipeline (SAMP RQ4.2)

## 0. What you are building, in one paragraph

A standalone, deterministic Python pipeline that executes a frozen literature-search protocol
and produces structured, auditable data. It retrieves bibliographic records from scholarly
sources according to a pre-registered query bank, preserves raw evidence, normalizes records,
separates retrieval hits from unique documents, deduplicates documents, and reports status.
It does not use any LLM for retrieval, and it does not screen or judge papers. It must never
run the real search on its own initiative.

## 1. Authoritative specification

The scientific specification is the Notion page
"SAMP RQ4.2. Block 4A: Frozen Systematic Search Protocol, revision 3" (approved and frozen on
29 September 2026) and its subpage "Block 4A: Query Bank, revision 3". The protocol is frozen: any
change you believe is needed must be proposed to the user and, if accepted, recorded in the
protocol's deviation log before it takes effect. The user will give you access or export them.
Where this brief and the Notion page disagree, the Notion page wins. Do not change the
scientific content (directions, queries, thresholds, rules). If you believe a query or a rule
cannot be executed as written, stop and report; do not adapt it silently.

Also provided: `block4A_query_bank_rev3.yaml` (54 queries with all source-specific forms, field
`openalex_oql` for OpenAlex). Treat it as the initial content of `config/queries.yaml`; validate it
against the Notion page.

## 1b. Open question for you (answer before any retrieval)

The OpenAlex forms in the query bank are written as OQL `title_and_abstract has ( ... )` with
Boolean operators, quoted phrases and `*` truncation, including truncation inside quoted phrases
(for example `"dependence relation*"`, `"social commitment*"`). Please establish, with a recorded
fixture (and a single live probe only if the user allows it), whether OpenAlex OQL/OQO accepts each
of these constructs with the intended meaning. Report per construct: accepted as intended /
accepted with different meaning / rejected, with the exact response. Propose a resolution for
anything not accepted as intended; the user decides and records it in the deviation log. Do not
work around it in code.

## 2. Hard constraints

- No LLM calls anywhere in the retrieval pipeline.
- No secrets in source code, config files, logs, exports, Notion, or Git. Credentials come from
  environment variables or the OS keyring only (`OPENALEX_API_KEY`, `SCOPUS_API_KEY`, `WOS_API_KEY`,
  `IEEE_API_KEY`). Add `.env`, browser profiles, cookies and session data to `.gitignore`.
- No scraping of licensed databases behind institutional authentication. No password storage,
  no MFA bypass, no circumvention of access controls or licence terms. Where no official API or
  legitimate export exists, the source is `MANUAL_EXPORT_REQUIRED` with a deterministic importer.
- No Block-3 identifiers or candidate names anywhere in the code, config or data schema. The
  pipeline knows nothing about earlier passes.
- The real 54-query retrieval must not run automatically. Build, test with fixtures and mocks,
  validate configuration. Live API connectivity may be tested only when the user explicitly asks,
  and only with one small probe query, never with the bank.

## 3. Suggested layout (you may improve it; keep the separation of concerns)

```
block4_pipeline/
  config/
    queries.yaml        # 54 queries, all source forms, direction, lens, basis, register
    sources.yaml        # source roles, mandatory/supplementary per direction, access mode
    protocol.yaml       # thresholds, refinement order, depths, dedup rules, ID formats
  adapters/
    base.py             # common adapter interface
    openalex.py         # implement first
    scopus.py           # official API if entitled, else MANUAL_EXPORT_REQUIRED
    webofscience.py     # same
    ieee.py             # same
    dblp.py             # public API
    manual_import.py    # CSV / RIS / BibTeX / OpenAlex-JSON importer for any source
  pipeline/
    retrieve.py         # runs queries per source, writes raw + hits
    normalize.py        # raw -> common document schema
    deduplicate.py      # documents from hits (DOI, source IDs, normalized title+year)
    provenance.py       # hit <-> document links, search log
    validate.py         # protocol and config validation
    export.py           # CSV / JSONL / Parquet exports for screening tools
    status.py           # progress and audit report
  data/
    raw/<source>/<query_id>/<run_ts>/page_N.json
    normalized/
    exports/
    logs/
  tests/
    fixtures/           # recorded API responses, sample exports
  run.py
  README.md
```

## 4. Configuration, machine-readable protocol

`config/queries.yaml`: one entry per query with `id`, `direction`, `lens`, `canonical`,
`openalex_oql`, `scopus`, `wos`, `ieee`, `heinonline`, `scholar`, `dblp`, `ssrn`, `basis`,
`community`, `register`. The 54 IDs are B4-Q01..B4-Q48, B4-XC01, B4-XC02, B4-BR01..B4-BR04.

`config/sources.yaml`: per source: `role` (core | curated | domain | supplementary),
`access_mode` (api | manual_export | web), `mandatory_for` (list of direction IDs or `all`),
`supplementary_for`. Encode the source matrix of protocol section 5 exactly: OpenAlex mandatory for
all 54; Scopus and Web of Science mandatory for all (Uni.lu interface and export access is
confirmed; whether an API entitlement exists is your implementation check, `access_mode` api or
manual_export); DBLP mandatory for D01–D05, D08–D10, D14, XC, and Q-B of D16; IEEE mandatory for
D09, D11, D12, D13, D15, BR; HeinOnline mandatory for D03, D06, D07, D08; SSRN, Google Scholar and
web supplementary everywhere (invoked on demand, never as a 54-query run).

`config/protocol.yaml`: `threshold_structured: 300`, `scholar_depth: 100`, `web_depth: 20`,
`refinement_order: [title_restrict_free_group, add_mechanism_group, subject_area_limit, split_or_groups]`,
`openalex_page_size: 100`, `openalex_order: publication_date:asc,id:asc`,
`dedup_order: [doi, source_ids, normalized_title_year]`,
`id_formats: {hit: "B4-H{:05d}", document: "B4-R{:05d}"}`, `upper_cutoff_date: null` (set at the first
real 4B run and never changed afterwards without a deviation-log entry).

## 5. Command-line interface (illustrative)

```
python run.py validate-protocol
python run.py retrieve --source openalex [--query B4-Q01] [--dry-run]
python run.py retrieve --source scopus
python run.py import-manual --source ieee --query B4-Q31 --file exports/ieee_Q31.csv
python run.py normalize
python run.py deduplicate
python run.py export --format csv
python run.py status
```

`validate-protocol` must pass before any `retrieve` is allowed. `retrieve` refuses to run if
`protocol.yaml` has `frozen: false`. The protocol was approved and frozen on 29 September 2026; ship
`protocol.yaml` with `frozen: true` and `protocol_revision: 3`, and still refuse to run until
`validate-protocol` passes and the OpenAlex construct check (section 1b) is resolved.

## 6. `validate-protocol` checks

- exactly 16 directions B4-D01..B4-D16 exist and each has exactly one A, one B and one C query;
- exactly 54 queries; IDs unique; XC01, XC02, BR01–BR04 present;
- every query has every source form its mandatory sources require;
- every query has `basis`, `community`, `register`;
- no string in any query form contains a name from `config/denylist.txt`, a list of specific
  candidate artifacts, projects and tools that the user supplies (it starts empty). The denylist is
  about contamination by specific known candidates only. Generic formalism, mechanism and community
  names (event calculus, Petri net, deontic logic, institutional grammar, real options, MBSE, and
  the like) are permitted and must not be flagged; do not add a heuristic proper-name check;
- no secret-looking strings (long alphanumerics, `key=`, `token=`) in config or code;
- `sources.yaml` matches the matrix in the protocol (hard-coded expectation in the test);
- no network access during validation.

## 7. OpenAlex adapter (implement first)

- Use the OpenAlex Query Language (OQL) and its query-object form (OQO) through the OpenAlex
  API, not the legacy `search=` / `filter=...search:` parameters. Each query's `openalex_oql` field
  is the expression `title_and_abstract has ( ... )` carrying the canonical Boolean and `*`
  truncation directly. Do not expand synonyms, do not rewrite the expression.
- Before touching the bank, verify OQL/OQO behaviour with one recorded fixture and, only if the
  user explicitly allows a live probe, one small probe expression. Check: parentheses, AND/OR,
  quoted phrases, `*` truncation, and phrase-internal truncation (`"dependence relation*"`). If any
  construct is rejected or behaves differently, stop and report to the user with the exact error;
  the resolution goes through the protocol's deviation log. Never rewrite queries silently.
- Key from `OPENALEX_API_KEY` (env or keyring); send `mailto` from `OPENALEX_MAILTO` if present.
  Never log the key; redact it from every URL or request object written to logs.
- No year, language or type filter.
- Page size 100. Deterministic pagination with cursor in the fixed order: publication date
  ascending, then OpenAlex work ID ascending. Ordering is for reproducibility only; it plays no
  role in inclusion because every result of a query at or below the threshold is retrieved.
- Record per run: query ID, exact query object (key redacted), UTC timestamp, total count, pages,
  records retrieved. Save every page's raw JSON under `data/raw/openalex/`.
- Threshold rule: read the total count first. If it is at most 300, retrieve all. If greater,
  write the count to the search log, retrieve nothing, mark the query `REFINEMENT_REQUIRED`, and
  stop. The refinement is a human decision recorded in the deviation log; the pipeline then runs
  the refined sub-queries (`B4-Qxx.r1`, `.r2`, …) that the user adds to `queries.yaml`.
- Normalized fields: openalex_id, doi, title, authors (names + OpenAlex author IDs), year,
  publication_date, venue (source display name, ISSN), type, abstract (reconstruct from
  `abstract_inverted_index`), language, cited_by_count, query_id, exact query, retrieved_at,
  total_count, rank, page.
- Cutoff: `normalize` compares `publication_date` with `upper_cutoff_date`; records after the
  cutoff stay in raw data, are flagged `after_cutoff: true` in the normalized table, and are
  excluded from the export used for S1.
- Forward snowballing support: `retrieve --cited-by <openalex_id>` (works citing a given work),
  same ordering and threshold rules.

## 8. Other adapters

- **Scopus, Web of Science, IEEE:** implement the official API path only if the user confirms an
  institutional API entitlement and provides a key; otherwise the adapter reports
  `MANUAL_EXPORT_REQUIRED` and `import-manual` accepts the database's native export (Scopus CSV,
  WoS tab-delimited or RIS, IEEE CSV). Importers must map every field to the common schema and
  keep the raw export file. Record the exact query string the user pasted (from `queries.yaml`) and
  the export date in the search log.
- **DBLP:** public API (`https://dblp.org/search/publ/api?q=...&format=json&h=1000`), use the `dblp`
  form; DBLP has no abstracts, note that in the record.
- **Google Scholar, web, HeinOnline, SSRN:** no automation. `MANUAL_EXPORT_REQUIRED`; importer
  accepts CSV with title, authors, year, venue, url, rank.
- **Browser-assisted option (only if the user asks):** a local persistent browser profile in
  which the user logs in manually; the tool then only navigates to the search page, pastes the
  query and triggers the site's own export. No credential handling, no session export, profile
  directory in `.gitignore`. If this is not clearly permitted by the licence, do not implement it.

## 9. Data model

- **Hit** (`B4-H#####`): `document_id`, `query_id`, `source`, `exact_query`, `rank`, `page`,
  `retrieved_at`, `source_record_id`, `run_id`. One per returned record per query per source.
- **Document** (`B4-R#####`): `doi`, `openalex_id`, `source_ids` (dict), `normalized_key`,
  `title`, `authors`, `year`, `venue`, `type`, `abstract`, `language`, `first_seen_run_id`.
  Created by `deduplicate` from hits; many hits map to one document; never delete hits.
- **Search log**: one row per query run (fields in protocol section 25).
- **Deviation log**: `data/logs/deviations.jsonl`, appended by a `run.py deviation add` command
  with the protocol's fields; never edited in place.
- Store as JSONL plus Parquet; keep raw files immutable (write once, checksum in a manifest).

## 10. Deduplication (`deduplicate`)

1. Exact DOI match (normalized: lower case, strip `https://doi.org/`).
2. OpenAlex ID or other source ID match.
3. Normalized title (lower case, ASCII-fold, remove punctuation and a fixed stop-word list,
   collapse whitespace) plus year; also flag near-duplicates (normalized Levenshtein ratio > 0.92,
   same year ±1) for human review in `exports/near_duplicates.csv` without merging them.
Report dedup statistics per query and per source.

## 11. `status` report

Per source and per query: not run / running / done / REFINEMENT_REQUIRED / MANUAL_EXPORT_REQUIRED
/ failed; `meta.count`; records retrieved; hits; new documents after dedup; missing access;
pending manual imports; failures with timestamps. Print as a table and write `data/logs/status.json`.

## 12. Tests

- Unit tests for query loading, form validation, OpenAlex abstract reconstruction, dedup rules,
  ID allocation, secret redaction.
- Adapter tests against recorded fixtures (no network in the test suite).
- A test that `normalize` flags and excludes records dated after `upper_cutoff_date`.
- A `--dry-run` mode for `retrieve` that prints the exact request parameters (key redacted) and
  exits without calling the network.

## 13. What to deliver

- The repository with README (setup, secrets via env/keyring, commands, what is and is not automated).
- `validate-protocol` passing on the provided YAML, with a report of anything it flags.
- A short `DEVNOTES.md` listing every place where you had to interpret the protocol, and every
  source whose access mode is still unknown (`ACCESS_TO_CONFIRM`).
- No search results. Do not run the bank. Ask before any live API call.
