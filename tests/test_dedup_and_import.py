from __future__ import annotations

from block4_pipeline.adapters.base import normalize_doi
from block4_pipeline.adapters.manual_import import detect_format, map_record, parse_bibtex, parse_export, parse_ris
from block4_pipeline.pipeline.deduplicate import levenshtein_ratio, normalize_title, normalized_key
from block4_pipeline.pipeline.normalize import is_after_cutoff
from block4_pipeline.storage import IdAllocator


def test_doi_normalization():
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_doi("doi:10.1000/abc ") == "10.1000/abc"
    assert normalize_doi("") is None and normalize_doi(None) is None


def test_title_normalization_and_key():
    assert normalize_title("The Résumé of a Model: Toward Formal Semantics!") == "resume model formal semantics"
    assert normalized_key("Dependence Relations in Organizations", 2005) == "dependence relations organizations|2005"
    assert normalized_key(None, None) == "|"


def test_levenshtein_ratio():
    assert levenshtein_ratio("abc", "abc") == 1.0
    assert levenshtein_ratio("abc", "") == 0.0
    assert abs(levenshtein_ratio("organizations", "organisations") - (1 - 1 / 13)) < 1e-9


def test_cutoff_flag():
    assert is_after_cutoff("2026-10-02", "2026-10-01")
    assert not is_after_cutoff("2026-10-01", "2026-10-01")
    assert not is_after_cutoff(None, "2026-10-01")
    assert not is_after_cutoff("2099-01-01", None)


def test_id_allocation_continues_from_existing():
    a = IdAllocator("B4-H{:05d}", ["B4-H00003", "B4-H00001", "junk"])
    assert a.next() == "B4-H00004"
    b = IdAllocator("B4-R{:05d}")
    assert b.next() == "B4-R00001"


def test_scopus_csv_mapping(fixtures):
    p = fixtures / "exports" / "scopus_sample.csv"
    assert detect_format(p, "scopus") == "scopus_csv"
    rows = parse_export(p, "scopus_csv")
    rec = map_record("scopus", "scopus_csv", rows[0])
    assert rec["source_record_id"] == "2-s2.0-0001"
    assert rec["doi"] == "10.1000/example.001" and rec["year"] == 1999
    assert [a["name"] for a in rec["authors"]] == ["Example A.", "Sample B."]
    assert rec["language"] == "English" and rec["cited_by_count"] == 42
    assert rec["publication_date"] == "1999-01-01"


def test_ris_and_bibtex_mapping(fixtures):
    ris = parse_ris((fixtures / "exports" / "wos_sample.ris").read_text())
    assert len(ris) == 2
    rec = map_record("wos", "ris", ris[0])
    assert rec["source_record_id"] == "WOS:000000000100001" and rec["doi"] == "10.1000/example.001"
    assert [a["name"] for a in rec["authors"]] == ["Example, Ada", "Sample, Bo"]
    bib = parse_bibtex((fixtures / "exports" / "generic_sample.bib").read_text())
    assert len(bib) == 2
    rec = map_record("ieee", "bibtex", bib[1])
    assert rec["title"] == "Dependence relations in organisations" and rec["year"] == 2005
    assert rec["venue"] == "Handbook of Examples" and rec["source_record_id"] == "instance2005"
