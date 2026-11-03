"""SQL store (psycopg 3, plain SQL). Single module so the schema's shape and
the queries stay reviewable together.

Sections:
  - people/threads/messages upserts (sync helpers)
  - pipeline op application: inserts, updates (as task_events), suggestions,
    merges + split (undo), one transaction per thread via apply_thread_ops
  - web reads/writes: task list/detail, calendar, status change, suggestion
    accept/reject, re-extract marks
  - chat sessions (version-checked CAS state machine) + idempotent actions
    (rows keyed by tool_call_id recorded BEFORE the external call)

Web endpoints and the sync service depend on the Store Protocol defined at
the bottom; tests run against an in-memory implementation with identical
semantics (see tests/fakes.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb

from email_task_agent.pipeline.reconcile import (
    ApplyUpdate,
    ExistingTask,
    InsertTask,
    MergeOps,
    ReconcileOutput,
)


@dataclass(frozen=True)
class TaskRow:
    id: int
    title: str
    owner_email: str | None
    owner_name: str | None
    due_date: date | None
    status: str
    confidence: float | None
    needs_review: bool
    thread_id: int | None
    gmail_thread_id: str | None


@dataclass(frozen=True)
class EventRow:
    id: int
    task_id: int
    at: datetime
    kind: str
    old: dict | None
    new: dict | None
    source_message_id: str | None


@dataclass(frozen=True)
class SuggestionRow:
    id: int
    kind: str
    task_id: int | None
    other_task_id: int | None
    payload: dict
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ThreadRow:
    id: int
    gmail_thread_id: str
    subject: str | None
    participants: list[str]
    last_message_at: datetime | None
    last_extracted_history_id: str | None
    cached_text: str | None


@dataclass
class ChatSessionRow:
    id: int
    messages: list[dict]
    pending_approvals: dict | None
    state: str
    version: int


class Store(Protocol):
    """The union of sync, web, and chat storage needs (see method docs below)."""

    # -- sync helpers (Gmail -> DB mirror) ------------------------------------------
    def upsert_person(self, email: str, display_name: str | None = None) -> int: ...
    def upsert_thread(
        self,
        gmail_thread_id: str,
        *,
        subject: str | None,
        participants: list[str],
        last_message_at: datetime | None,
        cached_text: str | None,
    ) -> int: ...
    def upsert_message(self, gmail_message_id: str, thread_db_id: int, internal_date: datetime | None) -> None: ...
    def thread_message_sets(self, thread_db_id: int) -> tuple[set[str], set[str]]:
        """(processed, unprocessed) message id sets for a thread."""

    def open_tasks_for(self, participant_emails: list[str]) -> list[ExistingTask]: ...
    def tasks_in_thread(self, thread_db_id: int) -> list[TaskRow]:
        """All tasks (any status) attached to one thread — per-thread seeding guard."""

    def apply_thread_ops(
        self, thread_db_id: int, output: ReconcileOutput, *, new_message_ids: list[str], history_id: str | None
    ) -> list[int]:
        """One transaction: ops + processed marks + per-thread history advance."""

    def get_sync_state(self) -> tuple[str | None, datetime | None]: ...
    def advance_sync_state(self, last_history_id: str, *, full_sync: bool = False) -> None: ...
    def reset_thread_processed(self, gmail_thread_id: str) -> int:
        """Un-mark all processed messages of a thread (manual re-extract); returns thread db id."""

    def update_task_fields(self, task_id: int, *, title: str | None = None, due_date: date | None = None, clear_due: bool = False) -> bool: ...

    def chat_turns_today(self) -> int:
        """LLM chat turns recorded today (demo spend cap, review finding 2)."""
    def record_chat_turn(self) -> None: ...

    # -- chat (§8.2 state machine) -------------------------------------------------
    def chat_create(self) -> int: ...
    def chat_get(self, session_id: int) -> ChatSessionRow | None: ...
    def chat_cas(
        self,
        session_id: int,
        expected_version: int,
        *,
        messages: list[dict],
        pending_approvals: dict | None,
        state: str,
    ) -> int | None:
        """Conditional update: returns the new version, or None when the
        stored version no longer matches (stale form / double click)."""
    def action_record(self, kind: str, args: dict, tool_call_id: str) -> tuple[int, bool]:
        """Idempotency gate: insert a proposed action keyed by tool_call_id.
        Returns (action_id, is_new); a retry after a crash gets the original
        row back (is_new=False) and must NOT resend."""

    def action_mark_sent(self, action_id: int) -> None:
        """proposed -> approved: set immediately BEFORE the external call, so a
        crash after the call leaves 'approved' and the retry refuses to send."""

    def action_mark_executed(self, action_id: int, external_id: str) -> None: ...
    def action_get(self, action_id: int) -> dict | None: ...

    # -- web pages -----------------------------------------------------------------
    def list_tasks(self, *, q: str | None = None, status: str | None = None) -> list[TaskRow]: ...
    def task_detail(self, task_id: int) -> tuple[TaskRow, list[EventRow], list[SuggestionRow]] | None: ...
    def pending_suggestions(self) -> list[SuggestionRow]: ...
    def tasks_due_between(self, start: date, end: date) -> list[TaskRow]: ...
    def list_threads(self) -> list[ThreadRow]: ...
    def thread_by_gmail_id(self, gmail_thread_id: str) -> ThreadRow | None: ...
    def set_task_status(self, task_id: int, status: str) -> bool: ...
    def accept_suggestion(self, suggestion_id: int, keep_id: int | None = None) -> bool: ...
    def reject_suggestion(self, suggestion_id: int) -> bool: ...
    def split_merge(self, task_id: int) -> bool: ...


def upsert_person(conn: psycopg.Connection, email: str, display_name: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into people (email, display_name)
            values (%s, %s)
            on conflict (email) do update
                set display_name = coalesce(excluded.display_name, people.display_name)
            returning id
            """,
            (email.strip().casefold(), display_name),
        )
        return cur.fetchone()[0]


