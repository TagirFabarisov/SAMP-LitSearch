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

Probe of 29 September 2026 over the Uni.lu VPN (logs `scopus_check_20260929T213709Z.json`,
`scopus_check_standard_*.json`): the key is valid, but the VPN is split-tunnel (public
address was a Post Luxembourg home line), so Elsevier saw no subscription: COMPLETE view →
HTTP 401 AUTHORIZATION_ERROR; STANDARD view → HTTP 200 with title, first author, venue,
date, DOI, EID, citation count, but no abstract and no author list. Options: run from
campus (or a full-tunnel VPN), ask Elsevier/the library for an institutional token
(`SCOPUS_INST_TOKEN`, sent as X-ELS-Insttoken), or retrieve STANDARD metadata by API and
complete abstracts from OpenAlex by DOI / interface export for the rest.

## Document folders and the S2 layer (decided 29 September 2026)

`deduplicate` writes `data/documents/B4-R#####/metadata.json` and `provenance.json`. The
evidence-packet idea (source-linked extraction of what artefact a paper defines, with page
evidence per claim) is the software-supported S2 worksheet and is built only for
documents that pass S1; it does not change the frozen protocol's order. Open-access PDFs
(location recorded from OpenAlex `best_oa_location`) may be downloaded by the pipeline;
paywalled copies are obtained by hand (`PDF_NEEDED`).

## 4B run record, OpenAlex (29–30 September 2026)

- Cutoff set to 2026-09-29. Bank run: 5 of 54 queries at or below 300 (Q04, Q18, Q27, BR01,
  BR04; 457 hits); 49 above, from 322 to 99,924.
- Refinement (deviation 4): 20 queries under 300 after step 1 (title restriction), 16 after
  step 2 (mechanism group), 2 after step 3 (subject areas), 11 needed the OR split; 87 runnable
  sub-queries, 7,727 hits.
- Second-level splits (deviation 5): 12 parts split again (levels 2–4); 46 more runnable parts,
  4,596 hits. Parts that cannot be split further and remain above 300 (REFINEMENT_EXHAUSTED,
  not retrieved; a decision for Tagir): Q16.r4.1.2 (3,215), Q24.r4.1.2 and .1.3 (680 each),
  Q24.r4.4.2 and .4.3 (903 each), Q42.r4.1.1.1 and .1.1.2 (540 each), Q48.r4.1.2 (1,624),
  Q48.r4.1.3 (1,387), Q48.r4.1.1.1 (411), XC01.r4.5.1 (577), XC01.r4.5.4 (535), and
  Q41.r4.4.3.4.1 (376). The only remaining pre-registered-style move would be splitting the
  title group as well; it is not implemented.
- Totals: 12,780 hits, 9,844 unique documents, 147 near-duplicate pairs
  (`exports/near_duplicates.csv`), 1 record after the cutoff, 246 non-English (flagged).
- DBLP: all 30 mandatory queries failed on 29 Sep: dblp.org and both mirrors serve a browser
  bot-check page to programs. To be run in a browser and imported (`--format dblp_json`).
- Scopus: adapter ready; entitlement probe over split-tunnel VPN failed (COMPLETE view 401);
  to be run from campus. Web of Science: browser-assisted export via a-z.lu, login pending.

## 4B run record, Scopus (30 September 2026, from the Uni.lu network)

- Entitlement confirmed from campus (deviation 6: API mode). Bank run: 10 of 54 queries at or
  below 300 (971 hits); 44 above, from 310 to 30,249 (about a third of the OpenAlex counts).
- Refinement, same rules in Scopus syntax (`TITLE(...)`, `SUBJAREA(COMP OR ENGI OR DECI OR SOCI
  OR BUSI OR ECON)`): 22 under 300 after step 1, 14 after step 2, 3 after step 3, 5 split;
  57 runnable sub-queries, 5,219 hits. Sub-IDs (`.r1`, `.r4.n`) name the step applied and carry
  one form per source, like the base queries; `refinements.yaml` keeps one entry per (sub-ID,
  source) with its own count.
- Parts above 300 after the first split, handled by the second-level split (deviation 5):
  Q24.r4.1 (373) and .r4.4 (526), Q41.r4.4 (375), Q42.r4.1 (451), Q48.r4.1 (1,369),
  XC01.r4.5 (712); see the search log for the outcome.
- Overlap after Scopus: 2,695 documents found by both OpenAlex and Scopus, 3,053 by Scopus only,
  7,149 by OpenAlex only (before the second-level split retrieval).
- 46 Scopus records carry a cover date after the cutoff (in-press items), flagged `after_cutoff`.

## DBLP (30 September 2026)

The JSON search API is behind a browser bot-check page for programs, and its syntax cannot
express the bank's short forms (quotes dropped, every word a prefix term, `|` joins only
adjacent single words): all 15 answers fetched by hand were empty (evidence kept under
`data/raw/manual_exports/dblp/`). Deviation 7: DBLP is retrieved through its official SPARQL
endpoint with the canonical Boolean evaluated over titles (substring semantics, lower-case),
ordered by year then record IRI, count first. Counts are small (titles only); no abstracts.

## Corpus after OpenAlex + Scopus + DBLP (30 September 2026, 14:30 UTC)

