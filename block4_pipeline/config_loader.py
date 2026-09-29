"""Loading of queries.yaml, sources.yaml and protocol.yaml into plain dictionaries."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml

from . import paths

# Query IDs: B4-Q01, B4-Q07.r1, B4-XC01, B4-BR04, B4-SN0001 (snowball)
DIRECTION_IDS = ["B4-D%02d" % i for i in range(1, 17)]
LENSES = ("A semantic", "B community", "C mechanism")
SOURCE_FORM_FIELDS = ("openalex_oql", "scopus", "wos", "ieee", "heinonline", "scholar", "dblp", "ssrn")


def load_yaml(path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_queries(path=None) -> List[Dict[str, Any]]:
    data = load_yaml(path or paths.QUERIES_FILE)
    return list(data.get("queries", []))


def load_query_bank(path=None) -> Dict[str, Any]:
    return load_yaml(path or paths.QUERIES_FILE)


def load_sources(path=None) -> Dict[str, Any]:
    return load_yaml(path or paths.SOURCES_FILE)


def load_protocol(path=None) -> Dict[str, Any]:
    return load_yaml(path or paths.PROTOCOL_FILE)


def load_denylist(path=None) -> List[str]:
    p = path or paths.DENYLIST_FILE
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    return entries


def query_by_id(queries: List[Dict[str, Any]], query_id: str) -> Optional[Dict[str, Any]]:
    for q in queries:
        if q.get("id") == query_id:
            return q
    return None


def direction_group(query: Dict[str, Any]) -> str:
    """Return the allocation key of a query: a direction ID, 'B4-XC' or 'B4-BR'."""
    d = str(query.get("direction", ""))
    if d.startswith("B4-D"):
        return d
    if d == "cross-cutting" or str(query.get("id", "")).startswith("B4-XC"):
        return "B4-XC"
    if d == "bridge" or str(query.get("id", "")).startswith("B4-BR"):
        return "B4-BR"
    return d


def _entry_matches(entry: Any, query: Dict[str, Any]) -> bool:
    group = direction_group(query)
    if isinstance(entry, str):
        return entry == group
    if isinstance(entry, dict):
        if entry.get("direction") != group:
            return False
        lenses = entry.get("lenses")
        return not lenses or query.get("lens") in lenses
    return False


def is_mandatory(source_cfg: Dict[str, Any], query: Dict[str, Any]) -> bool:
    spec = source_cfg.get("mandatory_for", [])
    if spec == "all":
        return True
    return any(_entry_matches(e, query) for e in (spec or []))


def is_supplementary(source_cfg: Dict[str, Any], query: Dict[str, Any]) -> bool:
    spec = source_cfg.get("supplementary_for", [])
    if spec == "all":
        return True
    return any(_entry_matches(e, query) for e in (spec or []))


def mandatory_sources(sources: Dict[str, Any], query: Dict[str, Any]) -> List[str]:
    order = sources.get("execution_order") or list(sources["sources"].keys())
    return [s for s in order if is_mandatory(sources["sources"][s], query)]


def base_query_id(query_id: str) -> str:
    """B4-Q07.r1 -> B4-Q07 (refinement sub-IDs share the parent's allocation)."""
    return query_id.split(".")[0]
