# Handover: SAMP RQ4.2 Block-4 search pipeline

Written 1 October 2026 (afternoon), for the next session. Read this first, then DEVNOTES.md.
Everything below is committed and pushed (GitHub TagirFabarisov/SAMP-LitSearch, branch main).

## 1. Where things stand, in one table

| Source | Status | Hits in corpus | What remains |
|---|---|---|---|
| OpenAlex | complete (API) | 12,780 | 13 split parts above 300 with no OR group left: Tagir's decision (DEVNOTES "4B run record, OpenAlex") |
| Scopus | complete (API, from the Uni.lu network only) | 6,796 + 1,577 | a few exhausted parts (Q24, Q42, Q48) likewise |
| DBLP | complete (official SPARQL endpoint) | 630 | nothing |
| IEEE Xplore | bank counted; refinement counted; **35 runnable sub-queries not yet retrieved** | 633 | `python3 run.py retrieve --source ieee --live` (needs a new day's quota, see §4); then Q38 part 6 (698) needs `refine --source ieee --further --live` |
| Web of Science | **all 54 queries counted and refined in the interface (Phase A done); 2 of 66 exports imported** | 189 | **Phase B: 64 exports, Tagir clicks Save** (§5) |
| HeinOnline | not started (mandatory for D03, D06, D07, D08 = 12 queries) | 0 | manual export in the interface via a-z.lu, `import-manual --source heinonline --format generic_csv` |
| ACM, SSRN, Scholar, web | supplementary, not invoked | 0 | only if a refinement calls for it |

Corpus after OpenAlex + Scopus + DBLP + 2 WoS files: 21,177 hits → 14,342 unique documents
(the two WoS imports were added after that count; rerun `normalize`, `deduplicate`, `export`
after Phase B).

## 2. How to run things (all from the repository root)

```
python3 run.py validate-protocol          # must pass; it does
python3 run.py status                     # table per (query, source)
python3 run.py normalize && python3 run.py deduplicate && python3 run.py export --format all
python3 -m pytest -q                      # 49 tests, no network
```
Keys live only in `.env` (gitignored): OPENALEX_API_KEY, SCOPUS_API_KEY, IEEE_API_KEY.
Scopus API works only from the Uni.lu network (not the split-tunnel VPN). IEEE: 200 calls/day,
guarded by `data/logs/ieee_calls_<date>.json` (the adapter stops at 190; resume next day).

## 3. Protocol bookkeeping

- 8 deviation-log entries in `block4_pipeline/data/logs/deviations.jsonl` (quoted OpenAlex
  wildcards; ids.openalex ordering; stemming note; algorithmic refinement; recursive split;
  Scopus API mode; DBLP via SPARQL; IEEE API with exact wildcard decomposition). Tagir still
  has to copy them into the Notion deviation table in his words.
- Sub-IDs: `.r1` = step 1 (title restriction), `.r2` = steps 1+2 (mechanism group), `.r3` =
  1+2+3 (subject areas), `.r4.n` = split part n, `.r4.n.m` = second-level split. One form per
  source under the same sub-ID, exactly as base queries have one form per source.
  Config entries for API sources are in `block4_pipeline/config/refinements.yaml`; for WoS the
  forms are derived on the fly by `block4_pipeline/tools/wos_plan.py` from the ID alone.
- WoS adaptations (record in DEVNOTES if not yet there): step 1 → `TS=(...) AND TI=(free group)`;
  step 3 → `AND WC=("Computer Science*" OR "Engineering*" OR "Operations Research & Management
  Science" OR "Management" OR "Business*" OR "Economics" OR "Law" OR "Social Sciences*" OR
  "Political Science" OR "Public Administration" OR "Information Science & Library Science")`
  (WoS accepted it); IEEE: step 1 and 3 not expressible → recorded as skipped.
- Library/licence: Tagir registered at the LLC on 1 Oct 2026; the info point said a
  systematic-review account is a typical use case. Tagir authorised tool-assisted use of the
  WoS interface with him present (his credentials, his clicks on Save). Do not automate the
  DBLP bot-check page (we use SPARQL instead) and do not script licensed interfaces beyond
  paste-search-export with Tagir present.

## 4. IEEE: what to do on a fresh day

```
python3 run.py retrieve --source ieee --live        # retrieves the 35 runnable sub-queries
python3 run.py refine --source ieee --further --live   # Q38.r4.6 (698) second-level split
python3 run.py retrieve --source ieee --live        # whatever became runnable
```
Q27 was accepted by the API despite three wildcard words (no decision needed).

## 5. Web of Science, Phase B (the export sitting)

Access: a-z.lu (Tagir signed in with uni.lu SSO) → search "Web of Science" → the record's
"Web of Science Core Collection" link → `https://eu04.alma.exlibrisgroup.com/view/action/uresolver.do?operation=resolveService&package_service_id=12538643910007251&institutionId=7251&customerId=7250`
→ lands on `https://www-webofscience-com.proxy.bnl.lu/wos/woscc/advanced-search`. If the
proxy session has expired, repeat the a-z.lu route (the browser pane blocks pop-ups: open
that link with `navigate`, not by clicking).

The browser pane must be ≥ 1,000 px wide (narrower, WoS hides the Export button). Do **not**
use viewport emulation (clicks land off-page). At the current width (1,146 px) the Advanced
Search "Search" button is at screenshot coordinate (395, 478); the query box is the textbox
"Enter or edit your query…" (ref via `find`). Read the count from `document.title`
(`– N –`). Zero results shows "Your search found no results" on the same page.

Export routine per entry (worked for Q01.r1 and Q02.r1):
1. Run the string (navigate to advanced-search, find textbox, form_input, click Search, wait 7 s).
2. `find "Export"` → click the generic "Export" ref (not "Export Refine") → `find "Tab delimited file"` → click the menuitem.
3. In the dialog: click the "Records from:" radio (ref via find), form_input start = 1, end = N,
   click the combobox "Filter by, Author, Title, Source" → click option "Full Record".
4. Press the dialog's Export button (JS: the button whose text is exactly "Export"; at 1,146 px
   width it was at screenshot (320, 363)). A macOS Save dialog appears for **Tagir**; he clicks
   Save (the dialog remembers the last folder, he chose the repository root).
