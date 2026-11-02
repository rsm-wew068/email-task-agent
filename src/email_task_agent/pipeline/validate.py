"""Validate stage (§7): evidence quotes, participants, parseable dates.

Pure functions — no I/O. Every check here is a plan rule:
  - the evidence quote must be locatable in the thread text (uses the frozen
    evidence module, so eval and runtime agree on what "real quote" means);
  - a stated owner must be a thread participant (else owner=None + review);
  - a stated due date must parse (else None + review);
  - updates must reference a task ID that was shown in the Extract context
    and cite a sentence from a NEW email (§7.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from email_task_agent import evidence
from email_task_agent.models.extraction import NewTask, TaskUpdate
from email_task_agent.pipeline.dates import resolve_due_date

LOW_CONFIDENCE = 0.5


@dataclass(frozen=True)
class ValidatedNew:
    task: NewTask
    owner_email: str | None
    due_date: date | None
    needs_review: bool


@dataclass(frozen=True)
class ValidatedUpdate:
    update: TaskUpdate
    owner_email: str | None
    due_date: date | None
    needs_review: bool


@dataclass(frozen=True)
class Rejected:
    kind: str  # new | update
    title_or_ref: str
    reason: str  # quote_not_found | quote_too_short | unknown_task_ref | stale_email | bad_message_ref


@dataclass(frozen=True)
class ValidatedExtraction:
    thread_id: str
    new_tasks: list[ValidatedNew] = field(default_factory=list)
    updates: list[ValidatedUpdate] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)


@dataclass(frozen=True)
class ThreadInput:
    """What the Extract stage was shown, and what counts as 'new'."""

    thread_id: str
    thread_text: str
    participants: set[str]  # casefolded email addresses
    shown_task_ids: set[int]
    new_message_ids: set[str]
    message_dates: dict[str, date]  # message id -> internal date (anchor for relative dates)


def _check_quote(kind: str, label: str, quote: str, inp: ThreadInput) -> Rejected | None:
    if len(evidence.tokenize(quote)) < evidence.MIN_QUOTE_TOKENS:
        return Rejected(kind, label, "quote_too_short")
    if evidence.locate_quote(quote, inp.thread_text) is None:
        return Rejected(kind, label, "quote_not_found")
    return None


def _check_owner(owner_email: str | None, inp: ThreadInput) -> tuple[str | None, bool]:
    if not owner_email:
        return None, False
    normalized = owner_email.strip().casefold()
    if normalized in inp.participants:
        return normalized, False
    return None, True  # not a participant: drop the owner, flag for review


def _resolve_due(raw: str | None, inp: ThreadInput, source_message_id: str) -> tuple[date | None, bool]:
    if not raw:
        return None, False
    anchor = inp.message_dates.get(source_message_id)
    resolved = resolve_due_date(raw, anchor) if anchor else None
    return resolved, resolved is None  # stated but unparseable -> review


def validate_extraction(extraction, inp: ThreadInput) -> ValidatedExtraction:
    out = ValidatedExtraction(thread_id=inp.thread_id)

    for task in extraction.new_tasks:
        if rejection := _check_quote("new", task.title, task.evidence_quote, inp):
            out.rejected.append(rejection)
            continue
        if task.source_message_id not in inp.message_dates:
            out.rejected.append(Rejected("new", task.title, "bad_message_ref"))
            continue
        owner, owner_review = _check_owner(task.owner_email, inp)
        due, due_review = _resolve_due(task.due_date, inp, task.source_message_id)
        out.new_tasks.append(
            ValidatedNew(
                task=task,
                owner_email=owner,
                due_date=due,
                needs_review=owner_review or due_review or task.confidence < LOW_CONFIDENCE,
            )
        )

    for update in extraction.updates:
        label = f"task#{update.ref_task_id}"
        if rejection := _check_quote("update", label, update.evidence_quote, inp):
            out.rejected.append(rejection)
            continue
        if update.ref_task_id not in inp.shown_task_ids:
            out.rejected.append(Rejected("update", label, "unknown_task_ref"))
            continue
        if update.source_message_id not in inp.new_message_ids:
            # §7.3: updates must cite a NEW email; quotes from already-processed
            # emails are stale by definition.
            out.rejected.append(Rejected("update", label, "stale_email"))
            continue
        owner, owner_review = _check_owner(update.owner_email, inp)
        due, due_review = _resolve_due(update.due_date, inp, update.source_message_id)
        out.updates.append(
            ValidatedUpdate(
                update=update,
                owner_email=owner,
                due_date=due,
                needs_review=owner_review or due_review or update.confidence < LOW_CONFIDENCE,
            )
        )

    return out
