"""Common adapter interface.

An adapter either retrieves through an official API (`supports_api()` is true) or
reports MANUAL_EXPORT_REQUIRED; in both cases it maps raw records to the common
schema and knows where the records sit inside a raw file.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from .. import secrets

MANUAL_EXPORT_REQUIRED = "MANUAL_EXPORT_REQUIRED"
REFINEMENT_REQUIRED = "REFINEMENT_REQUIRED"
DONE = "done"
FAILED = "failed"

# Common document schema. Every adapter returns exactly these keys from normalize_record.
COMMON_FIELDS = (
    "source",
    "source_record_id",
    "doi",
    "openalex_id",
    "title",
    "authors",           # list of {"name": str, "id": str|None}
    "year",
    "publication_date",  # ISO date string or None
    "venue",
    "venue_issn",
    "type",
    "abstract",
    "language",
    "cited_by_count",
    "url",
    "source_note",
)


def empty_record(source: str) -> Dict[str, Any]:
    rec: Dict[str, Any] = {k: None for k in COMMON_FIELDS}
    rec["source"] = source
    rec["authors"] = []
    return rec


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = str(doi).strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:", "doi "):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.strip()
    return d or None


@dataclass
class CountResult:
    count: int
    raw: Any
    request: Dict[str, Any]


@dataclass
class PageResult:
    page_number: int
    raw: Any
    records: List[Any]
    request: Dict[str, Any]
    next_cursor: Optional[str] = None


@dataclass
class RetrievalOutcome:
    status: str
    exact_query: str
    count: int
    count_raw: Any = None
    count_request: Dict[str, Any] = field(default_factory=dict)
    pages: List[PageResult] = field(default_factory=list)
    note: str = ""


class BaseAdapter:
    name = "base"

    def __init__(self, protocol: Dict[str, Any], source_cfg: Dict[str, Any]):
        self.protocol = protocol
        self.cfg = source_cfg
        self.session = requests.Session()
        self.min_interval_s = 0.15  # polite pacing between requests
        self._last_request = 0.0

    # --- capability --------------------------------------------------------
    def supports_api(self) -> bool:
        return False

    def query_field(self) -> str:
        return self.cfg.get("query_field", self.name)

    def exact_query(self, query: Dict[str, Any]) -> str:
        """The string exactly as it is sent to the source (recorded in the search log)."""
        return str(query[self.query_field()])

    # --- request description (dry run) -------------------------------------
    def describe_request(self, exact_query: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

    # --- retrieval -----------------------------------------------------------
    def count(self, exact_query: str, **kwargs) -> CountResult:
        raise NotImplementedError

    def pages(self, exact_query: str, **kwargs):
        """Yield PageResult objects in the source's deterministic order."""
        raise NotImplementedError

    def retrieve(self, exact_query: str, threshold: int, **kwargs) -> RetrievalOutcome:
        c = self.count(exact_query, **kwargs)
        outcome = RetrievalOutcome(
            status=DONE, exact_query=exact_query, count=c.count, count_raw=c.raw, count_request=c.request
        )
        if c.count > threshold:
            outcome.status = REFINEMENT_REQUIRED
            outcome.note = "count %d exceeds threshold %d; nothing retrieved" % (c.count, threshold)
            return outcome
        for page in self.pages(exact_query, **kwargs):
            outcome.pages.append(page)
        return outcome

    # --- raw file handling ----------------------------------------------------
    def records_in_raw(self, raw: Any) -> List[Any]:
        """Return the list of records contained in one raw page/file object."""
        raise NotImplementedError

    def source_record_id(self, raw_record: Any) -> Optional[str]:
        raise NotImplementedError

    def normalize_record(self, raw_record: Any) -> Dict[str, Any]:
        raise NotImplementedError

    # --- HTTP helpers -----------------------------------------------------------
    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_request = time.monotonic()

    def _request(self, method: str, url: str, retries: int = 5, **kwargs) -> requests.Response:
        """HTTP request with retry on 429 and 5xx. Never logs the key."""
        delay = 2.0
        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            self._pace()
            try:
                resp = self.session.request(method, url, timeout=60, **kwargs)
            except requests.RequestException as exc:  # network problem
                last_exc = exc
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                time.sleep(wait)
                delay *= 2
                last_exc = RuntimeError("HTTP %d from %s" % (resp.status_code, secrets.redact_text(url)))
                continue
            return resp
        raise RuntimeError("request failed after %d attempts: %s" % (retries, secrets.redact_text(str(last_exc))))
