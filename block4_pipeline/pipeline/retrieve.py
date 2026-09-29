"""`retrieve`: run queries against an API source; `import-manual`: ingest a hand-made export.

Both write raw evidence once (never overwritten), allocate hit IDs, and append one row per
query run to the search log. Guards (checked before any network call):

- protocol.yaml has frozen: true and validate-protocol passes;
- for OpenAlex, the construct check (brief 1b) has been resolved;
- the source is mandatory for the query, or --include-supplementary was given;
- the (query, source) pair has not been run already, or --rerun was given.

The threshold rule: the count is read first; if it exceeds the threshold, nothing is
retrieved, the count is logged, and the query is marked REFINEMENT_REQUIRED. The
pipeline never refines a query itself.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config_loader as cl
from .. import paths, secrets, storage
from ..adapters import get_adapter
from ..adapters.base import DONE, FAILED, MANUAL_EXPORT_REQUIRED, REFINEMENT_REQUIRED
from ..adapters.manual_import import FORMATS, ManualImportAdapter, detect_format, parse_export
from . import provenance, validate


class RetrievalBlocked(RuntimeError):
    pass


def _guards(protocol: Dict[str, Any], source: str) -> None:
    if protocol.get("frozen") is not True:
        raise RetrievalBlocked("protocol.yaml frozen is not true; retrieval refused")
    report = validate.validate(scan_code=False)
    if not report["ok"]:
        raise RetrievalBlocked("validate-protocol fails:\n" + validate.format_report(report))


def _live_guards(protocol: Dict[str, Any], source: str) -> None:
    """Checked only before a real network retrieval; a dry run needs none of this."""
    if source == "openalex" and not protocol.get("openalex_construct_check_resolved"):
        raise RetrievalBlocked(
            "OpenAlex construct check (brief section 1b) is not resolved. Run `run.py oql-check`, "
            "record the outcome in the deviation log, then set openalex_construct_check_resolved: true.")


def _ordered_queries(queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Protocol section 24: D01..D16, then XC, then BR; A, B, C within a direction; refinements after their parent."""
    def key(q):
        qid = q["id"]
        group = cl.direction_group(q)
        if group.startswith("B4-D"):
            g = (0, int(group[4:]))
        elif group == "B4-XC":
            g = (1, 0)
        else:
            g = (2, 0)
        lens_rank = {"A semantic": 0, "B community": 1, "C mechanism": 2}.get(q.get("lens"), 3)
        base, _, ref = qid.partition(".")
        return (g, base, lens_rank, int(ref[1:]) if ref.startswith("r") and ref[1:].isdigit() else 0)
    return sorted(queries, key=key)


def select_queries(queries: List[Dict[str, Any]], query_ids: Optional[List[str]]) -> List[Dict[str, Any]]:
    if not query_ids:
        return _ordered_queries(queries)
    picked = []
    for qid in query_ids:
        q = cl.query_by_id(queries, qid)
        if not q:
            raise RetrievalBlocked("unknown query ID %s" % qid)
        picked.append(q)
    return _ordered_queries(picked)


def run_dir_for(source: str, query_id: str, ts: str) -> Path:
    return paths.raw_dir() / source / query_id / ts


def retrieve(source: str, query_ids: Optional[List[str]] = None, dry_run: bool = False,
             include_supplementary: bool = False, rerun: bool = False,
             cited_by: Optional[str] = None, anchor: Optional[str] = None,
             live_confirmed: bool = False) -> List[Dict[str, Any]]:
    protocol = cl.load_protocol()
    sources = cl.load_sources()
    if source not in sources["sources"]:
        raise RetrievalBlocked("unknown source %s" % source)
    scfg = sources["sources"][source]
    _guards(protocol, source)
    adapter = get_adapter(source, protocol, scfg)
    threshold = int(protocol.get(scfg.get("threshold_key", "threshold_structured"), 300))
    results: List[Dict[str, Any]] = []

    if cited_by:
        # forward snowballing: one pseudo-query per anchor work
        qid = "B4-SNF-%s" % cited_by.rsplit("/", 1)[-1]
        pseudo = {"id": qid, "direction": "snowball", "lens": "forward", "openalex_oql": "",
                  "register": "snowball", "provenance": "snowball forward from %s" % (anchor or cited_by)}
        return [_run_one(adapter, source, scfg, protocol, pseudo, threshold, dry_run, rerun, live_confirmed,
                         cited_by=cited_by, provenance="snowball forward from %s" % (anchor or cited_by))]

    for q in select_queries(cl.load_queries(), query_ids):
        mandatory = cl.is_mandatory(scfg, q)
        supplementary = cl.is_supplementary(scfg, q)
        if not mandatory and not (include_supplementary and supplementary):
            results.append({"query_id": q["id"], "source": source, "status": "not_applicable",
                            "note": "source is %s for this query" % ("supplementary" if supplementary else "not allocated")})
            continue
        results.append(_run_one(adapter, source, scfg, protocol, q, threshold, dry_run, rerun, live_confirmed))
    return results


