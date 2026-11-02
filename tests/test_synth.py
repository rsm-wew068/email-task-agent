"""Label-first authoring honesty: every gold evidence sentence must appear in
its thread's rendered text (exactly after normalization), and suite files must
round-trip through the loader.
"""

from __future__ import annotations

from datetime import date

from email_task_agent.evals.loader import load_suite
from email_task_agent.evidence import locate_quote
from email_task_agent.synth.cases_demo import build_demo_extras
from email_task_agent.synth.cases_e1 import build_cases
from email_task_agent.synth.generate import ThreadSpec, render_thread, write_suite

SEED = date(2026, 11, 2)


def _all_specs() -> list[ThreadSpec]:
    return build_cases() + build_demo_extras()


def test_every_evidence_sentence_appears_verbatim_in_thread_text() -> None:
    for spec in _all_specs():
        rendered = render_thread(spec, SEED)
        text = "\n\n".join(f"Subject: {e['subject']}\n\n{e['body']}" for e in rendered["emails"])
        for g in rendered["gold"]:
            assert locate_quote(g["evidence_sentence"], text) is not None, (
                f"{spec.thread_id}: gold evidence sentence not found verbatim: "
                f"{g['evidence_sentence']!r}"
            )


def test_gold_email_index_in_range_and_dates_consistent() -> None:
    for spec in _all_specs():
        assert spec.emails, f"{spec.thread_id} has no emails"
        for g in spec.gold:
            assert 0 <= g.email_index < len(spec.emails), f"{spec.thread_id}: bad email_index"
            assert g.status in {"open", "done", "cancelled"}


def test_write_and_load_round_trip(tmp_path) -> None:
    specs = _all_specs()
    path = write_suite("round-trip", SEED, specs, tmp_path / "suite.json")
    suite = load_suite(path)
    assert suite.name == "round-trip"
    assert suite.seed_date == SEED
    assert len(suite.threads) == len(specs)
    by_id = {t.thread_id: t for t in suite.threads}
    for spec in specs:
        case = by_id[spec.thread_id]
        assert case.split == spec.split
        assert [g.title for g in case.gold] == [g.title for g in spec.gold]
        assert [e.subject for e in case.emails] == [e.subject for e in spec.emails]


def test_starter_matrix_covers_scope_and_precision_cases() -> None:
    specs = {s.thread_id: s for s in _all_specs()}
    # gold-empty scope/precision threads exist:
    for tid in ("e1-002-kickoff-scheduling", "e1-003-newsletter-renewal", "e1-004-cc-other-owner"):
        assert tid in specs and specs[tid].gold == []
    # two-tasks-one-sentence shares one evidence sentence across two gold tasks:
    two = specs["e1-006-two-tasks-one-sentence"].gold
    assert len(two) == 2 and two[0].evidence_sentence == two[1].evidence_sentence
    # test/dev split both populated:
    splits = {s.split for s in specs.values()}
    assert "test" in splits and "dev" in splits
