"""JSON API tests (migration plan §6.1) — replace test_web.py when the HTML
routes are removed. The API contract is what the Next.js app consumes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from email_task_agent.app.main import Deps, create_app
from email_task_agent.chat.service import ChatService
from email_task_agent.demo.seed import seed_demo_instance
from email_task_agent.memory import MemoryStore
from email_task_agent.pipeline.reconcile import InsertTask, ReconcileOutput, Suggest

OWNER = "alex@fernwoodlabs.com"


def make_client(*, chat_model=None, sync_runner=None, reextract_runner=None, store=None):
    demo_store = store or MemoryStore()
    seed_demo_instance(demo_store, owner_email=OWNER)
    chat = ChatService(demo_store, chat_model, mode="demo", me=OWNER) if chat_model else None
    app = create_app(
        Deps(
            store=demo_store,
            mode="demo",
            owner_email=OWNER,
            chat=chat,
            sync_runner=sync_runner,
            reextract_runner=reextract_runner,
        )
    )
    return TestClient(app), demo_store


# -- meta + health ---------------------------------------------------------------------


def test_healthz_and_meta():
    client, _ = make_client()
    assert client.get("/healthz").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["mode"] == "demo"
    assert meta["version"]
    assert meta["owner_email"] == OWNER
    assert meta["chat_enabled"] is False
    assert meta["sync_enabled"] is False


def test_meta_wiring_flags():
    client, _ = make_client(
        chat_model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart(content="hi")])),
        sync_runner=lambda: "ok",
    )
    meta = client.get("/api/meta").json()
    assert meta["chat_enabled"] is True and meta["sync_enabled"] is True


# -- task board ------------------------------------------------------------------------


def test_task_board_lists_seeded_tasks():
    client, _ = make_client()
    body = client.get("/api/tasks").json()
    assert len(body["tasks"]) == 9
    task = next(t for t in body["tasks"] if t["title"] == "Send revised Q3 draft to Kate")
    assert task["status"] == "open" and task["merged"] is False
    assert body["threads"], "threads present for re-extract buttons"


def test_task_board_search_hit_and_miss():
    client, _ = make_client()
    hit = client.get("/api/tasks", params={"q": "invoice"}).json()
    assert [t["title"] for t in hit["tasks"]] == ["Send October invoice to ClientCo billing"]
    miss = client.get("/api/tasks", params={"q": "xyzzynotfound"}).json()
    assert miss["tasks"] == []


def test_task_board_status_filter_and_empty_filters():
    client, store = make_client()
    first = store.list_tasks()[0]
    store.set_task_status(first.id, "done")
    done = client.get("/api/tasks", params={"status": "done"}).json()
    assert [t["id"] for t in done["tasks"]] == [first.id]
    # untouched filter form sends empty strings -> "no filter"
    everything = client.get("/api/tasks", params={"q": "", "status": ""}).json()
    assert len(everything["tasks"]) == 9


# -- calendar --------------------------------------------------------------------------


def test_calendar_range_returns_due_tasks():
    client, _ = make_client()
    body = client.get("/api/calendar", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert len(body) == 8  # seeded gold tasks with due dates in November 2026
    assert all(t["due_date"] for t in body)


def test_calendar_reversed_range_is_422():
    client, _ = make_client()
    response = client.get("/api/calendar", params={"start": "2026-11-30", "end": "2026-11-01"})
    assert response.status_code == 422


# -- status update -----------------------------------------------------------------------


def test_status_update_success_returns_task_view():
    client, store = make_client()
    task = store.list_tasks()[0]
    response = client.post(f"/api/tasks/{task.id}/status", json={"status": "done"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done" and body["id"] == task.id


def test_status_update_bad_enum_is_422():
    client, store = make_client()
    task = store.list_tasks()[0]
    response = client.post(f"/api/tasks/{task.id}/status", json={"status": "archived"})
    assert response.status_code == 422


def test_status_update_unknown_task_is_404():
    client, _ = make_client()
    response = client.post("/api/tasks/99999/status", json={"status": "done"})
    assert response.status_code == 404


# -- suggestions ---------------------------------------------------------------------------


def seed_duplicate_suggestion(store: MemoryStore) -> tuple[int, int]:
    """Two same-title tasks in different threads + a suggestion wiring them;
    returns (suggestion_id, existing_task_id)."""
    from email_task_agent.models.extraction import NewTask as NT

    def insert(title: str, message_id: str, *, suggestion: Suggest | None = None) -> int:
        thread_id = store.upsert_thread(
            f"api-dup-{message_id}", subject="Dup", participants=[OWNER], last_message_at=None, cached_text="x"
        )
        inserted = store.apply_thread_ops(
            thread_id,
            ReconcileOutput(
                inserts=[
                    InsertTask(
                        NT(title=title, source_message_id=message_id,
                           evidence_quote="send the signed form please"),
                        OWNER, None, False,
                    )
                ],
                suggestions=[suggestion] if suggestion else [],
            ),
            new_message_ids=[message_id],
            history_id=None,
        )
        return inserted[0]

    existing_id = insert("Send signed form", "m1")
    new_id = insert("Send signed form", "m2")
    insert(
        "Send signed form",
        "m3",
        suggestion=Suggest(
            kind="possible_duplicate", task_id=existing_id, other_task_id=new_id,
            payload={"new_title": "Send signed form"},
        ),
    )
    suggestion = store.pending_suggestions()[0]
    store.suggestions[suggestion.id] = suggestion.__class__(
        suggestion.id, suggestion.kind, existing_id, new_id, suggestion.payload, "pending", suggestion.created_at
    )
    return suggestion.id, existing_id


def test_suggestion_reject_clears_queue():
    client, store = make_client()
    suggestion_id, _ = seed_duplicate_suggestion(store)
    assert client.get("/api/tasks").json()["suggestions"]
    response = client.post(f"/api/suggestions/{suggestion_id}/reject", json={})
    assert response.status_code == 200 and response.json()["ok"] is True
    assert client.get("/api/tasks").json()["suggestions"] == []


def test_suggestion_accept_merges():
    client, store = make_client()
    suggestion_id, existing_id = seed_duplicate_suggestion(store)
    tasks_before = len(store.list_tasks())
    response = client.post(f"/api/suggestions/{suggestion_id}/accept", json={"keep": existing_id})
    assert response.json()["ok"] is True
    assert client.get("/api/tasks").json()["suggestions"] == []
    assert len(store.list_tasks()) == tasks_before - 1  # folded into the kept row


# -- sync + re-extract banners ---------------------------------------------------------------


def test_sync_banner_configured_and_not():
    client, _ = make_client(sync_runner=lambda: "Synced 1 thread.")
    assert "Synced 1 thread." in client.post("/api/sync", json={}).json()["message"]
    client2, _ = make_client()
    assert "not configured" in client2.post("/api/sync", json={}).json()["message"]


def test_reextract_banner_configured_and_not():
    client, _ = make_client(reextract_runner=lambda tid: f"Re-extracted {tid}: 1 tasks.")
    body = client.post("/api/threads/demo-001-expense-report/reextract", json={})
    assert "Re-extracted demo-001-expense-report" in body.json()["message"]
    client2, _ = make_client()
    assert "not configured" in client2.post("/api/threads/x/reextract", json={}).json()["message"]


# -- chat --------------------------------------------------------------------------------------


def _script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    calls = sum(1 for m in messages for p in getattr(m, "parts", []) if getattr(p, "part_kind", "") == "tool-call")
    if calls == 0:
        return ModelResponse(
            parts=[ToolCallPart(tool_name="create_gmail_draft",
                                args={"to": "k@x", "subject": "s", "body": "b"}, tool_call_id="tc1")]
        )
    return ModelResponse(parts=[TextPart(content="Created (id=demo-x).")])


def test_chat_disabled_is_503():
    client, _ = make_client()
    assert client.post("/api/chat/sessions", json={}).status_code == 503
    assert client.get("/api/chat/sessions/1").status_code == 503
    assert client.post("/api/chat/sessions/1/messages", json={"text": "hi"}).status_code == 503


def test_full_chat_flow_approve_then_stale():
    client, store = make_client(chat_model=FunctionModel(_script))

    created = client.post("/api/chat/sessions", json={})
    assert created.status_code == 201
    session = created.json()
    session_id = session["session_id"]

    paused = client.post(f"/api/chat/sessions/{session_id}/messages", json={"text": "draft it"})
    assert paused.status_code == 200
    body = paused.json()
    assert body["state"] == "awaiting_approval"
    assert body["actions"][0]["tool_call_id"] == "tc1"
    version = body["version"]

    refused = client.post(f"/api/chat/sessions/{session_id}/messages", json={"text": "again"})
    assert refused.status_code == 200  # expected refusal is data, not 4xx
    assert refused.json()["error"] and refused.json()["state"] == "awaiting_approval"

    approved = client.post(
        f"/api/chat/sessions/{session_id}/approve",
        json={"version": version, "decisions": {"tc1": "approve"}},
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["state"] == "idle"
    assert "Created (id=" in body["messages"][-1]["text"]
    assert [store.action_get(i)["status"] for i in store.actions] == ["executed"]

    stale = client.post(
        f"/api/chat/sessions/{session_id}/approve",
        json={"version": version, "decisions": {"tc1": "approve"}},  # old version
    )
    assert stale.status_code == 200
    assert "stale" in stale.json()["error"].lower()
    assert [store.action_get(i)["status"] for i in store.actions] == ["executed"]  # still one

    fetched = client.get(f"/api/chat/sessions/{session_id}")
    assert fetched.json()["version"] == body["version"]


def test_chat_unknown_session_is_404():
    client, _ = make_client(chat_model=FunctionModel(_script))
    assert client.get("/api/chat/sessions/999").status_code == 404
    assert client.post("/api/chat/sessions/999/messages", json={"text": "hi"}).status_code == 404
    assert client.post("/api/chat/sessions/999/approve", json={"version": 0, "decisions": {}}).status_code == 404


def test_chat_empty_text_and_bad_decision_are_422():
    client, _ = make_client(chat_model=FunctionModel(_script))
    session_id = client.post("/api/chat/sessions", json={}).json()["session_id"]
    assert client.post(f"/api/chat/sessions/{session_id}/messages", json={"text": ""}).status_code == 422
    paused = client.post(f"/api/chat/sessions/{session_id}/messages", json={"text": "draft it"})
    version = paused.json()["version"]
    bad = client.post(
        f"/api/chat/sessions/{session_id}/approve",
        json={"version": version, "decisions": {"tc1": "maybe"}},
    )
    assert bad.status_code == 422
