"""Demo seeding (D8): all gold tasks land, seeding is idempotent per thread."""

from __future__ import annotations

from email_task_agent.demo.seed import seed_demo_instance
from email_task_agent.memory import MemoryStore


def test_seed_lands_all_gold_tasks() -> None:
    store = MemoryStore()
    message = seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")

    tasks = store.list_tasks()
    # e1_test.json has 9 gold tasks across 6 gold-bearing threads (12 total).
    assert len(tasks) == 9, message
    assert len(store.list_threads()) == 20

    titles = {t.title for t in tasks}
    # Tasks from DIFFERENT threads must all land (regression: a global guard
    # silently dropped every thread after the first).
    assert "Send revised Q3 draft to Kate" in titles
    assert "Send me the onboarding checklist" in titles
    assert "Refresh staging SSL cert before pen test" in titles  # ownerless gold


def test_seed_is_idempotent_per_thread() -> None:
    store = MemoryStore()
    seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")
    seed_demo_instance(store, owner_email="alex@fernwoodlabs.com")
    assert len(store.list_tasks()) == 9  # no duplicates on re-seed


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
    assert len(after) == len(before) + 1  # re-seed added nothing else
