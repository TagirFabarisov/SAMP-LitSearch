"""Prepare, without applying, the OpenAlex forms with bare wildcards quoted.

Recorded 29 September 2026: OpenAlex OQL rejects a bare `actor*` ("wildcards run on exact
(no-stem) text; fix: quote it") and accepts `"actor*"`, which it evaluates as a prefix on
unstemmed text. This module rewrites every bare `word*` outside double quotes to `"word*"`
in the `openalex_oql` field only, and writes the result next to a diff summary under
data/logs/. Nothing in config/ is touched: the user reads the diff, records the deviation,
and copies the proposed file over config/queries.yaml if accepted.

Also flagged: any wildcard with fewer than three characters before it (OpenAlex requires
three), and any `?` (no single-character wildcard in OpenAlex).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .. import config_loader as cl
from .. import paths, storage

_BARE_WILDCARD = re.compile(r"(?<![\w\"\-])([A-Za-z][\w\-]*\*)(?![\w\"])")


def quote_bare_wildcards(expr: str) -> Tuple[str, List[str], List[str]]:
    """Return (rewritten expression, list of rewritten tokens, list of warnings)."""
    out: List[str] = []
    changed: List[str] = []
    warnings: List[str] = []
    parts = expr.split('"')
    for i, part in enumerate(parts):
        inside_quotes = i % 2 == 1
        if inside_quotes:
            if "*" in part and len(part.replace("*", "").split()[-1]) < 3:
                warnings.append("phrase %r: fewer than 3 characters before the wildcard" % part)
            out.append(part)
            continue
        def repl(m):
            tok = m.group(1)
            if len(tok) - 1 < 3:
                warnings.append("%r: fewer than 3 characters before the wildcard" % tok)
            changed.append(tok)
            return '"%s"' % tok
        out.append(_BARE_WILDCARD.sub(repl, part))
    result = '"'.join(out)
    if "?" in result:
        warnings.append("contains '?': OpenAlex has no single-character wildcard")
    return result, changed, warnings


def propose() -> Dict[str, Any]:
    bank = cl.load_query_bank()
    ts = storage.utc_stamp()
    out_dir = paths.logs_dir() / ("quoting_proposal_" + ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_lines: List[str] = []
    n_changed = 0
    all_warnings: List[str] = []
    for q in bank["queries"]:
        new, changed, warns = quote_bare_wildcards(str(q["openalex_oql"]))
        for w in warns:
            all_warnings.append("%s: %s" % (q["id"], w))
        if new != q["openalex_oql"]:
            n_changed += 1
            diff_lines.append("%s  (%d tokens quoted: %s)" % (q["id"], len(changed), ", ".join(changed)))
            diff_lines.append("  - " + q["openalex_oql"])
            diff_lines.append("  + " + new)
            q["openalex_oql"] = new
            q["openalex_note"] = (str(q.get("openalex_note", "")) +
                                  "; bare wildcards quoted (OpenAlex evaluates \"word*\" as a prefix on unstemmed text, recorded 2026-09-29)")
    proposed = out_dir / "queries_proposed.yaml"
    with open(proposed, "w", encoding="utf-8") as fh:
        yaml.safe_dump(bank, fh, allow_unicode=True, sort_keys=False, width=100000)
    (out_dir / "diff.txt").write_text("\n".join(diff_lines) + "\n", encoding="utf-8")
    (out_dir / "warnings.txt").write_text("\n".join(all_warnings) + "\n", encoding="utf-8")
    return {"queries_changed": n_changed, "warnings": all_warnings, "proposed_file": str(proposed),
            "diff_file": str(out_dir / "diff.txt")}
