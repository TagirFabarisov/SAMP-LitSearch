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

## Open question 1b: what the live check recorded (29 September 2026, user-approved)

Recordings: `block4_pipeline/data/logs/oql_check_20260929T210956Z/` and
`oql_check_20260929T211211Z/` (with count probes; `extra_phrase_decomposition_probe.json`).

| Construct | Result | Evidence |
|---|---|---|
| parentheses, AND/OR | accepted as intended | C1 parses; translated to nested OR/AND filter rows |
| quoted phrase `"resource dependence"` | accepted; evaluated on **unstemmed** text (`title_and_abstract.search.exact`) | C2: 7,703 |
| bare word `actor` | accepted; evaluated on **stemmed** text (`title_and_abstract.search`) | C3a: 901,744 |
| bare truncation `actor*` | **rejected** by the parser: "wildcards run on exact (no-stem) text; fix: quote it" | C3 |
| quoted truncation `"actor*"` | accepted; prefix match on unstemmed text | C3q: 913,810 (vs 206,116 for exact `"actor"`) |
| phrase-internal truncation `"dependence relation*"` | accepted as intended: phrase kept, `*` honoured | C4: 3,484 vs 715 singular, 985 plural, 966 "relationship"; the AND form `"dependence" AND "relation*"` gives 221,938, so the phrase was not decomposed |
| hyphenated phrase `"power-dependence"` | accepted | C5: 135,516 |
| column `title_and_abstract` | accepted; registered as `title_and_abstract.search` / `.search.exact` | properties registry |
| `cites is (W…)` for forward snowballing | accepted; translated to `referenced_works` | C7: 1,253 |
| sort `publication_date:asc,id:asc` (protocol.yaml as shipped) | **rejected**: `id` is not sortable | sort_checks |
| sort `publication_date:asc,ids.openalex:asc` | accepted | sort_checks |

Consequences for the user to decide and record in the deviation log:

1. Every bare `word*` in the 54 `openalex_oql` forms has to be written `"word*"`; 52 of
   the 54 queries are affected (no `?`, no token shorter than 3 characters). `run.py
   propose-quoting` writes the rewritten bank and a diff under
   `data/logs/quoting_proposal_<UTC>/`; the program does not apply it.
2. Quoted phrases are matched without stemming in OpenAlex (unlike Scopus/WoS loose
   phrases). Where a phrase's last word may vary (`"social commitment"` vs `"social
   commitments"`), only the forms already carrying `*` cover the variants. This is a
   property of the closest-equivalent adaptation, to be noted, not necessarily changed.
3. `openalex_order` in protocol.yaml must become `publication_date:asc,ids.openalex:asc`
   (same meaning as the protocol's "publication date, then OpenAlex work ID").

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

## Scopus API (29 September 2026)

Adapter implemented against the Scopus Search API (dev.elsevier.com): `TITLE-ABS-KEY(...)`
form sent unchanged, view COMPLETE (abstracts, 25 per page), ordering `+coverDate`, count
read first with a STANDARD-view request of one record. The key is a free developer key;
the subscription is checked by Elsevier from the network address, so the entitlement probe
(`run.py scopus-check --live`) has to be run from the Uni.lu network or VPN. Until it
succeeds, `sources.yaml` keeps `scopus: access_mode: manual_export`; switching it to `api`
is an implementation choice under protocol section 5 and gets a deviation-log entry for
the record. The Scopus search API does not return the language of a record.

## Document folders and the S2 layer (decided 29 September 2026)

`deduplicate` writes `data/documents/B4-R#####/metadata.json` and `provenance.json`. The
evidence-packet idea (source-linked extraction of what artefact a paper defines, with page
evidence per claim) is the software-supported S2 worksheet and is built only for
documents that pass S1; it does not change the frozen protocol's order. Open-access PDFs
(location recorded from OpenAlex `best_oa_location`) may be downloaded by the pipeline;
paywalled copies are obtained by hand (`PDF_NEEDED`).

## Not implemented on purpose

- Browser-assisted export (brief section 8): not implemented until the licence permits it
  and the user asks.
- Any screening (S1–S3), snowball anchoring logic beyond the `--cited-by` retrieval, and the
  registers (B4-A, B4-F, B4-S, B4-X, P2, RQ4.3): outside the retrieval pipeline.
