"""`status`: progress and audit report per source and per query; prints a table and writes
data/logs/status.json."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

from .. import config_loader as cl
from .. import paths, storage
from ..adapters.base import DONE, FAILED, MANUAL_EXPORT_REQUIRED, REFINEMENT_REQUIRED
from . import provenance


def build_status() -> Dict[str, Any]:
    protocol = cl.load_protocol()
    sources = cl.load_sources()
    queries = cl.load_queries()
    latest = provenance.latest_by_query_source()
    dedup = {}
    p = paths.logs_dir() / "dedup_stats.json"
    if p.exists():
        dedup = json.loads(p.read_text(encoding="utf-8")).get("per_query_source", {})
    order = sources.get("execution_order") or list(sources["sources"].keys())

    rows: List[Dict[str, Any]] = []
    for q in queries:
        for s in order:
            scfg = sources["sources"][s]
            mandatory = cl.is_mandatory(scfg, q)
            supplementary = cl.is_supplementary(scfg, q)
            if not mandatory and not supplementary:
                continue
            entry = latest.get((q["id"], s))
            if entry:
                st = entry.get("status")
            elif mandatory and scfg.get("access_mode") != "api":
                st = MANUAL_EXPORT_REQUIRED
            elif mandatory:
                st = "not run"
            else:
                st = "supplementary (on demand)"
            dd = dedup.get("%s|%s" % (q["id"], s), {})
            rows.append({
                "query_id": q["id"], "direction": q.get("direction"), "lens": q.get("lens"), "source": s,
                "mandatory": mandatory, "status": st,
                "count": entry.get("original_count") if entry else None,
                "hits": entry.get("hits_created") if entry else None,
                "new_documents": dd.get("new_documents"),
                "last_run": entry.get("datetime_utc") if entry else None,
                "note": (entry.get("note") or "")[:120] if entry else "",
            })

    by_status = Counter(r["status"] for r in rows if r["mandatory"])
    failures = [r for r in rows if r["status"] == FAILED]
    pending_manual = [r for r in rows if r["mandatory"] and r["status"] == MANUAL_EXPORT_REQUIRED]
    refine = [r for r in rows if r["status"] == REFINEMENT_REQUIRED]
    missing_access = [s for s, c in sources["sources"].items() if c.get("access_status") == "ACCESS_TO_CONFIRM"]
    docs_file = paths.documents_file()
    n_docs = sum(1 for _ in storage.read_jsonl(docs_file)) if docs_file.exists() else 0
    return {
        "generated_at": storage.utc_now(),
        "protocol_revision": protocol.get("protocol_revision"), "frozen": protocol.get("frozen"),
        "upper_cutoff_date": protocol.get("upper_cutoff_date"),
        "openalex_construct_check_resolved": protocol.get("openalex_construct_check_resolved"),
        "mandatory_pairs_by_status": dict(by_status),
        "total_hits": sum(1 for _ in provenance.hits()), "total_documents": n_docs,
        "refinement_required": [(r["query_id"], r["source"], r["count"]) for r in refine],
        "pending_manual_imports": len(pending_manual),
        "failures": [(r["query_id"], r["source"], r["last_run"], r["note"]) for r in failures],
        "access_to_confirm": missing_access,
        "deviations_recorded": len(provenance.deviations()),
        "rows": rows,
    }


def format_table(status: Dict[str, Any], only_mandatory: bool = True) -> str:
    rows = [r for r in status["rows"] if r["mandatory"] or not only_mandatory]
    cols = [("query_id", 10), ("lens", 12), ("source", 10), ("status", 24), ("count", 7), ("hits", 6), ("new_documents", 8), ("last_run", 20)]
    lines = [" ".join(name.ljust(w)[:w] for name, w in cols)]
    lines.append(" ".join("-" * w for _, w in cols))
    for r in rows:
        lines.append(" ".join(str(r.get(name) if r.get(name) is not None else "").ljust(w)[:w] for name, w in cols))
    lines.append("")
    lines.append("mandatory (query, source) pairs by status: %s" % status["mandatory_pairs_by_status"])
    lines.append("hits: %d   documents: %d   deviations recorded: %d" % (status["total_hits"], status["total_documents"], status["deviations_recorded"]))
    if status["refinement_required"]:
        lines.append("REFINEMENT_REQUIRED: %s" % status["refinement_required"])
    if status["failures"]:
        lines.append("failures: %s" % status["failures"])
    if status["access_to_confirm"]:
        lines.append("access to confirm: %s" % ", ".join(status["access_to_confirm"]))
    lines.append("upper_cutoff_date: %s   construct check resolved: %s" % (status["upper_cutoff_date"], status["openalex_construct_check_resolved"]))
    return "\n".join(lines)


def write_status() -> Dict[str, Any]:
    st = build_status()
    storage.write_json(paths.status_file(), st)
    return st
