#!/usr/bin/env python3
"""Command-line entry point of the Block-4 systematic-search pipeline (SAMP RQ4.2).

    python run.py validate-protocol
    python run.py oql-check [--live [--execute]]
    python run.py retrieve --source openalex [--query B4-Q01 ...] [--dry-run | --live]
    python run.py retrieve --source openalex --cited-by W123 --anchor B4-A001 --live
    python run.py import-manual --source scopus --query B4-Q01 --file exports/scopus_Q01.csv [--format scopus_csv] [--export-date 2026-10-02]
    python run.py normalize
    python run.py deduplicate
    python run.py export [--format csv|jsonl|parquet|all]
    python run.py status
    python run.py set-cutoff 2026-10-01
    python run.py deviation add --rule "..." --change "..." --reason "..." --timing before|after --effect "..." --rerun yes|no
    python run.py deviation list

Nothing here calls the network unless --live is given explicitly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from block4_pipeline import config_loader as cl  # noqa: E402
from block4_pipeline import paths, secrets, storage  # noqa: E402
from block4_pipeline.pipeline import deduplicate, export, normalize, oql_check, provenance, retrieve, status, validate  # noqa: E402


def _print(obj) -> None:
    print(json.dumps(secrets.redact_obj(obj), ensure_ascii=False, indent=2, default=str))


def cmd_validate(args) -> int:
    report = validate.validate()
    print(validate.format_report(report))
    return 0 if report["ok"] else 1


def cmd_oql_check(args) -> int:
    if args.live:
        report = oql_check.live_report(execute=args.execute)
    else:
        report = oql_check.offline_report()
    print(oql_check.format_report(report))
    return 0


def cmd_scopus_check(args) -> int:
    from block4_pipeline.pipeline import scopus_check
    if not args.live:
        print("scopus-check needs --live: it sends one count=1 request to the Scopus Search API (the user must ask for it)")
        return 1
    _print(scopus_check.live_probe())
    return 0


def cmd_refine(args) -> int:
    from block4_pipeline.pipeline import refine
    res = refine.refine(args.source, query_ids=args.query or None, live=args.live)
    _print(res)
    return 0


def cmd_propose_quoting(args) -> int:
    from block4_pipeline.pipeline import propose_quoting
    _print(propose_quoting.propose())
    return 0


def cmd_retrieve(args) -> int:
    try:
        results = retrieve.retrieve(
            args.source, query_ids=args.query or None, dry_run=args.dry_run,
            include_supplementary=args.include_supplementary, rerun=args.rerun,
            cited_by=args.cited_by, anchor=args.anchor, live_confirmed=args.live)
    except retrieve.RetrievalBlocked as exc:
        print("BLOCKED: %s" % exc)
        return 2
    _print(results)
    return 0


def cmd_import_manual(args) -> int:
    try:
        res = retrieve.import_manual(args.source, args.query, args.file, fmt=args.format,
                                     export_date=args.export_date, note=args.note or "")
    except retrieve.RetrievalBlocked as exc:
        print("BLOCKED: %s" % exc)
        return 2
    _print(res)
    return 0


def cmd_normalize(args) -> int:
    _print(normalize.normalize())
    return 0


def cmd_deduplicate(args) -> int:
    _print(deduplicate.deduplicate())
    return 0


def cmd_export(args) -> int:
    _print(export.export(args.format))
    return 0


def cmd_status(args) -> int:
    st = status.write_status()
    print(status.format_table(st, only_mandatory=not args.all))
    print("written to %s" % paths.status_file())
    return 0


def cmd_set_cutoff(args) -> int:
    protocol = cl.load_protocol()
    if protocol.get("upper_cutoff_date"):
        print("upper_cutoff_date is already %s; changing it needs a deviation-log entry and a manual edit"
              % protocol["upper_cutoff_date"])
        return 1
    text = paths.PROTOCOL_FILE.read_text(encoding="utf-8")
    new = text.replace("upper_cutoff_date: null", "upper_cutoff_date: \"%s\"" % args.date, 1)
    if new == text:
        print("could not find `upper_cutoff_date: null` in protocol.yaml")
        return 1
    paths.PROTOCOL_FILE.write_text(new, encoding="utf-8")
    print("upper_cutoff_date set to %s (protocol section 7: the date the first 4B retrieval starts)" % args.date)
    return 0


def cmd_deviation(args) -> int:
    if args.action == "list":
        for d in provenance.deviations():
            _print(d)
        return 0
    entry = {"date": args.date or storage.utc_now()[:10], "original_rule_or_query": args.rule, "change": args.change,
             "reason": args.reason, "before_or_after_results": args.timing, "effect_on_earlier_searches": args.effect,
             "earlier_queries_rerun": args.rerun}
    provenance.append_deviation(entry)
    print("deviation recorded in %s" % paths.deviation_log_file())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-protocol").set_defaults(fn=cmd_validate)

    s = sub.add_parser("oql-check", help="OpenAlex construct check (brief section 1b)")
    s.add_argument("--live", action="store_true", help="make non-retrieving API calls (needs the user's permission)")
    s.add_argument("--execute", action="store_true", help="with --live: also run count-only probes")
    s.set_defaults(fn=cmd_oql_check)

    s = sub.add_parser("scopus-check", help="one request to test whether the Scopus subscription applies from this network")
    s.add_argument("--live", action="store_true")
    s.set_defaults(fn=cmd_scopus_check)

    s = sub.add_parser("refine", help="apply the section-8 refinement sequence to pairs above the threshold (count-only requests)")
    s.add_argument("--source", required=True)
    s.add_argument("--query", action="append")
    s.add_argument("--live", action="store_true", help="send count requests; without it, print the forms only")
    s.set_defaults(fn=cmd_refine)

    sub.add_parser("propose-quoting", help="write the OpenAlex forms with bare wildcards quoted, for review; config untouched").set_defaults(fn=cmd_propose_quoting)

    s = sub.add_parser("retrieve")
    s.add_argument("--source", required=True)
    s.add_argument("--query", action="append", help="query ID; repeatable; default: all in protocol order")
    s.add_argument("--dry-run", action="store_true", help="print the exact request and exit, no network")
    s.add_argument("--live", action="store_true", help="actually call the source (the user must ask for this)")
    s.add_argument("--include-supplementary", action="store_true")
    s.add_argument("--rerun", action="store_true", help="run again even if the (query, source) pair is done")
    s.add_argument("--cited-by", help="OpenAlex work ID for forward snowballing")
    s.add_argument("--anchor", help="artifact ID (B4-Axxx) the snowball starts from")
    s.set_defaults(fn=cmd_retrieve)

    s = sub.add_parser("import-manual")
    s.add_argument("--source", required=True)
    s.add_argument("--query", required=True)
    s.add_argument("--file", required=True)
    s.add_argument("--format", choices=list(retrieve.FORMATS))
    s.add_argument("--export-date", help="date the export was made, YYYY-MM-DD")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_import_manual)

    sub.add_parser("normalize").set_defaults(fn=cmd_normalize)
    sub.add_parser("deduplicate").set_defaults(fn=cmd_deduplicate)

    s = sub.add_parser("export")
    s.add_argument("--format", default="csv", choices=["csv", "jsonl", "parquet", "all"])
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("status")
    s.add_argument("--all", action="store_true", help="include supplementary pairs")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("set-cutoff")
    s.add_argument("date", help="YYYY-MM-DD, the day the first real 4B retrieval starts")
    s.set_defaults(fn=cmd_set_cutoff)

    s = sub.add_parser("deviation")
    s.add_argument("action", choices=["add", "list"])
    s.add_argument("--date")
    s.add_argument("--rule", help="original rule or query")
    s.add_argument("--change")
    s.add_argument("--reason")
    s.add_argument("--timing", choices=["before", "after"], help="before or after seeing relevant results")
    s.add_argument("--effect", help="effect on earlier searches")
    s.add_argument("--rerun", choices=["yes", "no"], help="whether earlier queries are rerun")
    s.set_defaults(fn=cmd_deviation)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "deviation" and args.action == "add":
        missing = [f for f in ("rule", "change", "reason", "timing", "effect", "rerun") if not getattr(args, f)]
        if missing:
            print("deviation add needs --%s" % " --".join(missing))
            return 1
    paths.ensure_dirs()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