def _run_one(adapter, source: str, scfg: Dict[str, Any], protocol: Dict[str, Any], q: Dict[str, Any],
             threshold: int, dry_run: bool, rerun: bool, live_confirmed: bool,
             cited_by: Optional[str] = None, provenance_label: str = "search", **kw) -> Dict[str, Any]:
    provenance_label = kw.get("provenance", provenance_label)
    qid = q["id"]
    exact = adapter.exact_query(q) if not cited_by else "cites:%s" % cited_by
    latest = provenance.latest_by_query_source().get((qid, source))
    if latest and latest.get("status") == DONE and not rerun:
        return {"query_id": qid, "source": source, "status": "already_done", "log_id": latest["log_id"]}

    if not adapter.supports_api():
        desc = adapter.describe_request(exact) if isinstance(adapter, ManualImportAdapter) else {"status": MANUAL_EXPORT_REQUIRED}
        if not dry_run and not (latest and latest.get("status") == MANUAL_EXPORT_REQUIRED):
            provenance.append_search_log({
                "query_id": qid, "direction": q.get("direction"), "lens": q.get("lens"), "source": source,
                "exact_string_sent": exact, "status": MANUAL_EXPORT_REQUIRED,
                "note": "no API path for this source; export by hand and use import-manual"}, protocol)
        return {"query_id": qid, "source": source, "status": MANUAL_EXPORT_REQUIRED, "request": desc}

    request = adapter.describe_request(exact, cited_by=cited_by)
    if dry_run:
        return {"query_id": qid, "source": source, "status": "dry_run", "exact_query": exact,
                "request": secrets.redact_obj(request), "threshold": threshold}
    if not live_confirmed:
        raise RetrievalBlocked("live retrieval needs --live (the user must explicitly ask for network calls)")
    _live_guards(protocol, source)

    ts = storage.utc_stamp()
    run_id = protocol["id_formats"]["run"].format(ts=ts, source=source, query=qid)
    run_dir = run_dir_for(source, qid, ts)
    manifest: Dict[str, str] = {}
    started = storage.utc_now()
    try:
        outcome = adapter.retrieve(exact, threshold, cited_by=cited_by)
    except Exception as exc:  # network or API failure: log it, keep going
        run_dir.mkdir(parents=True, exist_ok=True)
        storage.write_json(run_dir / "error.json", {"error": secrets.redact_text(str(exc)), "at": storage.utc_now()})
        provenance.append_search_log({
            "query_id": qid, "direction": q.get("direction"), "lens": q.get("lens"), "source": source,
            "exact_string_sent": exact, "status": FAILED, "run_id": run_id, "run_dir": str(run_dir),
            "note": secrets.redact_text(str(exc))[:500]}, protocol)
        return {"query_id": qid, "source": source, "status": FAILED, "error": secrets.redact_text(str(exc))}

    manifest["count_check.json"] = storage.write_raw_once(run_dir / "count_check.json", secrets.redact_obj(outcome.count_raw))
    storage.write_json(run_dir / "request.json", secrets.redact_obj({"count_request": outcome.count_request, "page_request": request,
                                                                     "exact_query": exact, "started_at": started}))

    hit_rows: List[Dict[str, Any]] = []
    if outcome.status == DONE:
        alloc = provenance.hit_allocator(protocol)
        rank = 0
        for page in outcome.pages:
            fname = "page_%d.json" % page.page_number
            manifest[fname] = storage.write_raw_once(run_dir / fname, page.raw)
            for idx, rec in enumerate(page.records):
                rank += 1
                hit_rows.append(provenance.make_hit(
                    alloc.next(), qid, source, exact, rank, page.page_number, started,
                    adapter.source_record_id(rec), run_id, str(Path(source) / qid / ts / fname), idx,
                    provenance=provenance_label))
        provenance.append_hits(hit_rows)
    storage.write_manifest(run_dir, manifest, {"run_id": run_id, "query_id": qid, "source": source,
                                               "status": outcome.status, "count": outcome.count,
                                               "records_retrieved": len(hit_rows)})
    log_id = provenance.append_search_log({
        "query_id": qid, "direction": q.get("direction"), "lens": q.get("lens"), "source": source,
        "exact_string_sent": exact, "original_count": outcome.count,
        "depth_inspected": len(hit_rows) if outcome.status == DONE else 0,
        "hits_created": len(hit_rows),
        "hits_range": [hit_rows[0]["hit_id"], hit_rows[-1]["hit_id"]] if hit_rows else None,
        "status": outcome.status, "run_id": run_id, "run_dir": str(run_dir), "note": outcome.note}, protocol)
    return {"query_id": qid, "source": source, "status": outcome.status, "count": outcome.count,
            "hits": len(hit_rows), "log_id": log_id, "run_dir": str(run_dir)}


