from __future__ import annotations

import json

from block4_pipeline import config_loader as cl
from block4_pipeline.adapters.base import CountResult, PageResult, DONE
from block4_pipeline.adapters.scopus import ScopusAdapter


def _adapter():
    return ScopusAdapter(cl.load_protocol(), cl.load_sources()["sources"]["scopus"])


def test_exact_query_is_the_bank_form_unchanged():
    q = cl.query_by_id(cl.load_queries(), "B4-Q01")
    assert _adapter().exact_query(q) == q["scopus"]
    assert q["scopus"].startswith("TITLE-ABS-KEY(")


def test_request_description_redacts_key(monkeypatch):
    monkeypatch.setenv("SCOPUS_API_KEY", "0123456789abcdef0123456789abcdef")
    desc = _adapter().describe_request('TITLE-ABS-KEY("x")')
    assert "0123456789abcdef" not in json.dumps(desc)
    assert desc["headers"]["X-ELS-APIKey"] == "<REDACTED>"
    assert desc["params"] == {"query": 'TITLE-ABS-KEY("x")', "view": "COMPLETE", "count": 25, "start": 0, "sort": "+coverDate"}


def test_normalize_record(fixtures):
    page = json.loads((fixtures / "scopus" / "search_page_1.json").read_text())
    a = _adapter()
    recs = [a.normalize_record(e) for e in a.records_in_raw(page)]
    assert len(recs) == 2
    assert recs[0]["source_record_id"] == "2-s2.0-85000000001"
    assert recs[0]["doi"] == "10.1000/example.001" and recs[0]["year"] == 1999
    assert recs[0]["publication_date"] == "1999-03-01"
    assert [x["name"] for x in recs[0]["authors"]] == ["Example A.", "Sample B."]
    assert recs[0]["abstract"].startswith("We model") and recs[0]["cited_by_count"] == 42
    assert recs[0]["url"].startswith("https://www.scopus.com/")
    assert recs[1]["authors"] == [{"name": "Instance C.", "id": None}]
    assert recs[1]["doi"] is None and recs[1]["type"] == "Book Chapter"


def test_empty_result_set_yields_no_records(fixtures):
    empty = json.loads((fixtures / "scopus" / "search_empty.json").read_text())
    assert _adapter().records_in_raw(empty) == []
    assert ScopusAdapter._total(empty) == 0


def test_threshold_and_paging(monkeypatch, fixtures):
    a = _adapter()
    page = json.loads((fixtures / "scopus" / "search_page_1.json").read_text())
    monkeypatch.setattr(a, "count", lambda q, **kw: CountResult(count=2, raw=page, request={}))
    monkeypatch.setattr(a, "pages", lambda q, **kw: iter([PageResult(1, page, a.records_in_raw(page), {})]))
    out = a.retrieve('TITLE-ABS-KEY("x")', 300)
    assert out.status == DONE and len(out.pages[0].records) == 2
