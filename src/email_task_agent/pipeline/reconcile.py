"""Reconcile stage: no auto-merging, lean against merging.

Pure function producing persistable ops. Rules:
  - a task whose quote comes from an already-processed email is dropped as a repeat;
  - two different tasks stated in the same new sentence both survive;
  - possible duplicates become suggestions — never automatic merges
    (recurring tasks: same title with due dates more than 7 days apart are
    never suggested);
  - low-confidence "mark as done" updates become suggestions;
  - other validated updates are applied and recorded as task_events;
  - merges happen only when the user accepts a suggestion (accept flow uses
    merge_ops below; undoable via split using the snapshot in the event).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from email_task_agent.models.extraction import NewTask
from email_task_agent.pipeline.validate import ValidatedExtraction, ValidatedNew

DUPLICATE_WINDOW_DAYS = 7


@dataclass(frozen=True)
class ExistingTask:
    id: int
    title: str
    owner_email: str | None
    due_date: date | None
    status: str
    thread_id: int | None
    needs_review: bool = False


@dataclass(frozen=True)
class InsertTask:
    task: NewTask
    owner_email: str | None
    due_date: date | None
    needs_review: bool


@dataclass(frozen=True)
class ApplyUpdate:
    task_id: int
    title: str | None
    owner_email: str | None
    due_date: date | None
    status: str | None
    confidence: float
    needs_review: bool
    source_message_id: str
    evidence_quote: str


@dataclass(frozen=True)
class Suggest:
    kind: str  # possible_duplicate | low_confidence_done
    payload: dict
    task_id: int | None = None  # existing task the suggestion is about
    other_task_id: int | None = None


@dataclass(frozen=True)
class DropRepeat:
    title: str
    source_message_id: str


@dataclass
class ReconcileOutput:
    inserts: list[InsertTask] = field(default_factory=list)
    updates: list[ApplyUpdate] = field(default_factory=list)
    suggestions: list[Suggest] = field(default_factory=list)
    drops: list[DropRepeat] = field(default_factory=list)


def _normalized_title(title: str) -> str:
    return " ".join(title.casefold().split())


def _within_duplicate_window(a: date | None, b: date | None) -> bool:
    if a is None or b is None:
        return True  # undated tasks can't be excluded by the recurring rule
    return abs((a - b).days) <= DUPLICATE_WINDOW_DAYS


def _duplicate_of(new: ValidatedNew, existing: list[ExistingTask]) -> ExistingTask | None:
    """Same normalized title + same owner, due dates within the window (or
    undated). Recurring tasks (same title, dues > 7 days apart) never match."""
    owner = new.owner_email
    for task in existing:
        if task.status != "open":
            continue
        if owner and task.owner_email and owner != task.owner_email:
            continue
        if owner is None and task.owner_email is not None:
            continue
        if _normalized_title(new.task.title) != _normalized_title(task.title):
            continue
        if _within_duplicate_window(new.due_date, task.due_date):
            return task
    return None


def reconcile(
    validated: ValidatedExtraction,
    existing: list[ExistingTask],
    processed_message_ids: set[str],
) -> ReconcileOutput:
    out = ReconcileOutput()

    for new in validated.new_tasks:
        if new.task.source_message_id in processed_message_ids:
            out.drops.append(DropRepeat(new.task.title, new.task.source_message_id))
            continue
        out.inserts.append(
            InsertTask(
                task=new.task,
                owner_email=new.owner_email,
                due_date=new.due_date,
                needs_review=new.needs_review,
            )
        )
        if dup := _duplicate_of(new, existing):
            out.suggestions.append(
                Suggest(
                    kind="possible_duplicate",
                    task_id=dup.id,
                    payload={
                        "new_title": new.task.title,
                        "new_owner": new.owner_email,
                        "new_due": new.due_date.isoformat() if new.due_date else None,
                        "evidence_quote": new.task.evidence_quote,
                        "source_message_id": new.task.source_message_id,
                    },
                )
            )

    for upd in validated.updates:
        payload_update = upd.update
        if payload_update.status == "done" and upd.needs_review:
            out.suggestions.append(
                Suggest(
                    kind="low_confidence_done",
                    task_id=payload_update.ref_task_id,
                    payload={
                        "evidence_quote": payload_update.evidence_quote,
                        "source_message_id": payload_update.source_message_id,
                        "confidence": payload_update.confidence,
                    },
                )
            )
            continue
        out.updates.append(
            ApplyUpdate(
                task_id=payload_update.ref_task_id,
                title=payload_update.title,
                owner_email=upd.owner_email,
                due_date=upd.due_date,
                status=payload_update.status,
                confidence=payload_update.confidence,
                needs_review=upd.needs_review,
                source_message_id=payload_update.source_message_id,
                evidence_quote=payload_update.evidence_quote,
            )
        )

    return out


@dataclass(frozen=True)
class MergeOps:
    """Produced when a user ACCEPTS a possible_duplicate suggestion."""

    primary_id: int
    secondary_id: int


def merge_ops(suggestion_task_id: int, other_task_id: int, keep_id: int) -> MergeOps:
    """keep_id decides which row survives; the other is folded into it."""
    secondary = other_task_id if keep_id == suggestion_task_id else suggestion_task_id
    primary = keep_id
    return MergeOps(primary_id=primary, secondary_id=secondary)
