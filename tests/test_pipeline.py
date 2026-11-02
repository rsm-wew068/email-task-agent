"""Pipeline core tests: date rules, Validate stage, Reconcile (§7.3)."""

from __future__ import annotations

from datetime import date

import pytest

from email_task_agent.models.extraction import NewTask, TaskUpdate, ThreadExtraction
from email_task_agent.pipeline.dates import resolve_due_date
from email_task_agent.pipeline.reconcile import ExistingTask, reconcile
from email_task_agent.pipeline.validate import (
    ThreadInput,
    ValidatedExtraction,
    ValidatedNew,
    ValidatedUpdate,
    validate_extraction,
)

MONDAY = date(2026, 11, 2)  # anchor used across cases


# -- dates ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-11-06", date(2026, 11, 6)),  # ISO passthrough
        ("Friday", date(2026, 11, 6)),  # coming Friday
        ("friday", date(2026, 11, 6)),
        ("next Friday", date(2026, 11, 13)),
        ("end of the week", date(2026, 11, 6)),
        ("by end of week", date(2026, 11, 6)),
        ("end of the month", date(2026, 11, 30)),
        ("today", MONDAY),
        ("tomorrow", date(2026, 11, 3)),
        ("next week", date(2026, 11, 9)),
        ("in 3 days", date(2026, 11, 5)),
        ("the 20th", date(2026, 11, 20)),
        ("November 15", date(2026, 11, 15)),
        ("Nov 15", date(2026, 11, 15)),
        ("December 1", date(2026, 12, 1)),
    ],
)
def test_resolve_due_date_rules(raw, expected):
    assert resolve_due_date(raw, MONDAY) == expected


def test_resolve_due_date_roll_forward():
    # "the 5th" anchored on Nov 20 has passed -> Dec 5; anchored Nov 2 -> Nov 5.
    assert resolve_due_date("the 5th", date(2026, 11, 20)) == date(2026, 12, 5)
    assert resolve_due_date("the 5th", MONDAY) == date(2026, 11, 5)


def test_resolve_due_date_friday_anchor():
    # EOW on a Friday is that day; a bare weekday rolls to next week.
    friday = date(2026, 11, 6)
    assert resolve_due_date("end of the week", friday) == friday
    assert resolve_due_date("Friday", friday) == date(2026, 11, 13)


def test_resolve_due_date_unparseable_and_empty():
    assert resolve_due_date(None, MONDAY) is None
    assert resolve_due_date("", MONDAY) is None
    assert resolve_due_date("whenever it is convenient", MONDAY) is None


# -- validate -------------------------------------------------------------------------


def _thread_input(**overrides) -> ThreadInput:
    base = {
        "thread_id": "t1",
        "thread_text": "Hi Alex\n\nCould you send the revised Q3 draft by Friday so we can review?\n\nThanks, Kate",
        "participants": {"kate@x", "alex@x"},
        "shown_task_ids": {7},
        "new_message_ids": {"m2"},
        "message_dates": {"m1": MONDAY, "m2": date(2026, 11, 3)},
    }
    base.update(overrides)
    return ThreadInput(**base)


def _new_task(**overrides) -> NewTask:
    base = {
        "title": "Send Q3 draft",
        "owner_email": "alex@x",
        "due_date": "Friday",
        "status": "open",
        "confidence": 0.9,
        "evidence_quote": "Could you send the revised Q3 draft by Friday so we can review?",
        "source_message_id": "m2",
    }
    base.update(overrides)
    return NewTask(**base)


def test_validate_accepts_good_new_task():
    out = validate_extraction(ThreadExtraction(new_tasks=[_new_task()]), _thread_input())
    assert len(out.new_tasks) == 1 and not out.rejected
    assert out.new_tasks[0].due_date == date(2026, 11, 6)
    assert out.new_tasks[0].owner_email == "alex@x"


def test_validate_rejects_unlocatable_quote():
    task = _new_task(evidence_quote="This sentence appears nowhere in the email body at all.")
    out = validate_extraction(ThreadExtraction(new_tasks=[task]), _thread_input())
    assert out.new_tasks == [] and out.rejected[0].reason == "quote_not_found"


def test_validate_rejects_short_quote():
    task = _new_task(evidence_quote="send it")
    out = validate_extraction(ThreadExtraction(new_tasks=[task]), _thread_input())
    assert out.rejected[0].reason == "quote_too_short"


def test_validate_non_participant_owner_dropped_with_review():
    task = _new_task(owner_email="stranger@elsewhere")
    out = validate_extraction(ThreadExtraction(new_tasks=[task]), _thread_input())
    assert out.new_tasks[0].owner_email is None
    assert out.new_tasks[0].needs_review is True


