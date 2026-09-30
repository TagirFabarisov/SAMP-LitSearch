"""DBLP adapters.

Two record shapes exist for DBLP:

1. `DblpSparqlAdapter` (the retrieval path since 30 Sep 2026, deviation entry 7): the canonical
   Boolean of a query is evaluated over DBLP **titles** through DBLP's official SPARQL endpoint
   (https://sparql.dblp.org/sparql, QLever). Why: dblp.org's search API sits behind a browser
   bot-check page, and its query syntax cannot express the bank's short forms anyway (the `|`
   joins only adjacent single words, quotes are dropped, every word is a prefix term; all 15
   answers Tagir fetched by hand were empty). The SPARQL route is meant for programs and gives
   exact Boolean control.

   Adaptation (closest equivalent): the OpenAlex form of the query (which already spells out
   organi?ation and quotes wildcards) is translated term by term: a quoted phrase or word,
   with or without trailing `*`, becomes CONTAINS(lower(title), "phrase") — so truncation is a
   prefix and a bare word is a substring (slightly wider than a word match; screening handles
   that). AND / OR / parentheses map to && / || / ( ). Titles only, as DBLP's own search.
   Order: year, then record IRI. Count first (threshold rule), then one page of all records.

2. `DblpAdapter`: the record shape of the JSON search API (`format=json`), kept for
   `import-manual --format dblp_json` of answers a person fetched in a browser.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import secrets
from .base import BaseAdapter, CountResult, PageResult, empty_record, normalize_doi

SPARQL_ENDPOINT = "https://sparql.dblp.org/sparql"
PREFIXES = ("PREFIX dblp: <https://dblp.org/rdf/schema#>\n")


# ----------------------------------------------------------------------------- Boolean -> SPARQL

_TOKEN = re.compile(r'\s*(\(|\)|AND\b|OR\b|"[^"]*"|[^\s()]+)', re.S)


def boolean_to_sparql_filter(expr: str, var: str = "?l") -> str:
    """Translate the bank's Boolean (quoted phrases, `*` truncation, AND/OR, parentheses) into a
    SPARQL FILTER expression over the lower-cased title bound to `var`."""
    e = expr.strip()
    m = re.match(r"^(?:works where\s+)?title_and_abstract has\s*\((.*)\)\s*$", e, re.S)
    if m:
        e = m.group(1)
    out: List[str] = []
    pos = 0
    while pos < len(e):
        m = _TOKEN.match(e, pos)
        if not m:
            break
        tok = m.group(1)
        pos = m.end()
        if tok == "(" or tok == ")":
            out.append(tok)
        elif tok == "AND":
            out.append("&&")
        elif tok == "OR":
            out.append("||")
        else:
            term = tok.strip('"').rstrip("*").strip().lower().replace('"', "").replace("\\", "")
            if not term:
                continue
            out.append('CONTAINS(%s, "%s")' % (var, term))
    return " ".join(out)


# ----------------------------------------------------------------------------- SPARQL adapter

class DblpSparqlAdapter(BaseAdapter):
    name = "dblp"

    def __init__(self, protocol: Dict[str, Any], source_cfg: Dict[str, Any]):
        super().__init__(protocol, source_cfg)
        self.endpoint = protocol.get("dblp_sparql_endpoint", SPARQL_ENDPOINT)
        self.max_rows = int(protocol.get("dblp_sparql_max_rows", 1000))
        self.min_interval_s = 1.0

    def supports_api(self) -> bool:
        return True

    def exact_query(self, query: Dict[str, Any]) -> str:
        """The exact SPARQL filter derived from the OpenAlex (canonical) form; the full SPARQL
        text is recorded in the run's request.json."""
        return boolean_to_sparql_filter(str(query["openalex_oql"]))

    def _count_query(self, flt: str) -> str:
        return PREFIXES + ("SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?p dblp:title ?t . "
                           "BIND(LCASE(STR(?t)) AS ?l) FILTER(%s) }" % flt)

    def _select_query(self, flt: str) -> str:
        return PREFIXES + ('''SELECT ?p ?t ?y ?doi ?venue ?type (GROUP_CONCAT(?name; SEPARATOR="; ") AS ?authors) WHERE {
  ?p dblp:title ?t . BIND(LCASE(STR(?t)) AS ?l) FILTER(%s)
  OPTIONAL { ?p dblp:yearOfPublication ?y }
  OPTIONAL { ?p dblp:doi ?doi }
  OPTIONAL { ?p dblp:publishedIn ?venue }
  OPTIONAL { ?p dblp:bibtexType ?type }
  OPTIONAL { ?p dblp:authoredBy ?a . ?a dblp:primaryCreatorName ?name }
} GROUP BY ?p ?t ?y ?doi ?venue ?type ORDER BY ?y ?p LIMIT %d''' % (flt, self.max_rows))

    def describe_request(self, exact_query: str, **kwargs) -> Dict[str, Any]:
        return {"method": "GET", "url": self.endpoint, "params": {"query": self._select_query(exact_query)},
                "count_query": self._count_query(exact_query)}

    def _run(self, sparql: str) -> Dict[str, Any]:
        resp = self._request("GET", self.endpoint, params={"query": sparql},
                             headers={"Accept": "application/sparql-results+json",
                                      "User-Agent": "block4_pipeline (SAMP RQ4.2 systematic search)"})
        if resp.status_code != 200:
            raise RuntimeError("DBLP SPARQL returned HTTP %d: %s" % (resp.status_code, secrets.redact_text(resp.text[:400])))
        return resp.json()

    def count(self, exact_query: str, **kwargs) -> CountResult:
        sparql = self._count_query(exact_query)
        data = self._run(sparql)
        rows = (data.get("results") or {}).get("bindings") or []
        n = int(rows[0]["n"]["value"]) if rows else 0
        return CountResult(count=n, raw=data, request={"method": "GET", "url": self.endpoint, "params": {"query": sparql}})

    def pages(self, exact_query: str, **kwargs) -> Iterator[PageResult]:
        sparql = self._select_query(exact_query)
        data = self._run(sparql)
        yield PageResult(page_number=1, raw=data, records=self.records_in_raw(data),
                         request={"method": "GET", "url": self.endpoint, "params": {"query": sparql}})

    def records_in_raw(self, raw: Any) -> List[Any]:
        return list(((raw or {}).get("results") or {}).get("bindings") or [])

    @staticmethod
    def _v(row: Dict[str, Any], key: str) -> Optional[str]:
        v = row.get(key)
        return v.get("value") if isinstance(v, dict) else None

    def source_record_id(self, raw_record: Any) -> Optional[str]:
        p = self._v(raw_record, "p")
        return p.split("/rec/", 1)[1] if p and "/rec/" in p else p

    def normalize_record(self, row: Dict[str, Any]) -> Dict[str, Any]:
        rec = empty_record(self.name)
        rec["source_record_id"] = self.source_record_id(row)
        rec["doi"] = normalize_doi(self._v(row, "doi"))
        rec["title"] = (self._v(row, "t") or "").rstrip(".") or None
        authors = self._v(row, "authors") or ""
        rec["authors"] = [{"name": a.strip(), "id": None} for a in authors.split(";") if a.strip()]
        y = self._v(row, "y")
        rec["year"] = int(y) if y and y.isdigit() else None
        rec["publication_date"] = "%d-01-01" % rec["year"] if rec["year"] else None
        rec["venue"] = self._v(row, "venue")
        t = self._v(row, "type")
        rec["type"] = t.rsplit("#", 1)[-1] if t else None
        rec["url"] = self._v(row, "p")
        rec["source_note"] = "DBLP via SPARQL over titles (deviation 7); no abstract; publication_date is the year only"
        return rec


# ----------------------------------------------------------------------------- search-API record shape (import only)

class DblpAdapter(BaseAdapter):
    """Record shape of the dblp.org JSON search API; used only to normalize imported answers."""
    name = "dblp"

    def supports_api(self) -> bool:
        return False

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
