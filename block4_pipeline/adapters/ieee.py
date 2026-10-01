"""IEEE Xplore adapter: official Metadata Search API (developer.ieee.org, read 30 Sep 2026).

- `GET https://ieeexploreapi.ieee.org/api/v1/search/articles?apikey=...&querytext=...&format=json
  &max_records=200&start_record=N&sort_field=article_number&sort_order=asc`
- `querytext` accepts AND / OR / NOT (uppercase), quoted phrases and parentheses, but
  **at most two wildcard words per query**, each with at least three characters before `*`.
- `max_records` at most 200; `start_record` is 1-based. Sorting only by article_number,
  article_title or publication_title (no date sort): the pipeline orders by article number,
  IEEE's own identifier, which is deterministic. Ordering has no role in inclusion.
- Free (non-subscriber) keys: 200 calls per day, 10 per second.
- Response: `total_records`, `total_searched`, `articles[]` with title, abstract, authors.authors[]
  (full_name, author_order, id), publication_title, publication_year, publication_date, doi,
  article_number, content_type, isbn/issn, citing_paper_count, html_url, pdf_url, index_terms.

Wildcard limit and the bank: 12 of the 19 mandatory IEEE forms carry 3-6 wildcard words. Such a
query is not sent as one request. `decompose_for_wildcards` rewrites it into an exactly
equivalent set of requests, each with at most two wildcard words, by distributing OR over AND
(the union of the parts' results is the original result set; no term is added or removed).
The threshold rule is then applied to the size of the union, which is only known after all
parts are retrieved; every part's count is logged. Recorded as a deviation.

The key comes from IEEE_API_KEY (env or .env). It is sent as a URL parameter because the API
offers no header form; every logged URL and request has it redacted.
"""
from __future__ import annotations

import itertools
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import secrets
from .base import BaseAdapter, CountResult, PageResult, RetrievalOutcome, DONE, REFINEMENT_REQUIRED, empty_record, normalize_doi

IEEE_SEARCH_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
MAX_WILDCARD_WORDS = 2
_WILDCARD_WORD = re.compile(r"[\w\-]+\*")


# ----------------------------------------------------------------------------- Boolean helpers

def _split_top_level(expr: str, op: str) -> List[str]:
    parts, depth, in_quote, i, start = [], 0, False, 0, 0
    token = " %s " % op
    while i < len(expr):
        ch = expr[i]
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and expr.startswith(token, i):
                parts.append(expr[start:i].strip()); i += len(token); start = i
                continue
        i += 1
    parts.append(expr[start:].strip())
    return parts


def _strip_parens(s: str) -> str:
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        depth, ok = 0, True
        for i, ch in enumerate(s):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0 and i != len(s) - 1:
                ok = False
                break
        if not ok:
            break
        s = s[1:-1].strip()
    return s


def count_wildcard_words(expr: str) -> int:
    return len(_WILDCARD_WORD.findall(expr))


def decompose_for_wildcards(expr: str, limit: int = MAX_WILDCARD_WORDS) -> List[str]:
    """Return queries, each with at most `limit` wildcard words, whose OR-union equals `expr`.

    Method: take the top-level AND groups; in every group that carries wildcards, separate the
    alternatives into wildcard-free ones (kept together as one chunk) and one chunk per
    wildcard alternative. Start from the finest combination of chunks (one per group), then
    merge any two parts that differ in exactly one group by OR-ing that group's chunks, as long
    as the merged part stays within the limit. Each merge is an exact Boolean identity
    (distribution of OR over AND), so the union of the final parts equals the original query.
    A single alternative that alone exceeds the limit is kept as is and will be rejected by
    the API, which the run reports."""
    if count_wildcard_words(expr) <= limit:
        return [expr]
    groups = _split_top_level(_strip_parens(expr), "AND")
    per_group: List[List[str]] = []
    for g in groups:
        alts = _split_top_level(_strip_parens(g), "OR")
        if count_wildcard_words(g) == 0 or len(alts) == 1:
            per_group.append([_strip_parens(g)])
            continue
        free = [_strip_parens(a) for a in alts if count_wildcard_words(a) == 0]
        wild = [_strip_parens(a) for a in alts if count_wildcard_words(a) > 0]
        chunks = ([" OR ".join(free)] if free else []) + wild
        per_group.append(chunks)
    # parts as tuples of chunk-sets (one set per group)
    parts: List[List[frozenset]] = [[frozenset([c]) for c in combo] for combo in itertools.product(*per_group)]

    def render(part: List[frozenset]) -> str:
        return " AND ".join("(%s)" % " OR ".join(sorted(cs, key=lambda c: per_group[i].index(c))) for i, cs in enumerate(part))

    merged = True
    while merged:
        merged = False
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                a, b = parts[i], parts[j]
                diff = [k for k in range(len(a)) if a[k] != b[k]]
                if len(diff) != 1:
                    continue
                k = diff[0]
                cand = list(a)
                cand[k] = a[k] | b[k]
                if count_wildcard_words(render(cand)) <= limit:
                    parts[i] = cand
                    del parts[j]
                    merged = True
                    break
            if merged:
                break
    return [render(p) for p in parts]


