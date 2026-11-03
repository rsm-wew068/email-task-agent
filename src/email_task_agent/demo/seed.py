"""Demo instance seeding (D8): synthetic mailbox only, never real mail.

Loads the checked-in suites (evals/data/) into any Store:
  - demo_mailbox.json threads -> threads + messages + cached_text;
  - e1_test.json gold         -> starter tasks, inserted only when the store
    has none for those threads (idempotent across restarts).

The public demo also works with no LLM key: browse tasks/calendar and chat
against the seeded data (external writes stubbed in demo mode).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from email_task_agent.models.extraction import NewTask
from email_task_agent.pipeline.reconcile import InsertTask, ReconcileOutput
from email_task_agent.store import Store

REPO_ROOT = Path(__file__).resolve().parents[3]
# Repo checkout: <root>/evals/data. When installed as a wheel (Docker Space) the
# module lives under site-packages, so fall back to the working directory's copy.
_DATA_CANDIDATES = [REPO_ROOT / "evals" / "data", Path.cwd() / "evals" / "data"]
DATA_DIR = next((p for p in _DATA_CANDIDATES if p.is_dir()), _DATA_CANDIDATES[0])


def _load(name: str, data_dir: Path | None) -> dict:
    path = (data_dir or DATA_DIR) / name
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def seed_demo_instance(store: Store, *, owner_email: str, data_dir: Path | None = None) -> str:
    demo = _load("demo_mailbox.json", data_dir)
    e1 = _load("e1_test.json", data_dir)
    gold_by_thread = {t["thread_id"]: t.get("gold", []) for t in e1.get("threads", [])}

    def as_date(raw: str | None):
        return date.fromisoformat(raw) if raw else None

    seeded_threads, seeded_tasks = 0, 0
    for thread in demo.get("threads", []):
        thread_id = thread["thread_id"]
        emails = thread["emails"]
        participants = sorted(
            {e["from"].casefold() for e in emails}
            | {addr.casefold() for e in emails for addr in e.get("to", []) + e.get("cc", [])}
            | {owner_email.casefold()}
        )
        cached_text = "\n\n".join(f"Subject: {e['subject']}\n\n{e['body']}" for e in emails)
        thread_db_id = store.upsert_thread(
            thread_id,
            subject=emails[0]["subject"] if emails else None,
            participants=participants,
            last_message_at=max(
                (datetime.fromisoformat(e["date"]) for e in emails if e.get("date")), default=None
            ),
            cached_text=cached_text,
        )
        message_ids = []
        for index, email_data in enumerate(emails):
            message_id = f"{thread_id}#{index}"
            message_ids.append(message_id)
            store.upsert_message(
                message_id,
                thread_db_id,
                datetime.fromisoformat(email_data["date"]) if email_data.get("date") else None,
            )
        seeded_threads += 1

        gold = gold_by_thread.get(thread_id, [])
        if not gold:
            continue
        if store.tasks_in_thread(thread_db_id):
            continue  # this thread's tasks already seeded: keep restart idempotent
        inserts = []
        for item in gold:
            inserts.append(
                InsertTask(
                    task=NewTask(
                        title=item["title"],
                        owner_email=item.get("owner_email"),
                        due_date=item.get("due_date"),
                        status=item.get("status", "open"),
                        confidence=1.0,
                        evidence_quote=item["evidence_sentence"],
                        source_message_id=message_ids[item["email_index"]],
                    ),
                    owner_email=item.get("owner_email"),
                    due_date=as_date(item.get("due_date")),
                    needs_review=False,
                )
            )
        store.apply_thread_ops(thread_db_id, ReconcileOutput(inserts=inserts), new_message_ids=[], history_id=None)
        seeded_tasks += len(inserts)

    seeded_tasks += _seed_review_demo(store, owner_email=owner_email)
    return f"Seeded demo: {seeded_threads} threads, {seeded_tasks} tasks, 1 review-queue suggestion."


def _seed_review_demo(store: Store, *, owner_email: str) -> int:
    """A crafted duplicate pair + pending suggestion so the review queue has
    content in a fresh demo (suggestions otherwise only come from live syncs)."""
    from email_task_agent.models.extraction import NewTask
    from email_task_agent.pipeline.reconcile import Suggest

    existing = [t for t in store.list_tasks() if t.title == "Send signed renewal contract"]
    if existing:
        return 0  # already seeded

    def insert(title: str, message_id: str) -> int:
        thread_db_id = store.upsert_thread(
            f"demo-review-{message_id}",
            subject="Renewal paperwork",
            participants=[owner_email],
            last_message_at=None,
            cached_text="please send the signed renewal contract",
        )
        inserted = store.apply_thread_ops(
            thread_db_id,
            ReconcileOutput(
                inserts=[
                    InsertTask(
                        NewTask(
                            title=title,
                            source_message_id=message_id,
                            evidence_quote="please send the signed renewal contract",
                        ),
                        owner_email,
                        None,
                        False,
                    )
                ]
            ),
            new_message_ids=[message_id],
            history_id=None,
        )
        return inserted[0]

    first = insert("Send signed renewal contract", "demo-review-m1")
    second = insert("Send signed renewal contract", "demo-review-m2")
    store.apply_thread_ops(
        store.upsert_thread("demo-review-s", subject="s", participants=[owner_email], last_message_at=None, cached_text="x"),
        ReconcileOutput(
            suggestions=[
                Suggest(
                    kind="possible_duplicate",
                    task_id=first,
                    other_task_id=second,
                    payload={"new_title": "Send signed renewal contract"},
                )
            ]
        ),
        new_message_ids=[],
        history_id=None,
    )
    return 2