def upsert_thread(
    conn: psycopg.Connection,
    gmail_thread_id: str,
    *,
    subject: str | None,
    participants: list[str],
    last_message_at: datetime | None,
    cached_text: str | None,
) -> int:
    emails = [p.strip().casefold() for p in participants if p]
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into threads (gmail_thread_id, subject, participants, last_message_at, cached_text)
            values (%s, %s, %s, %s, %s)
            on conflict (gmail_thread_id) do update
                set subject = excluded.subject,
                    participants = excluded.participants,
                    last_message_at = greatest(threads.last_message_at, excluded.last_message_at),
                    cached_text = coalesce(excluded.cached_text, threads.cached_text)
            returning id
            """,
            (gmail_thread_id, subject, emails, last_message_at, cached_text),
        )
        return cur.fetchone()[0]


def upsert_message(
    conn: psycopg.Connection, gmail_message_id: str, thread_db_id: int, internal_date: datetime | None
) -> None:
    conn.execute(
        """
        insert into thread_messages (gmail_message_id, thread_id, internal_date)
        values (%s, %s, %s)
        on conflict (gmail_message_id) do nothing
        """,
        (gmail_message_id, thread_db_id, internal_date),
    )


def message_id_sets(conn: psycopg.Connection, thread_db_id: int) -> tuple[set[str], set[str]]:
    """(processed, unprocessed) message id sets for a thread (§7.3 repeat rules)."""
    with conn.cursor() as cur:
        cur.execute(
            "select gmail_message_id, processed_at is not null from thread_messages where thread_id = %s",
            (thread_db_id,),
        )
        processed, unprocessed = set(), set()
        for mid, done in cur.fetchall():
            (processed if done else unprocessed).add(mid)
        return processed, unprocessed


def mark_messages_processed(conn: psycopg.Connection, message_ids: list[str]) -> None:
    if not message_ids:
        return
    conn.execute(
        "update thread_messages set processed_at = now() where gmail_message_id = any(%s)",
        (message_ids,),
    )


def tasks_in_thread_db(conn: psycopg.Connection, thread_db_id: int) -> list[TaskRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.id, t.title, p.email, p.display_name, t.due_date, t.status,
                   t.confidence, t.needs_review, t.thread_id, th.gmail_thread_id
            from tasks t
            left join people p on p.id = t.owner_person_id
            left join threads th on th.id = t.thread_id
            where t.thread_id = %s
            order by t.id
            """,
            (thread_db_id,),
        )
        return [TaskRow(*r) for r in cur.fetchall()]