# ----------------------------------------------------------------------------- daily call budget

class IeeeQuotaExhausted(RuntimeError):
    pass


def _budget_tick(budget: int) -> None:
    """Count today's calls in data/logs/ieee_calls_<UTC date>.json and refuse beyond the budget,
    so a run never burns the key's 200 calls per day; the run resumes the next day."""
    import json
    from datetime import datetime, timezone
    from .. import paths
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    f = paths.logs_dir() / ("ieee_calls_%s.json" % day)
    n = 0
    if f.exists():
        try:
            n = int(json.loads(f.read_text()).get("calls", 0))
        except Exception:
            n = 0
    if n >= budget:
        raise IeeeQuotaExhausted("IEEE daily call budget reached (%d of %d on %s); resume tomorrow" % (n, budget, day))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"day": day, "calls": n + 1}))


# ----------------------------------------------------------------------------- adapter

class IeeeAdapter(BaseAdapter):
    name = "ieee"

    def __init__(self, protocol: Dict[str, Any], source_cfg: Dict[str, Any]):
        super().__init__(protocol, source_cfg)
        self.url = protocol.get("ieee_api_base", IEEE_SEARCH_URL)
        self.page_size = int(protocol.get("ieee_page_size", 200))
        self.sort_field = protocol.get("ieee_sort_field", "article_number")
        self.min_interval_s = 0.5
        self.calls_made = 0

    def supports_api(self) -> bool:
        return True

    def _params(self, querytext: str, max_records: int, start_record: int) -> Dict[str, Any]:
        p = {"querytext": querytext, "format": "json", "max_records": max_records,
             "start_record": start_record, "sort_field": self.sort_field, "sort_order": "asc"}
        key = secrets.get_secret("IEEE_API_KEY")
        if key:
            p["apikey"] = key
        return p

    def describe_request(self, exact_query: str, **kwargs) -> Dict[str, Any]:
        parts = decompose_for_wildcards(exact_query)
        return {"method": "GET", "url": self.url, "parts": len(parts),
                "params_per_part": [secrets.redact_obj(self._params(p, self.page_size, 1)) for p in parts]}

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.calls_made += 1
        _budget_tick(int(self.protocol.get("ieee_daily_call_budget", 190)))
        resp = self._request("GET", self.url, params=params,
                             headers={"Accept": "application/json", "User-Agent": "block4_pipeline (SAMP RQ4.2 systematic search)"})
        if resp.status_code != 200:
            raise RuntimeError("IEEE returned HTTP %d: %s" % (resp.status_code, secrets.redact_text(resp.text[:400])))
        data = resp.json()
        if isinstance(data, dict) and "articles" not in data and data.get("total_records") in (None, 0) and "error" in str(data).lower():
            raise RuntimeError("IEEE error: %s" % secrets.redact_text(str(data)[:400]))
        return data

    @staticmethod
    def _total(data: Dict[str, Any]) -> int:
        for k in ("total_records", "totalfound"):
            if k in data:
                return int(data[k] or 0)
        return 0

    def count(self, exact_query: str, **kwargs) -> CountResult:
        """Count of one *request*; for a decomposed query the per-part counts are summed as an
        upper bound (parts can overlap), and the exact union size is known after retrieval."""
        parts = decompose_for_wildcards(exact_query)
        raws, total, reqs = [], 0, []
        for p in parts:
            params = self._params(p, 1, 1)
            data = self._get(params)
            raws.append({"part": p, "response": data})
            total += self._total(data)
            reqs.append(secrets.redact_obj(params))
        return CountResult(count=total, raw={"parts": raws, "upper_bound_sum": total, "n_parts": len(parts)},
                           request={"method": "GET", "url": self.url, "params": reqs})

    def pages(self, exact_query: str, **kwargs) -> Iterator[PageResult]:
        """Pages of all parts in sequence; each page's request records which part it belongs to.
        Duplicates across parts are collapsed later by deduplication (same article_number)."""
        page_no = 0
        for pi, part in enumerate(decompose_for_wildcards(exact_query), 1):
            start = 1
            while True:
                page_no += 1
                params = self._params(part, self.page_size, start)
                data = self._get(params)
                records = self.records_in_raw(data)
                yield PageResult(page_number=page_no, raw=data, records=records,
                                 request=secrets.redact_obj({"method": "GET", "url": self.url, "params": params, "part": pi}))
                if not records or start + len(records) > self._total(data):
                    break
                start += len(records)

    def retrieve(self, exact_query: str, threshold: int, **kwargs) -> RetrievalOutcome:
        c = self.count(exact_query, **kwargs)
        outcome = RetrievalOutcome(status=DONE, exact_query=exact_query, count=c.count, count_raw=c.raw, count_request=c.request)
        if c.count > threshold:
            outcome.status = REFINEMENT_REQUIRED
            outcome.note = "sum of part counts %d exceeds threshold %d (upper bound of the union); nothing retrieved" % (c.count, threshold)
            return outcome
        seen = set()
        for page in self.pages(exact_query, **kwargs):
            # keep the union: drop records already seen in an earlier part
            fresh = [r for r in page.records if self.source_record_id(r) not in seen]
            seen.update(self.source_record_id(r) for r in fresh)
            page.records = fresh
            outcome.pages.append(page)
        outcome.count = len(seen)
        outcome.note = "union of %d part(s); sum of part counts %d" % (c.raw["n_parts"], c.raw["upper_bound_sum"])
        return outcome

    # --- raw handling -----------------------------------------------------------------
    def records_in_raw(self, raw: Any) -> List[Any]:
        return list((raw or {}).get("articles") or [])

    def source_record_id(self, raw_record: Any) -> Optional[str]:
        n = raw_record.get("article_number")
        return str(n) if n is not None else None

    def normalize_record(self, a: Dict[str, Any]) -> Dict[str, Any]:
        rec = empty_record(self.name)
        rec["source_record_id"] = self.source_record_id(a)
        rec["doi"] = normalize_doi(a.get("doi"))
        rec["title"] = a.get("title")
        authors = ((a.get("authors") or {}).get("authors")) or []
        rec["authors"] = [{"name": x.get("full_name"), "id": str(x.get("id")) if x.get("id") is not None else None}
                          for x in sorted(authors, key=lambda x: x.get("author_order", 0))]
        year = a.get("publication_year")
        rec["year"] = int(year) if year and str(year).isdigit() else None
        date = a.get("publication_date")
        rec["publication_date"] = _iso_date(date, rec["year"])
        rec["venue"] = a.get("publication_title")
        rec["venue_issn"] = a.get("issn")
        rec["type"] = a.get("content_type")
        rec["abstract"] = a.get("abstract")
        cited = a.get("citing_paper_count")
        rec["cited_by_count"] = int(cited) if cited not in (None, "") else None
        rec["url"] = a.get("html_url")
        rec["source_note"] = "IEEE Xplore Metadata API; language not provided"
        return rec


def _iso_date(date: Optional[str], year: Optional[int]) -> Optional[str]:
    """IEEE dates look like '15 March 2020', 'March 2020', '2020', or 'Nov.-Dec. 2019'."""
    if not date and year:
        return "%d-01-01" % year
    if not date:
        return None
    months = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
    m = re.search(r"(\d{1,2})?\s*([A-Za-z]{3})[A-Za-z.]*\s*(\d{4})", date)
    if m and m.group(2).lower() in months:
        day = int(m.group(1)) if m.group(1) else 1
        return "%s-%02d-%02d" % (m.group(3), months[m.group(2).lower()], day)
    y = re.search(r"(19|20)\d{2}", date)
    return "%s-01-01" % y.group(0) if y else ("%d-01-01" % year if year else None)
