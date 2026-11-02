"""Web routes over MemoryStore (no DB), plus chat-over-HTTP with a scripted
model, and demo seeding."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from email_task_agent.app.main import Deps, create_app
from email_task_agent.chat.service import ChatService
from email_task_agent.demo.seed import seed_demo_instance
from email_task_agent.memory import MemoryStore
from email_task_agent.pipeline.reconcile import InsertTask, ReconcileOutput, Suggest

REPO_DATA = None  # default: package-relative evals/data


@pytest.fixture
def store():
    demo_store = MemoryStore()
    seed_demo_instance(demo_store, owner_email="alex@fernwoodlabs.com")
    return demo_store


@pytest.fixture
def client(store):
    app = create_app(Deps(store=store, mode="demo", owner_email="alex@fernwoodlabs.com"))
    return TestClient(app)


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok" and body["mode"] == "demo"


def test_tasks_page_lists_seeded_tasks(client):
    html = client.get("/").text
    assert "Q3 draft" in html  # from e1_test.json gold seeding


def test_task_search_filter(client):
    html = client.get("/", params={"q": "invoice"}).text
    assert "invoice" in html.lower()


def test_calendar_page_renders_month(client):
    html = client.get("/calendar", params={"month": "2026-11"}).text
    assert "November 2026" in html
    assert "cal-event" in html  # seeded tasks with due dates appear


def test_task_status_toggle(client, store):
    task = store.list_tasks()[0]
    new_status = "done" if task.status == "open" else "open"
    response = client.post(f"/tasks/{task.id}/status", data={"status": new_status})
    assert response.status_code == 200
    assert store.list_tasks(status=new_status)


def test_suggestion_accept_merge_and_reject(client, store):
    # Build a duplicate pair through the real ops path.
    thread_id = store.upsert_thread("web-dup", subject="Dup", participants=["alex@x"], last_message_at=None, cached_text="x")
    from email_task_agent.models.extraction import NewTask as NT

    store.apply_thread_ops(
        thread_id,
        ReconcileOutput(
            inserts=[InsertTask(NT(title="Send signed form", source_message_id="m1", evidence_quote="send the signed form please"), "alex@x", None, False)],
            suggestions=[Suggest(kind="possible_duplicate", task_id=None, payload={"new_title": "Send signed form"})],
        ),
        new_message_ids=["m1"],
        history_id=None,
    )
    task_id = store.list_tasks()[0].id
    # wire the suggestion at the persisted task
    suggestion = store.pending_suggestions()[0]
    store.suggestions[suggestion.id] = suggestion.__class__(
        suggestion.id, suggestion.kind, task_id, None, suggestion.payload, "pending", suggestion.created_at
    )

    html = client.get("/").text
    assert "Possible duplicate" in html

    response = client.post(f"/suggestions/{suggestion.id}/reject", data={})
    assert response.status_code == 200
    assert store.pending_suggestions() == []


def test_sync_banner_demo_mode(client):
    app_client = TestClient(
        create_app(Deps(store=client.app and MemoryStore(), mode="demo", owner_email="x@x", sync_runner=lambda: "Synced 1 thread."))
    )
    response = app_client.post("/sync", data={})
    assert "Synced 1 thread." in response.text


def test_chat_setup_message_without_model(client):
    html = client.get("/chat").text
    assert "OPENAI_API_KEY" in html


def _script(messages, info: AgentInfo) -> ModelResponse:
    calls = sum(
        1 for m in messages for p in getattr(m, "parts", []) if getattr(p, "part_kind", "") == "tool-call"
    )
    if calls == 0:
        return ModelResponse(
            parts=[ToolCallPart(tool_name="create_gmail_draft", args={"to": "k@x", "subject": "s", "body": "b"}, tool_call_id="tc1")]
        )
    return ModelResponse(parts=[TextPart(content="Draft handled.")])


def test_chat_over_http_full_approval_flow(store):
    service = ChatService(store, FunctionModel(_script), mode="demo", me="alex@fernwoodlabs.com")
    client = TestClient(create_app(Deps(store=store, mode="demo", owner_email="alex@fernwoodlabs.com", chat=service)))

    first = client.post("/chat", data={"session_id": "", "message": "please draft a reply to Kate"})
    assert first.status_code == 200
    assert "approval" in first.text.lower() or "create_gmail_draft" in first.text
    assert "tc1" in first.text

    # Extract the rendered version from the session (the form carries it).
    session_id = int(first.cookies.get("chat_session"))
    session = store.chat_get(session_id)
    version = session.version

    second = client.post("/chat/approve", data={"session_id": str(session_id), "version": str(version), "decision_tc1": "approve"})
    assert second.status_code == 200
    assert "Draft handled." in second.text
