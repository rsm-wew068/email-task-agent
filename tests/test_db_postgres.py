"""PostgresStore against a REAL Postgres (the SQL surface was previously only
exercised via the memory twin).

Runs whenever a Postgres is reachable at POSTGRES_TEST_URL (defaults to the
local docker container used by this repo: `docker run --name eta-pg-check
-e POSTGRES_PASSWORD=check -e POSTGRES_DB=eta -p 5455:5432 postgres:16-alpine`);
skips otherwise. CI runs a postgres service container, so it always executes
there.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import psycopg
import pytest

from email_task_agent.db import migrate
from email_task_agent.models.extraction import NewTask
from email_task_agent.pipeline.reconcile import InsertTask, MergeOps, ReconcileOutput, Suggest
from email_task_agent.store import PostgresStore

URL = os.environ.get("POSTGRES_TEST_URL", "postgresql://postgres:check@127.0.0.1:5455/eta")


def _reachable() -> bool:
    try:
        with psycopg.connect(URL, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


pytestmark = [
    pytest.mark.skipif(not _reachable(), reason=f"no Postgres at {URL}"),
]


@pytest.fixture()
def store():
    """Fresh schema per test: the container is a throwaway, so wiping public is safe."""
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    conn = psycopg.connect(URL, autocommit=False)
    migrate(conn)
    yield PostgresStore(lambda: psycopg.connect(URL, autocommit=False, prepare_threshold=None))


def _seed_thread(store: PostgresStore, gmail_id: str, *, with_message: str | None = None):
    thread_db_id = store.upsert_thread(
        gmail_id,
        subject="Subject " + gmail_id,
        participants=["kate@x", "alex@x"],
        last_message_at=datetime(2026, 11, 2, 9, 0, tzinfo=UTC),
        cached_text=with_message,
    )
    if with_message:
        store.upsert_message(
            f"{gmail_id}#0", thread_db_id, datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
        )
    return thread_db_id


def test_migrations_create_all_tables(store):
    with psycopg.connect(URL, autocommit=True) as conn:
        names = {r[0] for r in conn.execute("select tablename from pg_tables where schemaname='public'").fetchall()}
    expected = {
        "schema_migrations", "sync_state", "people", "threads", "thread_messages", "tasks",
        "task_collaborators", "task_sources", "task_events", "actions", "chat_sessions",
        "suggestions", "usage_counters",
    }
    assert expected <= names


def test_thread_message_sets_and_ops_flow(store):
    thread_db_id = _seed_thread(store, "pg-1", with_message="Could you please send the draft by Friday?")

    store.upsert_message("pg-1#1", thread_db_id, datetime(2026, 11, 3, 9, 0, tzinfo=UTC))
    processed, unprocessed = store.thread_message_sets(thread_db_id)
    assert processed == set() and unprocessed == {"pg-1#0", "pg-1#1"}

    output = ReconcileOutput(
        inserts=[
            InsertTask(
                NewTask(
                    title="Send the draft",
                    owner_email="alex@x",
                    due_date=None,
                    confidence=0.95,
                    evidence_quote="Could you please send the draft by Friday?",
                    source_message_id="pg-1#0",
                ),
                "alex@x",
                date(2026, 11, 6),
                False,
            )
        ],
        suggestions=[
            Suggest(kind="possible_duplicate", task_id=None, payload={"new_title": "Send the draft"})
        ],
    )
    inserted = store.apply_thread_ops(thread_db_id, output, new_message_ids=["pg-1#0"], history_id="h1")
    assert inserted == [1]

    processed, unprocessed = store.thread_message_sets(thread_db_id)
    assert processed == {"pg-1#0"} and unprocessed == {"pg-1#1"}

    task = store.list_tasks(q="draft")[0]
    assert task.title == "Send the draft" and task.gmail_thread_id == "pg-1"
    events = store.task_detail(task.id)[1]
    assert events[0].kind == "created"

    # full-text search: hit and miss
    assert store.list_tasks(q="zzz-not-there") == []


def test_status_toggle_writes_event(store):
    thread_db_id = _seed_thread(store, "pg-2")
    store.apply_thread_ops(
        thread_db_id,
        ReconcileOutput(
            inserts=[
                InsertTask(
                    NewTask(title="Toggle me", source_message_id="m", evidence_quote="toggle quote"),
                    "alex@x", None, False,
                )
            ]
        ),
        new_message_ids=[],
        history_id=None,
    )
    task_id = store.list_tasks()[0].id
    assert store.set_task_status(task_id, "done") is True
    assert store.set_task_status(task_id, "done") is False  # no-op change
    kinds = [e.kind for e in store.task_detail(task_id)[1]]
    assert kinds.count("status_changed") == 1


def test_suggestion_accept_merge_and_split(store):
    t1 = _seed_thread(store, "pg-3a")
    t2 = _seed_thread(store, "pg-3b")
    for tid in (t1, t2):
        store.apply_thread_ops(
            tid,
            ReconcileOutput(
                inserts=[
                    InsertTask(
                        NewTask(title="Same title task", source_message_id=f"m-{tid}",
                                evidence_quote="same title quote"),
                        "alex@x", date(2026, 11, 6), False,
                    )
                ]
            ),
            new_message_ids=[],
            history_id=None,
        )
    a_id, b_id = (t.id for t in store.list_tasks())
    suggestion_id = 1
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute(
            "insert into suggestions (kind, task_id, other_task_id, payload) values (%s, %s, %s, %s::jsonb)",
            ("possible_duplicate", a_id, b_id, "{}"),
        )

    assert store.accept_suggestion(suggestion_id, keep_id=a_id) is True
    assert len(store.list_tasks()) == 1
    primary = store.list_tasks()[0]
    assert primary.id == a_id
    assert any(e.kind == "merged" for e in store.task_detail(a_id)[1])

    assert store.split_merge(a_id) is True
    assert len(store.list_tasks()) == 2
    assert any(e.kind == "split" for e in store.task_detail(a_id)[1])
    assert not store.pending_suggestions()


def test_merge_via_merge_task_rows(store):
    t1 = _seed_thread(store, "pg-4a")
    t2 = _seed_thread(store, "pg-4b")
    ids = []
    for tid in (t1, t2):
        ids += store.apply_thread_ops(
            tid,
            ReconcileOutput(
                inserts=[
                    InsertTask(
                        NewTask(title="Fold me", source_message_id=f"m-{tid}", evidence_quote="fold quote"),
                        "alex@x", None, False,
                    )
                ]
            ),
            new_message_ids=[],
            history_id=None,
        )
    assert store.accept_suggestion is not None
    from email_task_agent.store import merge_task_rows  # module-level helper

    with psycopg.connect(URL, autocommit=False) as conn:
        assert merge_task_rows(conn, MergeOps(primary_id=ids[0], secondary_id=ids[1])) is True
        conn.commit()
    assert len(store.list_tasks()) == 1


def test_chat_cas_and_actions_idempotency(store):
    session_id = store.chat_create()
    session = store.chat_get(session_id)
    assert session is not None and session.state == "idle" and session.version == 0

    v1 = store.chat_cas(session_id, 0, messages=[{"kind": "request", "parts": []}],
                        pending_approvals=None, state="running")
    assert v1 == 1
    assert store.chat_cas(session_id, 0, messages=[], pending_approvals=None, state="idle") is None  # stale
    assert store.chat_get(session_id).state == "running"

    action_id, is_new = store.action_record("create_gmail_draft", {"to": "k@x"}, "tc-1")
    assert is_new is True
    again_id, is_new = store.action_record("create_gmail_draft", {"to": "k@x"}, "tc-1")
    assert (again_id, is_new) == (action_id, False)  # the retry must not resend
    store.action_mark_sent(action_id)
    assert store.action_get(action_id)["status"] == "approved"
    store.action_mark_executed(action_id, "ext-1")
    assert store.action_get(action_id)["status"] == "executed"


def test_sync_state_and_usage_counter(store):
    assert store.get_sync_state() == (None, None)
    store.advance_sync_state("h9", full_sync=True)
    assert store.get_sync_state()[0] == "h9" and store.get_sync_state()[1] is not None

    assert store.chat_turns_today() == 0
    store.record_chat_turn()
    store.record_chat_turn()
    assert store.chat_turns_today() == 2


def test_calendar_and_person_upsert(store):
    thread_db_id = _seed_thread(store, "pg-5")
    store.apply_thread_ops(
        thread_db_id,
        ReconcileOutput(
            inserts=[
                InsertTask(
                    NewTask(title="Dated", source_message_id="m", evidence_quote="dated quote"),
                    "Alex@X", date(2026, 11, 6), False,  # mixed case: upsert must casefold
                )
            ]
        ),
        new_message_ids=[],
        history_id=None,
    )
    in_range = store.tasks_due_between(date(2026, 11, 1), date(2026, 11, 30))
    assert len(in_range) == 1 and in_range[0].owner_email == "alex@x"
    assert store.tasks_due_between(date(2026, 12, 1), date(2026, 12, 31)) == []