5. The file arrives as `savedrecs.txt` (or `savedrecs (1).txt`) in the chosen folder. Move it to
   `block4_pipeline/data/raw/manual_exports/wos/<ID>.txt` and import:
   `python3 run.py import-manual --source wos --query <ID> --file <path> --format wos_tab --export-date 2026-10-0X --note "Web of Science Core Collection, Full Record, exported in the interface by the user"`
   (refinement IDs are accepted; the exact string is taken from the count row in the search log).
   A watcher pattern that worked: a background `until ls savedrecs*.txt; do sleep 2; done` loop.
Downloads from synthetic clicks were never saved by the pane without Tagir's Save; page
hooks posting to a local receiver are blocked by the page's content-security rules — don't
retry those routes.

The export list: `block4_pipeline/data/raw/manual_exports/wos/wos_export_plan.jsonl` — 69
entries, 64 still to export (8,066 records), 3 zero-result parts (nothing to export), 2 done.
Each line has `id`, `count`, `string` (the exact TS=/TI=/WC= string to paste). Exhausted
parts above 300 with no OR group left (not exported, Tagir's decision): B4-Q48.r4.1.2 (471),
B4-Q48.r4.1.3 (490).

Every WoS count is already in the search log (rows with status `counted`,
`REFINEMENT_REQUIRED` or `refinement_count`, source `wos`); the import adds the `done` row.

## 6. After the exports

1. `normalize`, `deduplicate`, `export --format all`, `status`; commit `data/logs` and the
   corpus record in DEVNOTES (hits, documents, source overlap).
2. HeinOnline (12 queries) by hand via a-z.lu, then import.
3. S1 screening: design draft awaiting Tagir's approval in `docs/S1_screening_design.md`
   (prompt text, two model families, output schema, audit sample). He wants it run on
   Friday/weekend; it needs API access to two model families. Build the runner only after he
   approves the prompt and picks screener B.
4. Open decisions for Tagir: the exhausted parts above 300 in all sources (accept as gaps,
   split the title group too, or refine by hand); the Notion deviation table.

## 7. Files worth opening

- DEVNOTES.md — every interpretation, run records, access situation per source.
- docs/S1_screening_design.md — the S1 draft.
- block4_pipeline/data/logs/search_log.jsonl — the audit trail; status.json after `run.py status`.
- block4_pipeline/tools/wos_plan.py — `next <ID> <count>` logs a WoS count and prints the next
  string (RUN …) or EXPORT/EXHAUSTED; stateless apart from the log.
- block4_pipeline/tools/export_receiver.py — local receiver; not usable with WoS (blocked), kept.

## 8. Things that bit me (so they don't bite you)

- zsh does not word-split unquoted variables: write each `python3 … next ID N` call out.
- `form_input` needs a `find` first in the same batch (ref map); the WoS textbox has been
  `ref_100` after every page load, but still call `find` before using it.
- A WoS search sometimes does not fire on the first click right after load; a second click
  (same coordinate) fixes it. Always read the count from the title, never assume.
- Batches are capped at 25 actions (three searches per batch).
- Keep-awake: `mcp__ccd_host__request_keep_awake` (until session_idle) works; `caffeinate` as fallback.
