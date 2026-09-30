"""`deduplicate`: unique documents (B4-R) from normalized hit records.

Order (protocol section 9): (1) DOI, (2) OpenAlex ID or other source ID, (3) normalized
title plus year. Near-duplicates (Levenshtein ratio above the protocol threshold, year
within tolerance) are written to exports/near_duplicates.csv for a person to check;
they are never merged automatically.

Document IDs are stable across reruns: an existing documents.jsonl is read first and its
IDs are kept for documents that match; only new documents get new IDs. Hits are never
deleted; the hit -> document mapping is rewritten each run.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .. import config_loader as cl
from .. import paths, storage

_direction_of: Dict[str, str] = {}

STOP_WORDS = {"a", "an", "the", "of", "for", "and", "or", "in", "on", "to", "with", "by", "at",
              "from", "into", "as", "is", "are", "via", "toward", "towards", "using", "based"}


def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKD", str(title))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    words = [w for w in t.split() if w not in STOP_WORDS]
    return " ".join(words)


def normalized_key(title: Optional[str], year: Any) -> str:
    return "%s|%s" % (normalize_title(title), year if year else "")


def levenshtein_ratio(a: str, b: str) -> float:
    """1 - distance / max length; 1.0 for identical strings."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def _source_id_keys(rec: Dict[str, Any]) -> List[str]:
    keys = []
    if rec.get("openalex_id"):
        keys.append("openalex:%s" % rec["openalex_id"])
    sid = rec.get("source_record_id")
    if sid and not str(sid).startswith("row-"):
        keys.append("%s:%s" % (rec.get("source"), sid))
    return keys


def write_document_folders(docs: Dict[str, Dict[str, Any]], mapping: List[Dict[str, Any]],
                           records: List[Dict[str, Any]]) -> int:
    """One folder per document with metadata.json (the document record) and provenance.json
    (every hit that led to it: query, source, exact string, rank, run, raw file, matching rule).
    Only these two files are written; anything else in the folder (source.pdf, parsed text,
    evidence packet, added after S1) is left alone."""
    by_hit = {r["hit_id"]: r for r in records}
    matched = {m["hit_id"]: m["matched_by"] for m in mapping}
    n = 0
    for doc_id in sorted(docs):
        d = docs[doc_id]
        folder = paths.document_dir(doc_id)
        folder.mkdir(parents=True, exist_ok=True)
        metadata = {k: v for k, v in d.items() if k not in ("hit_ids", "source_id_keys")}
        provenance = {
            "document_id": doc_id,
            "written_at": storage.utc_now(),
            "hits": [{
                "hit_id": h, "query_id": by_hit[h]["query_id"], "source": by_hit[h]["source"],
                "exact_query": by_hit[h]["exact_query"], "rank": by_hit[h]["rank"], "page": by_hit[h]["page"],
                "retrieved_at": by_hit[h]["retrieved_at"], "run_id": by_hit[h]["run_id"],
                "source_record_id": by_hit[h].get("source_record_id"), "matched_by": matched.get(h),
                "after_cutoff": by_hit[h].get("after_cutoff"),
            } for h in d.get("hit_ids", []) if h in by_hit],
        }
        storage.write_json(folder / "metadata.json", metadata)
        storage.write_json(folder / "provenance.json", provenance)
        n += 1
    return n


