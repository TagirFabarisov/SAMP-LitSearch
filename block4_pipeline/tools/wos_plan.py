"""Helper for running Web of Science by hand, one string at a time.

    python3 block4_pipeline/tools/wos_plan.py next <ID> <count>

Logs the count observed for <ID> (base query or sub-query) in the search log, decides the next
step under the protocol's refinement sequence, and prints what to run next:

    EXPORT <ID> <count>           count at or below the threshold: export this one
    RUN <sub-ID> <string>         run this string next (one line per part for a split)
    EXHAUSTED <ID> <count>        no OR group left to split

Decisions are derived from the ID alone (r1 = step 1, r2 = steps 1+2, r3 = 1+2+3, r4.n = split
part n of the last applicable state, r4.n.m = part m of a further split), so the helper is
stateless apart from the search log. Export candidates are appended to wos_export_plan.jsonl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from block4_pipeline import config_loader as cl, paths  # noqa: E402
from block4_pipeline.pipeline import provenance, refine  # noqa: E402

SOURCE = "wos"
PLAN = Path(__file__).resolve().parents[1] / "data" / "raw" / "manual_exports" / "wos" / "wos_export_plan.jsonl"
STEP_NAMES = refine.STEP_NAMES


def state_for(qid: str):
    """Return (base query, ta_groups, others, steps applied, label) for the state the ID denotes."""
    queries = cl.load_queries()
    base_id = qid.split(".")[0]
    q = cl.query_by_id(queries, base_id)
    g, o = refine.parse_oql(q[SOURCE], SOURCE)
    mech = refine.mechanism_group_of_direction(queries, q["direction"], SOURCE) if str(q["direction"]).startswith("B4-D") else None
    applied = []
    parts = qid.split(".")[1:]
    if not parts:
        return q, g, o, applied, mech
    head = parts[0]  # r1 / r2 / r3 / r4
    level = int(head[1:])
    state = (g, o)
    for step in (1, 2, 3):
        if step > min(level, 3):
            break
        v, note = refine.apply_step(step, state[0], state[1], mech, q.get("lens", ""), SOURCE)
        if v is not None:
            state = v[0]
            applied.append(STEP_NAMES[step - 1])
    if level == 4:
        for idx_str in parts[1:]:
            v, note = refine.apply_step(4, state[0], state[1], mech, q.get("lens", ""), SOURCE)
            if v is None:
                raise SystemExit("cannot split further for %s" % qid)
            state = v[int(idx_str) - 1]
            applied.append("split_or_groups")
    return q, state[0], state[1], applied, mech


def main():
    cmd, qid, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
    assert cmd == "next"
    protocol = cl.load_protocol()
    threshold = int(protocol["threshold_structured"])
    q, g, o, applied, mech = state_for(qid)
    string = refine.build_oql(g, o, SOURCE)
    provenance.append_search_log({
        "query_id": qid, "direction": q.get("direction"), "lens": q.get("lens"), "source": SOURCE,
        "exact_string_sent": string, "original_count": count, "refinement_steps": applied or None,
        "status": "refinement_count" if "." in qid else ("REFINEMENT_REQUIRED" if count > threshold else "counted"),
        "note": "count read in the Web of Science interface (Core Collection)"}, protocol)
    if count <= threshold:
        with open(PLAN, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": qid, "count": count, "string": string}) + "\n")
        print("EXPORT %s %d" % (qid, count))
        return
    parts = qid.split(".")[1:]
    level = int(parts[0][1:]) if parts else 0
    # next cumulative step
    if level < 3:
        state = (g, o)
        for step in range(level + 1, 4):
            v, note = refine.apply_step(step, state[0], state[1], mech, q.get("lens", ""), SOURCE)
            if v is None:
                continue
            print("RUN %s.r%d %s" % (qid.split(".")[0], step, refine.build_oql(*v[0], SOURCE)))
            return
    # split (first or further)
    v, note = refine.apply_step(4, g, o, mech, q.get("lens", ""), SOURCE)
    if v is None:
        print("EXHAUSTED %s %d" % (qid, count))
        return
    prefix = qid if level == 4 else "%s.r4" % qid.split(".")[0]
    for n, (gg, oo) in enumerate(v, 1):
        print("RUN %s.%d %s" % (prefix, n, refine.build_oql(gg, oo, SOURCE)))


if __name__ == "__main__":
    main()