def test_validate_unparseable_due_date_flags_review():
    task = _new_task(due_date="whenever possible")
    out = validate_extraction(ThreadExtraction(new_tasks=[task]), _thread_input())
    assert out.new_tasks[0].due_date is None
    assert out.new_tasks[0].needs_review is True


def test_validate_update_must_reference_shown_task():
    update = TaskUpdate(
        ref_task_id=999, status="done", confidence=0.9,
        evidence_quote="Could you send the revised Q3 draft by Friday so we can review?",
        source_message_id="m2",
    )
    out = validate_extraction(ThreadExtraction(updates=[update]), _thread_input())
    assert out.updates == [] and out.rejected[0].reason == "unknown_task_ref"


def test_validate_update_must_cite_new_email():
    update = TaskUpdate(
        ref_task_id=7, status="done", confidence=0.9,
        evidence_quote="Could you send the revised Q3 draft by Friday so we can review?",
        source_message_id="m1",  # processed already
    )
    out = validate_extraction(
        ThreadExtraction(updates=[update]), _thread_input(new_message_ids={"m2"})
    )
    assert out.updates == [] and out.rejected[0].reason == "stale_email"


def test_validate_accepts_update_with_new_email_citation():
    update = TaskUpdate(
        ref_task_id=7, status="done", confidence=0.9,
        evidence_quote="Could you send the revised Q3 draft by Friday so we can review?",
        source_message_id="m2",
    )
    out = validate_extraction(ThreadExtraction(updates=[update]), _thread_input())
    assert len(out.updates) == 1


# -- reconcile ------------------------------------------------------------------------


def _validated(new_tasks=(), updates=()):
    return ValidatedExtraction(thread_id="t1", new_tasks=list(new_tasks), updates=list(updates))


def _vnew(title="Send Q3 draft", owner="alex@x", due=date(2026, 11, 6), msg="m2"):
    return ValidatedNew(
        task=_new_task(title=title, owner_email=owner, source_message_id=msg),
        owner_email=owner, due_date=due, needs_review=False,
    )


def test_reconcile_inserts_new_task():
    out = reconcile(_validated(new_tasks=[_vnew()]), existing=[], processed_message_ids=set())
    assert len(out.inserts) == 1 and not out.drops and not out.suggestions


def test_reconcile_drops_repeat_from_processed_email():
    out = reconcile(_validated(new_tasks=[_vnew()]), existing=[], processed_message_ids={"m2"})
    assert out.inserts == [] and out.drops[0].title == "Send Q3 draft"


def test_reconcile_two_tasks_same_sentence_both_survive():
    a, b = _vnew(title="Send invoice"), _vnew(title="Update tracker")
    out = reconcile(_validated(new_tasks=[a, b]), existing=[], processed_message_ids=set())
    assert len(out.inserts) == 2 and not out.suggestions


def test_reconcile_duplicate_suggested_not_merged():
    existing = [ExistingTask(1, "Send Q3 draft", "alex@x", date(2026, 11, 6), "open", None)]
    out = reconcile(_validated(new_tasks=[_vnew()]), existing=existing, processed_message_ids=set())
    assert len(out.inserts) == 1  # still inserted
    assert out.suggestions[0].kind == "possible_duplicate"
    assert out.suggestions[0].task_id == 1


def test_reconcile_recurring_over_seven_days_never_suggested():
    existing = [ExistingTask(1, "Send Q3 draft", "alex@x", date(2026, 10, 20), "open", None)]
    out = reconcile(_validated(new_tasks=[_vnew(due=date(2026, 11, 6))]), existing=existing, processed_message_ids=set())
    assert len(out.inserts) == 1 and not out.suggestions


def test_reconcile_low_confidence_done_becomes_suggestion():
    existing = [ExistingTask(1, "Refresh cert", "alex@x", None, "open", None)]
    update = ValidatedUpdate(
        update=TaskUpdate(
            ref_task_id=1, status="done", confidence=0.3,
            evidence_quote="might be done", source_message_id="m2",
        ),
        owner_email=None, due_date=None, needs_review=True,
    )
    out = reconcile(_validated(updates=[update]), existing=existing, processed_message_ids=set())
    assert out.updates == []
    assert out.suggestions[0].kind == "low_confidence_done"


def test_reconcile_normal_update_applied():
    existing = [ExistingTask(1, "Send Q3 draft", "alex@x", date(2026, 11, 6), "open", None)]
    update = ValidatedUpdate(
        update=TaskUpdate(
            ref_task_id=1, status="done", confidence=0.9,
            evidence_quote="sent it just now", source_message_id="m2",
        ),
        owner_email="alex@x", due_date=None, needs_review=False,
    )
    out = reconcile(_validated(updates=[update]), existing=existing, processed_message_ids=set())
    assert len(out.updates) == 1 and out.updates[0].status == "done"
    assert not out.suggestions
