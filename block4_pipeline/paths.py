"""Locations of configuration and data files.

Everything lives under the package directory unless BLOCK4_DATA_DIR overrides the
data root (useful for tests, which must never touch real data).
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = PACKAGE_DIR / "config"


def data_dir() -> Path:
    override = os.environ.get("BLOCK4_DATA_DIR")
    return Path(override).resolve() if override else PACKAGE_DIR / "data"


def raw_dir() -> Path:
    return data_dir() / "raw"


def normalized_dir() -> Path:
    return data_dir() / "normalized"


def exports_dir() -> Path:
    return data_dir() / "exports"


def logs_dir() -> Path:
    return data_dir() / "logs"


def imports_dir() -> Path:
    """Where the user drops manual exports before importing them (kept as raw evidence)."""
    return data_dir() / "raw" / "manual_exports"


def ensure_dirs() -> None:
    for d in (raw_dir(), normalized_dir(), exports_dir(), logs_dir()):
        d.mkdir(parents=True, exist_ok=True)


QUERIES_FILE = CONFIG_DIR / "queries.yaml"
SOURCES_FILE = CONFIG_DIR / "sources.yaml"
PROTOCOL_FILE = CONFIG_DIR / "protocol.yaml"
DENYLIST_FILE = CONFIG_DIR / "denylist.txt"


def search_log_file() -> Path:
    return logs_dir() / "search_log.jsonl"


def deviation_log_file() -> Path:
    return logs_dir() / "deviations.jsonl"


def hits_file() -> Path:
    return normalized_dir() / "hits.jsonl"


def records_file() -> Path:
    return normalized_dir() / "records.jsonl"


def documents_file() -> Path:
    return normalized_dir() / "documents.jsonl"


def hit_document_map_file() -> Path:
    return normalized_dir() / "hit_to_document.jsonl"


def status_file() -> Path:
    return logs_dir() / "status.json"