# ----------------------------------------------------------------------------- manual import

def import_manual(source: str, query_id: str, file: str, fmt: Optional[str] = None,
                  export_date: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    protocol = cl.load_protocol()
    sources = cl.load_sources()
    if source not in sources["sources"]:
        raise RetrievalBlocked("unknown source %s" % source)
    scfg = sources["sources"][source]
    if protocol.get("frozen") is not True:
        raise RetrievalBlocked("protocol.yaml frozen is not true; import refused")
    queries = cl.load_queries()
    q = cl.query_by_id(queries, query_id)
    if not q and not query_id.startswith("B4-SN"):
        raise RetrievalBlocked("unknown query ID %s" % query_id)
    q = q or {"id": query_id, "direction": "snowball", "lens": None}
    src_path = Path(file)
    if not src_path.exists():
        raise RetrievalBlocked("file not found: %s" % src_path)
    fmt = fmt or detect_format(src_path, source)
    if fmt not in FORMATS:
        raise RetrievalBlocked("unknown format %s (choose from %s)" % (fmt, ", ".join(FORMATS)))

    adapter = ManualImportAdapter(source, protocol, scfg)
    adapter.fmt = fmt
    exact = str(q.get(scfg.get("query_field", source), "")) if q.get("id") in {x["id"] for x in queries} else note
    threshold = int(protocol.get(scfg.get("threshold_key", "threshold_structured"), 300))

    ts = storage.utc_stamp()
    run_id = protocol["id_formats"]["run"].format(ts=ts, source=source, query=query_id)
    run_dir = run_dir_for(source, query_id, ts)
    run_dir.mkdir(parents=True, exist_ok=False)
    kept = run_dir / ("export" + src_path.suffix.lower())
    shutil.copy2(src_path, kept)
    rows = parse_export(kept, fmt)
    manifest = {kept.name: storage.sha256_file(kept)}
    manifest["parsed.json"] = storage.write_raw_once(run_dir / "parsed.json", rows)

    status = DONE
    note_out = note
    if len(rows) > threshold and scfg.get("threshold_key") == "threshold_structured":
        status = REFINEMENT_REQUIRED
        note_out = ("export holds %d records, above threshold %d; kept as evidence, no hits created. %s"
                    % (len(rows), threshold, note)).strip()

    hit_rows: List[Dict[str, Any]] = []
    if status == DONE:
        alloc = provenance.hit_allocator(protocol)
        retrieved_at = export_date or storage.utc_now()
        for idx, row in enumerate(rows):
            hit_rows.append(provenance.make_hit(
                alloc.next(), query_id, source, exact, idx + 1, 1, retrieved_at,
                adapter.source_record_id(row), run_id, str(Path(source) / query_id / ts / "parsed.json"), idx))
        provenance.append_hits(hit_rows)
    storage.write_manifest(run_dir, manifest, {"run_id": run_id, "query_id": query_id, "source": source,
                                               "format": fmt, "status": status, "count": len(rows),
                                               "records_retrieved": len(hit_rows), "export_date": export_date,
                                               "original_file": src_path.name})
    log_id = provenance.append_search_log({
        "query_id": query_id, "direction": q.get("direction"), "lens": q.get("lens"), "source": source,
        "exact_string_sent": exact, "original_count": len(rows), "depth_inspected": len(hit_rows),
        "hits_created": len(hit_rows),
        "hits_range": [hit_rows[0]["hit_id"], hit_rows[-1]["hit_id"]] if hit_rows else None,
        "status": status, "run_id": run_id, "run_dir": str(run_dir),
        "note": ("manual export (%s)%s. %s" % (fmt, (", exported " + export_date) if export_date else "", note_out)).strip()},
        protocol)
    return {"query_id": query_id, "source": source, "status": status, "format": fmt, "count": len(rows),
            "hits": len(hit_rows), "log_id": log_id, "run_dir": str(run_dir)}
