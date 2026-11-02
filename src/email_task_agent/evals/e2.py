"""E2 reconciliation eval (plan §9): recorded-output scenarios, must pass 100%.

Each scenario declares: initial open tasks, a validated extraction (the
"recorded output" of the Extract+Validate stages, hand-labeled), processed
message ids, and the EXACT expected ops reconcile() must produce. No model
involved — this pins the reconciliation rules of rev 5 §7.3.

  uv run python -m email_task_agent.evals.e2
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date

from email_task_agent.models.extraction import NewTask, TaskUpdate
from email_task_agent.pipeline.reconcile import (
    ApplyUpdate,
    ExistingTask,
    reconcile,
)
from email_task_agent.pipeline.validate import ValidatedExtraction, ValidatedNew, ValidatedUpdate


@dataclass
class Scenario:
    name: str
    existing: list[ExistingTask] = field(default_factory=list)
    processed: set[str] = field(default_factory=set)
    new_tasks: list[ValidatedNew] = field(default_factory=list)
    updates: list[ValidatedUpdate] = field(default_factory=list)
    expected_insert_titles: list[str] = field(default_factory=list)
    expected_update_keys: list[tuple] = field(default_factory=list)  # (task_id, field, new)
    expected_suggestions: list[tuple] = field(default_factory=list)  # (kind, task_id)
    expected_drops: list[str] = field(default_factory=list)  # titles


def _new(title, owner, due, quote, msg="m2-new", confidence=1.0) -> ValidatedNew:
    return ValidatedNew(
        task=NewTask(
            title=title, owner_email=owner,
            due_date=due.isoformat() if due else None,  # NewTask carries the raw/stated date
            status="open", confidence=confidence, evidence_quote=quote, source_message_id=msg,
        ),
        owner_email=owner, due_date=due, needs_review=False,
    )


def _update(ref, *, status=None, owner=None, due=None, quote="q", msg="m2-new", confidence=1.0) -> ValidatedUpdate:
    payload = TaskUpdate(
        ref_task_id=ref, title=None, owner_email=owner, due_date=due, status=status,
        confidence=confidence, evidence_quote=quote, source_message_id=msg,
    )
    return ValidatedUpdate(update=payload, owner_email=owner, due_date=due, needs_review=confidence < 0.5)


def _run(scenario: Scenario) -> tuple[bool, str]:
    validated = ValidatedExtraction(
        thread_id="t", new_tasks=scenario.new_tasks, updates=scenario.updates
    )
    out = reconcile(validated, scenario.existing, scenario.processed)

    problems = []
    got_titles = sorted(i.task.title for i in out.inserts)
    if got_titles != sorted(scenario.expected_insert_titles):
        problems.append(f"inserts {got_titles} != {sorted(scenario.expected_insert_titles)}")
    got_updates = sorted((u.task_id, field_name, new_value) for u in out.updates
                         for field_name, new_value in _update_fields(u))
    if got_updates != sorted(scenario.expected_update_keys):
        problems.append(f"updates {got_updates} != {sorted(scenario.expected_update_keys)}")
    got_suggestions = sorted((s.kind, s.task_id) for s in out.suggestions)
    if got_suggestions != sorted(scenario.expected_suggestions):
        problems.append(f"suggestions {got_suggestions} != {sorted(scenario.expected_suggestions)}")
    got_drops = sorted(d.title for d in out.drops)
    if got_drops != sorted(scenario.expected_drops):
        problems.append(f"drops {got_drops} != {sorted(scenario.expected_drops)}")
    return not problems, "; ".join(problems)


def _update_fields(u: ApplyUpdate):
    if u.status is not None:
        yield "status", u.status
    if u.owner_email is not None:
        yield "owner", u.owner_email
    if u.due_date is not None:
        yield "due", str(u.due_date)


def build_scenarios() -> list[Scenario]:
    return [
        Scenario(
            name="look-alike tasks in one thread both survive",
            new_tasks=[
                _new("Review contract draft", "a@x", date(2026, 11, 6), "review the contract draft by friday"),
                _new("Review contract redlines", "a@x", date(2026, 11, 6), "review the contract draft by friday"),
            ],
            expected_insert_titles=["Review contract draft", "Review contract redlines"],
        ),
        Scenario(
            name="weekly recurring: same title, dues >7d apart, never suggested",
            existing=[ExistingTask(1, "Post weekly standup notes", "a@x", date(2026, 11, 6), "open", None)],
            new_tasks=[_new("post weekly standup notes", "a@x", date(2026, 11, 16), "post the notes")],
            expected_insert_titles=["post weekly standup notes"],
        ),
        Scenario(
            name="request re-sent in a new thread: suggestion, no merge",
            existing=[ExistingTask(1, "Send signed contract", "a@x", date(2026, 11, 6), "open", None)],
            new_tasks=[_new("Send signed contract", "a@x", date(2026, 11, 9), "please send the signed contract")],
            expected_insert_titles=["Send signed contract"],
            expected_suggestions=[("possible_duplicate", 1)],
        ),
        Scenario(
            name="one email completing two tasks",
            existing=[
                ExistingTask(1, "Send invoice", "a@x", date(2026, 11, 6), "open", None),
                ExistingTask(2, "Update tracker", "a@x", date(2026, 11, 6), "open", None),
            ],
            updates=[
                _update(1, status="done", quote="invoice sent and tracker updated"),
                _update(2, status="done", quote="invoice sent and tracker updated"),
            ],
            expected_update_keys=[(1, "status", "done"), (2, "status", "done")],
        ),
        Scenario(
            name="handoff to another person",
            existing=[ExistingTask(1, "Prepare demo env", "a@x", date(2026, 11, 6), "open", None)],
            updates=[_update(1, owner="b@x", quote="b will prepare the demo env")],
            expected_update_keys=[(1, "owner", "b@x")],
        ),
        Scenario(
            name="quote from processed email dropped as repeat",
            processed={"m1-old"},
            new_tasks=[_new("File expense report", "a@x", date(2026, 11, 6), "file the expense report", msg="m1-old")],
            expected_drops=["File expense report"],
        ),
        Scenario(
            name="low-confidence done goes to review, not applied",
            existing=[ExistingTask(1, "Refresh SSL cert", "a@x", date(2026, 11, 6), "open", None)],
            updates=[_update(1, status="done", quote="i think that got done", confidence=0.4)],
            expected_suggestions=[("low_confidence_done", 1)],
        ),
        Scenario(
            name="undated look-alike same owner: suggestion (window rule)",
            existing=[ExistingTask(1, "Order team shirts", "a@x", None, "open", None)],
            new_tasks=[_new("order team shirts", "a@x", None, "order shirts")],
            expected_insert_titles=["order team shirts"],
            expected_suggestions=[("possible_duplicate", 1)],
        ),
    ]


def main() -> int:
    passed = 0
    failures = []
    for scenario in build_scenarios():
        ok, problems = _run(scenario)
        if ok:
            passed += 1
        else:
            failures.append((scenario.name, problems))
    print(f"E2 reconciliation: {passed}/{len(build_scenarios())} scenarios pass (gate: 100%)")
    for name, problems in failures:
        print(f"  FAIL {name}: {problems}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
