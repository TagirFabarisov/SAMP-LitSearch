"""End-to-end run on fixtures: retrieve (stubbed adapter) -> import-manual -> normalize ->
deduplicate -> export -> status. No network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from block4_pipeline import config_loader as cl
from block4_pipeline import paths, storage
from block4_pipeline.adapters.base import CountResult, PageResult, REFINEMENT_REQUIRED, MANUAL_EXPORT_REQUIRED
from block4_pipeline.adapters.openalex import OpenAlexAdapter
from block4_pipeline.adapters.dblp import DblpAdapter
from block4_pipeline.pipeline import deduplicate, export, normalize, provenance, retrieve, status


def _stub_openalex(monkeypatch, fixtures, count=None):
    p1 = json.loads((fixtures / "openalex" / "works_page_1.json").read_text())
    p2 = json.loads((fixtures / "openalex" / "works_page_2.json").read_text())
    monkeypatch.setattr(OpenAlexAdapter, "count", lambda self, q, **kw: CountResult(count=count if count is not None else p1["meta"]["count"], raw=p1, request={"x": 1}))
    monkeypatch.setattr(OpenAlexAdapter, "pages", lambda self, q, **kw: iter([PageResult(1, p1, p1["results"], {}), PageResult(2, p2, [], {})]))


def _stub_dblp(monkeypatch, fixtures):
    d = json.loads((fixtures / "dblp" / "publ_page_1.json").read_text())
    monkeypatch.setattr(DblpAdapter, "count", lambda self, q, **kw: CountResult(count=2, raw=d, request={}))
    monkeypatch.setattr(DblpAdapter, "pages", lambda self, q, **kw: iter([PageResult(1, d, d["result"]["hits"]["hit"], {})]))


def _unlock_openalex(monkeypatch, tmp_path, cutoff="2026-10-01"):
    proto = cl.load_protocol()
    proto["openalex_construct_check_resolved"] = True
    proto["upper_cutoff_date"] = cutoff
    p = tmp_path / "protocol.yaml"
    p.write_text(yaml.safe_dump(proto), encoding="utf-8")
    monkeypatch.setattr(paths, "PROTOCOL_FILE", p)


def test_dry_run_makes_no_network_call_and_prints_request():
    res = retrieve.retrieve("openalex", query_ids=["B4-Q01"], dry_run=True)
    assert res[0]["status"] == "dry_run"
    assert res[0]["request"]["json"]["oql"].startswith("works where title_and_abstract has")
    assert not paths.search_log_file().exists()


def test_live_without_flag_is_blocked(monkeypatch, tmp_path):
    _unlock_openalex(monkeypatch, tmp_path)
    with pytest.raises(retrieve.RetrievalBlocked):
        retrieve.retrieve("openalex", query_ids=["B4-Q01"])


def test_openalex_blocked_until_construct_check_resolved(monkeypatch, tmp_path):
    proto = cl.load_protocol()
    proto["openalex_construct_check_resolved"] = False
    p = tmp_path / "protocol.yaml"
    p.write_text(yaml.safe_dump(proto), encoding="utf-8")
    monkeypatch.setattr(paths, "PROTOCOL_FILE", p)
    with pytest.raises(retrieve.RetrievalBlocked):
        retrieve.retrieve("openalex", query_ids=["B4-Q01"], live_confirmed=True)


def test_full_pipeline_on_fixtures(monkeypatch, tmp_path, fixtures):
    _unlock_openalex(monkeypatch, tmp_path)
    _stub_openalex(monkeypatch, fixtures)
    _stub_dblp(monkeypatch, fixtures)

    r = retrieve.retrieve("openalex", query_ids=["B4-Q01"], live_confirmed=True)
    assert r[0]["status"] == "done" and r[0]["hits"] == 3
    run_dir = Path(r[0]["run_dir"])
    assert (run_dir / "page_1.json").exists() and (run_dir / "count_check.json").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert set(manifest["files"]) >= {"page_1.json", "page_2.json", "count_check.json"}

    # raw evidence is write-once
    with pytest.raises(FileExistsError):
        storage.write_raw_once(run_dir / "page_1.json", {})

    # a second run of the same pair is skipped unless --rerun
    assert retrieve.retrieve("openalex", query_ids=["B4-Q01"], live_confirmed=True)[0]["status"] == "already_done"

    r2 = retrieve.retrieve("dblp", query_ids=["B4-Q01"], live_confirmed=True)
    assert r2[0]["status"] == "done" and r2[0]["hits"] == 2

    # a manual-export source reports MANUAL_EXPORT_REQUIRED (wos is manual in the shipped config), then an import works
    r3 = retrieve.retrieve("wos", query_ids=["B4-Q01"], live_confirmed=True)
    assert r3[0]["status"] == MANUAL_EXPORT_REQUIRED
    imp = retrieve.import_manual("scopus", "B4-Q01", str(fixtures / "exports" / "scopus_sample.csv"), export_date="2026-10-02")
    assert imp["status"] == "done" and imp["hits"] == 3 and imp["format"] == "scopus_csv"
    imp2 = retrieve.import_manual("wos", "B4-Q01", str(fixtures / "exports" / "wos_sample.ris"))
    assert imp2["hits"] == 2 and imp2["format"] == "ris"

    hits = provenance.hits()
    assert [h["hit_id"] for h in hits] == ["B4-H%05d" % i for i in range(1, 11)]
    log = provenance.search_log_entries()
    assert [e["source"] for e in log] == ["openalex", "dblp", "wos", "scopus", "wos"]
    assert log[0]["exact_string_sent"].startswith("works where")
    assert log[3]["note"].startswith("manual export (scopus_csv), exported 2026-10-02")
    assert log[2]["status"] == MANUAL_EXPORT_REQUIRED

    st = normalize.normalize()
    assert st["records_written"] == 10 and st["after_cutoff"] == 1
    recs = list(storage.read_jsonl(paths.records_file()))
    late = [r for r in recs if r["after_cutoff"]]
    assert late[0]["openalex_id"] == "W1000000003" and late[0]["non_english"]

    dd = deduplicate.deduplicate()
    docs = {d["document_id"]: d for d in storage.read_jsonl(paths.documents_file())}
    # 10 hits -> 5 documents: paper 1 (DOI match across 4 sources); paper 2 spelled
    # "organizations" (OpenAlex + Scopus, title+year match) and "organisations" (DBLP + WoS):
    # different normalized titles, so NOT merged, only flagged as a near-duplicate pair;
    # the after-cutoff paper; and "a wholly different paper".
    assert dd["documents"] == 5, docs
    assert dd["near_duplicate_pairs"] == 1
    paper1 = [d for d in docs.values() if d["doi"] == "10.1000/example.001"][0]
    assert sorted(paper1["sources"]) == ["dblp", "openalex", "scopus", "wos"]
    assert len(paper1["hit_ids"]) == 4
    paper2 = sorted((d for d in docs.values() if d["title"] and d["title"].lower().startswith("dependence relations")), key=lambda d: d["document_id"])
    assert [sorted(d["sources"]) for d in paper2] == [["openalex", "scopus"], ["dblp", "wos"]]
    mapping = list(storage.read_jsonl(paths.hit_document_map_file()))
    assert {m["matched_by"] for m in mapping} >= {"new", "doi", "normalized_title_year"}
    near = (paths.exports_dir() / "near_duplicates.csv").read_text()
    assert "organisations" in near.lower() and "organizations" in near.lower()

    # document IDs stay stable on rerun
    ids_before = sorted(docs)
    deduplicate.deduplicate()
    assert sorted(d["document_id"] for d in storage.read_jsonl(paths.documents_file())) == ids_before

    # per-document folders: metadata + provenance only
    folder = paths.document_dir(paper1["document_id"])
    assert (folder / "metadata.json").exists() and (folder / "provenance.json").exists()
    prov = json.loads((folder / "provenance.json").read_text())
    assert sorted(h["source"] for h in prov["hits"]) == ["dblp", "openalex", "scopus", "wos"]
    assert all(h["matched_by"] for h in prov["hits"])
    meta = json.loads((folder / "metadata.json").read_text())
    assert meta["oa_pdf_url"] == "https://repo.example.org/paper1.pdf" and meta["is_oa"] is True
    assert "hit_ids" not in meta
    # a file another stage put there survives a rerun
    (folder / "source.pdf").write_bytes(b"%PDF-1.4 placeholder")
    deduplicate.deduplicate()
    assert (folder / "source.pdf").read_bytes().startswith(b"%PDF")

    ex = export.export("all")
    assert ex["excluded_after_cutoff"] == 1
    assert (paths.exports_dir() / "documents_for_s1.csv").exists()
    assert (paths.exports_dir() / "near_duplicates.csv").exists()

    st = status.write_status()
    assert st["total_hits"] == 10 and st["total_documents"] == 5
    row = [r for r in st["rows"] if r["query_id"] == "B4-Q01" and r["source"] == "openalex"][0]
    assert row["status"] == "done" and row["new_documents"] == 3
    assert paths.status_file().exists()


def test_refinement_required_writes_count_and_no_hits(monkeypatch, tmp_path, fixtures):
    _unlock_openalex(monkeypatch, tmp_path)
    _stub_openalex(monkeypatch, fixtures, count=1234)
    r = retrieve.retrieve("openalex", query_ids=["B4-Q02"], live_confirmed=True)
    assert r[0]["status"] == REFINEMENT_REQUIRED and r[0]["count"] == 1234 and r[0]["hits"] == 0
    assert not (Path(r[0]["run_dir"]) / "page_1.json").exists()
    assert provenance.search_log_entries()[-1]["original_count"] == 1234
    assert not paths.hits_file().exists()


def test_manual_import_above_threshold_is_refinement_required(monkeypatch, tmp_path, fixtures):
    big = tmp_path / "big.csv"
    lines = ["title,authors,year,venue,url,rank"] + ["Paper %d,A,2001,V,http://x/%d,%d" % (i, i, i) for i in range(301)]
    big.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = retrieve.import_manual("heinonline", "B4-Q07", str(big), fmt="generic_csv")
    assert r["status"] == REFINEMENT_REQUIRED and r["hits"] == 0 and r["count"] == 301


def test_protocol_order_of_execution():
    ordered = retrieve.select_queries(cl.load_queries(), None)
    ids = [q["id"] for q in ordered]
    assert ids[:3] == ["B4-Q01", "B4-Q02", "B4-Q03"]
    assert ids[-6:] == ["B4-XC01", "B4-XC02", "B4-BR01", "B4-BR02", "B4-BR03", "B4-BR04"]


def test_deviation_log_is_append_only(tmp_path):
    provenance.append_deviation({"date": "2026-10-01", "change": "x"})
    provenance.append_deviation({"date": "2026-10-02", "change": "y"})
    assert [d["change"] for d in provenance.deviations()] == ["x", "y"]
