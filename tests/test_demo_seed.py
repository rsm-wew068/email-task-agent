"""Demo seeding: all gold tasks land, seeding is idempotent per thread."""

from __future__ import annotations

import json
from pathlib import Path

from email_task_agent.demo.seed import seed_demo_instance
from email_task_agent.memory import MemoryStore

_SUITE = json.loads((Path(__file__).resolve().parents[1] / "evals" / "data" / "e1_test.json").read_text())
SEED_GOLD_COUNT = sum(len(t["gold"]) for t in _SUITE["threads"]) + 2  # + crafted review-queue pair
SEED_THREAD_COUNT = sum(1 for t in _SUITE["threads"]) + 11  # + 8 demo extras + 3 review-queue threads


def test_seed_lands_all_gold_tasks() -> None:
    store = MemoryStore()
    message = seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")

    tasks = store.list_tasks()
    assert len(tasks) == SEED_GOLD_COUNT, message
    assert len(store.list_threads()) == SEED_THREAD_COUNT

    titles = {t.title for t in tasks}
    # Tasks from different threads must all land.
    assert "Send revised Q3 draft to Kate" in titles
    assert "Send me the onboarding checklist" in titles
    assert "Refresh staging SSL cert before pen test" in titles  # ownerless gold


def test_seed_is_idempotent_per_thread() -> None:
    store = MemoryStore()
    seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")
    seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")
    assert len(store.list_tasks()) == SEED_GOLD_COUNT


def test_seed_respects_existing_thread_tasks() -> None:
    # A thread that already has tasks (e.g. from a sync run) keeps them; the
    # seeder must not duplicate into it.
    store = MemoryStore()
    seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")
    before = {(t.title) for t in store.list_tasks()}
    thread = store.list_threads()[0]
    from email_task_agent.models.extraction import NewTask
    from email_task_agent.pipeline.reconcile import InsertTask, ReconcileOutput

    store.apply_thread_ops(
        thread.id,
        ReconcileOutput(
            inserts=[
                InsertTask(
                    NewTask(title="Synced task", source_message_id="m-sync",
                            evidence_quote="quote present in the thread body"),
                    "alex@fernwoodlabs.com",
                    None,
                    False,
                )
            ]
        ),
        new_message_ids=[],
        history_id=None,
    )
    seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")
    after = {t.title for t in store.list_tasks()}
    assert "Synced task" in after
    assert len(after) == len(before) + 1


def test_demo_reextract_runs_the_real_pipeline() -> None:
    """load_demo_thread feeds the checked-in mailbox into the standard
    pipeline; a repeat run must not duplicate (already-processed marks)."""
    from email_task_agent.demo.seed import load_demo_thread
    from email_task_agent.models.extraction import NewTask, ThreadExtraction
    from email_task_agent.pipeline.sync import reextract_thread_data

    store = MemoryStore()
    seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")
    before = len(store.list_tasks())

    thread = load_demo_thread("demo-001-expense-report")
    assert thread is not None and len(thread.messages) == 1

    def fake_extract(extract_input):
        # Like the real model: returns nothing when the task already exists in
        # the open-tasks context it is shown.
        if any("expense" in t.title for t in extract_input.open_tasks):
            return ThreadExtraction()
        return ThreadExtraction(
            new_tasks=[
                NewTask(
                    title="File October expense report",
                    owner_email="alex@fernwoodlabs.com",
                    due_date="2026-11-10",
                    confidence=0.95,
                    evidence_quote="Please file your October expense report by Tuesday so payroll can reimburse you this cycle.",
                    source_message_id=thread.messages[0].message_id,
                )
            ]
        )

    outcome = reextract_thread_data(store, thread, fake_extract, owner_email="alex@fernwoodlabs.com")
    assert outcome.inserted_task_ids and outcome.skipped is None
    assert len(store.list_tasks()) == before + 1

    task = next(t for t in store.list_tasks() if t.title == "File October expense report")
    assert task.evidence_quote.startswith("Please file your October")

    outcome2 = reextract_thread_data(store, thread, fake_extract, owner_email="alex@fernwoodlabs.com")
    assert outcome2.inserted_task_ids == []  # the extractor saw the open task and returned nothing
    assert len(store.list_tasks()) == before + 1
