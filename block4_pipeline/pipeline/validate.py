"""`validate-protocol`: checks the configuration against the frozen protocol.

No network access. Returns a report with `ok`, `errors`, `warnings`.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from .. import config_loader as cl
from .. import paths

EXPECTED_QUERY_IDS = ["B4-Q%02d" % i for i in range(1, 49)] + ["B4-XC01", "B4-XC02"] + ["B4-BR%02d" % i for i in range(1, 5)]

# Section 5 of the protocol, hard-coded so that sources.yaml cannot drift silently.
EXPECTED_MATRIX: Dict[str, Dict[str, Any]] = {
    "openalex": {"mandatory": "all"},
    "scopus": {"mandatory": "all"},
    "wos": {"mandatory": "all"},
    "dblp": {"mandatory": ["B4-D01", "B4-D02", "B4-D03", "B4-D04", "B4-D05", "B4-D08", "B4-D09", "B4-D10", "B4-D14", "B4-XC"],
             "mandatory_lens": {"B4-D16": ["B community"]}},
    "ieee": {"mandatory": ["B4-D09", "B4-D11", "B4-D12", "B4-D13", "B4-D15", "B4-BR"]},
    "heinonline": {"mandatory": ["B4-D03", "B4-D06", "B4-D07", "B4-D08"]},
    "ssrn": {"mandatory": [], "supplementary": "all"},
    "scholar": {"mandatory": [], "supplementary": "all"},
    "web": {"mandatory": [], "supplementary": "all"},
}

# Secret-looking strings: key=... / token=... assignments with a real-looking value, or long
# mixed letter+digit tokens that are not hex digests.
_ASSIGN_RE = re.compile(r"(?i)\b(?:api[_-]?key|apikey|secret|token|password)\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{12,})")
_LONG_TOKEN_RE = re.compile(r"\b(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{20,}\b")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_PLACEHOLDERS = {"OPENALEX_API_KEY", "SCOPUS_API_KEY", "WOS_API_KEY", "IEEE_API_KEY", "REDACTED"}


def _matrix_expected_mandatory(source: str, query: Dict[str, Any]) -> bool:
    exp = EXPECTED_MATRIX[source]
    if exp.get("mandatory") == "all":
        return True
    group = cl.direction_group(query)
    if group in exp.get("mandatory", []):
        return True
    lenses = exp.get("mandatory_lens", {}).get(group)
    return bool(lenses and query.get("lens") in lenses)


def scan_for_secrets(files: List[Path]) -> List[str]:
    findings = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in _ASSIGN_RE.finditer(line):
                if m.group(1) not in _PLACEHOLDERS:
                    findings.append("%s:%d secret-looking assignment" % (f, lineno))
            for m in _LONG_TOKEN_RE.finditer(line):
                tok = m.group(0)
                if _HEX_RE.match(tok) or tok in _PLACEHOLDERS:
                    continue
                if tok.startswith(("B4", "W", "run_")):
                    continue
                findings.append("%s:%d long token %s…" % (f, lineno, tok[:6]))
    return findings


def validate(queries_path=None, sources_path=None, protocol_path=None, denylist_path=None,
             scan_code: bool = True) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    bank = cl.load_query_bank(queries_path)
    queries = list(bank.get("queries", []))
    sources = cl.load_sources(sources_path)
    protocol = cl.load_protocol(protocol_path)
    denylist = cl.load_denylist(denylist_path)

    # --- protocol header
    if protocol.get("protocol_revision") != 3:
        errors.append("protocol_revision must be 3, found %r" % protocol.get("protocol_revision"))
    if bank.get("revision") != 3:
        errors.append("query bank revision must be 3, found %r" % bank.get("revision"))
    if protocol.get("frozen") is not True:
        errors.append("protocol.yaml frozen must be true")
    if protocol.get("threshold_structured") != 300:
        errors.append("threshold_structured must be 300")
    if protocol.get("openalex_page_size") != 100:
        errors.append("openalex_page_size must be 100")
    if protocol.get("openalex_order") != "publication_date:asc,ids.openalex:asc":
        errors.append("openalex_order must be publication_date:asc,ids.openalex:asc (deviation log, 2026-09-29)")
    if protocol.get("refinement_order") != ["title_restrict_free_group", "add_mechanism_group", "subject_area_limit", "split_or_groups"]:
        errors.append("refinement_order differs from protocol section 8")
    if protocol.get("dedup_order") != ["doi", "source_ids", "normalized_title_year"]:
        errors.append("dedup_order differs from protocol section 9")

    # --- query set
    ids = [q.get("id") for q in queries]
    base_ids = [i for i in ids if i and "." not in i]
    refinement_ids = [i for i in ids if i and "." in i]
    if len(ids) != len(set(ids)):
        errors.append("duplicate query IDs")
    if sorted(base_ids) != sorted(EXPECTED_QUERY_IDS):
        missing = sorted(set(EXPECTED_QUERY_IDS) - set(base_ids))
        extra = sorted(set(base_ids) - set(EXPECTED_QUERY_IDS))
        errors.append("query set differs from the 54 pre-registered IDs; missing=%s extra=%s" % (missing, extra))
    for rid in refinement_ids:
        if not re.match(r"^B4-(Q\d{2}|XC\d{2}|BR\d{2})\.r\d+$", rid):
            errors.append("malformed refinement ID %s" % rid)
        elif rid.split(".")[0] not in base_ids:
            errors.append("refinement %s has no parent query" % rid)

    per_direction: Dict[str, List[str]] = defaultdict(list)
    for q in queries:
        if q.get("id") in base_ids and str(q.get("direction", "")).startswith("B4-D"):
            per_direction[q["direction"]].append(q.get("lens"))
    if sorted(per_direction.keys()) != cl.DIRECTION_IDS:
        errors.append("directions found: %s (expected B4-D01..B4-D16)" % sorted(per_direction.keys()))
    for d, lenses in sorted(per_direction.items()):
        if sorted(lenses) != sorted(cl.LENSES):
            errors.append("%s lenses are %s, expected one A, one B, one C" % (d, lenses))

    # --- per-query fields and source forms
    for q in queries:
        qid = q.get("id", "?")
        for f in ("basis", "community", "register", "canonical", "direction", "lens"):
            if not q.get(f):
                errors.append("%s: missing %s" % (qid, f))
        for sname, scfg in sources["sources"].items():
            if cl.is_mandatory(scfg, q):
                fld = scfg.get("query_field", sname)
                if not q.get(fld):
                    errors.append("%s: mandatory source %s needs form %s" % (qid, sname, fld))
        for fld in cl.SOURCE_FORM_FIELDS + ("canonical",):
            val = str(q.get(fld, ""))
            low = val.lower()
            for term in denylist:
                if term.lower() in low:
                    errors.append("%s: form %s contains denylisted name %r" % (qid, fld, term))
            if fld == "openalex_oql" and val and "?" in val:
                errors.append("%s: openalex_oql contains '?', which OpenAlex has no single-character wildcard for" % qid)
            if fld == "openalex_oql" and val and not val.strip().startswith("title_and_abstract has"):
                warnings.append("%s: openalex_oql does not start with 'title_and_abstract has'" % qid)

    # --- source matrix vs hard-coded expectation
    for sname, exp in EXPECTED_MATRIX.items():
        scfg = sources["sources"].get(sname)
        if not scfg:
            errors.append("sources.yaml lacks %s" % sname)
            continue
        for q in queries:
            if q.get("id") not in base_ids:
                continue
            want = _matrix_expected_mandatory(sname, q)
            got = cl.is_mandatory(scfg, q)
            if want != got:
                errors.append("sources.yaml: %s mandatory for %s is %s, protocol says %s" % (sname, q["id"], got, want))
        if exp.get("supplementary") == "all" and scfg.get("supplementary_for") != "all":
            errors.append("sources.yaml: %s must be supplementary everywhere" % sname)
    for sname, scfg in sources["sources"].items():
        if scfg.get("access_mode") not in ("api", "manual_export", "web"):
            errors.append("sources.yaml: %s has invalid access_mode" % sname)
        if scfg.get("access_status") == "ACCESS_TO_CONFIRM":
            warnings.append("%s: access mode %s, entitlement ACCESS_TO_CONFIRM" % (sname, scfg.get("access_mode")))

    # --- secrets in config and code
    files = [paths.QUERIES_FILE, paths.SOURCES_FILE, paths.PROTOCOL_FILE, paths.DENYLIST_FILE]
    if scan_code:
        files += sorted(paths.PACKAGE_DIR.rglob("*.py")) + [paths.PACKAGE_DIR.parent / "run.py"]
    for finding in scan_for_secrets([f for f in files if f.exists()]):
        errors.append("possible secret: " + finding)

    # --- state flags that gate retrieval
    if not protocol.get("openalex_construct_check_resolved"):
        warnings.append("OpenAlex construct check (brief 1b) not yet resolved; `retrieve --source openalex` is blocked")
    if protocol.get("upper_cutoff_date") is None:
        warnings.append("upper_cutoff_date not set; set it with `run.py set-cutoff` when the first real 4B retrieval starts")

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "n_queries": len(queries), "n_refinements": len(refinement_ids)}


def format_report(report: Dict[str, Any]) -> str:
    lines = ["validate-protocol: %s (%d queries, %d refinement sub-queries)" % (
        "PASS" if report["ok"] else "FAIL", report["n_queries"], report["n_refinements"])]
    for e in report["errors"]:
        lines.append("  ERROR   " + e)
    for w in report["warnings"]:
        lines.append("  warning " + w)
    return "\n".join(lines)
