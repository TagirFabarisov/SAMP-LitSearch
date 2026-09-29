from __future__ import annotations

from block4_pipeline.adapters.manual_import import detect_format, map_record, parse_export


def test_dblp_json_import(fixtures):
    p = fixtures / "dblp" / "publ_page_1.json"
    assert detect_format(p, "dblp") == "dblp_json"
    rows = parse_export(p, "dblp_json")
    assert len(rows) == 2
    rec = map_record("dblp", "dblp_json", rows[0])
    assert rec["source"] == "dblp" and rec["source_record_id"] == "conf/exconf/ExampleS99"
    assert rec["doi"] == "10.1000/example.001" and rec["year"] == 1999
    assert [a["name"] for a in rec["authors"]] == ["Ada Example", "Bo Sample"]
    assert rec["abstract"] is None
