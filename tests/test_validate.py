from __future__ import annotations

from pathlib import Path

import yaml

from block4_pipeline import config_loader as cl
from block4_pipeline.pipeline import validate


def test_shipped_configuration_passes():
    report = validate.validate()
    assert report["ok"], report["errors"]
    assert report["n_queries"] == 54


def test_source_matrix_matches_protocol_section_5():
    """Hard-coded expectation, independent of sources.yaml."""
    sources = cl.load_sources()["sources"]
    queries = cl.load_queries()
    by_id = {q["id"]: q for q in queries}
    assert cl.mandatory_sources({"sources": sources, "execution_order": list(sources)}, by_id["B4-Q01"]) == ["openalex", "scopus", "wos", "dblp"]
    assert "heinonline" in cl.mandatory_sources({"sources": sources}, by_id["B4-Q07"])   # D03
    assert "ieee" in cl.mandatory_sources({"sources": sources}, by_id["B4-Q25"])          # D09
    assert "dblp" not in cl.mandatory_sources({"sources": sources}, by_id["B4-Q31"])      # D11
    assert "dblp" in cl.mandatory_sources({"sources": sources}, by_id["B4-Q47"])          # D16 Q-B
    assert "dblp" not in cl.mandatory_sources({"sources": sources}, by_id["B4-Q46"])      # D16 Q-A
    assert "dblp" in cl.mandatory_sources({"sources": sources}, by_id["B4-XC01"])
    assert "ieee" in cl.mandatory_sources({"sources": sources}, by_id["B4-BR01"])
    assert "dblp" not in cl.mandatory_sources({"sources": sources}, by_id["B4-BR01"])
    for name in ("scholar", "ssrn", "web"):
        assert sources[name]["supplementary_for"] == "all"
        assert not cl.is_mandatory(sources[name], by_id["B4-Q01"])


def test_missing_query_is_reported(tmp_path):
    bank = cl.load_query_bank()
    bank["queries"] = [q for q in bank["queries"] if q["id"] != "B4-Q05"]
    p = tmp_path / "queries.yaml"
    p.write_text(yaml.safe_dump(bank, allow_unicode=True), encoding="utf-8")
    report = validate.validate(queries_path=p, scan_code=False)
    assert not report["ok"]
    assert any("B4-Q05" in e for e in report["errors"])


def test_denylist_hit_is_reported(tmp_path):
    deny = tmp_path / "denylist.txt"
    deny.write_text("# test\nresource dependence\n", encoding="utf-8")
    report = validate.validate(denylist_path=deny, scan_code=False)
    assert not report["ok"]
    assert any("denylisted" in e for e in report["errors"])


def test_generic_formalism_names_are_not_flagged():
    report = validate.validate(scan_code=False)
    assert not any("denylisted" in e for e in report["errors"])


def test_secret_scan_flags_key_assignment(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("api_key: abcdefghij1234567890XYZ\n", encoding="utf-8")
    assert validate.scan_for_secrets([f])


def test_secret_scan_ignores_hex_digests_and_placeholders(tmp_path):
    f = tmp_path / "ok.yaml"
    f.write_text("sha: 3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\nkey: OPENALEX_API_KEY\n", encoding="utf-8")
    assert validate.scan_for_secrets([f]) == []


def test_unfrozen_protocol_fails(tmp_path):
    proto = cl.load_protocol()
    proto["frozen"] = False
    p = tmp_path / "protocol.yaml"
    p.write_text(yaml.safe_dump(proto), encoding="utf-8")
    report = validate.validate(protocol_path=p, scan_code=False)
    assert any("frozen" in e for e in report["errors"])
