"""Source adapters. Each adapter knows how to talk to one source (or how to import its
exports) and how to map its records to the common document schema."""
from __future__ import annotations

from typing import Dict

from .base import BaseAdapter
from .openalex import OpenAlexAdapter
from .dblp import DblpAdapter, DblpSparqlAdapter
from .scopus import ScopusAdapter
from .webofscience import WebOfScienceAdapter
from .ieee import IeeeAdapter
from .manual_import import ManualImportAdapter


def get_adapter(source: str, protocol: Dict, source_cfg: Dict) -> BaseAdapter:
    mode = source_cfg.get("access_mode")
    if source == "openalex":
        return OpenAlexAdapter(protocol, source_cfg)
    if source == "dblp":
        return DblpSparqlAdapter(protocol, source_cfg)
    if source == "scopus" and mode == "api":
        return ScopusAdapter(protocol, source_cfg)
    if source == "wos" and mode == "api":
        return WebOfScienceAdapter(protocol, source_cfg)
    if source == "ieee" and mode == "api":
        return IeeeAdapter(protocol, source_cfg)
    # every other source, and every licensed source without a confirmed API entitlement
    return ManualImportAdapter(source, protocol, source_cfg)