def open_tasks_as_existing(conn: psycopg.Connection, participant_emails: list[str]) -> list[ExistingTask]:
    """Open tasks owned by the thread's participants — the task IDs shown to
    the Extract stage so updates can reference them (§7.3)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.id, t.title, p.email, t.due_date, t.status, t.thread_id, t.needs_review
            from tasks t left join people p on p.id = t.owner_person_id
            where t.status = 'open' and (p.email = any(%s) or p.email is null)
            order by t.updated_at desc
            limit 200
            """,
            (participant_emails,),
        )
        return [
            ExistingTask(id=r[0], title=r[1], owner_email=r[2], due_date=r[3], status=r[4], thread_id=r[5], needs_review=r[6])
            for r in cur.fetchall()
        ]


def _task_event(cur, task_id: int, kind: str, old: dict | None, new: dict | None, source_message_id: str | None) -> None:
    cur.execute(
        """
        insert into task_events (task_id, kind, old, new, source_message_id)
        values (%s, %s, %s, %s, %s)
        """,
        (task_id, kind, Jsonb(old) if old is not None else None, Jsonb(new) if new is not None else None, source_message_id),
    )


def apply_insert(conn: psycopg.Connection, ins: InsertTask, thread_db_id: int) -> int:
    owner_id = upsert_person(conn, ins.owner_email) if ins.owner_email else None
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into tasks (title, owner_person_id, due_date, status, confidence, needs_review, thread_id)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                ins.task.title,
                owner_id,
                ins.due_date,
                ins.task.status,
                ins.task.confidence,
                ins.needs_review,
                thread_db_id,
            ),
        )
        task_id = cur.fetchone()[0]
        cur.execute(
            "insert into task_sources (task_id, gmail_message_id, evidence_quote, kind) values (%s, %s, %s, 'creation')",
            (task_id, ins.task.source_message_id, ins.task.evidence_quote),
        )
        _task_event(
            cur,
            task_id,
            "created",
            None,
            {"title": ins.task.title, "owner": ins.owner_email, "due": str(ins.due_date) if ins.due_date else None, "status": ins.task.status},
            ins.task.source_message_id,
        )
    return task_id


_FIELD_EVENTS = (("title", "title_changed"), ("owner_email", "owner_changed"), ("due_date", "due_changed"), ("status", "status_changed"))


