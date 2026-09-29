"""Search log, deviation log and hit records (protocol sections 9, 22, 25).

All three are append-only JSONL files; nothing is edited in place.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .. import paths, storage


SEARCH_LOG_FIELDS = (
    "log_id", "datetime_utc", "query_id", "direction", "lens", "source", "exact_string_sent",
    "original_count", "refinement_steps", "depth_inspected", "hits_created", "hits_range",
    "documents_new_after_dedup", "status", "run_id", "run_dir", "note",
)


def search_log_entries() -> List[Dict[str, Any]]:
    return list(storage.read_jsonl(paths.search_log_file()))


def latest_by_query_source() -> Dict[tuple, Dict[str, Any]]:
    latest: Dict[tuple, Dict[str, Any]] = {}
    for row in search_log_entries():
        latest[(row["query_id"], row["source"])] = row
    return latest


def append_search_log(row: Dict[str, Any], protocol: Dict[str, Any]) -> str:
    alloc = storage.max_existing_id(paths.search_log_file(), "log_id", protocol["id_formats"].get("search_log", "B4-L{:05d}"))
    row = dict(row)
    row["log_id"] = alloc.next()
    row.setdefault("datetime_utc", storage.utc_now())
    for f in SEARCH_LOG_FIELDS:
        row.setdefault(f, None)
    storage.append_jsonl(paths.search_log_file(), [row])
    return row["log_id"]


def append_deviation(entry: Dict[str, Any]) -> None:
    entry = dict(entry)
    entry.setdefault("recorded_at", storage.utc_now())
    storage.append_jsonl(paths.deviation_log_file(), [entry])


def deviations() -> List[Dict[str, Any]]:
    return list(storage.read_jsonl(paths.deviation_log_file()))


def hits() -> List[Dict[str, Any]]:
    return list(storage.read_jsonl(paths.hits_file()))


def hit_allocator(protocol: Dict[str, Any]) -> storage.IdAllocator:
    return storage.max_existing_id(paths.hits_file(), "hit_id", protocol["id_formats"]["hit"])


def append_hits(rows: Iterable[Dict[str, Any]]) -> int:
    return storage.append_jsonl(paths.hits_file(), rows)


def make_hit(hit_id: str, query_id: str, source: str, exact_query: str, rank: int, page: int,
             retrieved_at: str, source_record_id: Optional[str], run_id: str,
             raw_file: str, raw_index: int, provenance: str = "search") -> Dict[str, Any]:
    return {
        "hit_id": hit_id, "document_id": None, "query_id": query_id, "source": source,
        "exact_query": exact_query, "rank": rank, "page": page, "retrieved_at": retrieved_at,
        "source_record_id": source_record_id, "run_id": run_id, "raw_file": raw_file,
        "raw_index": raw_index, "provenance": provenance,
    }
