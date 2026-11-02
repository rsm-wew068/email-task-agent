"""Sync service (plan §5): history.list -> group -> per thread pipeline.

Steps per the plan:
  1. history.list from the stored last_history_id; on HTTP 404 (history
     expired) fall back to a full sync of the last N days.
  2. Group changed messages by thread; the client prefilters
     (spam/trash/promotions/social/bulk).
  3. For each thread (capped per run): threads.get -> extract -> validate ->
     reconcile -> persist. Leftover threads continue on the next run.
  4. Store the new last_history_id — only advancing past PROCESSED threads.

The GmailClient protocol keeps this testable; the real client is in
email_task_agent.gmail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from email_task_agent.pipeline.extract import ExtractInput, ExtractMessage
from email_task_agent.pipeline.reconcile import reconcile
from email_task_agent.pipeline.validate import ThreadInput, validate_extraction
from email_task_agent.store import Store


@dataclass(frozen=True)
class SyncMessage:
    message_id: str
    sender: str
    to: list[str]
    cc: list[str]
    internal_date: datetime
    subject: str
    body: str


@dataclass(frozen=True)
class SyncThread:
    gmail_thread_id: str
    subject: str
    participants: list[str]
    messages: list[SyncMessage]
    history_id: str  # newest history id covering this thread's changes
    cached_text: str = ""


@dataclass
class HistoryResult:
    threads: list[SyncThread] = field(default_factory=list)
    latest_history_id: str | None = None
    expired: bool = False  # 404 from history.list -> caller should full-sync


class GmailClientProtocol:
    """Structural interface; real implementation in email_task_agent.gmail."""

    def changed_since(self, start_history_id: str) -> HistoryResult: ...
    def full_sync(self, days: int) -> HistoryResult: ...
    def fetch_single(self, gmail_thread_id: str) -> SyncThread: ...


@dataclass
class SyncOutcome:
    gmail_thread_id: str
    inserted_task_ids: list[int]
    dropped_repeats: int
    suggestions: int
    skipped: str | None = None  # "no_new_messages" | extraction rejected everything -> None


class SyncService:
    def __init__(
        self,
        store: Store,
        client: GmailClientProtocol,
        extract_fn,
        *,
        owner_email: str,
        cap_per_run: int = 20,
        full_sync_days: int = 30,
    ):
        self.store = store
        self.client = client
        self.extract_fn = extract_fn  # ExtractInput -> ThreadExtraction (agent or fake)
        self.owner_email = owner_email.strip().casefold()
        self.cap = cap_per_run
        self.full_sync_days = full_sync_days

    def run(self) -> list[SyncOutcome]:
        last_history_id, _ = self.store.get_sync_state()
        if last_history_id is None:
            result = self.client.full_sync(self.full_sync_days)
        else:
            result = self.client.changed_since(last_history_id)
            if result.expired:
                result = self.client.full_sync(self.full_sync_days)

        outcomes: list[SyncOutcome] = []
        for sync_thread in result.threads[: self.cap]:
            outcome = self._process_thread(sync_thread)
            outcomes.append(outcome)

        # Advance sync_state only past processed threads (§5 step 4); the rest
        # reappear on the next run.
        processed_ids = {t.gmail_thread_id for t in result.threads[: self.cap]}
        latest_processed = next(
            (t.history_id for t in reversed(result.threads[: self.cap]) if t.gmail_thread_id in processed_ids),
            None,
        )
        if latest_processed:
            self.store.advance_sync_state(latest_processed, full_sync=(last_history_id is None))
        elif result.latest_history_id and not result.threads:
            # Nothing changed: still checkpoint so we don't re-scan the same window.
            self.store.advance_sync_state(result.latest_history_id, full_sync=(last_history_id is None))
        return outcomes

    def _process_thread(self, sync_thread: SyncThread) -> SyncOutcome:
        thread_db_id = self.store.upsert_thread(
            sync_thread.gmail_thread_id,
            subject=sync_thread.subject,
            participants=sync_thread.participants,
            last_message_at=max((m.internal_date for m in sync_thread.messages), default=None),
            cached_text=sync_thread.cached_text or None,
        )
        for message in sync_thread.messages:
            self.store.upsert_message(message.message_id, thread_db_id, message.internal_date)

        processed, unprocessed = self.store.thread_message_sets(thread_db_id)
        new_ids = sorted(unprocessed)
        if not new_ids:
            return SyncOutcome(sync_thread.gmail_thread_id, [], 0, 0, skipped="no_new_messages")

        participants = set(sync_thread.participants) | {self.owner_email}
        open_tasks = self.store.open_tasks_for(sorted(participants))
        message_dates = {m.message_id: m.internal_date.date() for m in sync_thread.messages}

        extract_input = ExtractInput(
            gmail_thread_id=sync_thread.gmail_thread_id,
            subject=sync_thread.subject,
            owner_email=self.owner_email,
            messages=[
                ExtractMessage(
                    message_id=m.message_id, sender=m.sender, to=m.to, cc=m.cc,
                    date=m.internal_date.date(), subject=m.subject, body=m.body,
                )
                for m in sync_thread.messages
            ],
            open_tasks=open_tasks,
        )
        extraction = self.extract_fn(extract_input)

        validated = validate_extraction(
            extraction,
            ThreadInput(
                thread_id=sync_thread.gmail_thread_id,
                thread_text=sync_thread.cached_text,
                participants=participants,
                shown_task_ids={t.id for t in open_tasks},
                new_message_ids=set(new_ids),
                message_dates=message_dates,
            ),
        )
        output = reconcile(validated, open_tasks, processed)
        inserted = self.store.apply_thread_ops(
            thread_db_id, output, new_message_ids=new_ids, history_id=sync_thread.history_id
        )
        return SyncOutcome(
            gmail_thread_id=sync_thread.gmail_thread_id,
            inserted_task_ids=inserted,
            dropped_repeats=len(output.drops),
            suggestions=len(output.suggestions),
        )


def reextract_thread(store: Store, client: GmailClientProtocol, extract_fn, *, owner_email: str, gmail_thread_id: str) -> SyncOutcome:
    """Manual re-extract (rev 5 §7.3 cost of design): reset processed marks so
    the whole thread is treated as new, then run the standard pipeline."""
    service = SyncService(store, client, extract_fn, owner_email=owner_email, cap_per_run=1)
    thread = client.fetch_single(gmail_thread_id)
    store.reset_thread_processed(gmail_thread_id)
    return service._process_thread(thread)  # noqa: SLF001 - intentional single-thread entry
