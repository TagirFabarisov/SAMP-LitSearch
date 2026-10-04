"""S0 quality filtering of batch 1 (decided by Tagir, 4 October 2026).

    python3 block4_pipeline/tools/s0_filter.py [--sjr data/reference/sjr_2024.csv]

Rules, applied in order; the first rule a record fails is its reason:
 1. not a scholarly record (dataset, software, slides, poster, erratum, front matter, book review,
    editorial, news, no title)
 2. every subject label is in the excluded life/physical/earth sciences list
 3. published 2023 or earlier and 0 citations
 4. published 2023 or earlier, not in a ranked venue, and 3 citations or fewer
Citations: OpenAlex cited_by_count; without an OpenAlex match the higher of Scopus and Web of Science;
with neither, rules 3 and 4 do not apply. Ranked venue: SJR Q1/Q2 by ISSN, or CORE A*/A/B; a
conference in a book series not matched to CORE uses the series' SJR quartile. Repositories (arXiv,
SSRN, ...) and theses are never ranked.

Reads only local files: normalized documents, raw source answers, the OpenAlex DOI lookup
(tools/s0_openalex_lookup.py), data/reference/core_2023.csv and the SJR file. Writes into
data/exports/batches/batch1_2026-10-02/: documents_s0.csv, s0_passed.csv, s0_summary.json.
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "exports" / "batches" / "batch1_2026-10-02"
BATCH_IDS = ROOT / "data" / "logs" / "batches" / "batch1_2026-10-02_document_ids.txt"

EXCLUDED_FIELDS = {
    "medicine", "nursing", "dentistry", "health professions", "veterinary",
    "pharmacology, toxicology and pharmaceutics", "biochemistry, genetics and molecular biology",
    "immunology and microbiology", "neuroscience", "chemistry", "chemical engineering",
    "physics and astronomy", "earth and planetary sciences", "environmental science",
    "agricultural and biological sciences",
}
# Web of Science categories that fall inside the excluded list (used only when neither OpenAlex nor
# SJR gives labels): matched on words in the category name
WOS_EXCLUDED_WORDS = re.compile(
    r"medic|nursing|dentist|oral surg|health|veterin|pharmac|toxicol|biochem|molecular biol|genetic|"
    r"immunol|microbiol|neurosci|neurolog|psychiatr|chemi|physics|astronom|geosci|geolog|geochem|"
    r"meteorol|oceanogr|environmental scien|ecolog|agricult|agronom|biolog|plant scien|zoolog|"
    r"oncolog|surgery|cardi|pediatr|clinical|nutrition|endocrin|infectious|virolog|pathol|radiolog|"
    r"ophthalm|obstetr|rehabilitation|sport scien|hematol|urolog|gastro|dermatol|respirat|"
    r"anesthes|forestry|fisheries|soil scien|water resources|marine|mineralog|spectroscop|optics|"
    r"crystallogr|electrochem|polymer|nuclear|thermodynamics|mycolog|entomolog|ornitholog", re.I)
WOS_KEEP_WORDS = re.compile(r"computer|engineering, (?!chemical)|information|management|business|"
                            r"econom|law|social|operations research|mathemat|statistic|psycholog|"
                            r"education|political|public administration|philosoph|logic|automation|"
                            r"robotics|telecommunication|multidisciplinary", re.I)

NON_SCHOLARLY_OA = {"dataset", "paratext", "editorial", "erratum", "peer-review", "supplementary-materials",
                    "retraction", "grant", "libguides"}
NON_SCHOLARLY_SCOPUS = {"ed": "editorial", "er": "erratum", "tb": "retracted"}
NON_SCHOLARLY_WOS = re.compile(r"editorial material|book review|correction|erratum|meeting abstract|"
                               r"news item|biographical|item about an individual|software review|"
                               r"database review|poster|retract|reprint|bibliography", re.I)
REPOSITORY_NAME = re.compile(r"arxiv|ssrn|research square|zenodo|figshare|repositor|preprints?\b|"
                             r"techrxiv|osf preprints|biorxiv|medrxiv|hal\b|e-?prints", re.I)


def norm_issn(s):
    s = re.sub(r"[^0-9Xx]", "", str(s or "")).upper()
    return s if len(s) == 8 else None


def norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    s = re.sub(r"\b\d+(st|nd|rd|th)\b", " ", s)
    s = re.sub(r"proceedings of (the )?|proc\.? (of )?(the )?|annual|international|conference on|"
               r"conference|symposium on|workshop on|ieee|acm|ifip|\bthe\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


# ----------------------------------------------------------------------------- reference lists

def load_core():
    by_title, by_acr = {}, {}
    with open(ROOT / "data" / "reference" / "core_2023.csv", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 5:
                continue
            title, acr, rank = row[1].strip(), row[2].strip(), row[4].strip()
            by_title.setdefault(norm_name(title), rank)
            if acr:
                by_acr.setdefault(acr.upper(), rank)
    return by_title, by_acr


def load_sjr(path):
    if not path or not Path(path).exists():
        return None
    q, areas = {}, {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            quart = (row.get("SJR Best Quartile") or "").strip()
            ar = [a.strip() for a in (row.get("Areas") or "").split(";") if a.strip()]
            for i in (row.get("Issn") or "").split(","):
                i = norm_issn(i)
                if i:
                    if quart and (i not in q or quart < q[i]):
                        q[i] = quart
                    areas.setdefault(i, ar)
    return q, areas


# ----------------------------------------------------------------------------- source indices

def oa_index():
    idx, by_doi = {}, {}
    for p in glob.glob(str(RAW / "openalex" / "*" / "*" / "page_*.json")):
        for w in json.load(open(p)).get("results", []):
            idx[w["id"].rsplit("/", 1)[-1]] = w
    for p in glob.glob(str(RAW / "openalex_s0_lookup" / "*" / "batch_*.json")):
        for w in json.load(open(p))["response"].get("results", []):
            if w.get("doi"):
                by_doi[w["doi"].lower().replace("https://doi.org/", "")] = w
    return idx, by_doi


def scopus_index():
    idx = {}
    for p in glob.glob(str(RAW / "scopus" / "*" / "*" / "page_*.json")):
        for e in json.load(open(p)).get("search-results", {}).get("entry", []):
            if e.get("eid"):
                idx[e["eid"]] = e
    return idx


def wos_index():
    idx = {}
    for p in glob.glob(str(RAW / "wos" / "*" / "*" / "parsed.json")):
        for r in json.load(open(p)):
            idx[r.get("UT")] = r
    return idx


def ieee_index():
    idx = {}
    for p in glob.glob(str(RAW / "ieee" / "*" / "*" / "page_*.json")):
        for a in json.load(open(p)).get("articles", []):
            idx[str(a.get("article_number"))] = a
    return idx


def dblp_index():
    idx = {}
    for p in glob.glob(str(RAW / "dblp" / "*" / "*" / "page_*.json")):
        for b in json.load(open(p)).get("results", {}).get("bindings", []):
            key = b["p"]["value"].replace("https://dblp.org/rec/", "")
            idx[key] = {k: v.get("value") for k, v in b.items()}
    return idx


# ----------------------------------------------------------------------------- per document

def oa_issns(w):
    out = []
    for loc in [w.get("primary_location")] + (w.get("locations") or []):
        src = (loc or {}).get("source") or {}
        out += [src.get("issn_l")] + (src.get("issn") or [])
    return [i for i in map(norm_issn, out) if i]


def main():
    sjr_path = sys.argv[sys.argv.index("--sjr") + 1] if "--sjr" in sys.argv else str(ROOT / "data" / "reference" / "sjr_2024.csv")
    sjr = load_sjr(sjr_path)
    core_title, core_acr = load_core()
    oa, oa_doi = oa_index()
    sc, wo, ie, db = scopus_index(), wos_index(), ieee_index(), dblp_index()
    batch = set(open(BATCH_IDS).read().split())
    docs = [json.loads(l) for l in open(ROOT / "data" / "normalized" / "documents.jsonl")]
    docs = [d for d in docs if d["document_id"] in batch]

    rows, reasons = [], Counter()
    core_matched = core_tried = 0
    tight_pass = Counter()
    for d in docs:
        ids = d.get("source_ids") or {}
        w = next((oa[i] for i in ids.get("openalex", []) if i in oa), None)
        if w is None and d.get("doi"):
            w = oa_doi.get(d["doi"].lower())
        s = next((sc[i] for i in ids.get("scopus", []) if i in sc), None)
        r = next((wo[i] for i in ids.get("wos", []) if i in wo), None)
        e = next((ie[str(i)] for i in ids.get("ieee", []) if str(i) in ie), None)
        b = next((db[i] for i in ids.get("dblp", []) if i in db), None)

        # type
        oa_type = (w or {}).get("type")
        s_sub = (s or {}).get("subtype")
        w_dt = (r or {}).get("DT") or ""
        e_ct = (e or {}).get("content_type") or ""
        b_t = ((b or {}).get("type") or "").rsplit("#", 1)[-1]
        if w is not None:
            type_label = oa_type
        elif s is not None:
            type_label = (s.get("subtypeDescription") or s_sub)
        elif r is not None:
            type_label = w_dt
        elif e is not None:
            type_label = e_ct
        elif b is not None:
            type_label = b_t
        else:
            type_label = d.get("type")

        # venue names and ISSNs
        venue = d.get("venue") or ""
        names = [venue]
        issns = []
        src_type = None
        if w:
            src = (w.get("primary_location") or {}).get("source") or {}
            names += [src.get("display_name"), (w.get("primary_location") or {}).get("raw_source_name")]
            src_type = src.get("type")
            issns += oa_issns(w)
        if s:
            names.append(s.get("prism:publicationName"))
            issns += [norm_issn(s.get("prism:issn")), norm_issn(s.get("prism:eIssn"))]
        if r:
            names += [r.get("CT"), r.get("SO"), r.get("SE")]
            issns += [norm_issn(r.get("SN")), norm_issn(r.get("EI"))]
        if e:
            names.append(e.get("publication_title"))
            issns.append(norm_issn(e.get("issn")))
        if b:
            names.append(b.get("venue"))
        names = [n for n in names if n]
        issns = sorted({i for i in issns if i})

        # subject labels
        labels = sorted({t["field"]["display_name"] for t in (w or {}).get("topics") or [] if t.get("field")})
        label_src = "openalex" if labels else ""
        if not labels and sjr:
            ar = sorted({a for i in issns for a in sjr[1].get(i, [])})
            if ar:
                labels, label_src = ar, "sjr"
        if not labels and r and r.get("WC"):
            labels, label_src = [c.strip() for c in r["WC"].split(";") if c.strip()], "wos"

        def excluded(lab):
            if label_src == "wos":
                return bool(WOS_EXCLUDED_WORDS.search(lab)) and not WOS_KEEP_WORDS.search(lab)
            return lab.lower() in EXCLUDED_FIELDS or lab.lower().startswith("veterinary")

        # citations
        if w is not None:
            cites, cite_src = int(w.get("cited_by_count") or 0), "openalex"
        else:
            vals = [int(x) for x in [(s or {}).get("citedby-count"), (r or {}).get("TC")] if str(x or "").strip().isdigit()]
            cites, cite_src = (max(vals), "scopus/wos") if vals else (None, "")

        # ranked venue
        is_conf = bool(re.search(r"proceeding|conference", " ".join([str(type_label or ""), str(src_type or ""),
                       (s or {}).get("prism:aggregationType") or "", w_dt, e_ct, b_t]), re.I)) or (r or {}).get("PT") == "C"
        repository = (src_type == "repository") or bool(REPOSITORY_NAME.search(" ".join(names))) or \
            re.search(r"thesis|dissertation", str(type_label or "") + b_t, re.I)
        core_rank = None
        if is_conf:
            core_tried += 1
            for n in names:
                nn = norm_name(n)
                if nn in core_title:
                    core_rank = core_title[nn]
                    break
            if core_rank is None:
                for n in names:
                    for tok in re.findall(r"\b[A-Z][A-Za-z\-/&]{2,}\b", n):
                        if tok.upper() in core_acr and (tok.isupper() or n.strip() == tok):
                            core_rank = core_acr[tok.upper()]
                            break
                    if core_rank:
                        break
            if core_rank not in ("A*", "A", "B", "C"):
                core_rank = None  # TBR, National, Journal Published, Unranked: treat as not matched
            if core_rank is not None:
                core_matched += 1
        sjr_q = None
        if sjr:
            qs = [sjr[0][i] for i in issns if i in sjr[0]]
            sjr_q = min(qs) if qs else None
        if repository:
            ranked, ranked_by = False, "repository or thesis"
        elif core_rank is not None:
            ranked, ranked_by = core_rank in ("A*", "A", "B"), "CORE " + core_rank
        elif sjr is None:
            ranked, ranked_by = None, "SJR not loaded"
        else:
            ranked, ranked_by = sjr_q in ("Q1", "Q2"), ("SJR " + sjr_q) if sjr_q else "no SJR/CORE match"
        tight = (not repository) and ((core_rank in ("A*", "A")) if core_rank is not None else (sjr_q == "Q1"))

        year = d.get("year")
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None
        old = year is not None and year <= 2023

        # rules
        title = (d.get("title") or "").strip()
        reason = ""
        if not title or (w and w.get("is_paratext")) or (oa_type in NON_SCHOLARLY_OA) or \
                (w is None and s_sub in NON_SCHOLARLY_SCOPUS) or (w is None and NON_SCHOLARLY_WOS.search(w_dt)) or \
                re.search(r"\b(courses|book review)\b", e_ct, re.I) or re.search(r"\[reviews\]|book review", title, re.I):
            reason = "1 not a scholarly record (%s)" % (type_label or "no title")
        elif labels and all(excluded(x) for x in labels):
            reason = "2 subject outside scope (%s)" % "; ".join(labels)
        elif old and cites == 0:
            reason = "3 published 2023 or earlier, 0 citations"
        elif old and cites is not None and cites <= 3 and ranked is False:
            reason = "4 published 2023 or earlier, unranked venue, %d citations" % cites
        elif old and cites is not None and cites <= 3 and ranked is None:
            reason = "pending: SJR needed for rule 4"
        passed = reason == ""
        reasons[reason.split(" (")[0].split(",")[0] if reason else "passed"] += 1
        # tightened rule 4 (reported only): ranked = SJR Q1 or CORE A*/A, and 5 citations or fewer
        if passed or reason.startswith("4") or reason.startswith("pending"):
            if not (old and cites is not None and cites <= 5 and not tight):
                tight_pass["passes tightened rule 4"] += 1
        rows.append({
            "document_id": d["document_id"], "s0_pass": "yes" if passed else ("pending" if reason.startswith("pending") else "no"),
            "s0_reason": reason, "title": title, "year": year or "", "venue": venue, "type": type_label or "",
            "citations": "" if cites is None else cites, "citation_source": cite_src,
            "subject_labels": "; ".join(labels), "subject_label_source": label_src,
            "ranked_venue": ranked_by, "issns": " ".join(issns), "doi": d.get("doi") or "",
            "sources": "; ".join(sorted(ids.keys())),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "documents_s0.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    keep = ["document_id", "title", "year", "venue", "type", "citations", "subject_labels", "doi"]
    passed_rows = sorted([x for x in rows if x["s0_pass"] == "yes"], key=lambda x: x["title"].lower())
    with open(OUT / "s0_passed.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=keep, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(passed_rows)
    summary = {"total": len(rows), "by_outcome": dict(reasons), "passed": len(passed_rows),
               "sjr_loaded": sjr is not None, "conference_records": core_tried, "matched_to_core": core_matched,
               "tightened_rule4_would_pass": tight_pass["passes tightened rule 4"]}
    (OUT / "s0_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
