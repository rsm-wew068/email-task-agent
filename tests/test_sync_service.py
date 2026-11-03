"""Sync service end-to-end with a fake Gmail client and a fake extractor."""

from __future__ import annotations

from datetime import UTC, datetime

from email_task_agent.models.extraction import NewTask, ThreadExtraction
from email_task_agent.pipeline.sync import HistoryResult, SyncMessage, SyncService, SyncThread
from email_task_agent.pipeline.validate import ValidatedExtraction  # noqa: F401 (re-export use)


class FakeGmail:
    def __init__(self, threads: list[SyncThread], *, latest: str = "h999"):
        self.threads = threads
        self.latest = latest
        self.full_sync_calls = 0

    def changed_since(self, start_history_id: str) -> HistoryResult:
        return HistoryResult(threads=self.threads, latest_history_id=self.latest)

    def full_sync(self, days: int) -> HistoryResult:
        self.full_sync_calls += 1
        return HistoryResult(threads=self.threads, latest_history_id=self.latest)

    def fetch_single(self, gmail_thread_id: str) -> SyncThread:
        return next(t for t in self.threads if t.gmail_thread_id == gmail_thread_id)


def make_thread(tid: str, subject: str, body: str, history_id: str) -> SyncThread:
    message = SyncMessage(
        message_id=f"{tid}#0",
        sender="kate@x",
        to=["alex@x"],
        cc=[],
        internal_date=datetime(2026, 11, 2, 9, 0, tzinfo=UTC),
        subject=subject,
        body=body,
    )
    return SyncThread(
        gmail_thread_id=tid,
        subject=subject,
        participants=["kate@x", "alex@x"],
        messages=[message],
        history_id=history_id,
        cached_text=f"Subject: {subject}\n\n{body}",
    )


def fake_extract(data) -> ThreadExtraction:
    quote = next(
        line for line in data.messages[0].body.split(".") if "please" in line.lower() or "could you" in line.lower()
    ).strip() + "."
    return ThreadExtraction(
        new_tasks=[
            NewTask(
                title=f"Handle {data.subject}",
                owner_email="alex@x",
                due_date=None,
                confidence=0.95,
                evidence_quote=quote,
                source_message_id=data.messages[0].message_id,
            )
        ],
        updates=[],
    )


def make_service(store, client, cap=10):
    return SyncService(
        store, client, fake_extract, owner_email="alex@x", cap_per_run=cap
    )


def test_full_sync_then_incremental_and_repeat_drop(memory_store):
    thread = make_thread("t-1", "Q3 draft", "Could you please send the draft by Friday?", "h1")
    client = FakeGmail([thread])
    service = make_service(memory_store, client)

    # No sync state yet -> full sync fallback.
    outcomes = service.run()
    assert client.full_sync_calls == 1
    assert len(outcomes) == 1 and outcomes[0].inserted_task_ids
    assert not outcomes[0].skipped

    tasks = memory_store.list_tasks()
    assert tasks and tasks[0].title == "Handle Q3 draft"
    # created event + processed marks + per-thread history + sync checkpoint
    detail = memory_store.task_detail(tasks[0].id)
    assert detail[1][0].kind == "created"
    processed, unprocessed = memory_store.thread_message_sets(1)
    assert processed == {"t-1#0"} and not unprocessed
    assert memory_store.threads[1].last_extracted_history_id == "h1"
    assert memory_store.get_sync_state()[0] == "h1"

    # Re-running with nothing new: skipped, no duplicate task.
    outcomes = service.run()
    assert outcomes[0].skipped == "no_new_messages"
    assert len(memory_store.list_tasks()) == 1

    # A NEW message in the same thread, but the extractor (bogus) cites the
    # already-processed email -> dropped as a repeat, no insertion.

    batch = SyncThread(
        gmail_thread_id="t-1",
        subject="Q3 draft",
        participants=["kate@x", "alex@x"],
        history_id="h2",
        cached_text=(
            "Subject: Q3 draft\n\nCould you please send the draft by Friday?\n\n"
            "Subject: Re: Q3 draft\n\nAny update on this?"
        ),
        messages=[
            SyncMessage(
                message_id="t-1#0",
                sender="kate@x",
                to=["alex@x"],
                cc=[],
                internal_date=datetime(2026, 11, 2, 9, 0, tzinfo=UTC),
                subject="Q3 draft",
                body="Could you please send the draft by Friday?",
            ),
            SyncMessage(
                message_id="t-1#1",
                sender="kate@x",
                to=["alex@x"],
                cc=[],
                internal_date=datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
                subject="Re: Q3 draft",
                body="Any update on this?",
            ),
        ],
    )

    def stale_extract(data) -> ThreadExtraction:
        return ThreadExtraction(
            new_tasks=[
                NewTask(
                    title="Handle Q3 draft",
                    owner_email="alex@x",
                    due_date=None,
                    confidence=0.9,
                    evidence_quote="Could you please send the draft by Friday?",  # cites t-1#0 (processed)
                    source_message_id="t-1#0",
                )
            ],
            updates=[],
        )

    SyncService(memory_store, FakeGmail([batch]), stale_extract, owner_email="alex@x").run()
    assert len(memory_store.list_tasks()) == 1  # still just the original task
    _, unprocessed = memory_store.thread_message_sets(1)
    assert unprocessed == set()  # the new message was marked processed


