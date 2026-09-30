# S1 screening: design for approval (draft 1, 30 September 2026)

Status: **draft, not run**. Nothing below has been sent to any model. Tagir approves the
prompt and the model choice; then the prompt version and model identifiers are recorded in
the search log before screening starts (protocol section 14), and cannot change without a
deviation-log entry.

## 1. What S1 is (protocol sections 12–14)

Title-and-abstract screening of every unique document (`B4-R`) by two independent screeners
from two different language-model families, each blind to the other and to all Block-3
material. Recall-oriented: a document proceeds if **either** screener says proceed.
Disagreements are recorded with both rationales. "Unsure" from either screener → human
adjudication. Documents excluded by both are audited by a person on a random 10 % sample,
stratified by direction; if more than 5 % of a stratum were wrongly excluded, that stratum is
rescreened by a third screener.

Inclusion at S1 (section 12): credible evidence that the document **defines a concrete
modelling artefact** (modelling language, formalism or logic, metamodel, ontology,
specification language, executable institutional or organisational framework, process /
state / graph modelling method, architecture or enterprise modelling language) that
**represents actors, arrangements, relations, norms, commitments, authority, membership,
change, dependencies** or another Block-4 direction, with identifiable constructs or
semantics, and could plausibly contribute to Problem 1. Not required: completeness, tooling,
maturity, popularity, breadth.

Exclusion and routing codes (section 13):

| Code | Meaning |
|---|---|
| E1 | survey or review only → search-aid ledger (B4-S) |
| E2 | descriptive theory or empirical framework only, no representation |
| E3 | management practice without explicit representation |
| E4 | tool without identifiable underlying model (attach as evidence if it implements a known artefact) |
| E5 | duplicate publication or same-artefact evidence (link) |
| E6 | no actor-side arrangement content |
| E7 | purely technical architecture artefact → RQ4.3 register |
| E8 | purely Problem-2 decision or coordination artefact → P2 register |
| E9 | insufficient information to verify (hold; one attempt to obtain the primary source) |
| E10 | outside scope for another stated reason |

A document may carry a routing code (E1, E7, E8) and still proceed in Problem 1.

## 2. Input

`data/exports/documents_for_s1.csv` after all mandatory sources are in: one row per unique
document with `document_id`, `title`, `abstract`, `year`, `venue`, `type`, `language`,
`directions` (the directions whose queries found it). Records without abstract are still
screened on title alone and flagged `no_abstract` so the auditor can weigh them.

The screener sees **only** title, abstract, year, venue and type. It does not see the
directions, the query, the source, Block-3 material, or the other screener's answer.

## 3. Prompt (version s1-p1, to be frozen on approval)

System message:

> You are screening bibliographic records for a systematic search on how actor-side
> arrangements in large engineering programmes are represented. Decide from the title and
> abstract only. Do not use knowledge about the authors, the venue's reputation, or what the
> paper is known for elsewhere; judge what the record itself states. Be recall-oriented: when
> the record could plausibly define a modelling artefact of the kind described, say PROCEED.
> Answer with the JSON object described, nothing else.

