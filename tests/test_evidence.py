"""Frozen evidence machinery (§9.3): normalization, location, overlap."""

from __future__ import annotations

from email_task_agent.evidence import (
    MIN_QUOTE_TOKENS,
    locate_quote,
    normalize,
    overlap_coefficient,
    quote_overlaps_sentence,
    tokenize,
)


def test_normalize_collapses_whitespace_and_casefolds() -> None:
    assert normalize("  Hello\n\tWORLD  ") == "hello world"


def test_locate_quote_exact() -> None:
    email = "Hi Alex,\n\nPlease send the Q3 draft by Friday.\n\nKate"
    loc = locate_quote("Please send the Q3 draft by Friday.", email)
    assert loc is not None
    assert loc.score == 100.0
    # Offsets index the normalized text; matched_text is the located span itself.
    assert loc.matched_text == normalize("Please send the Q3 draft by Friday.")
    assert normalize(email)[loc.start : loc.end] == loc.matched_text


def test_locate_quote_fuzzy_survives_whitespace_and_case() -> None:
    email = "please SEND the Q3 Draft by  friday!!"
    loc = locate_quote("Please send the Q3 draft by Friday.", email)
    assert loc is not None
    assert loc.score >= 90.0


def test_locate_quote_missing_returns_none() -> None:
    assert locate_quote("wire the invoice to a different account", "no such sentence here") is None


def test_locate_quote_empty_quote_returns_none() -> None:
    assert locate_quote("   ", "anything") is None


def test_overlap_coefficient_definition() -> None:
    p = {"please", "send", "the", "draft"}
    s = {"please", "send", "the", "draft", "by", "friday"}
    # |p ∩ s| / min(|p|, |s|) = 4/4
    assert overlap_coefficient(p, s) == 1.0
    assert overlap_coefficient({"a", "b"}, {"c", "d"}) == 0.0
    assert overlap_coefficient(set(), {"a"}) == 0.0


def test_quote_overlaps_sentence_uses_tokens() -> None:
    score = quote_overlaps_sentence("Please send the draft", "please send the draft by friday")
    assert score == 1.0


def test_min_quote_tokens_constant_is_three() -> None:
    # Pin the rev-5-review rule: shorter quotes can anchor on almost anything.
    assert MIN_QUOTE_TOKENS == 3
    assert len(tokenize("send it")) == 2  # below the floor