def deduplicate() -> Dict[str, Any]:
    protocol = cl.load_protocol()
    order = protocol.get("dedup_order", ["doi", "source_ids", "normalized_title_year"])
    ratio_threshold = float(protocol.get("near_duplicate_ratio", 0.92))
    year_tol = int(protocol.get("near_duplicate_year_tolerance", 1))
    doc_fmt = protocol["id_formats"]["document"]

    records = sorted(storage.read_jsonl(paths.records_file()), key=lambda r: r["hit_id"])
    global _direction_of
    _direction_of = {q["id"]: cl.direction_group(q) for q in cl.load_queries()}
    existing_docs = {d["document_id"]: d for d in storage.read_jsonl(paths.documents_file())}
    alloc = storage.IdAllocator(doc_fmt, existing_docs.keys())

    by_doi: Dict[str, str] = {}
    by_source_id: Dict[str, str] = {}
    by_key: Dict[str, str] = {}
    docs: Dict[str, Dict[str, Any]] = {}

    def index(doc: Dict[str, Any]) -> None:
        if doc.get("doi"):
            by_doi.setdefault(doc["doi"], doc["document_id"])
        for k in doc.get("source_id_keys", []):
            by_source_id.setdefault(k, doc["document_id"])
        if doc.get("normalized_key") and not doc["normalized_key"].startswith("|"):
            by_key.setdefault(doc["normalized_key"], doc["document_id"])

    for d in existing_docs.values():
        d = dict(d)
        d["hit_ids"] = []
        docs[d["document_id"]] = d
        index(d)

    def find(rec: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        for rule in order:
            if rule == "doi" and rec.get("doi") and rec["doi"] in by_doi:
                return by_doi[rec["doi"]], "doi"
            if rule == "source_ids":
                for k in _source_id_keys(rec):
                    if k in by_source_id:
                        return by_source_id[k], "source_ids"
            if rule == "normalized_title_year":
                k = normalized_key(rec.get("title"), rec.get("year"))
                if not k.startswith("|") and k in by_key:
                    return by_key[k], "normalized_title_year"
        return None, None

    mapping: List[Dict[str, Any]] = []
    stats_new = defaultdict(int)
    stats_merged = defaultdict(int)
    for rec in records:
        doc_id, rule = find(rec)
        if doc_id is None:
            doc_id = alloc.next()
            docs[doc_id] = {
                "document_id": doc_id, "doi": rec.get("doi"), "openalex_id": rec.get("openalex_id"),
                "source_ids": {}, "source_id_keys": [], "normalized_key": normalized_key(rec.get("title"), rec.get("year")),
                "title": rec.get("title"), "authors": rec.get("authors") or [], "year": rec.get("year"),
                "publication_date": rec.get("publication_date"), "venue": rec.get("venue"), "type": rec.get("type"),
                "abstract": rec.get("abstract"), "language": rec.get("language"), "url": rec.get("url"),
                "first_seen_run_id": rec.get("run_id"), "first_hit_id": rec["hit_id"], "hit_ids": [],
                "after_cutoff": bool(rec.get("after_cutoff")), "sources": [], "query_ids": [], "directions": [],
            }
            rule = "new"
            stats_new[(rec["query_id"], rec["source"])] += 1
        else:
            stats_merged[(rec["query_id"], rec["source"])] += 1
        doc = docs[doc_id]
        # enrich the document with anything the new record adds (never overwrite present values)
        for f in ("doi", "openalex_id", "abstract", "publication_date", "venue", "type", "language", "url", "title", "year",
                  "is_oa", "oa_pdf_url", "oa_landing_url"):
            if not doc.get(f) and rec.get(f):
                doc[f] = rec[f]
        if not doc.get("authors") and rec.get("authors"):
            doc["authors"] = rec["authors"]
        if rec.get("source_record_id"):
            ids = doc.setdefault("source_ids", {}).setdefault(rec["source"], [])
            if isinstance(ids, str):  # older single-value form
                ids = doc["source_ids"][rec["source"]] = [ids]
            if rec["source_record_id"] not in ids:
                ids.append(rec["source_record_id"])
        base_qid = str(rec.get("query_id", "")).split(".")[0]
        if base_qid and base_qid not in doc.setdefault("query_ids", []):
            doc["query_ids"].append(base_qid)
        direction = _direction_of.get(base_qid)
        if direction and direction not in doc.setdefault("directions", []):
            doc["directions"].append(direction)
        doc["source_id_keys"] = sorted(set(doc.get("source_id_keys", [])) | set(_source_id_keys(rec)))
        if rec["source"] not in doc.setdefault("sources", []):
            doc["sources"].append(rec["source"])
        doc["after_cutoff"] = bool(doc.get("after_cutoff")) and bool(rec.get("after_cutoff"))
        doc["hit_ids"].append(rec["hit_id"])
        if not doc.get("normalized_key") or doc["normalized_key"].startswith("|"):
            doc["normalized_key"] = normalized_key(doc.get("title"), doc.get("year"))
        index(doc)
        mapping.append({"hit_id": rec["hit_id"], "document_id": doc_id, "query_id": rec["query_id"],
                        "source": rec["source"], "matched_by": rule})

    # near-duplicates for human review (documents only, blocked by year)
    near: List[Dict[str, Any]] = []
    by_year: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for d in docs.values():
        y = d.get("year")
        by_year[int(y) if y else 0].append(d)
    seen_pairs = set()
    for y, group in by_year.items():
        candidates = list(group)
        for dy in range(1, year_tol + 1):
            candidates += by_year.get(y + dy, [])
        for i, a in enumerate(group):
            ta = normalize_title(a.get("title"))
            if not ta:
                continue
            wa = set(ta.split())
            for b in candidates:
                if b is a or (a["document_id"], b["document_id"]) in seen_pairs or (b["document_id"], a["document_id"]) in seen_pairs:
                    continue
                tb = normalize_title(b.get("title"))
                if not tb or abs(len(ta) - len(tb)) > max(len(ta), len(tb)) * (1 - ratio_threshold):
                    continue
                # cheap prefilter: a pair above the ratio threshold shares most of its words
                wb = set(tb.split())
                if len(wa & wb) < 0.6 * max(len(wa), len(wb)):
                    continue
                r = levenshtein_ratio(ta, tb)
                if r > ratio_threshold:
                    seen_pairs.add((a["document_id"], b["document_id"]))
                    near.append({"document_a": a["document_id"], "document_b": b["document_id"], "ratio": round(r, 4),
                                 "title_a": a.get("title"), "title_b": b.get("title"), "year_a": a.get("year"),
                                 "year_b": b.get("year"), "doi_a": a.get("doi"), "doi_b": b.get("doi")})

    storage.rewrite_jsonl(paths.documents_file(), (docs[k] for k in sorted(docs)))
    storage.rewrite_jsonl(paths.hit_document_map_file(), mapping)
    write_document_folders(docs, mapping, records)
    paths.exports_dir().mkdir(parents=True, exist_ok=True)
    with open(paths.exports_dir() / "near_duplicates.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["document_a", "document_b", "ratio", "year_a", "year_b", "title_a", "title_b", "doi_a", "doi_b"])
        w.writeheader()
        for row in sorted(near, key=lambda r: -r["ratio"]):
            w.writerow(row)

    # "documents new after dedup" per (query, source): a document is credited to the hit that
    # first produced it, so the numbers do not change when deduplicate is run again.
    hit_origin = {r["hit_id"]: (r["query_id"], r["source"]) for r in records}
    credited = defaultdict(int)
    total_hits = defaultdict(int)
    for d in docs.values():
        origin = hit_origin.get(d.get("first_hit_id"))
        if origin:
            credited[origin] += 1
    for r in records:
        total_hits[(r["query_id"], r["source"])] += 1
    per_query_source = {}
    for key in total_hits:
        per_query_source["%s|%s" % key] = {"hits": total_hits[key], "new_documents": credited.get(key, 0),
                                           "merged_into_existing": total_hits[key] - credited.get(key, 0)}
    stats = {"records": len(records), "documents": len(docs), "near_duplicate_pairs": len(near),
             "per_query_source": per_query_source, "computed_at": storage.utc_now()}
    storage.write_json(paths.logs_dir() / "dedup_stats.json", stats)
    return stats
