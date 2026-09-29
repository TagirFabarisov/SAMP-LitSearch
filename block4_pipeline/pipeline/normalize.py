"""`normalize`: raw records -> common schema, one row per hit, with the cutoff flag.

Reads every hit, locates its raw record (raw_file + raw_index), maps it through the
source adapter, and rewrites data/normalized/records.jsonl (a derived table).
Records dated after `upper_cutoff_date` stay in the raw data and in this table, but
carry `after_cutoff: true` and are excluded from the S1 export.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config_loader as cl
from .. import paths, storage
from ..adapters import get_adapter
from ..adapters.manual_import import ManualImportAdapter
from . import provenance


def is_after_cutoff(publication_date: Optional[str], cutoff: Optional[str]) -> bool:
    if not cutoff or not publication_date:
        return False
    return str(publication_date)[:10] > str(cutoff)[:10]


def _load_raw(cache: Dict[str, Any], rel: str) -> Any:
    if rel not in cache:
        with open(paths.raw_dir() / rel, "r", encoding="utf-8") as fh:
            cache[rel] = json.load(fh)
    return cache[rel]


def normalize() -> Dict[str, Any]:
    protocol = cl.load_protocol()
    sources = cl.load_sources()
    cutoff = protocol.get("upper_cutoff_date")
    adapters: Dict[str, Any] = {}
    manifests: Dict[str, Dict[str, Any]] = {}
    cache: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    stats = {"hits": 0, "after_cutoff": 0, "non_english": 0, "missing_raw": 0}

    for hit in provenance.hits():
        stats["hits"] += 1
        source = hit["source"]
        if source not in adapters:
            adapters[source] = get_adapter(source, protocol, sources["sources"][source])
        adapter = adapters[source]
        rel = hit["raw_file"]
        try:
            raw = _load_raw(cache, rel)
        except FileNotFoundError:
            stats["missing_raw"] += 1
            continue
        if isinstance(adapter, ManualImportAdapter):
            run_dir = (paths.raw_dir() / rel).parent
            key = str(run_dir)
            if key not in manifests:
                with open(run_dir / "manifest.json", "r", encoding="utf-8") as fh:
                    manifests[key] = json.load(fh)
            adapter.fmt = manifests[key].get("format")
        records = adapter.records_in_raw(raw)
        raw_record = records[hit["raw_index"]]
        rec = adapter.normalize_record(raw_record)
        rec["hit_id"] = hit["hit_id"]
        rec["query_id"] = hit["query_id"]
        rec["exact_query"] = hit["exact_query"]
        rec["retrieved_at"] = hit["retrieved_at"]
        rec["rank"] = hit["rank"]
        rec["page"] = hit["page"]
        rec["run_id"] = hit["run_id"]
        rec["after_cutoff"] = is_after_cutoff(rec.get("publication_date"), cutoff)
        lang = (rec.get("language") or "").lower()
        rec["non_english"] = bool(lang) and lang not in ("en", "eng", "english")
        stats["after_cutoff"] += int(rec["after_cutoff"])
        stats["non_english"] += int(rec["non_english"])
        rows.append(rec)

    storage.rewrite_jsonl(paths.records_file(), rows)
    stats["records_written"] = len(rows)
    stats["upper_cutoff_date"] = cutoff
    return stats