def test_incremental_run_when_state_exists(memory_store):
    memory_store.advance_sync_state("h0")
    thread = make_thread("t-1", "Expenses", "Please file the October expense report by Tuesday.", "h5")
    client = FakeGmail([thread], latest="h6")
    assert client.full_sync_calls == 0  # lazily confirmed after run below
    make_service(memory_store, client).run()
    assert client.full_sync_calls == 0  # incremental path used
    assert memory_store.get_sync_state()[0] == "h5"  # advanced past PROCESSED thread only


def test_cap_leaves_remaining_threads_for_next_run(memory_store):
    threads = [make_thread(f"t-{i}", f"S{i}", "Could you please handle item one?", f"h{i}") for i in range(3)]
    service = make_service(memory_store, FakeGmail(threads), cap=2)
    outcomes = service.run()
    assert len(outcomes) == 2
    assert memory_store.get_sync_state()[0] == "h1"  # only past the processed two


def test_no_change_run_checkpoints_latest(memory_store):
    memory_store.advance_sync_state("h0")
    client = FakeGmail([], latest="h2")
    make_service(memory_store, client).run()
    assert memory_store.get_sync_state()[0] == "h2"


def test_expired_history_falls_back_to_full_sync(memory_store):
    class ExpiringGmail(FakeGmail):
        def changed_since(self, start_history_id: str) -> HistoryResult:
            return HistoryResult(expired=True)

    memory_store.advance_sync_state("h0")
    thread = make_thread("t-1", "One task", "Could you please take the trash out?", "h7")
    client = ExpiringGmail([thread])
    make_service(memory_store, client).run()
    assert client.full_sync_calls == 1
    assert len(memory_store.list_tasks()) == 1


def test_update_flow_creates_field_events(memory_store):
    from email_task_agent.models.extraction import TaskUpdate

    # First sync inserts the task.
    thread = make_thread("t-1", "Checklist", "Could you please send the checklist?", "h1")
    make_service(memory_store, FakeGmail([thread])).run()
    task_id = memory_store.list_tasks()[0].id

    # Second sync: a NEW message updates the task's status.
    follow_up = SyncThread(
        gmail_thread_id="t-1",
        subject="Checklist",
        participants=["kate@x", "alex@x"],
        history_id="h9",
        cached_text="Subject: Re: Checklist\n\nJust checking — the checklist was sent this morning.",
        messages=[
            SyncMessage(
                message_id="t-1#1",
                sender="kate@x",
                to=["alex@x"],
                cc=[],
                internal_date=datetime(2026, 11, 3, 10, 0, tzinfo=UTC),
                subject="Re: Checklist",
                body="The checklist was sent this morning.",
            )
        ],
    )

    def update_extract(data) -> ThreadExtraction:
        return ThreadExtraction(
            new_tasks=[],
            updates=[
                TaskUpdate(
                    ref_task_id=task_id,
                    status="done",
                    confidence=0.95,
                    evidence_quote="The checklist was sent this morning.",
                    source_message_id="t-1#1",
                )
            ],
        )

    SyncService(memory_store, FakeGmail([follow_up]), update_extract, owner_email="alex@x").run()
    kinds = [e.kind for e in memory_store.task_detail(task_id)[1]]
    assert "status_changed" in kinds
    assert memory_store.list_tasks()[0].status == "done"
