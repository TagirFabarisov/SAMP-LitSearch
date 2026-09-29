from __future__ import annotations

import json

import pytest

from block4_pipeline import config_loader as cl
from block4_pipeline.adapters.base import REFINEMENT_REQUIRED, DONE, CountResult, PageResult
from block4_pipeline.adapters.openalex import OpenAlexAdapter, reconstruct_abstract, short_openalex_id
from block4_pipeline import secrets


def _adapter():
    return OpenAlexAdapter(cl.load_protocol(), cl.load_sources()["sources"]["openalex"])


def test_abstract_reconstruction():
    idx = {"We": [0], "model": [1, 5], "resource": [2], "dependence": [3], "as": [4], "a": [6], "relation.": [7]}
    assert reconstruct_abstract(idx) == "We model resource dependence as model a relation."
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_exact_query_gets_entity_prefix():
    q = cl.query_by_id(cl.load_queries(), "B4-Q01")
    exact = _adapter().exact_query(q)
    assert exact.startswith("works where title_and_abstract has (")
    assert q["openalex_oql"] in exact


def test_request_description_has_no_key(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "abcdefghij1234567890XYZ")
    desc = _adapter().describe_request("works where title_and_abstract has (actor*)")
    text = json.dumps(desc)
    assert "abcdefghij1234567890XYZ" not in text
    assert desc["headers"]["Authorization"] == "Bearer <REDACTED>"
    assert desc["json"]["per_page"] == 100
    assert desc["json"]["sort"] == "publication_date:asc,ids.openalex:asc"
    assert desc["json"]["cursor"] == "*"
    assert desc["method"] == "POST" and desc["url"].endswith("openalex.org/")


def test_normalize_record(fixtures):
    page = json.loads((fixtures / "openalex" / "works_page_1.json").read_text())
    a = _adapter()
    recs = [a.normalize_record(w) for w in a.records_in_raw(page)]
    assert recs[0]["openalex_id"] == "W1000000001"
    assert recs[0]["doi"] == "10.1000/example.001"
    assert recs[0]["authors"][0] == {"name": "Ada Example", "id": "A500000001"}
    assert recs[0]["venue"] == "Journal of Examples" and recs[0]["venue_issn"] == "1234-5678"
    assert recs[0]["abstract"].startswith("We model")
    assert recs[1]["abstract"] is None and recs[1]["doi"] is None
    assert recs[2]["doi"] == "10.1000/example.003"   # lower-cased
    assert recs[2]["venue"] is None


def test_threshold_rule_retrieves_nothing_above_300(monkeypatch):
    a = _adapter()
    monkeypatch.setattr(a, "count", lambda q, **kw: CountResult(count=301, raw={"meta": {"count": 301}}, request={}))
    monkeypatch.setattr(a, "pages", lambda q, **kw: (_ for _ in ()).throw(AssertionError("pages must not be fetched")))
    out = a.retrieve("works where title_and_abstract has (actor*)", 300)
    assert out.status == REFINEMENT_REQUIRED and out.count == 301 and out.pages == []


def test_threshold_rule_retrieves_all_at_300(monkeypatch, fixtures):
    a = _adapter()
    p1 = json.loads((fixtures / "openalex" / "works_page_1.json").read_text())
    p2 = json.loads((fixtures / "openalex" / "works_page_2.json").read_text())
    monkeypatch.setattr(a, "count", lambda q, **kw: CountResult(count=300, raw=p1, request={}))
    monkeypatch.setattr(a, "pages", lambda q, **kw: iter([PageResult(1, p1, p1["results"], {}), PageResult(2, p2, [], {})]))
    out = a.retrieve("works where title_and_abstract has (actor*)", 300)
    assert out.status == DONE and sum(len(p.records) for p in out.pages) == 3


def test_short_id():
    assert short_openalex_id("https://openalex.org/W12") == "W12"
    assert short_openalex_id("W12") == "W12"
    assert short_openalex_id(None) is None


def test_redaction(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "abcdefghij1234567890XYZ")
    assert "abcdefghij1234567890XYZ" not in secrets.redact_text("https://x/?api_key=abcdefghij1234567890XYZ&x=1")
    assert secrets.redact_text("Authorization: Bearer abc.def-123") == "Authorization: Bearer <REDACTED>"
    assert secrets.redact_obj({"api_key": "zzz", "nested": {"token": "yyy", "ok": "fine"}}) == {"api_key": "<REDACTED>", "nested": {"token": "<REDACTED>", "ok": "fine"}}
