"""OpenAlex adapter: OpenAlex Query Language (OQL) executed at the API root.

Mechanics, from the OpenAlex help center (help.openalex.org/api/oql/, /api/searching/,
/api/llm-quick-reference/, read 29 Sep 2026):

- Execution: `POST https://api.openalex.org/` with a JSON body `{"oql": "...", "sort": ...,
  "per_page": ..., "cursor": ...}`; exactly one of "oql" / "oqo". The OQL expression names
  its own entity, so the query bank's `title_and_abstract has (...)` is sent as
  `works where title_and_abstract has (...)` (protocol.yaml: openalex_entity_prefix).
- Invalid expressions return HTTP 400 with a structured `validation` block
  (`errors[].type` in parse_error / bad_request / invalid_entity / invalid_body).
- `GET /validate?q=<oql>` lints an expression without executing it;
  `POST /query` translates between OQL, OQO and the classic URL without executing.
- Every response echoes the query in all three forms in `meta.x_query`.
- Authentication: `Authorization: Bearer <key>` header (never the URL); optional `mailto`.
- Deep paging: `cursor=*` first, then `meta.next_cursor`; `per_page` max 100.

What the documentation does NOT settle, and what the construct check (brief section 1b)
must establish before the bank is run: whether `*` truncation is honoured inside
`has (...)` at all (the classic API honours wildcards only under `search.exact`), whether
it is honoured inside a quoted phrase (`"dependence relation*"`), and whether
`title_and_abstract` is the column OQL expects. See `oql_check.py`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from .. import secrets
from .base import BaseAdapter, CountResult, PageResult, empty_record, normalize_doi


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> Optional[str]:
    """Rebuild the abstract text from OpenAlex's inverted index (word -> positions)."""
    if not inverted_index:
        return None
    positions: List[tuple] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def short_openalex_id(value: Optional[str]) -> Optional[str]:
    """https://openalex.org/W123 -> W123"""
    if not value:
        return None
    return str(value).rsplit("/", 1)[-1]