User message (per document; the criteria text is the protocol's, verbatim):

> **Task.** A document PROCEEDS if there is credible evidence that it defines a concrete
> modelling artefact — a modelling language, formalism or logic, metamodel, ontology,
> specification language, executable institutional or organisational framework, process /
> state / graph modelling method, or an architecture or enterprise modelling language — that
> represents actors, arrangements (agreements, contracts, licences, permissions, authorisations,
> memberships), relations between actors, norms and rules, commitments, obligations, authority
> and power, membership and participation, change (amendment, substitution, withdrawal,
> termination, staged commitment, configuration control), dependencies between arrangements or
> between arrangements and a technical system, or how rules governing such change are
> represented; and that has identifiable constructs or semantics. A theory, tool, standard or
> management framework proceeds only if it defines an identifiable representation with
> constructs, relations or semantics that can be compared. Completeness, tooling, maturity,
> popularity and breadth are not required.
>
> **If it does not proceed, give one exclusion code:** E1 survey or review only; E2 descriptive
> theory or empirical framework only; E3 management practice without explicit representation;
> E4 tool without identifiable underlying model; E5 duplicate publication; E6 no actor-side
> arrangement content; E7 purely technical architecture artefact; E8 purely a decision-making or
> coordination artefact (how participants make, negotiate or coordinate decisions), not an
> actor-side arrangement; E9 insufficient information to decide; E10 outside scope for another
> reason. **A proceeding document may additionally carry a routing note** R-SURVEY (it is also a
> review useful for finding artefacts), R-TECH (it also represents technical architecture), or
> R-P2 (it also represents collaborative decision-making).
>
> **Record**
> Title: …
> Abstract: … (or "[no abstract available]")
> Year: … Venue: … Type: …
>
> **Answer** as JSON: `{"decision": "PROCEED" | "EXCLUDE" | "UNSURE", "code": "E1".."E10" or null,
> "routing": ["R-SURVEY" | "R-TECH" | "R-P2"], "artefact_named": "<name the record gives its
> artefact, or null>", "rationale": "<one or two sentences quoting or paraphrasing the record>"}`

Design notes:
- The criteria are the protocol's own words, lightly re-flowed; the direction list is
  paraphrased from section 1. No candidate names, no Block-3 vocabulary.
- `artefact_named` is asked for because S2 starts from it; it costs nothing at S1.
- `UNSURE` is explicit so that the model is not forced into a decision.
- E9 is reserved for records that truly lack information (no abstract, or an abstract that does
  not say what the paper does).

## 4. Screeners

Two families, one model each, fixed for the whole run:

| Screener | Family | Model identifier | Role |
|---|---|---|---|
| A | Anthropic | to confirm (Claude Sonnet 5.5, `claude-sonnet-5-5`) | independent screener |
| B | OpenAI or Google | to confirm by Tagir | independent screener |
| C | third family or a stronger model of A's family | used only for rescreening a failed stratum |

Temperature 0 where the API allows it; no tools; no retrieval; one document per request
(no cross-document context). Every request and answer is saved raw; the prompt text is
stored once with a content hash, and each answer row carries model id, prompt version,
request time and the hash.

## 5. Decision logic and outputs

Per document: `decision_A`, `code_A`, `routing_A`, `rationale_A`, same for B, then
`final_S1`:

- PROCEED if A or B says PROCEED;
- HOLD (human adjudication) if either says UNSURE and neither says PROCEED;
- EXCLUDE if both say EXCLUDE (codes may differ; both kept).

Routing notes are merged (union). E1/E7/E8 documents go to their registers whether or not
they proceed.

Outputs (derived tables, rewritten per run; raw answers append-only):
- `data/screening/s1/answers.jsonl` — one row per (document, screener) with the raw JSON;
- `data/screening/s1/decisions.jsonl` and `exports/s1_decisions.csv` — the merged decision;
- `exports/s1_disagreements.csv` — documents where A and B differ, with both rationales;
- `exports/s1_hold_for_adjudication.csv` — the UNSURE cases;
- `exports/s1_audit_sample.csv` — the 10 % sample of double-excludes, stratified by direction
  (a document found by several directions is sampled under its first direction), with empty
  columns `auditor_decision`, `auditor_note` for Tagir;
- `exports/s1_proceed.csv` — the S2 input.

Audit rule: after Tagir fills the sample, `s1 audit-report` computes the wrong-exclusion rate
per stratum; strata above 5 % are listed for rescreening by screener C, whose answers replace
nothing — they are added as a third column and the final decision becomes "any of A, B, C
says PROCEED".

## 6. Cost and time (order of magnitude)

Per document about 700 input tokens and 120 output tokens per screener. For 15,000 documents
and two screeners: roughly 21 M input and 3.6 M output tokens. At current list prices for a
mid-size model this is in the tens of euros per screener; a top model would be a few hundred.
Throughput with modest concurrency: a few hours per screener.

## 7. What Tagir decides

1. Approve or edit the prompt text (section 3).
2. Choose screener B's family and model; confirm screener A's model.
3. Whether records without abstract are screened on title alone (default: yes, flagged) or
   held as E9 directly.
4. Whether the direction is shown to the screener (default: no, to keep it blind to the search
   design; the audit is stratified by direction afterwards).
