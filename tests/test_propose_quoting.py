from __future__ import annotations

from block4_pipeline.pipeline.propose_quoting import quote_bare_wildcards


def test_bare_wildcards_are_quoted_and_phrases_left_alone():
    expr = 'title_and_abstract has (("social dependence" OR "dependence relation*") AND (actor* OR agent* OR (organization* OR organisation*)) AND (model* OR formal* OR representation))'
    new, changed, warns = quote_bare_wildcards(expr)
    assert new == 'title_and_abstract has (("social dependence" OR "dependence relation*") AND ("actor*" OR "agent*" OR ("organization*" OR "organisation*")) AND ("model*" OR "formal*" OR representation))'
    assert changed == ["actor*", "agent*", "organization*", "organisation*", "model*", "formal*"]
    assert warns == []


def test_hyphenated_and_short_tokens():
    new, changed, warns = quote_bare_wildcards("(inter-organi* OR ai*)")
    assert new == '("inter-organi*" OR "ai*")'
    assert any("fewer than 3" in w for w in warns)


def test_question_mark_is_flagged():
    _, _, warns = quote_bare_wildcards("organi?ation*")
    assert any("'?'" in w for w in warns)


def test_idempotent():
    once, _, _ = quote_bare_wildcards('("actor*" OR agent*)')
    twice, changed, _ = quote_bare_wildcards(once)
    assert once == twice and changed == []
