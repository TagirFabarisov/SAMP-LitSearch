"""DBLP adapter: public publication search API, no key.

`GET https://dblp.org/search/publ/api?q=<query>&format=json&h=<page size>&f=<offset>`.
DBLP matches word prefixes by default, `|` is OR, and it searches titles only.
DBLP has no abstracts; every record carries a `source_note` saying so.
`h=0` returns the total count without records, which is used for the threshold check.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from .. import secrets
from .base import BaseAdapter, CountResult, PageResult, empty_record, normalize_doi


class DblpAdapter(BaseAdapter):
    name = "dblp"

    def __init__(self, protocol: Dict[str, Any], source_cfg: Dict[str, Any]):
        super().__init__(protocol, source_cfg)
        self.base = protocol.get("dblp_api_base", "https://dblp.org/search/publ/api")
        self.page_size = int(protocol.get("dblp_page_size", 1000))
        self.min_interval_s = 1.0  # DBLP asks for gentle use

    def supports_api(self) -> bool:
        return True

    def _params(self, exact_query: str, h: int, f: int) -> Dict[str, Any]:
        return {"q": exact_query, "format": "json", "h": h, "f": f}

    def describe_request(self, exact_query: str, **kwargs) -> Dict[str, Any]:
        return {"method": "GET", "url": self.base, "params": self._params(exact_query, self.page_size, 0)}

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._request("GET", self.base, params=params,
                             headers={"User-Agent": "block4_pipeline (SAMP RQ4.2 systematic search)"})
        if resp.status_code != 200:
            raise RuntimeError("DBLP returned HTTP %d: %s" % (resp.status_code, secrets.redact_text(resp.text[:500])))
        ctype = resp.headers.get("Content-Type", "")
        if "json" not in ctype:
            # Since 2026 dblp.org (and its mirrors) put the search API behind a browser bot-check
            # page ("Making sure you're not a bot"). The pipeline does not try to pass it: the query
            # is run in a browser by a person and the JSON answer imported with
            # `import-manual --format dblp_json` (protocol section 23).
            raise RuntimeError("DBLP answered with %s instead of JSON (bot-check page); use the browser and import-manual --format dblp_json" % ctype)
        return resp.json()

    @staticmethod
    def _total(data: Dict[str, Any]) -> int:
        hits = (data.get("result") or {}).get("hits") or {}
        return int(hits.get("@total", 0))

    def count(self, exact_query: str, **kwargs) -> CountResult:
        params = self._params(exact_query, 0, 0)
        data = self._get(params)
        return CountResult(count=self._total(data), raw=data, request={"method": "GET", "url": self.base, "params": params})

    def pages(self, exact_query: str, **kwargs) -> Iterator[PageResult]:
        offset = 0
        page_no = 0
        while True:
            page_no += 1
            params = self._params(exact_query, self.page_size, offset)
            data = self._get(params)
            records = self.records_in_raw(data)
            yield PageResult(page_number=page_no, raw=data, records=records,
                             request={"method": "GET", "url": self.base, "params": params})
            if not records or offset + len(records) >= self._total(data):
                break
            offset += len(records)

    def records_in_raw(self, raw: Any) -> List[Any]:
        hits = ((raw or {}).get("result") or {}).get("hits") or {}
        return list(hits.get("hit") or [])

    def source_record_id(self, raw_record: Any) -> Optional[str]:
        info = raw_record.get("info") or {}
        return info.get("key") or raw_record.get("@id")

    def normalize_record(self, h: Dict[str, Any]) -> Dict[str, Any]:
        info = h.get("info") or {}
        rec = empty_record(getattr(self, "name", "dblp"))
        rec["source_record_id"] = DblpAdapter.source_record_id(self, h)
        rec["doi"] = normalize_doi(info.get("doi"))
        rec["title"] = (info.get("title") or "").rstrip(".") or None
        authors = (info.get("authors") or {}).get("author") or []
        if isinstance(authors, dict):
            authors = [authors]
        rec["authors"] = [{"name": a.get("text") if isinstance(a, dict) else str(a),
                           "id": a.get("@pid") if isinstance(a, dict) else None} for a in authors]
        year = info.get("year")
        rec["year"] = int(year) if year and str(year).isdigit() else None
        rec["publication_date"] = "%s-01-01" % rec["year"] if rec["year"] else None
        rec["venue"] = info.get("venue")
        rec["type"] = info.get("type")
        rec["url"] = info.get("ee") or info.get("url")
        rec["source_note"] = "DBLP provides no abstract; publication_date is the year only"
        return rec
