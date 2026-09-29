"""Scopus adapter: official Scopus Search API (Elsevier).

From dev.elsevier.com (ScopusSearchAPI.wadl, api_key_settings, sc_search_tips; read 29 Sep 2026):

- `GET https://api.elsevier.com/content/search/scopus?query=...&view=COMPLETE&count=25&start=N&sort=...`
  headers `X-ELS-APIKey`, `Accept: application/json`. The query is the bank's `scopus` form
  (`TITLE-ABS-KEY( ... )`) unchanged: Scopus supports `*` and `?` (3 characters minimum before
  a wildcard) and loose phrases in double quotes (plurals included, punctuation ignored).
- `view=COMPLETE` returns abstracts (`dc:description`) and the author list, at most 25 per
  request; `view=STANDARD` allows 200 per request but no abstract. COMPLETE needs the
  institution's subscription, which Elsevier checks by network address (campus or VPN)
  or an institutional token (`X-ELS-Insttoken`). Without it the API answers 401/403.
- Quota: 20,000 requests per week, 9 per second. The bank needs about 700 requests.
- Paging by `start` offset (5,000-record limit without cursor paging, irrelevant at a
  300-record threshold). Ordering: `sort=+coverDate` (ascending publication date); Scopus
  offers no secondary key equivalent to the OpenAlex work ID. Ordering has no role in
  inclusion because every result at or below the threshold is retrieved.
- An empty result set comes back as one `entry` carrying `"error": "Result set was empty"`.

The key comes from SCOPUS_API_KEY (env or .env), never from code or config.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from .. import secrets
from .base import BaseAdapter, CountResult, PageResult, empty_record, normalize_doi

SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"


class ScopusEntitlementError(RuntimeError):
    pass


class ScopusAdapter(BaseAdapter):
    name = "scopus"

    def __init__(self, protocol: Dict[str, Any], source_cfg: Dict[str, Any]):
        super().__init__(protocol, source_cfg)
        self.url = protocol.get("scopus_api_base", SCOPUS_SEARCH_URL)
        self.page_size = int(protocol.get("scopus_page_size", 25))   # COMPLETE view maximum
        self.view = protocol.get("scopus_view", "COMPLETE")
        self.order = protocol.get("scopus_order", "+coverDate")
        self.min_interval_s = 0.2   # well under Elsevier's 9 requests per second

    def supports_api(self) -> bool:
        return True

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json",
                   "User-Agent": "block4_pipeline (SAMP RQ4.2 systematic search)"}
        key = secrets.get_secret("SCOPUS_API_KEY")
        if key:
            headers["X-ELS-APIKey"] = key
        inst = secrets.get_secret("SCOPUS_INST_TOKEN")
        if inst:
            headers["X-ELS-Insttoken"] = inst
        return headers

    def _params(self, exact_query: str, count: int, start: int, view: Optional[str] = None) -> Dict[str, Any]:
        return {"query": exact_query, "view": view or self.view, "count": count, "start": start, "sort": self.order}

    def describe_request(self, exact_query: str, **kwargs) -> Dict[str, Any]:
        headers = dict(self._headers())
        for h in ("X-ELS-APIKey", "X-ELS-Insttoken"):
            if h in headers:
                headers[h] = "<REDACTED>"
        return {"method": "GET", "url": self.url, "headers": headers,
                "params": self._params(exact_query, self.page_size, 0)}

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._request("GET", self.url, params=params, headers=self._headers())
        if resp.status_code in (401, 403):
            raise ScopusEntitlementError(
                "Scopus returned HTTP %d: %s. The COMPLETE view needs the institution's subscription; "
                "run from the Uni.lu network or VPN, or check the key." % (resp.status_code, secrets.redact_text(resp.text[:400])))
        if resp.status_code != 200:
            raise RuntimeError("Scopus returned HTTP %d: %s" % (resp.status_code, secrets.redact_text(resp.text[:400])))
        return resp.json()

    @staticmethod
    def _total(data: Dict[str, Any]) -> int:
        return int((data.get("search-results") or {}).get("opensearch:totalResults", 0))

    def count(self, exact_query: str, **kwargs) -> CountResult:
        # STANDARD view, one record: the cheapest way to read the total (count=0 is not documented)
        params = self._params(exact_query, 1, 0, view="STANDARD")
        data = self._get(params)
        return CountResult(count=self._total(data), raw=data,
                           request={"method": "GET", "url": self.url, "params": params})

    def pages(self, exact_query: str, **kwargs) -> Iterator[PageResult]:
        start = 0
        page_no = 0
        while True:
            page_no += 1
            params = self._params(exact_query, self.page_size, start)
            data = self._get(params)
            records = self.records_in_raw(data)
            yield PageResult(page_number=page_no, raw=data, records=records,
                             request={"method": "GET", "url": self.url, "params": params})
            if not records or start + len(records) >= self._total(data):
                break
            start += len(records)

    def entitlement_probe(self, query: str = 'TITLE-ABS-KEY("resource dependence")') -> Dict[str, Any]:
        """One COMPLETE-view request for a single record: shows whether the subscription applies
        from the current network (abstract present) or not (401/403)."""
        params = self._params(query, 1, 0, view="COMPLETE")
        resp = self._request("GET", self.url, params=params, headers=self._headers())
        out: Dict[str, Any] = {"http_status": resp.status_code, "params": params}
        try:
            body = resp.json()
        except ValueError:
            body = secrets.redact_text(resp.text[:1000])
        out["body"] = body
        if resp.status_code == 200 and isinstance(body, dict):
            entries = self.records_in_raw(body)
            out["total"] = self._total(body)
            out["abstract_present"] = bool(entries and entries[0].get("dc:description"))
            out["authors_present"] = bool(entries and entries[0].get("author"))
        return out

    # --- raw handling ---------------------------------------------------------------
    def records_in_raw(self, raw: Any) -> List[Any]:
        entries = ((raw or {}).get("search-results") or {}).get("entry") or []
        return [e for e in entries if isinstance(e, dict) and "error" not in e]

    def source_record_id(self, raw_record: Any) -> Optional[str]:
        return raw_record.get("eid") or raw_record.get("dc:identifier")

    def normalize_record(self, e: Dict[str, Any]) -> Dict[str, Any]:
        rec = empty_record(self.name)
        rec["source_record_id"] = self.source_record_id(e)
        rec["doi"] = normalize_doi(e.get("prism:doi"))
        rec["title"] = e.get("dc:title")
        authors = e.get("author") or []
        if isinstance(authors, dict):
            authors = [authors]
        if authors:
            rec["authors"] = [{"name": a.get("authname") or " ".join(filter(None, [a.get("given-name"), a.get("surname")])),
                               "id": a.get("authid")} for a in authors]
        elif e.get("dc:creator"):
            rec["authors"] = [{"name": e["dc:creator"], "id": None}]
        date = e.get("prism:coverDate")
        rec["publication_date"] = date
        rec["year"] = int(date[:4]) if date and date[:4].isdigit() else None
        rec["venue"] = e.get("prism:publicationName")
        rec["venue_issn"] = e.get("prism:issn") or e.get("prism:eIssn")
        rec["type"] = e.get("subtypeDescription") or e.get("subtype")
        rec["abstract"] = e.get("dc:description")
        cited = e.get("citedby-count")
        rec["cited_by_count"] = int(cited) if cited not in (None, "") else None
        links = e.get("link") or []
        scopus_link = next((l.get("@href") for l in links if l.get("@ref") == "scopus"), None)
        rec["url"] = scopus_link or ("https://www.scopus.com/record/display.uri?eid=%s&origin=api" % e.get("eid") if e.get("eid") else None)
        rec["source_note"] = "Scopus Search API, view %s; language not provided by the search API" % self.view
        return rec
