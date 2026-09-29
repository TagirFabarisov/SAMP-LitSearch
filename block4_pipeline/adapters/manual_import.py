"""Deterministic importer for exports made by hand from a database interface.

Supported formats (chosen by --format, or detected from the file):
  scopus_csv   Scopus "Export CSV" (Authors, Title, Year, Source title, DOI, EID, Abstract, ...)
  wos_tab      Web of Science tab-delimited (AU, TI, PY, SO, DI, UT, AB, LA, DT, ...)
  ieee_csv     IEEE Xplore CSV (Document Title, Authors, Publication Year, DOI, Abstract, ...)
  acm_csv      ACM Digital Library CSV (best-effort column names; verify on first use)
  ris          RIS (TY/AU/TI/PY/T2/DO/AB/UR/LA)
  bibtex       BibTeX (title, author, year, journal|booktitle, doi, abstract, url)
  generic_csv  title, authors, year, venue, url, rank  (Scholar, web, HeinOnline, SSRN)
  openalex_json  a saved OpenAlex works response ({"results": [...]})

The export file is copied unchanged into the raw run folder; the parsed rows are kept
next to it as parsed.json so that normalization can locate every record by index.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseAdapter, MANUAL_EXPORT_REQUIRED, empty_record, normalize_doi
from .openalex import OpenAlexAdapter

FORMATS = ("scopus_csv", "wos_tab", "ieee_csv", "acm_csv", "ris", "bibtex", "generic_csv", "openalex_json")


# ----------------------------------------------------------------------------- parsers

def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_csv(text: str, delimiter: str = ",") -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for i, row in enumerate(reader):
        row = {(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        row["_row"] = i + 1
        rows.append(row)
    return rows


def parse_ris(text: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])\s\s-\s?(.*)$", line)
        if not m:
            continue
        tag, value = m.group(1), m.group(2).strip()
        if tag == "TY":
            current = {"TY": value}
        elif tag == "ER":
            if current:
                current["_row"] = len(records) + 1
                records.append(current)
            current = {}
        else:
            current.setdefault(tag, [])
            if isinstance(current[tag], list):
                current[tag].append(value)
    if current and "TY" in current:
        current["_row"] = len(records) + 1
        records.append(current)
    return records


def parse_bibtex(text: str) -> List[Dict[str, Any]]:
    """Small BibTeX reader: entries `@type{key, field = {value}, ...}`; braces or quotes."""
    records: List[Dict[str, Any]] = []
    pos = 0
    while True:
        at = text.find("@", pos)
        if at < 0:
            break
        m = re.match(r"@(\w+)\s*\{\s*([^,\s]*)\s*,", text[at:])
        if not m:
            pos = at + 1
            continue
        entry_type, key = m.group(1).lower(), m.group(2)
        if entry_type in ("comment", "preamble", "string"):
            pos = at + 1
            continue
        i = at + m.end()
        depth = 1
        start = i
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[start:i - 1]
        fields = {"_type": entry_type, "_key": key}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)", body):
            name = fm.group(1).lower()
            val = fm.group(2).strip()
            if (val.startswith("{") and val.endswith("}")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            fields[name] = re.sub(r"\s+", " ", val.replace("{", "").replace("}", "")).strip()
        fields["_row"] = len(records) + 1
        records.append(fields)
        pos = i
    return records


def detect_format(path: Path, source: str) -> str:
    ext = path.suffix.lower()
    if ext == ".ris":
        return "ris"
    if ext in (".bib", ".bibtex"):
        return "bibtex"
    if ext == ".json":
        return "openalex_json"
    head = _read_text(path)[:4000]
    if ext in (".txt", ".tsv") or "\t" in head.splitlines()[0]:
        return "wos_tab"
    if source == "scopus" or "EID" in head:
        return "scopus_csv"
    if source == "ieee" or "Document Title" in head:
        return "ieee_csv"
    if source == "acm":
        return "acm_csv"
    return "generic_csv"


def parse_export(path: Path, fmt: str) -> List[Dict[str, Any]]:
    if fmt == "openalex_json":
        import json
        return list(json.loads(_read_text(path)).get("results", []))
    text = _read_text(path)
    if fmt == "ris":
        return parse_ris(text)
    if fmt == "bibtex":
        return parse_bibtex(text)
    if fmt == "wos_tab":
        return parse_csv(text, delimiter="\t")
    return parse_csv(text, delimiter=",")


# ----------------------------------------------------------------------------- mapping

def _split_authors(value: Optional[str], sep_regex: str = r";|\band\b") -> List[Dict[str, Any]]:
    if not value:
        return []
    return [{"name": a.strip(), "id": None} for a in re.split(sep_regex, value) if a.strip()]


def _year(value: Any) -> Optional[int]:
    if value is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(value))
    return int(m.group(0)) if m else None


def _first(row: Dict[str, Any], *names: str) -> Optional[str]:
    for n in names:
        v = row.get(n)
        if isinstance(v, list):
            v = v[0] if v else None
        if v not in (None, ""):
            return str(v)
    return None


def _join(row: Dict[str, Any], name: str) -> Optional[str]:
    v = row.get(name)
    if isinstance(v, list):
        return "; ".join(v) if v else None
    return v or None


def map_record(source: str, fmt: str, row: Dict[str, Any]) -> Dict[str, Any]:
    rec = empty_record(source)
    if fmt == "openalex_json":
        rec.update(OpenAlexAdapter.normalize_record(OpenAlexAdapter.__new__(OpenAlexAdapter), row))  # type: ignore[arg-type]
        rec["source"] = source
        return rec
    if fmt == "scopus_csv":
        rec["source_record_id"] = _first(row, "EID")
        rec["doi"] = normalize_doi(_first(row, "DOI"))
        rec["title"] = _first(row, "Title")
        rec["authors"] = _split_authors(_first(row, "Authors", "Author full names"), r";|,(?=\s*[A-Z])" if False else r";")
        rec["year"] = _year(_first(row, "Year"))
        rec["venue"] = _first(row, "Source title")
        rec["venue_issn"] = _first(row, "ISSN")
        rec["type"] = _first(row, "Document Type")
        rec["abstract"] = _first(row, "Abstract")
        rec["language"] = _first(row, "Language of Original Document")
        rec["cited_by_count"] = int(_first(row, "Cited by") or 0) if _first(row, "Cited by") else None
        rec["url"] = _first(row, "Link")
    elif fmt == "wos_tab":
        rec["source_record_id"] = _first(row, "UT")
        rec["doi"] = normalize_doi(_first(row, "DI"))
        rec["title"] = _first(row, "TI")
        rec["authors"] = _split_authors(_first(row, "AF", "AU"))
        rec["year"] = _year(_first(row, "PY"))
        rec["venue"] = _first(row, "SO")
        rec["venue_issn"] = _first(row, "SN")
        rec["type"] = _first(row, "DT")
        rec["abstract"] = _first(row, "AB")
        rec["language"] = _first(row, "LA")
        rec["cited_by_count"] = int(_first(row, "TC") or 0) if _first(row, "TC") else None
    elif fmt in ("ieee_csv", "acm_csv"):
        rec["doi"] = normalize_doi(_first(row, "DOI"))
        rec["source_record_id"] = _first(row, "Document Identifier", "PDF Link", "DOI", "Item DOI")
        rec["title"] = _first(row, "Document Title", "Title")
        rec["authors"] = _split_authors(_first(row, "Authors", "Author"), r";")
        rec["year"] = _year(_first(row, "Publication Year", "Year", "Publication Date"))
        rec["venue"] = _first(row, "Publication Title", "Proceedings title", "Journal")
        rec["venue_issn"] = _first(row, "ISSN")
        rec["type"] = _first(row, "Document Type", "Item Type")
        rec["abstract"] = _first(row, "Abstract")
        rec["cited_by_count"] = int(_first(row, "Article Citation Count") or 0) if _first(row, "Article Citation Count") else None
        rec["url"] = _first(row, "PDF Link", "URL")
    elif fmt == "ris":
        rec["doi"] = normalize_doi(_first(row, "DO"))
        rec["source_record_id"] = _first(row, "AN", "ID", "UR")
        rec["title"] = _first(row, "TI", "T1")
        rec["authors"] = [{"name": a, "id": None} for a in (row.get("AU") or row.get("A1") or [])]
        rec["year"] = _year(_first(row, "PY", "Y1"))
        rec["venue"] = _first(row, "T2", "JO", "JF", "BT")
        rec["venue_issn"] = _first(row, "SN")
        rec["type"] = _first(row, "TY")
        rec["abstract"] = _first(row, "AB", "N2")
        rec["language"] = _first(row, "LA")
        rec["url"] = _first(row, "UR")
    elif fmt == "bibtex":
        rec["doi"] = normalize_doi(row.get("doi"))
        rec["source_record_id"] = row.get("_key")
        rec["title"] = row.get("title")
        rec["authors"] = _split_authors(row.get("author"), r"\band\b")
        rec["year"] = _year(row.get("year"))
        rec["venue"] = row.get("journal") or row.get("booktitle")
        rec["venue_issn"] = row.get("issn")
        rec["type"] = row.get("_type")
        rec["abstract"] = row.get("abstract")
        rec["language"] = row.get("language")
        rec["url"] = row.get("url")
    else:  # generic_csv
        lower = {k.lower(): v for k, v in row.items()}
        rec["doi"] = normalize_doi(lower.get("doi"))
        rec["title"] = lower.get("title")
        rec["authors"] = _split_authors(lower.get("authors"), r";")
        rec["year"] = _year(lower.get("year"))
        rec["venue"] = lower.get("venue")
        rec["url"] = lower.get("url")
        rec["abstract"] = lower.get("abstract")
        rec["source_record_id"] = lower.get("id") or lower.get("url") or ("row-%s" % row.get("_row"))
    if not rec["source_record_id"]:
        rec["source_record_id"] = rec["doi"] or ("row-%s" % row.get("_row"))
    rec["publication_date"] = ("%d-01-01" % rec["year"]) if rec.get("year") and not rec.get("publication_date") else rec.get("publication_date")
    rec["source_note"] = "imported from manual export (%s); publication_date is the year only" % fmt
    return rec


# ----------------------------------------------------------------------------- adapter

class ManualImportAdapter(BaseAdapter):
    """Reports MANUAL_EXPORT_REQUIRED for retrieval; maps imported rows to the common schema."""

    def __init__(self, source: str, protocol: Dict[str, Any], source_cfg: Dict[str, Any]):
        super().__init__(protocol, source_cfg)
        self.name = source
        self.fmt: Optional[str] = None  # set per import

    def supports_api(self) -> bool:
        return False

    def status(self) -> str:
        return MANUAL_EXPORT_REQUIRED

    def describe_request(self, exact_query: str, **kwargs) -> Dict[str, Any]:
        return {"status": MANUAL_EXPORT_REQUIRED, "source": self.name,
                "instruction": "paste this string into the %s interface and export the result" % self.cfg.get("display_name", self.name),
                "exact_query": exact_query}

    def records_in_raw(self, raw: Any) -> List[Any]:
        if isinstance(raw, dict) and "results" in raw:
            return list(raw["results"])
        return list(raw or [])

    def source_record_id(self, raw_record: Any) -> Optional[str]:
        return map_record(self.name, self.fmt or "generic_csv", raw_record).get("source_record_id")

    def normalize_record(self, raw_record: Any) -> Dict[str, Any]:
        return map_record(self.name, self.fmt or "generic_csv", raw_record)
