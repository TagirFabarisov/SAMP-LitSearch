"""`oql-check`: the OpenAlex construct check of brief section 1b.

Constructs in the query bank that must be accepted with the intended meaning:
  C1  parentheses and AND / OR nesting
  C2  quoted phrase                        "resource dependence"
  C3  bare-term truncation                 actor*
  C4  phrase-internal truncation           "dependence relation*"
  C5  hyphenated phrase                    "power-dependence"
  C6  the column name                      title_and_abstract

Two modes:
  offline (default)  reads recorded fixtures under tests/fixtures/openalex/ and prints what
                     they say; no network. The shipped fixtures were written by hand from the
                     OpenAlex documentation and are placeholders until a live check is recorded.
  --live             requires the user's explicit permission. Makes only non-retrieving calls:
                     GET /properties/works (is the column known?), GET /validate?q= per construct
                     (parse only), POST /query per construct (how `*` is translated). With
                     --execute it additionally runs count-only probes (per_page=1) to compare
                     "dependence relation*" against "dependence relation" and "dependence
                     relations", which is the only way to see whether truncation changes the
                     result set. Every response is saved under data/logs/oql_check_<ts>/.

The command never changes queries.yaml or protocol.yaml. The user reads the report, records
the outcome in the deviation log, and sets openalex_construct_check_resolved: true by hand.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .. import config_loader as cl
from .. import paths, secrets, storage
from ..adapters.openalex import OpenAlexAdapter

FIXTURE_DIR = paths.PACKAGE_DIR.parent / "tests" / "fixtures" / "openalex"

CONSTRUCTS: List[Dict[str, str]] = [
    {"id": "C1", "name": "parentheses and AND/OR", "oql": 'works where title_and_abstract has (("resource dependence" OR "social dependence") AND (actor OR agent))'},
    {"id": "C2", "name": "quoted phrase", "oql": 'works where title_and_abstract has ("resource dependence")'},
    {"id": "C3", "name": "bare truncation", "oql": "works where title_and_abstract has (actor*)"},
    {"id": "C3q", "name": "quoted single-word truncation (the fix OpenAlex proposes)", "oql": 'works where title_and_abstract has ("actor*")'},
    {"id": "C3a", "name": "bare word, stemmed (comparison)", "oql": "works where title_and_abstract has (actor)"},
    {"id": "C3b", "name": "quoted word, exact (comparison)", "oql": 'works where title_and_abstract has ("actor")'},
    {"id": "C4", "name": "phrase-internal truncation", "oql": 'works where title_and_abstract has ("dependence relation*")'},
    {"id": "C4a", "name": "phrase without truncation (comparison)", "oql": 'works where title_and_abstract has ("dependence relation")'},
    {"id": "C4b", "name": "phrase plural (comparison)", "oql": 'works where title_and_abstract has ("dependence relations")'},
    {"id": "C5", "name": "hyphenated phrase", "oql": 'works where title_and_abstract has ("power-dependence")'},
    {"id": "C7", "name": "cites filter for forward snowballing", "oql": "works where cites is (W2741809807)"},
]


def offline_report() -> Dict[str, Any]:
    report: Dict[str, Any] = {"mode": "offline", "fixtures": {}, "note": ""}
    if not FIXTURE_DIR.exists():
        report["note"] = "no fixtures found"
        return report
    for f in sorted(FIXTURE_DIR.glob("oql_check_*.json")):
        report["fixtures"][f.name] = json.loads(f.read_text(encoding="utf-8"))
    report["note"] = ("Fixtures under tests/fixtures/openalex/ are hand-written from the documentation unless "
                      "their 'recorded' field says otherwise; they show the response SHAPE the pipeline handles, "
                      "not the live behaviour. Run with --live (after the user's permission) to record the real answer.")
    return report


def live_report(execute: bool = False) -> Dict[str, Any]:
    protocol = cl.load_protocol()
    sources = cl.load_sources()
    adapter = OpenAlexAdapter(protocol, sources["sources"]["openalex"])
    ts = storage.utc_stamp()
    out_dir = paths.logs_dir() / ("oql_check_" + ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {"mode": "live", "recorded_at": storage.utc_now(), "executed_probes": execute, "constructs": []}

    props = adapter.properties()
    storage.write_json(out_dir / "properties_works.json", secrets.redact_obj(props))
    columns = _column_ids(props.get("body"))
    # OQL's `title_and_abstract has (...)` is registered as title_and_abstract.search (stemmed)
    # and title_and_abstract.search.exact (unstemmed, used for quoted values)
    report["column_title_and_abstract_known"] = ("title_and_abstract.search" in columns) if columns else None
    report["columns_sample"] = [c for c in columns if "title" in c or "abstract" in c or "search" in c or "cite" in c][:40]

    for c in CONSTRUCTS:
        entry: Dict[str, Any] = dict(c)
        entry["validate"] = adapter.validate_expression(c["oql"])
        entry["translate"] = adapter.translate(c["oql"])
        if execute:
            try:
                cr = adapter.count(c["oql"])
                entry["count"] = cr.count
                entry["meta_x_query"] = (cr.raw.get("meta") or {}).get("x_query")
            except Exception as exc:
                entry["count_error"] = secrets.redact_text(str(exc))
        entry["verdict"] = _verdict(entry)
        report["constructs"].append(entry)
        storage.write_json(out_dir / ("%s.json" % c["id"]), secrets.redact_obj(entry))

    if execute:
        # Ordering check: the protocol's "publication date, then OpenAlex work ID". `id` is not a
        # sortable column (recorded 29 Sep 2026); `ids.openalex` is. One request, per_page=1.
        report["sort_checks"] = {}
        for sort in (protocol.get("openalex_order", ""), "publication_date:asc,ids.openalex:asc"):
            body = {"oql": CONSTRUCTS[1]["oql"], "sort": sort, "per_page": 1, "cursor": "*"}
            try:
                data = adapter._post(body)
                report["sort_checks"][sort] = {"accepted": True, "first_id": (data.get("results") or [{}])[0].get("id"),
                                               "next_cursor_present": bool((data.get("meta") or {}).get("next_cursor"))}
            except Exception as exc:
                report["sort_checks"][sort] = {"accepted": False, "error": secrets.redact_text(str(exc))[:400]}
        storage.write_json(out_dir / "sort_checks.json", report["sort_checks"])
        counts = {e["id"]: e.get("count") for e in report["constructs"]}
        report["truncation_comparison"] = {
            "dependence relation*": counts.get("C4"), "dependence relation": counts.get("C4a"),
            "dependence relations": counts.get("C4b"),
            '"actor*" quoted wildcard': counts.get("C3q"), "actor bare (stemmed)": counts.get("C3a"),
            '"actor" quoted (exact)': counts.get("C3b"),
            "reading": ("if C4 >= max(C4a, C4b) and differs from both, phrase-internal truncation is honoured; "
                        "if C4 equals C4a, the '*' is ignored or stemming already covers the plural; "
                        "if C4 is 0 or errors, the '*' is taken literally or rejected"),
        }
    storage.write_json(out_dir / "report.json", secrets.redact_obj(report))
    report["saved_to"] = str(out_dir)
    return report


def _column_ids(body: Any) -> List[str]:
    ids: List[str] = []
    def walk(x):
        if isinstance(x, dict):
            for k in ("id", "column_id", "name"):
                if isinstance(x.get(k), str):
                    ids.append(x[k])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(body)
    return sorted(set(ids))


def _verdict(entry: Dict[str, Any]) -> str:
    v = entry.get("validate", {})
    body = v.get("body") if isinstance(v, dict) else None
    if v.get("http_status") == 200 and isinstance(body, dict):
        val = body.get("validation", body)
        if val.get("valid") is True:
            return "accepted by the parser (meaning still to be judged from translate/count)"
        if val.get("valid") is False:
            return "REJECTED: " + "; ".join(e.get("message", "") for e in val.get("errors", []))
    return "unclear (HTTP %s)" % v.get("http_status")


def format_report(report: Dict[str, Any]) -> str:
    lines = ["oql-check (%s)" % report["mode"]]
    if report["mode"] == "offline":
        lines.append(report["note"])
        for name, fx in report["fixtures"].items():
            lines.append("  fixture %s: %s" % (name, fx.get("summary", "")))
        return "\n".join(lines)
    lines.append("column title_and_abstract known: %s" % report.get("column_title_and_abstract_known"))
    for e in report["constructs"]:
        lines.append("  %-4s %-40s %s" % (e["id"], e["name"], e["verdict"]))
        tr = e.get("translate", {}).get("body")
        if isinstance(tr, dict) and tr.get("oxurl"):
            lines.append("       classic form: %s" % tr["oxurl"])
        if "count" in e:
            lines.append("       count: %s" % e["count"])
    if report.get("truncation_comparison"):
        lines.append("  truncation comparison: %s" % json.dumps(report["truncation_comparison"], ensure_ascii=False))
    for sort, res in (report.get("sort_checks") or {}).items():
        lines.append("  sort %-45s %s" % (sort, "accepted" if res.get("accepted") else "REJECTED: " + res.get("error", "")))
    lines.append("saved to %s" % report.get("saved_to"))
    return "\n".join(lines)
