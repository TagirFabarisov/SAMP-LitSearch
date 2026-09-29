"""`export`: tables for screening tools. CSV and JSONL always; Parquet when pyarrow is installed."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .. import paths, storage
from . import provenance


def _flatten(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in row.items():
        if k == "authors" and isinstance(v, list):
            out[k] = "; ".join(a.get("name") or "" for a in v)
        elif isinstance(v, (list, dict)):
            out[k] = json.dumps(v, ensure_ascii=False)
        else:
            out[k] = v
    return out


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    rows = [_flatten(r) for r in rows]
    fields: List[str] = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_parquet(path: Path, rows: List[Dict[str, Any]]) -> bool:
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError:
        return False
    table = pa.Table.from_pylist([_flatten(r) for r in rows])
    pq.write_table(table, path)
    return True


def export(fmt: str = "csv") -> Dict[str, Any]:
    out = paths.exports_dir()
    out.mkdir(parents=True, exist_ok=True)
    documents = list(storage.read_jsonl(paths.documents_file()))
    hits = provenance.hits()
    log = provenance.search_log_entries()
    for_s1 = [d for d in documents if not d.get("after_cutoff")]
    written = {}
    tables = {"documents": documents, "documents_for_s1": for_s1, "hits": hits, "search_log": log}
    for name, rows in tables.items():
        if fmt in ("csv", "all"):
            p = out / (name + ".csv")
            _write_csv(p, rows)
            written[name + ".csv"] = len(rows)
        if fmt in ("jsonl", "all"):
            p = out / (name + ".jsonl")
            storage.rewrite_jsonl(p, rows)
            written[name + ".jsonl"] = len(rows)
        if fmt in ("parquet", "all"):
            p = out / (name + ".parquet")
            if _write_parquet(p, rows):
                written[name + ".parquet"] = len(rows)
            else:
                written[name + ".parquet"] = "skipped: pyarrow not installed"
    return {"exports_dir": str(out), "written": written,
            "excluded_after_cutoff": len(documents) - len(for_s1)}
