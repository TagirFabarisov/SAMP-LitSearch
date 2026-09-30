from __future__ import annotations

from block4_pipeline import config_loader as cl
from block4_pipeline.adapters.dblp import DblpSparqlAdapter, boolean_to_sparql_filter


def test_boolean_translation():
    f = boolean_to_sparql_filter('title_and_abstract has (("social dependence" OR "dependence relation*") AND ("actor*" OR agent OR (organization* OR "organisation*")) AND representation)')
    assert f == ('( CONTAINS(?l, "social dependence") || CONTAINS(?l, "dependence relation") ) && '
                 '( CONTAINS(?l, "actor") || CONTAINS(?l, "agent") || ( CONTAINS(?l, "organization") || CONTAINS(?l, "organisation") ) ) && '
                 'CONTAINS(?l, "representation")')


def test_every_query_translates_and_balances():
    for q in cl.load_queries():
        f = boolean_to_sparql_filter(q["openalex_oql"])
        assert f.count("(") == f.count(")") and "CONTAINS" in f, q["id"]
        assert "*" not in f and "AND" not in f and " OR " not in f, q["id"]


def test_normalize_sparql_row():
    a = DblpSparqlAdapter.__new__(DblpSparqlAdapter); a.name = "dblp"
    row = {"p": {"value": "https://dblp.org/rec/conf/x/Y20"}, "t": {"value": "A Title."}, "y": {"value": "2020"},
           "doi": {"value": "https://doi.org/10.1000/ABC"}, "venue": {"value": "CONF"},
           "type": {"value": "http://purl.org/net/nknouf/ns/bibtex#Inproceedings"}, "authors": {"value": "A One; B Two"}}
    rec = a.normalize_record(row)
    assert rec["source_record_id"] == "conf/x/Y20" and rec["doi"] == "10.1000/abc" and rec["year"] == 2020
    assert rec["title"] == "A Title" and rec["type"] == "Inproceedings"
    assert [x["name"] for x in rec["authors"]] == ["A One", "B Two"]
