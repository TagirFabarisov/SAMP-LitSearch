"""Append-only JSONL stores, write-once raw files with checksums, and ID allocation."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)


def write_raw_once(path: Path, obj: Any) -> str:
    """Write a raw evidence file exactly once and return its sha256.

    Raising on an existing path is deliberate: raw evidence is never overwritten.
    """
    if path.exists():
        raise FileExistsError("raw file already exists, refusing to overwrite: %s" % path)
    write_json(path, obj)
    return sha256_file(path)


def write_manifest(run_dir: Path, entries: Dict[str, str], extra: Optional[Dict[str, Any]] = None) -> None:
    manifest = {"files": entries, "written_at": utc_now()}
    if extra:
        manifest.update(extra)
    write_json(run_dir / "manifest.json", manifest)


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.exists():
        return iter(())
    return _iter_jsonl(path)


def _iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def append_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
    return n


def rewrite_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    """Rewrite a derived (not raw) table atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
    os.replace(tmp, path)
    return n


class IdAllocator:
    """Allocates sequential IDs like B4-H00001, continuing from the highest ID already in use."""

    def __init__(self, fmt: str, existing: Iterable[str] = ()):
        self.fmt = fmt
        self._prefix, self._width = self._parse(fmt)
        self.counter = 0
        for existing_id in existing:
            n = self.parse_number(existing_id)
            if n is not None and n > self.counter:
                self.counter = n

    @staticmethod
    def _parse(fmt: str):
        m = re.match(r"^(.*)\{:0?(\d+)d\}$", fmt)
        if not m:
            raise ValueError("unsupported ID format: %s" % fmt)
        return m.group(1), int(m.group(2))

    def parse_number(self, id_str: str) -> Optional[int]:
        if not id_str.startswith(self._prefix):
            return None
        tail = id_str[len(self._prefix):]
        return int(tail) if tail.isdigit() else None

    def next(self) -> str:
        self.counter += 1
        return self.fmt.format(self.counter)

    def peek(self) -> str:
        return self.fmt.format(self.counter + 1)


def max_existing_id(path: Path, field: str, fmt: str) -> IdAllocator:
    return IdAllocator(fmt, (row.get(field, "") for row in read_jsonl(path)))
