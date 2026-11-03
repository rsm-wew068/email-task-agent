"""E1 scorer and gate unit tests — pin the frozen scorer behavior."""

from __future__ import annotations

from datetime import date

from email_task_agent.evals.gate import gate_decision
from email_task_agent.evals.scoring import GoldTask, PredictedTask, score_thread

TEXT = (
    "Subject: Q3 draft\n\n"
    "Could you send me the revised Q3 draft by Friday so I can review it before the board meeting?\n\n"
    "Please also file your October expense report by Tuesday."
)


def gold(*, due: date | None = date(2026, 11, 6), owner: str | None = "alex@x.example") -> GoldTask:
    return GoldTask(
        title="Send revised Q3 draft",
        owner_email=owner,
        due_date=due,
        status="open",
        evidence_sentence=(
            "Could you send me the revised Q3 draft by Friday so I can review it "
            "before the board meeting?"
        ),
        email_index=0,
    )


def pred(
    *,
    quote: str = (
        "Could you send me the revised Q3 draft by Friday so I can review it before the board meeting?"
    ),
    owner: str | None = "alex@x.example",
    due: date | None = date(2026, 11, 6),
    status: str = "open",
) -> PredictedTask:
    return PredictedTask(
        title="whatever", owner_email=owner, due_date=due, status=status, evidence_quote=quote
    )


def test_perfect_prediction_matches() -> None:
    ts = score_thread("t1", [gold()], [pred()], TEXT)
    assert ts.tp == 1 and ts.fp == 0 and ts.fn == 0
    m = ts.matches[0]
    assert m.owner_ok and m.due_ok and m.status_ok and m.strict_ok


def test_wrong_owner_is_match_with_field_error_not_fp_fn() -> None:
    # Owner is not part of the match; a wrong owner is one matched pair with owner_ok=False.
    ts = score_thread("t1", [gold()], [pred(owner="tom@x.example")], TEXT)
    assert ts.tp == 1 and ts.fp == 0 and ts.fn == 0
    assert ts.matches[0].owner_ok is False
    assert ts.matches[0].strict_ok is False


def test_quote_not_found_is_false_positive() -> None:
    ts = score_thread("t1", [gold()], [pred(quote="The board approved the budget last quarter.")], TEXT)
    assert ts.tp == 0 and ts.fp == 1 and ts.fn == 1
    assert ts.rejected[0].reason == "quote_not_found"


def test_short_quote_is_rejected() -> None:
    ts = score_thread("t1", [gold()], [pred(quote="send it")], TEXT)
    assert ts.fp == 1 and ts.rejected[0].reason == "quote_too_short"


def test_two_tasks_one_sentence_pair_one_to_one() -> None:
    g2 = GoldTask(
        title="File expense report",
        owner_email="alex@x.example",
        due_date=date(2026, 11, 3),
        status="open",
        evidence_sentence="Please also file your October expense report by Tuesday.",
        email_index=0,
    )
    preds = [
        pred(quote="Could you send me the revised Q3 draft by Friday", due=date(2026, 11, 6)),
        pred(quote="Please also file your October expense report by Tuesday.", due=date(2026, 11, 3)),
    ]
    ts = score_thread("t1", [gold(), g2], preds, TEXT)
    assert ts.tp == 2 and ts.fn == 0 and ts.fp == 0
    assert all(m.strict_ok for m in ts.matches)


def test_empty_gold_thread_predictions_are_all_fp() -> None:
    # Newsletters must not spawn tasks: on a gold-empty thread every prediction is precision loss.
    ts = score_thread("newsletter", [], [pred()], TEXT)
    assert ts.tp == 0 and ts.fp == 1 and ts.fn == 0


def test_duplicate_predictions_only_one_matches() -> None:
    # Two predictions anchored on the same sentence: one-to-one assignment leaves one unpaired.
    ts = score_thread("t1", [gold()], [pred(), pred()], TEXT)
    assert ts.tp == 1 and ts.fp == 1 and ts.fn == 0


def test_optimal_assignment_not_greedy() -> None:
    # Greedy would give p1->g1 (overlap 0.9) leaving p2 unmatched; optimal pairs p2->g1 (1.0)
    # and p1->g2 (0.8). Construct overlaps accordingly.
    g1 = GoldTask("t", "a@x", None, "open", "alpha bravo charlie delta echo", 0)
    g2 = GoldTask("u", "a@x", None, "open", "alpha bravo charlie foxtrot", 0)
    p1 = PredictedTask("t", "a@x", None, "open", "alpha bravo charlie delta zulu")
    p2 = PredictedTask("u", "a@x", None, "open", "alpha bravo charlie delta echo")
    ts = score_thread("t1", [g1, g2], [p1, p2], "alpha bravo charlie delta echo foxtrot")
    assert ts.tp == 2 and ts.fp == 0 and ts.fn == 0


def test_metrics_micro_over_threads() -> None:
    perfect = score_thread("a", [gold()], [pred()], TEXT)
    empty = score_thread("b", [], [pred()], TEXT)
    from email_task_agent.evals.scoring import ScorerReport

    report = ScorerReport(scorer_version="x", suite="s", threads=[perfect, empty])
    m = report.metrics()
    # tp=1, fp=1, fn=0 → P=0.5, R=1.0
    assert abs(m["precision"] - 0.5) < 1e-9
    assert abs(m["recall"] - 1.0) < 1e-9
    assert abs(m["f1"] - 2 * 0.5 / 1.5) < 1e-9


def test_gate_uses_points_and_two_sigma() -> None:
    baseline = [
        {"f1": 0.90, "strict_f1": 0.80, "owner_accuracy": 0.95, "due_accuracy": 0.90},
        {"f1": 0.92, "strict_f1": 0.82, "owner_accuracy": 0.95, "due_accuracy": 0.92},
        {"f1": 0.91, "strict_f1": 0.81, "owner_accuracy": 0.95, "due_accuracy": 0.91},
    ]
    # f1 baseline mean 91.0 pts, std ≈ 0.816 → allowed = max(2, 1.63) = 2.0 pts.
    same = [dict(r) for r in baseline]
    assert gate_decision(baseline, same).passed

    drop_3 = [{"f1": 0.88, "strict_f1": 0.81, "owner_accuracy": 0.95, "due_accuracy": 0.91}]
    decision = gate_decision(baseline, drop_3)
    assert not decision.passed  # 3 pts > 2.0 allowed

    drop_1 = [{"f1": 0.90, "strict_f1": 0.81, "owner_accuracy": 0.95, "due_accuracy": 0.91}]
    assert gate_decision(baseline, drop_1).passed
