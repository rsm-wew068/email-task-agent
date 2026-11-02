"""App shell, extraction models, and suite-builder CLI contract tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from email_task_agent.app.main import create_app
from email_task_agent.models.extraction import NewTask, TaskUpdate, ThreadExtraction


def test_healthz() -> None:
    from email_task_agent.app.main import Deps
    from email_task_agent.memory import MemoryStore

    app = create_app(Deps(store=MemoryStore(), mode="demo", owner_email="alex@x.example"))
    client = TestClient(app)
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["mode"] == "demo"


def test_thread_extraction_contract() -> None:
    ext = ThreadExtraction(
        new_tasks=[
            NewTask(
                title="Send Q3 draft",
                owner_email="alex@x.example",
                due_date="2026-11-06",
                status="open",
                confidence=0.9,
                evidence_quote="Could you send me the revised Q3 draft by Friday?",
                source_message_id="msg-1",
            )
        ],
        updates=[
            TaskUpdate(
                ref_task_id=42,
                status="done",
                confidence=0.8,
                evidence_quote="Done — sent just now.",
                source_message_id="msg-2",
            )
        ],
    )
    payload = json.loads(ext.model_dump_json())
    assert payload["new_tasks"][0]["evidence_quote"].startswith("Could you")
    assert payload["updates"][0]["ref_task_id"] == 42


def test_invalid_status_rejected_by_schema() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NewTask(
            title="x",
            status="archived",  # not in the allowed pattern
            evidence_quote="quote of at least some length here",
            source_message_id="m",
        )


def test_build_suites_module_generates_files(tmp_path, monkeypatch) -> None:
    from email_task_agent.synth import build_suites

    out_e1 = tmp_path / "e1.json"
    out_demo = tmp_path / "demo.json"
    monkeypatch.setattr(build_suites, "E1_PATH", out_e1)
    monkeypatch.setattr(build_suites, "DEMO_PATH", out_demo)

    build_suites.main()

    raw_e1 = json.loads(out_e1.read_text())
    raw_demo = json.loads(out_demo.read_text())
    assert raw_e1["suite"] == "e1-v1"
    assert raw_demo["suite"] == "demo-v1"
    assert len(raw_e1["threads"]) >= 12
    gold_count = sum(len(t["gold"]) for t in raw_e1["threads"])
    assert gold_count == 9  # starter set: 9 gold tasks across the e1 cases
    # demo suite = e1 threads + extras, all with gold stripped
    assert len(raw_demo["threads"]) > len(raw_e1["threads"])
    assert all(t["gold"] == [] for t in raw_demo["threads"])