class OpenAlexAdapter(BaseAdapter):
    name = "openalex"

    def __init__(self, protocol: Dict[str, Any], source_cfg: Dict[str, Any]):
        super().__init__(protocol, source_cfg)
        self.base = protocol.get("openalex_api_base", "https://api.openalex.org").rstrip("/")
        self.page_size = int(protocol.get("openalex_page_size", 100))
        self.order = protocol.get("openalex_order", "publication_date:asc,id:asc")
        self.prefix = protocol.get("openalex_entity_prefix", "works where")
        self.min_interval_s = 0.12  # OpenAlex ceiling is far higher; this keeps us well below it

    def supports_api(self) -> bool:
        return True

    # --- query construction ------------------------------------------------
    def exact_query(self, query: Dict[str, Any]) -> str:
        expr = str(query["openalex_oql"]).strip()
        if expr.lower().startswith("works where"):
            return expr
        return "%s %s" % (self.prefix, expr)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "block4_pipeline (SAMP RQ4.2 systematic search)"}
        key = secrets.get_secret("OPENALEX_API_KEY")
        if key:
            headers["Authorization"] = "Bearer " + key
        return headers

    def _body(self, exact_query: str, per_page: int, cursor: Optional[str], cited_by: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"sort": self.order, "per_page": per_page}
        if cited_by:
            # Forward snowballing: works citing a given work. This is a plain filter, not a text
            # search, so it is expressed in OQL as well (validated by the construct check).
            body["oql"] = "works where cites is (%s)" % short_openalex_id(cited_by)
        else:
            body["oql"] = exact_query
        if cursor is not None:
            body["cursor"] = cursor
        mailto = secrets.get_mailto()
        if mailto:
            body["mailto"] = mailto
        return body

    def describe_request(self, exact_query: str, **kwargs) -> Dict[str, Any]:
        body = self._body(exact_query, self.page_size, "*", kwargs.get("cited_by"))
        headers = dict(self._headers())
        if "Authorization" in headers:
            headers["Authorization"] = "Bearer <REDACTED>"
        return {"method": "POST", "url": self.base + "/", "headers": headers, "json": body}

    # --- retrieval -------------------------------------------------------------
    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._request("POST", self.base + "/", json=body, headers=self._headers())
        if resp.status_code != 200:
            detail = secrets.redact_text(resp.text[:2000])
            raise RuntimeError("OpenAlex returned HTTP %d: %s" % (resp.status_code, detail))
        return resp.json()

    def count(self, exact_query: str, **kwargs) -> CountResult:
        body = self._body(exact_query, 1, None, kwargs.get("cited_by"))
        data = self._post(body)
        count = int(data.get("meta", {}).get("count", 0))
        return CountResult(count=count, raw=data, request=secrets.redact_obj(self.describe_request(exact_query, **kwargs) | {"json": body}))

    def pages(self, exact_query: str, **kwargs) -> Iterator[PageResult]:
        cursor: Optional[str] = "*"
        page_no = 0
        while cursor:
            page_no += 1
            body = self._body(exact_query, self.page_size, cursor, kwargs.get("cited_by"))
            data = self._post(body)
            records = data.get("results", [])
            next_cursor = data.get("meta", {}).get("next_cursor")
            yield PageResult(page_number=page_no, raw=data, records=records,
                             request=secrets.redact_obj({"method": "POST", "url": self.base + "/", "json": body}),
                             next_cursor=next_cursor)
            if not records:
                break
            cursor = next_cursor

    # --- OQL checks (no execution) --------------------------------------------------
    def validate_expression(self, oql: str) -> Dict[str, Any]:
        """GET /validate?q=<oql>: lint only, no retrieval."""
        resp = self._request("GET", self.base + "/validate", params={"q": oql}, headers=self._headers())
        try:
            return {"http_status": resp.status_code, "body": resp.json()}
        except ValueError:
            return {"http_status": resp.status_code, "body": secrets.redact_text(resp.text[:2000])}

    def translate(self, oql: str) -> Dict[str, Any]:
        """POST /query: OQL -> OQO + classic URL, no retrieval. Shows how `*` is interpreted."""
        resp = self._request("POST", self.base + "/query", json={"oql": oql}, headers=self._headers())
        try:
            return {"http_status": resp.status_code, "body": resp.json()}
        except ValueError:
            return {"http_status": resp.status_code, "body": secrets.redact_text(resp.text[:2000])}

    def properties(self) -> Dict[str, Any]:
        """GET /properties/works: the column registry (is `title_and_abstract` a column?)."""
        resp = self._request("GET", self.base + "/properties/works", headers=self._headers())
        try:
            return {"http_status": resp.status_code, "body": resp.json()}
        except ValueError:
            return {"http_status": resp.status_code, "body": secrets.redact_text(resp.text[:2000])}

    # --- raw handling -----------------------------------------------------------------
    def records_in_raw(self, raw: Any) -> List[Any]:
        return list(raw.get("results", [])) if isinstance(raw, dict) else []

    def source_record_id(self, raw_record: Any) -> Optional[str]:
        return short_openalex_id(raw_record.get("id"))

    def normalize_record(self, w: Dict[str, Any]) -> Dict[str, Any]:
        rec = empty_record(self.name)
        rec["source_record_id"] = short_openalex_id(w.get("id"))
        rec["openalex_id"] = rec["source_record_id"]
        rec["doi"] = normalize_doi(w.get("doi"))
        rec["title"] = w.get("display_name") or w.get("title")
        rec["authors"] = [
            {"name": (a.get("author") or {}).get("display_name"),
             "id": short_openalex_id((a.get("author") or {}).get("id"))}
            for a in (w.get("authorships") or [])
        ]
        rec["year"] = w.get("publication_year")
        rec["publication_date"] = w.get("publication_date")
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        rec["venue"] = src.get("display_name")
        rec["venue_issn"] = src.get("issn_l") or (src.get("issn") or [None])[0]
        rec["type"] = w.get("type")
        rec["abstract"] = reconstruct_abstract(w.get("abstract_inverted_index"))
        rec["language"] = w.get("language")
        rec["cited_by_count"] = w.get("cited_by_count")
        rec["url"] = w.get("id")
        return rec
