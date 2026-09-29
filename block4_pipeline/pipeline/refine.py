"""`refine`: apply the protocol's pre-registered refinement sequence (section 8) to every
(query, source) pair whose count exceeded the threshold.

Steps, in the frozen order, applied cumulatively until the count is at most the threshold:

  1. title_restrict_free_group  the free (representation) group, taken as the last top-level
                                AND group of the expression, is moved to the title field
  2. add_mechanism_group        the direction's Q-C mechanism group (last top-level AND group
                                of the C query) is added as an extra AND; skipped for a C
                                query itself and for XC / BR queries, which have no Q-C
  3. subject_area_limit         the six areas the protocol names, expressed in OpenAlex as the
                                field of any topic of the work: Computer Science (17),
                                Engineering (22), Decision Sciences (18), Social Sciences incl.
                                Law (33), Business/Management/Accounting (14), Economics (20)
  4. split_or_groups            one sub-query per alternative of the largest top-level OR group

Every step's exact form and count is logged (search log, status `refinement_count`), the
resulting sub-queries are appended to config/refinements.yaml (never rewritten) with sub-IDs
`B4-Qxx.r<step>` (and `.r4.<n>` for split parts), and only the runnable ones are retrieved
afterwards by `retrieve`. A pair still above the threshold after step 4 is reported as
REFINEMENT_EXHAUSTED for the user to decide.

The application was authorised by the user on 29 September 2026 (deviation log). The
program applies the pre-registered steps; it invents no new term.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .. import config_loader as cl
from .. import paths, storage
from ..adapters import get_adapter
from ..adapters.base import REFINEMENT_REQUIRED
from . import provenance

FIELD_IDS = {"Computer Science": 17, "Engineering": 22, "Decision Sciences": 18,
             "Social Sciences (incl. Law)": 33, "Business, Management and Accounting": 14,
             "Economics, Econometrics and Finance": 20}
FIELD_CLAUSE = "topics.field.id is (%s)" % " OR ".join("fields/%d" % i for i in FIELD_IDS.values())

STEP_NAMES = ["title_restrict_free_group", "add_mechanism_group", "subject_area_limit", "split_or_groups"]


# ----------------------------------------------------------------------------- expression handling

def split_top_level(expr: str, op: str) -> List[str]:
    """Split `expr` at top-level occurrences of the Boolean operator `op` (AND / OR),
    respecting parentheses and double quotes."""
    parts: List[str] = []
    depth = 0
    in_quote = False
    i = 0
    start = 0
    token = " %s " % op
    while i < len(expr):
        ch = expr[i]
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and expr.startswith(token, i):
                parts.append(expr[start:i].strip())
                i += len(token)
                start = i
                continue
        i += 1
    parts.append(expr[start:].strip())
    return parts


def strip_outer_parens(s: str) -> str:
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        balanced = True
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    balanced = False
                    break
        if not balanced:
            break
        s = s[1:-1].strip()
    return s


def parse_oql(openalex_oql: str) -> Tuple[List[str], List[str]]:
    """Return (AND groups of the title_and_abstract clause, other top-level clauses)."""
    expr = openalex_oql.strip()
    if expr.lower().startswith("works where"):
        expr = expr[len("works where"):].strip()
    clauses = split_top_level(expr, "AND")
    ta_groups: List[str] = []
    others: List[str] = []
    for c in clauses:
        m = re.match(r"^title_and_abstract has\s*\((.*)\)$", c.strip(), re.S)
        if m:
            ta_groups = [g.strip() for g in split_top_level(m.group(1).strip(), "AND")]
        else:
            others.append(c.strip())
    return ta_groups, others


def build_oql(ta_groups: List[str], others: List[str]) -> str:
    clauses = []
    if ta_groups:
        clauses.append("title_and_abstract has (%s)" % " AND ".join(ta_groups))
    clauses.extend(others)
    return " AND ".join(clauses)


def mechanism_group_of_direction(queries: List[Dict[str, Any]], direction: str) -> Optional[str]:
    for q in queries:
        if q.get("direction") == direction and q.get("lens") == "C mechanism":
            groups, _ = parse_oql(str(q["openalex_oql"]))
            return groups[-1] if groups else None
    return None


def or_alternatives(group: str) -> List[str]:
    return [a.strip() for a in split_top_level(strip_outer_parens(group), "OR")]


# ----------------------------------------------------------------------------- step application

def apply_step(step: int, ta_groups: List[str], others: List[str], mech_group: Optional[str],
               lens: str) -> Tuple[Optional[List[Tuple[List[str], List[str]]]], str]:
    """Return (list of (ta_groups, others) variants, note). None means the step is skipped."""
    if step == 1:
        if len(ta_groups) < 2:
            return None, "no free group to move (single group)"
        free = ta_groups[-1]
        return [(ta_groups[:-1], others + ["title has %s" % _paren(free)])], "free group %s moved to title" % free
    if step == 2:
        if lens == "C mechanism":
            return None, "C query already carries its mechanism group"
        if not mech_group:
            return None, "no Q-C mechanism group for this direction"
        if mech_group in ta_groups:
            return None, "mechanism group already present"
        return [(ta_groups + [mech_group], others)], "mechanism group %s added" % mech_group
    if step == 3:
        if FIELD_CLAUSE in others:
            return None, "field limit already present"
        return [(ta_groups, others + [FIELD_CLAUSE])], "subject areas limited to fields %s" % sorted(FIELD_IDS.values())
    if step == 4:
        if not ta_groups:
            return None, "nothing to split"
        idx = max(range(len(ta_groups)), key=lambda i: len(or_alternatives(ta_groups[i])))
        alts = or_alternatives(ta_groups[idx])
        if len(alts) < 2:
            return None, "largest group has a single alternative"
        variants = []
        for alt in alts:
            g = list(ta_groups)
            g[idx] = _paren(alt)
            variants.append((g, others))
        return variants, "group %d split into %d parts" % (idx + 1, len(alts))
    return None, "unknown step"


def _paren(s: str) -> str:
    s = s.strip()
    return s if s.startswith("(") and s.endswith(")") and strip_outer_parens(s) != s else "(%s)" % s


# ----------------------------------------------------------------------------- persistence

def load_refinements() -> List[Dict[str, Any]]:
    p = paths.REFINEMENTS_FILE
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return list(data.get("refinements", []))


def append_refinements(entries: List[Dict[str, Any]]) -> None:
    p = paths.REFINEMENTS_FILE
    existing = load_refinements()
    existing.extend(entries)
    header = ("# Refinement sub-queries generated by `run.py refine` under the protocol's section-8\n"
              "# sequence (see pipeline/refine.py). Append-only; each entry records the step applied,\n"
              "# the exact form and the count observed. Only entries with runnable: true are retrieved.\n")
    p.write_text(header + yaml.safe_dump({"refinements": existing}, allow_unicode=True, sort_keys=False, width=100000),
                 encoding="utf-8")


# ----------------------------------------------------------------------------- driver

def refine(source: str, query_ids: Optional[List[str]] = None, live: bool = False) -> List[Dict[str, Any]]:
    protocol = cl.load_protocol()
    sources = cl.load_sources()
    scfg = sources["sources"][source]
    threshold = int(protocol.get(scfg.get("threshold_key", "threshold_structured"), 300))
    queries = cl.load_queries()
    adapter = get_adapter(source, protocol, scfg)
    if not adapter.supports_api():
        raise RuntimeError("refine needs an API source; %s is manual" % source)
    latest = provenance.latest_by_query_source()
    existing_ids = {r["id"] for r in load_refinements()}
    results: List[Dict[str, Any]] = []

    for q in queries:
        if query_ids and q["id"] not in query_ids:
            continue
        entry = latest.get((q["id"], source))
        if not entry or entry.get("status") != REFINEMENT_REQUIRED:
            continue
        if any(i.startswith(q["id"] + ".") for i in existing_ids):
            results.append({"query_id": q["id"], "status": "already_refined"})
            continue
        base_count = entry.get("original_count")
        ta_groups, others = parse_oql(str(q["openalex_oql"]))
        mech = mechanism_group_of_direction(queries, q["direction"]) if str(q["direction"]).startswith("B4-D") else None
        trajectory: List[Dict[str, Any]] = [{"step": 0, "name": "original", "count": base_count}]
        new_entries: List[Dict[str, Any]] = []
        final_status = "REFINEMENT_EXHAUSTED"
        state = (ta_groups, others)
        for step in (1, 2, 3, 4):
            variants, note = apply_step(step, state[0], state[1], mech, q.get("lens", ""))
            if variants is None:
                trajectory.append({"step": step, "name": STEP_NAMES[step - 1], "skipped": note})
                continue
            counts = []
            for n, (g, o) in enumerate(variants, 1):
                expr = build_oql(g, o)
                sub_id = "%s.r%d" % (q["id"], step) if step < 4 else "%s.r4.%d" % (q["id"], n)
                if not live:
                    results.append({"query_id": q["id"], "dry_run": sub_id, "oql": expr})
                    counts.append(None)
                    continue
                c = adapter.count(adapter.exact_query({"openalex_oql": expr}))
                counts.append(c.count)
                provenance.append_search_log({
                    "query_id": sub_id, "direction": q.get("direction"), "lens": q.get("lens"), "source": source,
                    "exact_string_sent": adapter.exact_query({"openalex_oql": expr}), "original_count": c.count,
                    "refinement_steps": [t.get("name") for t in trajectory if "skipped" not in t and t["step"] > 0] + [STEP_NAMES[step - 1]],
                    "status": "refinement_count", "note": note}, protocol)
                new_entries.append({
                    "id": sub_id, "refinement_of": q["id"], "direction": q.get("direction"), "lens": q.get("lens"),
                    "applies_to_source": source, "step": step, "step_name": STEP_NAMES[step - 1],
                    "openalex_oql": expr, "count": c.count, "runnable": c.count <= threshold,
                    "basis": q.get("basis"), "community": q.get("community"), "register": q.get("register"),
                    "created_at": storage.utc_now(), "note": note,
                })
            trajectory.append({"step": step, "name": STEP_NAMES[step - 1], "note": note, "counts": counts})
            if not live:
                state = variants[0]
                continue
            if step < 4:
                state = variants[0]
                if counts[0] <= threshold:
                    final_status = "refined_at_step_%d" % step
                    break
            else:
                final_status = "split_%d_parts_%d_runnable" % (len(counts), sum(1 for c in counts if c <= threshold))
        if live and new_entries:
            append_refinements(new_entries)
            existing_ids.update(e["id"] for e in new_entries)
        results.append({"query_id": q["id"], "status": final_status, "trajectory": trajectory,
                        "runnable": [e["id"] for e in new_entries if e["runnable"]],
                        "still_above": [e["id"] for e in new_entries if not e["runnable"] and (e["step"] == 4 or final_status == "REFINEMENT_EXHAUSTED")]})
    return results
