"""Chat state machine (§8.2) with scripted FunctionModel agents: approve,
deny, double-submit staleness, two actions in one turn, crash-after-call
retry idempotency."""

from __future__ import annotations

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from email_task_agent.chat.service import ChatError, ChatService
from email_task_agent.memory import MemoryStore


def _counts(messages: list[ModelMessage]) -> tuple[int, int]:
    """(tool-call parts, tool-return parts) across the history."""
    calls = returns = 0
    for message in messages:
        for part in getattr(message, "parts", []):
            kind = getattr(part, "part_kind", "")
            calls += kind == "tool-call"
            returns += kind == "tool-return"
    return calls, returns


def draft_script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    calls, returns = _counts(messages)
    if calls == 0 and returns == 0:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="create_gmail_draft",
                    args={"to": "kate@x", "subject": "Q3 draft", "body": "Here it is."},
                    tool_call_id="tc1",
                )
            ]
        )
    # A realistic model echoes the tool outcome into its answer (the tool's
    # refusal or confirmation becomes the reply text).
    last_return = None
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", "") == "tool-return":
                last_return = getattr(part, "content", None)
    return ModelResponse(parts=[TextPart(content=str(last_return or "done"))])


def two_action_script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    calls, returns = _counts(messages)
    if calls == 0 and returns == 0:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="create_gmail_draft",
                    args={"to": "kate@x", "subject": "s", "body": "b"},
                    tool_call_id="tcA",
                ),
                ToolCallPart(
                    tool_name="create_google_task",
                    args={"title": "Follow up", "due": None},
                    tool_call_id="tcB",
                ),
            ]
        )
    return ModelResponse(parts=[TextPart(content="Both actions resolved.")])


def make_service(store: MemoryStore, model: FunctionModel, *, mode="demo", gmail=None) -> ChatService:
    return ChatService(store, model, mode=mode, me="alex@x", gmail=gmail)


class FlakyGmail:
    """create_draft raises the first time (the crash), succeeds afterwards."""

    def __init__(self):
        self.calls = 0

    def create_draft(self, to: str, subject: str, body: str) -> str:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("connection reset after sending")
        return "draft-real-1"


def test_turn_awaits_approval_then_approve_executes_once():
    store = MemoryStore()
    service = make_service(store, FunctionModel(draft_script))
    session_id = service.create_session()

    result = service.run_turn(session_id, "please draft the Q3 email to Kate")
    assert result.state == "awaiting_approval"
    assert result.pending and result.pending["approvals"][0]["tool_call_id"] == "tc1"
    assert result.pending["approvals"][0]["args"]["to"] == "kate@x"

    final = service.approve(session_id, result.version, {"tc1": True})
    assert final.state == "idle" and final.reply
    assert "Created (id=" in final.reply
    actions = [store.action_get(aid) for aid in store.actions]
    assert [a["status"] for a in actions] == ["executed"]
    session = store.chat_get(session_id)
    assert session.state == "idle" and session.pending_approvals is None


def test_deny_returns_denial_to_model():
    store = MemoryStore()
    service = make_service(store, FunctionModel(draft_script))
    session_id = service.create_session()
    paused = service.run_turn(session_id, "draft it")
    final = service.approve(session_id, paused.version, {"tc1": False})
    assert final.state == "idle" and final.reply
    assert all(a["status"] == "proposed" for a in (store.action_get(i) for i in store.actions))


def test_double_submit_stale_version_is_noop():
    store = MemoryStore()
    service = make_service(store, FunctionModel(draft_script))
    session_id = service.create_session()
    paused = service.run_turn(session_id, "draft it")
    first = service.approve(session_id, paused.version, {"tc1": True})
    again = service.approve(session_id, paused.version, {"tc1": True})  # stale form resubmitted
    assert first.state == "idle"
    assert again.stale is True  # old form: nothing applied twice
    assert len(store.actions) == 1


def test_two_actions_in_one_turn_both_resolved():
    store = MemoryStore()
    service = make_service(store, FunctionModel(two_action_script))
    session_id = service.create_session()
    paused = service.run_turn(session_id, "draft and make a follow-up task")
    assert paused.state == "awaiting_approval"
    assert {a["tool_call_id"] for a in paused.pending["approvals"]} == {"tcA", "tcB"}
    final = service.approve(session_id, paused.version, {"tcA": True, "tcB": True})
    assert final.state == "idle"
    statuses = sorted(a["status"] for a in (store.action_get(i) for i in store.actions))
    assert statuses == ["executed", "executed"]


def test_crash_after_api_call_retry_never_sends_twice():
    store = MemoryStore()
    gmail = FlakyGmail()
    service = make_service(store, FunctionModel(draft_script), mode="private", gmail=gmail)
    session_id = service.create_session()

    paused = service.run_turn(session_id, "draft it")
    assert paused.state == "awaiting_approval"

    # First approve: the tool marks the action 'approved' (sent), then the
    # external call crashes -> run fails, pending kept for retry.
    failed = service.approve(session_id, paused.version, {"tc1": True})
    assert failed.state == "failed" and failed.error
    assert gmail.calls == 1

    # Retry from the same form: the gate sees status 'approved' and refuses.
    retry = service.approve(session_id, failed.version, {"tc1": True})
    assert retry.state == "idle"
    assert gmail.calls == 1  # never sent twice
    assert "NOT resending" in (retry.reply or "")


def test_daily_turn_cap_blocks_without_spending():
    store = MemoryStore()
    service = make_service(store, FunctionModel(draft_script), )
    service.daily_turn_cap = 1

    first = service.run_turn(service.create_session(), "draft it")
    assert first.state == "awaiting_approval" and store.chat_turns_today() == 1

    session_id = first.session_id
    final = service.approve(session_id, first.version, {"tc1": True})  # approvals are free
    assert final.state == "idle"

    second = service.run_turn(session_id, "one more")
    assert second.error and "cap reached" in second.error
    assert store.chat_turns_today() == 1  # the blocked turn did not spend
    session = store.chat_get(session_id)
    assert session.state == "idle"  # session restored, not stuck running


def test_approve_requires_exactly_the_pending_ids():
    store = MemoryStore()
    service = make_service(store, FunctionModel(draft_script))
    session_id = service.create_session()
    paused = service.run_turn(session_id, "draft it")

    for bad in ({"tcX": True}, {"tc1": True, "tc2": False}, {}):
        with pytest.raises(ChatError, match="exactly the pending"):
            service.approve(session_id, paused.version, bad)
    assert store.actions == {}  # nothing executed on malformed decisions


def test_run_turn_guardrails():
    store = MemoryStore()
    service = make_service(store, FunctionModel(draft_script))
    session_id = service.create_session()
    service.run_turn(session_id, "draft it")
    with pytest.raises(ChatError):
        service.run_turn(session_id, "another message while awaiting approval")
    with pytest.raises(ChatError):
        service.run_turn(999, "no such session")
