from __future__ import annotations

import json

from block4_pipeline import config_loader as cl
from block4_pipeline.adapters.ieee import IeeeAdapter, count_wildcard_words, decompose_for_wildcards, _iso_date
from block4_pipeline.pipeline.retrieve import split_json_bundle


def test_decomposition_keeps_queries_within_two_wildcards_for_every_ieee_form():
    scfg = cl.load_sources()["sources"]["ieee"]
    for q in cl.load_queries():
        if not cl.is_mandatory(scfg, q):
            continue
        parts = decompose_for_wildcards(q["ieee"])
        # a part cannot have fewer wildcard words than the number of AND groups that carry one
        # (Q27: three such groups, so three is the floor and the API's limit of two cannot be met)
        from block4_pipeline.adapters.ieee import _split_top_level, _strip_parens
        floor = sum(1 for g in _split_top_level(_strip_parens(q["ieee"]), "AND") if count_wildcard_words(g) > 0)
        assert all(count_wildcard_words(p) <= max(2, floor) for p in parts), (q["id"], parts)
        if count_wildcard_words(q["ieee"]) <= 2:
            assert parts == [q["ieee"]]


def test_decomposition_is_exact_distribution():
    expr = '("actor*" OR stakeholder* OR contract) AND (dependen* OR coupling) AND ("formal model")'
    parts = decompose_for_wildcards(expr)
    # 3 wildcard words -> at least two parts; every part keeps every AND group
    assert len(parts) >= 2
    for p in parts:
        assert p.count(" AND ") == 2 and '"formal model"' in p
    # every wildcard alternative appears in some part, together with the non-wildcard alternative kept
    joined = " | ".join(parts)
    for tok in ("actor*", "stakeholder*", "contract", "dependen*", "coupling"):
        assert tok in joined


def test_iso_date():
    assert _iso_date("15 March 2020", 2020) == "2020-03-15"
    assert _iso_date("Nov.-Dec. 2019", 2019) == "2019-12-01"
    assert _iso_date("2018", 2018) == "2018-01-01"
    assert _iso_date(None, 2017) == "2017-01-01"


def test_normalize_record():
    a = {"title": "A paper", "abstract": "Text.", "doi": "10.1109/X.2020.1", "article_number": "9000001",
         "authors": {"authors": [{"full_name": "B Second", "author_order": 2, "id": 2}, {"full_name": "A First", "author_order": 1, "id": 1}]},
         "publication_title": "IEEE Trans. Example", "publication_year": "2020", "publication_date": "1 May 2020",
         "content_type": "Journals", "issn": "1234-5678", "citing_paper_count": 7, "html_url": "https://ieeexplore.ieee.org/document/9000001"}
    rec = IeeeAdapter.normalize_record(IeeeAdapter.__new__(IeeeAdapter), a)  # type: ignore[arg-type]
    assert rec["source_record_id"] == "9000001" and rec["doi"] == "10.1109/x.2020.1"
    assert [x["name"] for x in rec["authors"]] == ["A First", "B Second"]
    assert rec["publication_date"] == "2020-05-01" and rec["cited_by_count"] == 7


def test_json_bundle_split():
    text = '{"a": 1}\n\n{"b": [1, 2]} junk {"c": {"d": "}"}}'
    assert split_json_bundle(text) == [{"a": 1}, {"b": [1, 2]}, {"c": {"d": "}"}}]
