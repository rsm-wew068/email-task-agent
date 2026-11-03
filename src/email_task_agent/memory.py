"""In-memory Store implementation with the same semantics as PostgresStore —
used by unit tests and the Playwright suite (no database needed). Not for
production: nothing persists across processes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime

from email_task_agent.pipeline.reconcile import (
    ApplyUpdate,
    ExistingTask,
    MergeOps,
)
from email_task_agent.store import (
    ChatSessionRow,
    EventRow,
    SuggestionRow,
    TaskRow,
    ThreadRow,
)


@dataclass
class _Person:
    id: int
    email: str
    display_name: str | None = None


@dataclass
class _Task:
    id: int
    title: str
    owner_id: int | None
    due_date: date | None
    status: str
    confidence: float | None
    needs_review: bool
    thread_id: int | None
    sources: list[tuple[str, str, str]] = field(default_factory=list)  # (message_id, quote, kind)
    search_terms: str = ""


@dataclass
class _Thread:
    id: int
    gmail_thread_id: str
    subject: str | None
    participants: list[str]
    last_message_at: datetime | None
    last_extracted_history_id: str | None
    cached_text: str | None


@dataclass
class _Message:
    gmail_message_id: str
    thread_id: int
    internal_date: datetime | None
    processed_at: datetime | None = None


@dataclass
class _Action:
    id: int
    kind: str
    args: dict
    status: str
    external_id: str | None
    tool_call_id: str


class MemoryStore:
    """Mirrors every Store method, including the version-checked CAS."""

    def __init__(self) -> None:
        self.people: dict[str, _Person] = {}
        self.tasks: dict[int, _Task] = {}
        self.threads: dict[int, _Thread] = {}
        self.messages: dict[str, _Message] = {}
        self.events: list[EventRow] = []
        self.suggestions: dict[int, SuggestionRow] = {}
        self.sessions: dict[int, ChatSessionRow] = {}
        self.actions: dict[int, _Action] = {}
        self.sync_history_id: str | None = None
        self.sync_full_at: datetime | None = None
        self.chat_turns: dict[date, int] = {}
        self._next = {"person": 1, "task": 1, "thread": 1, "event": 1, "suggestion": 1, "session": 1, "action": 1}

    def _id(self, kind: str) -> int:
        value = self._next[kind]
        self._next[kind] += 1
        return value

    # -- helpers ---------------------------------------------------------------------
    def _person_id(self, email: str | None) -> int | None:
        if not email:
            return None
        normalized = email.strip().casefold()
        if normalized not in self.people:
            self.people[normalized] = _Person(self._id("person"), normalized)
        return self.people[normalized].id

    def _owner_email(self, owner_id: int | None) -> tuple[str | None, str | None]:
        if owner_id is None:
            return None, None
        person = next(p for p in self.people.values() if p.id == owner_id)
        return person.email, person.display_name

    def _task_row(self, task: _Task) -> TaskRow:
        owner_email, owner_name = self._owner_email(task.owner_id)
        thread = self.threads.get(task.thread_id) if task.thread_id else None
        return TaskRow(
            id=task.id, title=task.title, owner_email=owner_email, owner_name=owner_name,
            due_date=task.due_date, status=task.status, confidence=task.confidence,
            needs_review=task.needs_review, thread_id=task.thread_id,
            gmail_thread_id=thread.gmail_thread_id if thread else None,
        )

    def _existing(self, task: _Task) -> ExistingTask:
        owner_email, _ = self._owner_email(task.owner_id)
        return ExistingTask(
            id=task.id, title=task.title, owner_email=owner_email, due_date=task.due_date,
            status=task.status, thread_id=task.thread_id, needs_review=task.needs_review,
        )

    # -- sync helpers ------------------------------------------------------------------
    def upsert_person(self, email: str, display_name: str | None = None) -> int:
        normalized = email.strip().casefold()
        if normalized in self.people:
            if display_name:
                self.people[normalized].display_name = display_name
        else:
            self.people[normalized] = _Person(self._id("person"), normalized, display_name)
        return self.people[normalized].id

    def upsert_thread(self, gmail_thread_id, *, subject, participants, last_message_at, cached_text):
        for thread in self.threads.values():
            if thread.gmail_thread_id == gmail_thread_id:
                thread.subject = subject
                thread.participants = [p.strip().casefold() for p in participants if p]
                if last_message_at and (thread.last_message_at is None or last_message_at > thread.last_message_at):
                    thread.last_message_at = last_message_at
                thread.cached_text = cached_text or thread.cached_text
                return thread.id
        thread_id = self._id("thread")
        self.threads[thread_id] = _Thread(
            id=thread_id, gmail_thread_id=gmail_thread_id, subject=subject,
            participants=[p.strip().casefold() for p in participants if p],
            last_message_at=last_message_at, last_extracted_history_id=None, cached_text=cached_text,
        )
        return thread_id

    def upsert_message(self, gmail_message_id, thread_db_id, internal_date):
        if gmail_message_id not in self.messages:
            self.messages[gmail_message_id] = _Message(gmail_message_id, thread_db_id, internal_date)

    def thread_message_sets(self, thread_db_id):
        processed = {m.gmail_message_id for m in self.messages.values() if m.thread_id == thread_db_id and m.processed_at}
        unprocessed = {m.gmail_message_id for m in self.messages.values() if m.thread_id == thread_db_id and not m.processed_at}
        return processed, unprocessed

    def open_tasks_for(self, participant_emails):
        wanted = {e.strip().casefold() for e in participant_emails}
        out = []
        for task in self.tasks.values():
            if task.status != "open":
                continue
            owner_email, _ = self._owner_email(task.owner_id)
            if owner_email is None or owner_email in wanted:
                out.append(self._existing(task))
        return out

    def tasks_in_thread(self, thread_db_id):
        return [self._task_row(t) for t in sorted(self.tasks.values(), key=lambda t: t.id)
                if t.thread_id == thread_db_id]

    def _event(self, task_id: int, kind: str, old: dict | None, new: dict | None, source_message_id: str | None) -> None:
        self.events.append(EventRow(self._id("event"), task_id, datetime.now(), kind, old, new, source_message_id))

    def apply_thread_ops(self, thread_db_id, output, *, new_message_ids, history_id):
        inserted: list[int] = []
        for ins in output.inserts:
            task_id = self._id("task")
            self.tasks[task_id] = _Task(
                id=task_id, title=ins.task.title, owner_id=self._person_id(ins.owner_email),
                due_date=ins.due_date, status=ins.task.status, confidence=ins.task.confidence,
                needs_review=ins.needs_review, thread_id=thread_db_id,
                sources=[(ins.task.source_message_id, ins.task.evidence_quote, "creation")],
                search_terms=ins.task.title.casefold(),
            )
            self._event(
                task_id, "created", None,
                {"title": ins.task.title, "owner": ins.owner_email,
                 "due": str(ins.due_date) if ins.due_date else None, "status": ins.task.status},
                ins.task.source_message_id,
            )
            inserted.append(task_id)
        for upd in output.updates:
            self._apply_update(upd)
        for sug in output.suggestions:
            suggestion_id = self._id("suggestion")  # key and row.id must match
            self.suggestions[suggestion_id] = SuggestionRow(
                id=suggestion_id, kind=sug.kind, task_id=sug.task_id,
                other_task_id=sug.other_task_id, payload=sug.payload, status="pending", created_at=datetime.now(),
            )
        for message_id in new_message_ids:
            if message_id in self.messages:
                self.messages[message_id].processed_at = datetime.now()
        if history_id:
            thread = self.threads[thread_db_id]
            thread.last_extracted_history_id = history_id
        return inserted

    def _apply_update(self, upd: ApplyUpdate) -> None:
        task = self.tasks.get(upd.task_id)
        if task is None:
            return
        old_owner_email, _ = self._owner_email(task.owner_id)
        new_owner_id = self._person_id(upd.owner_email) if upd.owner_email else task.owner_id
        new_owner_email = upd.owner_email if upd.owner_email else old_owner_email
        if upd.title is not None and upd.title != task.title:
            self._event(task.id, "title_changed", {"value": task.title}, {"value": upd.title}, upd.source_message_id)
            task.title = upd.title
        if new_owner_email != old_owner_email:
            self._event(task.id, "owner_changed", {"value": old_owner_email}, {"value": new_owner_email}, upd.source_message_id)
            task.owner_id = new_owner_id
        if upd.due_date is not None and upd.due_date != task.due_date:
            self._event(task.id, "due_changed", {"value": str(task.due_date) if task.due_date else None},
                        {"value": str(upd.due_date)}, upd.source_message_id)
            task.due_date = upd.due_date
        if upd.status is not None and upd.status != task.status:
            self._event(task.id, "status_changed", {"value": task.status}, {"value": upd.status}, upd.source_message_id)
            task.status = upd.status
        task.confidence = upd.confidence
        task.needs_review = upd.needs_review
        task.sources.append((upd.source_message_id, upd.evidence_quote, "update"))

    def get_sync_state(self):
        return self.sync_history_id, self.sync_full_at

    def advance_sync_state(self, last_history_id, *, full_sync=False):
        self.sync_history_id = last_history_id
        if full_sync:
            self.sync_full_at = datetime.now()

    def reset_thread_processed(self, gmail_thread_id):
        for thread in self.threads.values():
            if thread.gmail_thread_id == gmail_thread_id:
                for message in self.messages.values():
                    if message.thread_id == thread.id:
                        message.processed_at = None
                return thread.id
        raise LookupError(f"unknown thread {gmail_thread_id}")

    def update_task_fields(self, task_id, *, title=None, due_date=None, clear_due=False):
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if title is not None and title != task.title:
            self._event(task_id, "title_changed", {"value": task.title}, {"value": title}, None)
            task.title = title
        new_due = None if clear_due else (due_date if due_date is not None else task.due_date)
        if new_due != task.due_date:
            self._event(task_id, "due_changed", {"value": str(task.due_date) if task.due_date else None},
                        {"value": str(new_due) if new_due else None}, None)
            task.due_date = new_due
        return True

    def chat_turns_today(self):
        return self.chat_turns.get(date.today(), 0)

    def record_chat_turn(self):
        today = date.today()
        self.chat_turns[today] = self.chat_turns.get(today, 0) + 1

    # -- chat -----------------------------------------------------------------------
    def chat_create(self) -> int:
        session_id = self._id("session")
        self.sessions[session_id] = ChatSessionRow(session_id, [], None, "idle", 0)
        return session_id

    def chat_get(self, session_id):
        session = self.sessions.get(session_id)
        if session is None:
            return None
        # A copy: the store must not alias rows that callers treat as snapshots
        # (PostgresStore returns fresh DB rows, never live objects).
        return replace(session)

    def chat_cas(self, session_id, expected_version, *, messages, pending_approvals, state):
        session = self.sessions.get(session_id)
        if session is None or session.version != expected_version:
            return None
        session.messages = messages
        session.pending_approvals = pending_approvals
        session.state = state
        session.version = expected_version + 1
        return session.version

    def action_record(self, kind, args, tool_call_id):
        for action in self.actions.values():
            if action.tool_call_id == tool_call_id:
                return action.id, False
        action_id = self._id("action")
        self.actions[action_id] = _Action(action_id, kind, args, "proposed", None, tool_call_id)
        return action_id, True

    def action_mark_sent(self, action_id):
        if self.actions[action_id].status == "proposed":
            self.actions[action_id].status = "approved"

    def action_mark_executed(self, action_id, external_id):
        action = self.actions[action_id]
        action.status = "executed"
        action.external_id = external_id

    def action_get(self, action_id):
        action = self.actions.get(action_id)
        if action is None:
            return None
        return {"id": action.id, "kind": action.kind, "args": action.args, "status": action.status, "external_id": action.external_id}

    # -- web pages ---------------------------------------------------------------------
    def list_tasks(self, *, q=None, status=None):
        rows = [self._task_row(t) for t in self.tasks.values()]
        if q:
            needle = q.casefold()
            rows = [r for r in rows if needle in r.title.casefold()]
        if status:
            rows = [r for r in rows if r.status == status]
        return sorted(rows, key=lambda r: (r.due_date is None, r.due_date or date.max, -r.id))

    def task_detail(self, task_id):
        task = self.tasks.get(task_id)
        if task is None:
            return None
        events = [e for e in self.events if e.task_id == task_id]
        events.reverse()
        suggestions = [s for s in self.suggestions.values() if s.task_id == task_id]
        return self._task_row(task), events, suggestions

    def pending_suggestions(self):
        return sorted((s for s in self.suggestions.values() if s.status == "pending"), key=lambda s: s.id)

    def tasks_due_between(self, start, end):
        rows = [self._task_row(t) for t in self.tasks.values()
                if t.due_date and start <= t.due_date <= end and t.status == "open"]
        return sorted(rows, key=lambda r: r.due_date or date.max)

    def list_threads(self):
        rows = [
            ThreadRow(t.id, t.gmail_thread_id, t.subject, t.participants, t.last_message_at,
                      t.last_extracted_history_id, t.cached_text)
            for t in self.threads.values()
        ]
        return sorted(rows, key=lambda r: -(r.last_message_at.timestamp() if r.last_message_at else 0))

    def thread_by_gmail_id(self, gmail_thread_id):
        for thread in self.threads.values():
            if thread.gmail_thread_id == gmail_thread_id:
                return ThreadRow(thread.id, thread.gmail_thread_id, thread.subject, thread.participants,
                                 thread.last_message_at, thread.last_extracted_history_id, thread.cached_text)
        return None

    def set_task_status(self, task_id, status):
        task = self.tasks.get(task_id)
        if task is None or task.status == status:
            return False
        self._event(task_id, "status_changed", {"value": task.status}, {"value": status}, None)
        task.status = status
        return True

    def accept_suggestion(self, suggestion_id, keep_id=None):
        suggestion = self.suggestions.get(suggestion_id)
        if suggestion is None or suggestion.status != "pending":
            return False
        if suggestion.kind == "possible_duplicate":
            primary = keep_id or suggestion.task_id
            secondary = suggestion.other_task_id
            if primary is None or secondary is None or primary == secondary:
                return False
            self._merge(MergeOps(primary_id=primary, secondary_id=secondary))
        elif suggestion.kind == "low_confidence_done":
            if suggestion.task_id is None:
                return False
            self.set_task_status(suggestion.task_id, "done")
        else:
            return False
        self.suggestions[suggestion_id] = SuggestionRow(
            suggestion.id, suggestion.kind, suggestion.task_id, suggestion.other_task_id,
            suggestion.payload, "accepted", suggestion.created_at,
        )
        return True

    def _merge(self, ops: MergeOps) -> None:
        secondary = self.tasks[ops.secondary_id]
        primary = self.tasks[ops.primary_id]
        for source in secondary.sources:
            primary.sources.append(source)
        for event in self.events:
            if event.task_id == ops.secondary_id:
                object.__setattr__(event, "task_id", ops.primary_id)
        self._event(
            ops.primary_id, "merged", None,
            {"merged_task_id": ops.secondary_id,
             "snapshot": {"title": secondary.title, "owner": self._owner_email(secondary.owner_id)[0],
                          "due": str(secondary.due_date) if secondary.due_date else None,
                          "status": secondary.status}},
            None,
        )
        del self.tasks[ops.secondary_id]

    def reject_suggestion(self, suggestion_id):
        suggestion = self.suggestions.get(suggestion_id)
        if suggestion is None or suggestion.status != "pending":
            return False
        self.suggestions[suggestion_id] = SuggestionRow(
            suggestion.id, suggestion.kind, suggestion.task_id, suggestion.other_task_id,
            suggestion.payload, "rejected", suggestion.created_at,
        )
        return True

    def split_merge(self, task_id):
        merge_events = [e for e in self.events if e.task_id == task_id and e.kind == "merged"]
        if not merge_events:
            return False
        event = max(merge_events, key=lambda e: e.id)
        snapshot = (event.new or {}).get("snapshot", {})
        owner_id = self._person_id(snapshot.get("owner")) if snapshot.get("owner") else None
        restored_id = self._id("task")
        self.events = [e for e in self.events if e.id != event.id]
        self.tasks[restored_id] = _Task(
            id=restored_id, title=snapshot.get("title", "restored"), owner_id=owner_id,
            due_date=date.fromisoformat(snapshot["due"]) if snapshot.get("due") else None,
            status=snapshot.get("status", "open"), confidence=None, needs_review=True,
            thread_id=self.tasks[task_id].thread_id if task_id in self.tasks else None,
            sources=[],
            search_terms=snapshot.get("title", "").casefold(),
        )
        self._event(restored_id, "created", None, {"restored_from_split_of": task_id}, None)
        self._event(task_id, "split", {"value": task_id}, {"value": restored_id}, None)
        return True