21,177 hits → 14,342 unique documents; 250 near-duplicate pairs for review; 61 hits (35
documents) after the cutoff, excluded from the S1 file; 441 non-English hits flagged.
Source sets: OpenAlex only 6,767; Scopus only 4,088; OpenAlex+Scopus 2,876; DBLP only 342;
all three 149; DBLP+OpenAlex 61; DBLP+Scopus 59. Still to come: Web of Science (all 54,
manual export), IEEE Xplore (19, API once the key is active), HeinOnline (12, manual).

## 4B run record, IEEE Xplore (1 October 2026, API mode, deviation 8)

- 19 mandatory queries. Bank run: 8 at or below 300 and retrieved (Q27, Q32, Q33, Q36, Q45,
  BR01, BR03, BR04; 633 hits); 11 above, from 319 to 11,604. Q27 was accepted with three
  wildcard words, so no decision was needed there.
- Refinement in IEEE syntax: step 1 (title restriction) and step 3 (subject areas) cannot be
  expressed in the API and are recorded as skipped; step 2 (mechanism group) and step 4 (OR
  split) apply. 39 sub-queries counted: 35 runnable (2,210 hits, not yet retrieved), Q35.r2,
  Q38.r2 and Q44.r2 above 300 and split, Q38.r4.6 (698) still above 300 and waiting for the
  second-level split (deviation 5).
- Call budget: the free key allows 200 calls per day; the adapter stops at 190 and records the
  day's calls in `data/logs/ieee_calls_<date>.json`. 180 calls were used on 1 October, so the
  retrieval of the 35 sub-queries (about 80 calls) runs on the next UTC day.

## 4B run record, Web of Science (1 October 2026, licensed interface via a-z.lu)

- Access through a-z.lu (uni.lu SSO) to the Core Collection advanced search; the pipeline
  logs the counts and derives the refinement strings (`tools/wos_plan.py`), the search is run
  and the export saved by hand in the interface. Tagir authorised tool-assisted use of the
  interface with him present after registering at the LLC on 1 October.
- Adaptations of the refinement steps to WoS syntax: step 1 becomes `TS=(...) AND TI=(free
  group)`; step 3 uses the WoS categories (`WC=`) Computer Science, Engineering, Operations
  Research & Management Science, Management, Business, Economics, Law, Social Sciences,
  Political Science, Public Administration, Information Science & Library Science.
- Bank run: 20 of 54 queries at or below 300; 34 above, from 329 to 15,558. Refinement: 17
  under 300 after step 1, 13 after step 2, 1 after step 3, the rest split; 22 split parts
  counted, 18 at or below 300 (3 of them empty), parts above 300 split again. Two parts stay
  above 300 with no OR group left (not exported, Tagir's decision): Q48.r4.1.2 (471) and
  Q48.r4.1.3 (490).
- Export plan (`data/raw/manual_exports/wos/wos_export_plan.jsonl`): 69 entries, 66 with
  records (8,255), of which Q01.r1 (87) and Q02.r1 (102) are imported; 64 exports (8,066
  records) remain. Format: tab-delimited Full Record, imported with `--format wos_tab`.

- Phase B (2 October 2026): all 66 exports with records imported (8,261 WoS hits), each file's
  record count checked against the interface count. Six counts had grown by one record since the
  count on 1 October and were exported at the new count: Q06 (267 to 268), Q19.r2 (180 to 181),
  Q27 (9 to 10), Q33 (299 to 300, still within the limit), Q43.r1 (229 to 230), Q42.r3 (274 to 275).
  The search log keeps both the count row of 1 October and the import row of 2 October.

## Corpus after OpenAlex + Scopus + DBLP + IEEE (bank) + Web of Science (2 October 2026)

30,071 hits, 18,578 unique documents. Largest source sets: OpenAlex only 6,520; WoS only 3,864;
Scopus only 2,497; OpenAlex+Scopus+WoS 1,734; Scopus+WoS 1,493; OpenAlex+Scopus 1,057. Still to
come: IEEE refinement sub-queries (35 runnable, about 2,200 hits), HeinOnline (12 queries).

## HeinOnline (2 October 2026, deviation 9)

Supplementary check, not a one-to-one run of the bank (Tagir's decision). Four merged searches in the
Law Journal Library, one per direction, topic terms in the title combined with representation terms in
the title or text: D03 89, D06 75, D07 62, D08 38 records (strings in
`data/raw/manual_exports/heinonline/heinonline_plan.jsonl`). HeinOnline has no bulk citation export
without a personal MyHein account, so the result lists were read from the interface pages (27 pages,
two seconds apart) and saved as one CSV by Tagir. 264 hits; 238 documents found only in HeinOnline.

## IEEE rate limit (2 October 2026)

The retrieval of the refinement sub-queries ran into HTTP 403 "Service Over Qps" after about 20 calls;
a one-second gap did not help and the day's call budget was spent on refused calls. 18 sub-queries
were retrieved (826 hits); the rest resume on the next day. The adapter now waits and retries twice
on this answer and then stops the whole run instead of failing every remaining query.

## Corpus after all sources except the remaining IEEE sub-queries (2 October 2026)

31,161 hits, 19,254 unique documents.

## Not implemented on purpose

- Browser-assisted export (brief section 8): not implemented until the licence permits it
  and the user asks.
- Any screening (S1–S3), snowball anchoring logic beyond the `--cited-by` retrieval, and the
  registers (B4-A, B4-F, B4-S, B4-X, P2, RQ4.3): outside the retrieval pipeline.