def apply_update(conn: psycopg.Connection, upd: ApplyUpdate) -> bool:
    """Diff-apply an update; each changed field gets its own task_event."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.title, p.email, t.due_date, t.status
            from tasks t left join people p on p.id = t.owner_person_id
            where t.id = %s for update
            """,
            (upd.task_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        old_title, old_owner, old_due, old_status = row

        owner_id = upsert_person(conn, upd.owner_email) if upd.owner_email else None
        new_title = upd.title if upd.title is not None else old_title
        new_owner = upd.owner_email if upd.owner_email is not None else old_owner
        new_due = upd.due_date if upd.due_date is not None else old_due
        new_status = upd.status if upd.status is not None else old_status

        cur.execute(
            """
            update tasks set title = %s, owner_person_id = %s, due_date = %s, status = %s,
                confidence = %s, needs_review = %s, updated_at = now()
            where id = %s
            """,
            (new_title, owner_id, new_due, new_status, upd.confidence, upd.needs_review, upd.task_id),
        )
        changes = {
            "title_changed": (old_title, new_title),
            "owner_changed": (old_owner, new_owner),
            "due_changed": (str(old_due) if old_due else None, str(new_due) if new_due else None),
            "status_changed": (old_status, new_status),
        }
        for kind, (old_value, new_value) in changes.items():
            if old_value != new_value:
                _task_event(cur, upd.task_id, kind, {"value": old_value}, {"value": new_value}, upd.source_message_id)
        cur.execute(
            "insert into task_sources (task_id, gmail_message_id, evidence_quote, kind) values (%s, %s, %s, 'update')",
            (upd.task_id, upd.source_message_id, upd.evidence_quote),
        )
    return True


def apply_reconcile_output(conn: psycopg.Connection, out: ReconcileOutput, thread_db_id: int) -> list[int]:
    """Apply all safe ops; return inserted task ids. Caller owns the transaction."""
    inserted: list[int] = []
    for ins in out.inserts:
        inserted.append(apply_insert(conn, ins, thread_db_id))
    for upd in out.updates:
        apply_update(conn, upd)
    for sug in out.suggestions:
        with conn.cursor() as cur:
            cur.execute(
                "insert into suggestions (kind, task_id, other_task_id, payload) values (%s, %s, %s, %s)",
                (sug.kind, sug.task_id, sug.other_task_id, Jsonb(sug.payload)),
            )
    return inserted


def merge_task_rows(conn: psycopg.Connection, ops: MergeOps) -> bool:
    """Fold secondary into primary, keeping the audit trail: sources and events
    move to the primary; a 'merged' event snapshots the secondary for split."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.title, p.email, t.due_date, t.status
            from tasks t left join people p on p.id = t.owner_person_id
            where t.id = %s for update
            """,
            (ops.secondary_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        title, owner_email, due, status = row
        snapshot = {
            "title": title,
            "owner": owner_email,
            "due": str(due) if due else None,
            "status": status,
        }

        cur.execute("update task_sources set task_id = %s where task_id = %s", (ops.primary_id, ops.secondary_id))
        cur.execute(
            """
            insert into task_collaborators (task_id, person_id)
            select %s, person_id from task_collaborators where task_id = %s
            on conflict do nothing
            """,
            (ops.primary_id, ops.secondary_id),
        )
        cur.execute(
            """
            update task_events set task_id = %s
            where task_id = %s
            returning id
            """,
            (ops.primary_id, ops.secondary_id),
        )
        moved_event_ids = [r[0] for r in cur.fetchall()]
        snapshot["moved_event_ids"] = moved_event_ids

        cur.execute("delete from tasks where id = %s", (ops.secondary_id,))
        _task_event(cur, ops.primary_id, "merged", None, {"merged_task_id": ops.secondary_id, "snapshot": snapshot}, None)
    return True


def split_merged_task(conn: psycopg.Connection, task_id: int) -> bool:
    """Undo the most recent merge on a task using its snapshot event."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, new from task_events
            where task_id = %s and kind = 'merged'
            order by id desc limit 1
            """,
            (task_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        event_id, payload = row
        snapshot = payload["snapshot"]

        cur.execute("delete from task_events where id = %s", (event_id,))
        for eid in snapshot.get("moved_event_ids", []):
            cur.execute("update task_events set task_id = %s where id = %s", (task_id, eid))
        # Re-create the folded task with a fresh id; its sources stayed on the
        # primary, so re-attach the ones the snapshot's events point at.
        owner_id = None
        if snapshot.get("owner"):
            owner_id = upsert_person(conn, snapshot["owner"])
        cur.execute(
            """
            insert into tasks (title, owner_person_id, due_date, status, needs_review)
            values (%s, %s, %s, %s, true)
            returning id
            """,
            (snapshot["title"], owner_id, snapshot["due"] or None, snapshot["status"]),
        )
        new_id = cur.fetchone()[0]
        cur.execute(
            """
            insert into task_sources (task_id, gmail_message_id, evidence_quote, kind)
            select %s, gmail_message_id, evidence_quote, kind from task_sources
            where task_id = %s and kind = 'creation'
            """,
            (new_id, task_id),
        )
        _task_event(cur, new_id, "created", None, {"restored_from_split_of": task_id}, None)
        _task_event(cur, task_id, "split", {"value": task_id}, {"value": new_id}, None)
    return True


# -- web reads/writes -----------------------------------------------------------


def list_tasks_db(conn: psycopg.Connection, *, q: str | None = None, status: str | None = None) -> list[TaskRow]:
    clauses, params = ["true"], []
    if q:
        clauses.append("t.search @@ plainto_tsquery('english', %s)")
        params.append(q)
    if status:
        clauses.append("t.status = %s")
        params.append(status)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select t.id, t.title, p.email, p.display_name, t.due_date, t.status,
                   t.confidence, t.needs_review, t.thread_id, th.gmail_thread_id
            from tasks t
            left join people p on p.id = t.owner_person_id
            left join threads th on th.id = t.thread_id
            where {' and '.join(clauses)}
            order by t.due_date nulls last, t.id desc
            """,
            params,
        )
        return [TaskRow(*r) for r in cur.fetchall()]


def task_detail_db(conn: psycopg.Connection, task_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.id, t.title, p.email, p.display_name, t.due_date, t.status,
                   t.confidence, t.needs_review, t.thread_id, th.gmail_thread_id
            from tasks t
            left join people p on p.id = t.owner_person_id
            left join threads th on th.id = t.thread_id
            where t.id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        task = TaskRow(*row)
        cur.execute(
            """
            select id, task_id, at, kind, old, new, source_message_id
            from task_events where task_id = %s order by id desc
            """,
            (task_id,),
        )
        events = [EventRow(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in cur.fetchall()]
        cur.execute(
            "select id, kind, task_id, other_task_id, payload, status, created_at from suggestions where task_id = %s",
            (task_id,),
        )
        suggestions = [SuggestionRow(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in cur.fetchall()]
        return task, events, suggestions


def pending_suggestions_db(conn: psycopg.Connection) -> list[SuggestionRow]:
    with conn.cursor() as cur:
        cur.execute(
            "select id, kind, task_id, other_task_id, payload, status, created_at from suggestions "
            "where status = 'pending' order by id"
        )
        return [SuggestionRow(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in cur.fetchall()]


def tasks_due_between_db(conn: psycopg.Connection, start: date, end: date) -> list[TaskRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.id, t.title, p.email, p.display_name, t.due_date, t.status,
                   t.confidence, t.needs_review, t.thread_id, th.gmail_thread_id
            from tasks t
            left join people p on p.id = t.owner_person_id
            left join threads th on th.id = t.thread_id
            where t.due_date between %s and %s and t.status = 'open'
            order by t.due_date
            """,
            (start, end),
        )
        return [TaskRow(*r) for r in cur.fetchall()]


def list_threads_db(conn: psycopg.Connection) -> list[ThreadRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, gmail_thread_id, subject, participants, last_message_at,
                   last_extracted_history_id, cached_text
            from threads order by last_message_at desc nulls last
            """
        )
        return [ThreadRow(*r) for r in cur.fetchall()]


def thread_by_gmail_id_db(conn: psycopg.Connection, gmail_thread_id: str) -> ThreadRow | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, gmail_thread_id, subject, participants, last_message_at,
                   last_extracted_history_id, cached_text
            from threads where gmail_thread_id = %s
            """,
            (gmail_thread_id,),
        )
        row = cur.fetchone()
        return ThreadRow(*row) if row else None


def set_task_status_db(conn: psycopg.Connection, task_id: int, status: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("select status from tasks where id = %s for update", (task_id,))
        row = cur.fetchone()
        if row is None or row[0] == status:
            return False
        _task_event(cur, task_id, "status_changed", {"value": row[0]}, {"value": status}, None)
        cur.execute("update tasks set status = %s, updated_at = now() where id = %s", (status, task_id))
    return True


def accept_suggestion_db(conn: psycopg.Connection, suggestion_id: int, keep_id: int | None = None) -> bool:
    """possible_duplicate -> merge (keep_id picks the surviving row, default =
    the suggestion's existing task); low_confidence_done -> apply the status."""
    with conn.cursor() as cur:
        cur.execute(
            "select kind, task_id, other_task_id, payload from suggestions where id = %s and status = 'pending' for update",
            (suggestion_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        kind, task_id, other_task_id, _payload = row

    if kind == "possible_duplicate":
        primary = keep_id or task_id
        secondary = other_task_id
        if primary is None or secondary is None or primary == secondary:
            return False
        merge_task_rows(conn, MergeOps(primary_id=primary, secondary_id=secondary))
    elif kind == "low_confidence_done":
        if task_id is None:
            return False
        set_task_status_db(conn, task_id, "done")
    else:
        return False

    with conn.cursor() as cur:
        cur.execute("update suggestions set status = 'accepted', decided_at = now() where id = %s", (suggestion_id,))
    return True


def reject_suggestion_db(conn: psycopg.Connection, suggestion_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "update suggestions set status = 'rejected', decided_at = now() "
            "where id = %s and status = 'pending'",
            (suggestion_id,),
        )
        return cur.rowcount == 1


def split_merge_db(conn: psycopg.Connection, task_id: int) -> bool:
    return split_merged_task(conn, task_id)


# -- sync state -----------------------------------------------------------------


def get_sync_state(conn: psycopg.Connection) -> tuple[str | None, datetime | None]:
    with conn.cursor() as cur:
        cur.execute("select last_history_id, last_full_sync_at from sync_state where id = 1")
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def set_sync_state(conn: psycopg.Connection, last_history_id: str, *, full_sync: bool = False) -> None:
    conn.execute(
        """
        update sync_state set last_history_id = %s,
            last_full_sync_at = case when %s then now() else last_full_sync_at end,
            updated_at = now()
        where id = 1
        """,
        (last_history_id, full_sync),
    )


def advance_thread_extraction(conn: psycopg.Connection, thread_db_id: int, history_id: str) -> None:
    conn.execute("update threads set last_extracted_history_id = %s where id = %s", (history_id, thread_db_id))


# -- chat sessions + actions (§8.2) ---------------------------------------------


def chat_create_db(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("insert into chat_sessions default values returning id")
        return cur.fetchone()[0]


def chat_get_db(conn: psycopg.Connection, session_id: int) -> ChatSessionRow | None:
    with conn.cursor() as cur:
        cur.execute("select id, messages, pending_approvals, state, version from chat_sessions where id = %s", (session_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return ChatSessionRow(row[0], row[1] or [], row[2], row[3], row[4])


def chat_cas_db(
    conn: psycopg.Connection,
    session_id: int,
    expected_version: int,
    *,
    messages: list[dict],
    pending_approvals: dict | None,
    state: str,
) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update chat_sessions
            set messages = %s, pending_approvals = %s, state = %s, version = version + 1, updated_at = now()
            where id = %s and version = %s
            returning version
            """,
            (Jsonb(messages), Jsonb(pending_approvals) if pending_approvals is not None else None, state, session_id, expected_version),
        )
        row = cur.fetchone()
        return row[0] if row else None


def action_record_db(conn: psycopg.Connection, kind: str, args: dict, tool_call_id: str) -> tuple[int, bool]:
    """Record BEFORE any external call; the unique tool_call_id makes retries
    after a crash return the original row instead of sending twice."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into actions (kind, args, status, tool_call_id)
            values (%s, %s, 'proposed', %s)
            on conflict (tool_call_id) do nothing
            returning id
            """,
            (kind, Jsonb(args), tool_call_id),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0], True
        cur.execute("select id from actions where tool_call_id = %s", (tool_call_id,))
        return cur.fetchone()[0], False


def chat_turns_today_db(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("select chat_turns from usage_counters where day = current_date")
        row = cur.fetchone()
        return row[0] if row else 0


def record_chat_turn_db(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        insert into usage_counters (day, chat_turns) values (current_date, 1)
        on conflict (day) do update set chat_turns = usage_counters.chat_turns + 1
        """
    )


def action_mark_sent_db(conn: psycopg.Connection, action_id: int) -> None:
    conn.execute(
        "update actions set status = 'approved', updated_at = now() where id = %s and status = 'proposed'",
        (action_id,),
    )


def action_mark_executed_db(conn: psycopg.Connection, action_id: int, external_id: str) -> None:
    conn.execute(
        "update actions set status = 'executed', external_id = %s, updated_at = now() where id = %s",
        (external_id, action_id),
    )


def action_get_db(conn: psycopg.Connection, action_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("select id, kind, args, status, external_id from actions where id = %s", (action_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return {"id": row[0], "kind": row[1], "args": row[2], "status": row[3], "external_id": row[4]}


class PostgresStore:
    """Store Protocol implementation over psycopg. Each method owns its
    transaction (autocommit connections would break multi-statement paths,
    so callers pass a plain psycopg connection factory)."""

    def __init__(self, connect_factory):
        self._connect = connect_factory

    def _run(self, fn):
        with self._connect() as conn:
            try:
                result = fn(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def chat_create(self) -> int:
        return self._run(chat_create_db)

    def chat_get(self, session_id: int) -> ChatSessionRow | None:
        return self._run(chat_get_db)

    def chat_cas(self, session_id, expected_version, *, messages, pending_approvals, state):
        return self._run(
            lambda c: chat_cas_db(c, session_id, expected_version, messages=messages, pending_approvals=pending_approvals, state=state)
        )

    def action_record(self, kind, args, tool_call_id):
        return self._run(lambda c: action_record_db(c, kind, args, tool_call_id))

    def action_mark_sent(self, action_id):
        return self._run(lambda c: action_mark_sent_db(c, action_id))

    def action_mark_executed(self, action_id, external_id):
        return self._run(lambda c: action_mark_executed_db(c, action_id, external_id))

    def action_get(self, action_id):
        return self._run(lambda c: action_get_db(c, action_id))

    def list_tasks(self, *, q=None, status=None):
        return self._run(lambda c: list_tasks_db(c, q=q, status=status))

    def task_detail(self, task_id):
        return self._run(lambda c: task_detail_db(c, task_id))

    def pending_suggestions(self):
        return self._run(pending_suggestions_db)

    def tasks_due_between(self, start, end):
        return self._run(lambda c: tasks_due_between_db(c, start, end))

    def list_threads(self):
        return self._run(list_threads_db)

    def thread_by_gmail_id(self, gmail_thread_id):
        return self._run(lambda c: thread_by_gmail_id_db(c, gmail_thread_id))

    def set_task_status(self, task_id, status):
        return self._run(lambda c: set_task_status_db(c, task_id, status))

    def accept_suggestion(self, suggestion_id, keep_id=None):
        return self._run(lambda c: accept_suggestion_db(c, suggestion_id, keep_id))

    def reject_suggestion(self, suggestion_id):
        return self._run(lambda c: reject_suggestion_db(c, suggestion_id))

    def split_merge(self, task_id: int):
        return self._run(split_merge_db)

    # -- sync helpers ---------------------------------------------------------------
    def upsert_person(self, email, display_name=None):
        return self._run(lambda c: upsert_person(c, email, display_name))

    def upsert_thread(self, gmail_thread_id, *, subject, participants, last_message_at, cached_text):
        return self._run(
            lambda c: upsert_thread(
                c, gmail_thread_id, subject=subject, participants=participants,
                last_message_at=last_message_at, cached_text=cached_text,
            )
        )

    def upsert_message(self, gmail_message_id, thread_db_id, internal_date):
        return self._run(lambda c: upsert_message(c, gmail_message_id, thread_db_id, internal_date))

    def thread_message_sets(self, thread_db_id):
        return self._run(lambda c: message_id_sets(c, thread_db_id))

    def open_tasks_for(self, participant_emails):
        return self._run(lambda c: open_tasks_as_existing(c, participant_emails))

    def tasks_in_thread(self, thread_db_id):
        return self._run(lambda c: tasks_in_thread_db(c, thread_db_id))

    def apply_thread_ops(self, thread_db_id, output, *, new_message_ids, history_id):
        def fn(conn: psycopg.Connection) -> list[int]:
            inserted = apply_reconcile_output(conn, output, thread_db_id)
            mark_messages_processed(conn, new_message_ids)
            if history_id:
                advance_thread_extraction(conn, thread_db_id, history_id)
            return inserted

        return self._run(fn)

    def get_sync_state(self):
        return self._run(get_sync_state)

    def advance_sync_state(self, last_history_id, *, full_sync=False):
        return self._run(lambda c: set_sync_state(c, last_history_id, full_sync=full_sync))

    def reset_thread_processed(self, gmail_thread_id):
        def fn(conn: psycopg.Connection) -> int:
            with conn.cursor() as cur:
                cur.execute("select id from threads where gmail_thread_id = %s", (gmail_thread_id,))
                row = cur.fetchone()
                if row is None:
                    raise LookupError(f"unknown thread {gmail_thread_id}")
                thread_db_id = row[0]
            conn.execute("update thread_messages set processed_at = null where thread_id = %s", (thread_db_id,))
            return thread_db_id

        return self._run(fn)

    def update_task_fields(self, task_id, *, title=None, due_date=None, clear_due=False):
        def fn(conn: psycopg.Connection) -> bool:
            with conn.cursor() as cur:
                cur.execute("select title, due_date from tasks where id = %s for update", (task_id,))
                row = cur.fetchone()
                if row is None:
                    return False
                old_title, old_due = row
                new_title = title if title is not None else old_title
                new_due = None if clear_due else (due_date if due_date is not None else old_due)
                if new_title != old_title:
                    _task_event(cur, task_id, "title_changed", {"value": old_title}, {"value": new_title}, None)
                if new_due != old_due:
                    _task_event(
                        cur, task_id, "due_changed",
                        {"value": str(old_due) if old_due else None},
                        {"value": str(new_due) if new_due else None},
                        None,
                    )
                cur.execute(
                    "update tasks set title = %s, due_date = %s, updated_at = now() where id = %s",
                    (new_title, new_due, task_id),
                )
            return True

        return self._run(fn)

    def chat_turns_today(self):
        return self._run(chat_turns_today_db)

    def record_chat_turn(self):
        return self._run(record_chat_turn_db)


@dataclass
class SyncOutcome:
    thread_id: str
    inserted_task_ids: list[int] = field(default_factory=list)
    dropped_repeats: int = 0
    suggestions: int = 0
    error: str | None = None


def persist_synced_thread(
    conn: psycopg.Connection,
    thread_db_id: int,
    output: ReconcileOutput,
    *,
    new_message_ids: list[str],
    history_id: str | None,
) -> list[int]:
    """One transaction per thread (§7 Persist): ops + processed marks + history."""
    inserted = apply_reconcile_output(conn, output, thread_db_id)
    mark_messages_processed(conn, new_message_ids)
    if history_id:
        advance_thread_extraction(conn, thread_db_id, history_id)
    return inserted


def serialize_messages(messages: list[Any]) -> list[dict]:
    """pydantic-ai ModelMessage -> JSON dicts for chat_sessions.messages."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    raw = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    return raw if isinstance(raw, list) else [raw]


def deserialize_messages(raw: list[dict]) -> list[Any]:
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    return ModelMessagesTypeAdapter.validate_python(raw)


def pending_to_dict(requests_obj) -> dict:
    """DeferredToolRequests -> JSON-safe dict (tool name + args + ids)."""
    from pydantic_ai.messages import ToolCallPart

    def part(part_obj: ToolCallPart) -> dict:
        args = part_obj.args
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        return {"tool_call_id": part_obj.tool_call_id, "tool_name": part_obj.tool_name, "args": args}

    return {
        "approvals": [part(p) for p in requests_obj.approvals],
        "calls": [part(p) for p in requests_obj.calls],
        "metadata": requests_obj.metadata,
    }
