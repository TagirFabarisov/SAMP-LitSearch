# Development notes: interpretations and open points

Every place where the code had to interpret the protocol or the coder brief, and every
source whose access mode is still to confirm. Written 29 September 2026.

## Interpretations of the protocol / brief

1. **OQL entity prefix.** The query bank stores `title_and_abstract has (...)`; OpenAlex OQL
   names its entity, so the string actually sent is `works where title_and_abstract has (...)`.
   The search log records the full string sent. (`protocol.yaml: openalex_entity_prefix`)
2. **Count check retrieves one record.** To "read the total count first", the OpenAlex
   adapter sends the query with `per_page: 1`; OpenAlex returns `meta.count` plus one record,
   which is saved as `count_check.json` and never becomes a hit. DBLP supports `h=0` and
   returns no record.
3. **"Stop" on REFINEMENT_REQUIRED** is read per query: the pair is logged and the run
   continues with the next query so that no direction is starved (section 24). Nothing is
   retrieved for the flagged query.
4. **Threshold on manual exports.** An export with more than 300 rows for a structured
   source is kept as evidence but creates no hits and is marked REFINEMENT_REQUIRED; the
   protocol's refinement sequence then applies by hand.
5. **Manual-export dates.** Records imported from an export get `publication_date` = year
   only (`YYYY-01-01`) when the export gives no full date; the cutoff comparison therefore
   errs towards keeping such records. `retrieved_at` is the `--export-date` if given.
6. **Document IDs are stable.** `deduplicate` reads the existing `documents.jsonl` and
   keeps its IDs; only genuinely new documents get new B4-R numbers. Hits are never deleted.
   The hit → document mapping and the document table are derived and rewritten each run.
7. **`after_cutoff` on a document** is true only if every hit of that document is after the
   cutoff.
8. **Near-duplicates** use a plain Levenshtein ratio on the normalized title, year within
   ±1, blocked by year for speed. Pairs above 0.92 are written to
   `exports/near_duplicates.csv` and never merged.
9. **Forward snowballing** uses OQL `works where cites is (W...)`. Whether that is the
   column name OQL expects is part of the live construct check (construct C7).
10. **Search-log field "documents new after dedup"** cannot be known at retrieval time and
    the log is append-only, so it is reported by `status` from `dedup_stats.json` instead
    of being written into the log row.
11. **Parquet** is written only if `pyarrow` is installed (it is not on the current
    machine); CSV and JSONL are always written.
12. **Raw data and derived tables are not committed** to git for now (`.gitignore`);
    logs (`search_log.jsonl`, `deviations.jsonl`) are committed. Decide before the real run
    whether raw JSON should be versioned too (about 16k records at most for the bank).
13. **Resolution of the construct check is a manual edit** of `protocol.yaml`
    (`openalex_construct_check_resolved: true`) after the deviation-log entry; the program
    does not flip that flag itself.
14. **Web source query form.** The protocol gives no separate string for general web
    search; `sources.yaml` reuses the Scholar short form.
15. **ACM DL** shares the IEEE form (protocol section 4) and is listed as a separate
    source so its exports and search-log rows stay distinguishable.
16. **Denylist check** is a case-insensitive substring match per line against every query
    form. No heuristic proper-name check, as instructed.

## Recorded fixtures

The fixtures in `tests/fixtures/` were written by hand from the OpenAlex and DBLP
documentation, not recorded from the services, because no live call was permitted. Each
file says so (`"recorded": false`). They exercise the response shapes the code handles.
The first permitted live `oql-check --live` will produce real recordings under
`data/logs/oql_check_<UTC>/`; copy those into `tests/fixtures/openalex/` afterwards.

## Open question 1b: OpenAlex constructs — what the documentation says

Read on 29 September 2026 from help.openalex.org (`/api/oql/`, `/api/searching/`,
`/api/llm-quick-reference/`):

- OQL executes at the API root (`POST /` with `{"oql": ...}`), `has` is the text-search
  operator, invalid expressions return HTTP 400 with a `validation` block; `/validate` lints
  and `/query` translates without executing. → The mechanics are settled and implemented.
- The **classic** search honours `*` and `?` wildcards only under `search.exact`; the
  stemmed `search` treats them differently, and a term needs at least three characters
  before a wildcard. Whether `has (...)` maps to the stemmed or the exact search, and
  whether `*` inside a quoted phrase (`"dependence relation*"`) is honoured, is **not stated**.
- Whether `title_and_abstract` is a valid OQL column (as opposed to `title_and_abstract.search`
  or `default.search`) is **not stated**.

`run.py oql-check --live` answers these with non-retrieving calls; `--execute` adds
count-only probes comparing `"dependence relation*"`, `"dependence relation"` and
`"dependence relations"`. Nothing in the query bank is changed by the program.

## Access modes still to confirm (`ACCESS_TO_CONFIRM`)

| Source | Current mode | To confirm |
|---|---|---|
| Scopus | manual_export | institutional Scopus API entitlement (Elsevier developer key) |
| Web of Science | manual_export | WoS Starter/Expanded API entitlement |
| IEEE Xplore | manual_export | IEEE Xplore metadata API key |
| ACM DL | manual_export | export format of the ACM interface (CSV/BibTeX) |
| HeinOnline | manual_export | export format (the importer expects generic CSV) |
| SSRN, Google Scholar, web | manual_export / web | on demand only; generic CSV import |

The API adapters for Scopus, WoS and IEEE are stubs that report the situation; they are
implemented only once an entitlement and key exist.

## Not implemented on purpose

- Browser-assisted export (brief section 8): not implemented until the licence permits it
  and the user asks.
- Any screening (S1–S3), snowball anchoring logic beyond the `--cited-by` retrieval, and the
  registers (B4-A, B4-F, B4-S, B4-X, P2, RQ4.3): outside the retrieval pipeline.
