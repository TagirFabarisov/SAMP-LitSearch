# SAMP RQ4.2 — Block-4 systematic-search pipeline

A standalone Python program that executes the frozen literature-search protocol
"SAMP RQ4.2. Block 4A: Frozen Systematic Search Protocol, revision 3" (approved and
frozen 29 September 2026) and produces structured, auditable data: raw retrieval evidence,
a search log, retrieval hits (B4-H), unique documents (B4-R) and status reports.

It retrieves and records. It does not screen, judge or rank papers, and it contains no
language-model call. It never runs the 54-query bank on its own: every network call needs
an explicit `--live` flag.

The scientific specification is the Notion page and its query bank; copies are in
`docs/`. Where this code and the protocol disagree, the protocol wins.

## Layout

```
run.py                      command-line entry point
block4_pipeline/
  config/queries.yaml       the 54 pre-registered queries, all source forms (query bank rev. 3)
  config/sources.yaml       source roles, mandatory/supplementary allocation, access mode
  config/protocol.yaml      thresholds, ordering, deduplication rules, ID formats, cutoff date
  config/denylist.txt       specific candidate names that must not appear in any query (empty)
  adapters/                 one module per source (OpenAlex, DBLP, manual-export importer, ...)
  pipeline/                 validate, retrieve/import, normalize, deduplicate, export, status, oql-check
  data/                     raw evidence, normalized tables, exports, logs (local, not committed)
tests/                      unit and end-to-end tests on recorded/hand-written fixtures, no network
docs/                       protocol PDF, landscape page PDF, coder brief, query bank YAML
DEVNOTES.md                 every interpretation of the protocol made in code; open access questions
```

## Setup

Python 3.9 or newer.

```bash
python3 -m pip install -r requirements.txt
```

Credentials come only from environment variables or a local `.env` file in the repository
root (ignored by git). Never put a key in code, configuration, logs or Notion.

```
OPENALEX_API_KEY=...      # OpenAlex, sent as an Authorization: Bearer header
OPENALEX_MAILTO=...       # optional, polite-pool contact address
SCOPUS_API_KEY=...        # only if an institutional API entitlement is confirmed
WOS_API_KEY=...
IEEE_API_KEY=...
```

## Commands

```bash
python3 run.py validate-protocol
```
Checks the configuration against the protocol: 16 directions with one A, B and C query each;
54 IDs; every mandatory source has its form; basis/community/register present; no denylisted
name; no secret-looking string in config or code; `sources.yaml` matches the section-5 matrix.
No network. Must pass before any retrieval.

```bash
python3 run.py oql-check                  # offline: shows the recorded fixtures
python3 run.py oql-check --live           # non-retrieving API calls: /properties, /validate, /query
python3 run.py oql-check --live --execute # additionally count-only probes for the truncation question
```
The OpenAlex construct check of the coder brief (section 1b). `--live` is only run when the
user asks for it. The report is written under `data/logs/oql_check_<UTC>/`. Retrieval from
OpenAlex stays blocked until the user records the outcome in the deviation log and sets
`openalex_construct_check_resolved: true` in `protocol.yaml`.

```bash
python3 run.py retrieve --source openalex --query B4-Q01 --dry-run   # prints the exact request, no network
python3 run.py retrieve --source openalex --live                     # all queries, protocol order
python3 run.py retrieve --source dblp --query B4-Q01 --live
python3 run.py retrieve --source openalex --cited-by W2741809807 --anchor B4-A001 --live   # forward snowballing
```
Runs mandatory (query, source) pairs in the protocol's order (D01..D16, XC, BR; A, B, C).
The count is read first; above the threshold (300) nothing is retrieved, the count is
logged and the pair is marked `REFINEMENT_REQUIRED`. Every page's raw JSON is written once
under `data/raw/<source>/<query>/<UTC>/` with a checksum manifest. A pair already done is
skipped unless `--rerun`. Supplementary sources need `--include-supplementary`.

```bash
python3 run.py import-manual --source scopus --query B4-Q01 --file ~/Downloads/scopus.csv --export-date 2026-10-02
python3 run.py import-manual --source wos --query B4-Q01 --file export.ris
python3 run.py import-manual --source heinonline --query B4-Q07 --file hein.csv --format generic_csv
```
For sources without an API path (Scopus, Web of Science, IEEE, ACM, HeinOnline, SSRN,
Google Scholar, web): paste the exact string from `queries.yaml` into the database,
export, and import. The export file is kept unchanged as raw evidence. Formats:
`scopus_csv`, `wos_tab`, `ieee_csv`, `acm_csv`, `ris`, `bibtex`, `generic_csv`
(title, authors, year, venue, url, rank), `openalex_json`.

```bash
python3 run.py normalize      # raw records -> common schema, one row per hit, after_cutoff flag
python3 run.py deduplicate    # unique documents B4-R; near-duplicates to exports/near_duplicates.csv
python3 run.py export --format csv|jsonl|parquet|all
python3 run.py status         # table per query and source; writes data/logs/status.json
python3 run.py set-cutoff 2026-10-01
python3 run.py deviation add --rule "..." --change "..." --reason "..." --timing before --effect "..." --rerun no
python3 run.py deviation list
```

## What is and is not automated

| Source | Mode | Notes |
|---|---|---|
| OpenAlex | API (OQL) | mandatory for all 54 queries; blocked until the construct check is resolved |
| DBLP | public API | mandatory where the protocol says; titles only, no abstracts |
| Scopus, Web of Science | manual export | interface access confirmed; API entitlement to confirm |
| IEEE Xplore, ACM DL | manual export | API entitlement to confirm |
| HeinOnline, SSRN, Google Scholar, web | manual export | no automation, by protocol section 23 |

No scraping, no stored passwords, no circumvention of licence terms. Browser-assisted
export is not implemented.

## Data model

- **Hit** `B4-H#####` — one per returned record per query per source: query ID, source,
  exact string sent, rank, page, retrieval time, source record ID, run ID, raw-file locator.
  Append-only (`data/normalized/hits.jsonl`).
- **Document** `B4-R#####` — one per distinct work, built by `deduplicate` in the order
  DOI → source IDs → normalized title + year. IDs are stable across reruns.
- **Search log** — one row per query run (`data/logs/search_log.jsonl`), append-only.
- **Deviation log** — `data/logs/deviations.jsonl`, append-only.
- **Raw evidence** — write-once files with sha256 manifests.

## Tests

```bash
python3 -m pytest -q
```
All tests run against a temporary data directory and a stubbed network; any attempt to
reach the network fails the test.
