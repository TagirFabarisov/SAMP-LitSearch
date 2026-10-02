# SAMP RQ4.2 Block 4: first batch of the search corpus (2 October 2026)

Briefing for checking and for planning S1 screening. Everything below comes from the pipeline in this
repository; the numbers are in `block4_pipeline/data/logs/batches/batch1_2026-10-02_manifest.json`.

## What batch 1 is

The search results of all sources run so far, deduplicated into unique documents. It is a fixed,
cite-able snapshot: its document IDs are listed in
`block4_pipeline/data/logs/batches/batch1_2026-10-02_document_ids.txt`. Document IDs (B4-R…) carry
over unchanged when later results are added, so a second batch is simply "the IDs not in batch 1"
and S1 work on batch 1 is never redone.

| | |
|---|---|
| Unique documents for S1 | 19,232 (22 more fall after the search cutoff of 29 Sep 2026 and are left out) |
| Documents without abstract | 1,398 (screened on title, flagged) |
| Documents found by several directions | 446 |
| Possible duplicate pairs left for a person to check | 318 |
| Search log entries / deviation entries | 1,230 / 9 |

## Sources

| Source | How | Documents | Found only there |
|---|---|---|---|
| OpenAlex | API, all 54 queries with refinement | 9,854 | 6,508 |
| Web of Science Core Collection | interface, all 54 queries counted, refined and exported (66 files) | 7,691 | 3,819 |
| Scopus | API from the university network, all 54 queries with refinement | 7,159 | 2,472 |
| IEEE Xplore | API; 19 mandatory queries, refinement partly retrieved | 1,128 | 757 |
| DBLP | official SPARQL endpoint, titles only (30 mandatory queries) | 611 | 266 |
| HeinOnline | 4 merged title searches for D03, D06, D07, D08 (supplementary) | 259 | 238 |

Overlap is moderate: about two thirds of the documents come from a single source, which is expected
for interdisciplinary directions spread over computing, engineering, management and law.

## Documents per direction (a document can belong to several)

| D01 | D02 | D03 | D04 | D05 | D06 | D07 | D08 | D09 |
|---|---|---|---|---|---|---|---|---|
| 846 | 875 | 591 | 556 | 849 | 1,072 | 1,469 | 1,588 | 311 |

| D10 | D11 | D12 | D13 | D14 | D15 | D16 | XC | BR |
|---|---|---|---|---|---|---|---|---|
| 953 | 787 | 1,008 | 988 | 1,137 | 1,063 | 1,938 | 2,715 | 974 |

Years: before 2000: 1,002; 2000–2009: 3,243; 2010–2019: 6,504; 2020 onwards: 8,399; unknown: 84.

## How the search departed from the plan (deviation log, 9 entries)

1. OpenAlex: bare truncated words had to be quoted (`"word*"`) because OpenAlex rejects them otherwise.
2. OpenAlex: ordering by the OpenAlex work ID under its sortable column name.
3. Note only: OpenAlex matches quoted phrases on unstemmed text, single words on stemmed text.
4. The four pre-registered refinement steps for counts above 300 (title restriction, mechanism group,
   subject areas, split along the OR group) are applied by the program, cumulatively, in the frozen order.
5. Parts still above 300 after the split are split again, up to three levels.
6. Scopus retrieved through its search API instead of interface exports.
7. DBLP retrieved through its official SPARQL endpoint (the search API blocks programs and cannot
   express the Boolean forms).
8. IEEE retrieved through its API; forms with more than two truncated words are sent as an exactly
   equivalent set of smaller requests.
9. HeinOnline treated as a supplementary check: four merged title searches instead of the 12 bank
   queries one by one; result lists read from the interface pages (no bulk export available).

The Web of Science adaptations of the refinement steps (title field, subject categories) are recorded
in DEVNOTES.md; six WoS counts grew by one record between counting (1 Oct) and export (2 Oct).

## Known gaps (the second batch)

- **IEEE:** 17 refinement sub-queries not yet retrieved (the IEEE server refused calls as too frequent
  on 2 Oct), plus one further split (B4-Q38.r4.6). Expected a few hundred new documents at most,
  given that most IEEE records are also in Scopus or WoS.
- **Parts above 300 that cannot be split further:** OpenAlex 13, Scopus 8, Web of Science 2. These
  are recorded, not retrieved. Decision pending: accept as gaps, split the title group as well, or
  refine by hand.
- **Snowballing** from included documents comes after S1/S2, as planned.

## Known quirks in the data (harmless for S1, to tidy before analysis)

- Language and document type are written differently by different sources ("en" and "English",
  "article" and "Article"); 5,198 records carry no language at all. Not used by the screener.
- 2,812 documents have an open-access PDF link (from OpenAlex), useful for S2.

## Files

- `block4_pipeline/data/exports/batches/batch1_2026-10-02/s1_input_batch1.csv` (and `.zip`, 11 MB):
  the screening input, with only what the screener may see: document ID, title, abstract, year,
  venue, type, and a no-abstract flag. Directions, queries and sources are deliberately left out to keep
  the screeners blind to the search design.
- `documents_for_s1_full.csv` in the same folder: everything per document (sources, directions,
  queries, IDs, open-access links), for the audit and for stratifying by direction.
- `near_duplicates.csv`: the 318 pairs to look at once.
- `docs/S1_screening_design.md`: the S1 design draft awaiting approval.

## What can start now

S1 screening of batch 1 can start as soon as the S1 design is approved (prompt text, choice of the
second screener, title-only records, blindness to direction). Batch 2 is screened the same way later
and merged by document ID.
