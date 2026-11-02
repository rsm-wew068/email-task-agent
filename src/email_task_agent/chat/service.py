"""Chat turn orchestration (§8.2): four-state machine, version-checked CAS,
approve/deny only, idempotent external writes (the tools own the actions gate).

v0 has no streaming: each turn is a request/response; the UI shows a spinner.
If a tool needs approval the run ends with DeferredToolRequests, the page
renders an approval form with full arguments, and POST /chat/approve resumes
from stored history plus DeferredToolResults. A browser reconnect cannot start
a second run: starting one requires state idle/failed, and every state change
is a version-checked CAS — a double click or a stale form is a no-op.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic_ai.agent import Agent
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolDenied

from email_task_agent.agent.chat import ChatDeps, build_chat_agent
from email_task_agent.store import Store, deserialize_messages, pending_to_dict, serialize_messages


class ChatError(Exception):
    pass


@dataclass(frozen=True)
class TurnResult:
    session_id: int
    version: int
    state: str
    reply: str | None = None
    pending: dict | None = None
    error: str | None = None
    stale: bool = False  # approve arrived for an old form version: nothing done


class ChatService:
    def __init__(
        self,
        store: Store,
        model: Model,
        *,
        mode: str,
        me: str,
        gmail=None,
        agent: Agent[ChatDeps, str] | None = None,
    ):
        self.store = store
        self.mode = mode
        self.me = me
        self.gmail = gmail
        self.agent = agent or build_chat_agent(model)

    def create_session(self) -> int:
        return self.store.chat_create()

    def session(self, session_id: int):
        return self.store.chat_get(session_id)

    # -- turns ------------------------------------------------------------------------

    def run_turn(self, session_id: int, user_text: str) -> TurnResult:
        session = self._claim(session_id, user_text is not None)
        deps = self._deps()
        try:
            result = self.agent.run_sync(
                user_prompt=user_text,
                message_history=deserialize_messages(session.messages) or None,
                deps=deps,
            )
        except Exception as error:  # noqa: BLE001 - state must reflect the failure
            self._finish(session, state="failed", error=str(error))
            return TurnResult(session_id, session.version, "failed", error=str(error))
        return self._persist_output(session, result)

    def approve(self, session_id: int, expected_version: int, decisions: dict[str, bool]) -> TurnResult:
        """Resume a paused run. A version mismatch is a stale form: no-op."""
        session = self.store.chat_get(session_id)
        if session is None:
            raise ChatError(f"unknown session {session_id}")
        if session.state != "awaiting_approval" or session.version != expected_version:
            return TurnResult(session_id, session.version, session.state, stale=True)

        requests = _rebuild_requests(session.pending_approvals)
        results = requests.build_results(
            approvals={
                tool_call_id: (ToolDenied() if granted is False else True)
                for tool_call_id, granted in decisions.items()
            }
        )

        claimed = self.store.chat_cas(
            session_id,
            session.version,
            messages=session.messages,
            pending_approvals=session.pending_approvals,
            state="running",
        )
        if claimed is None:
            return TurnResult(session_id, session.version, session.state, stale=True)

        deps = self._deps()
        try:
            result = self.agent.run_sync(
                message_history=deserialize_messages(session.messages),
                deferred_tool_results=results,
                deps=deps,
            )
        except Exception as error:  # noqa: BLE001
            self._finish(session, state="failed", error=str(error))
            return TurnResult(session_id, claimed, "failed", error=str(error))
        return self._persist_output(session, result, claimed_version=claimed)

    # -- internals ----------------------------------------------------------------------

    def _deps(self) -> ChatDeps:
        return ChatDeps(store=self.store, mode=self.mode, me=self.me, gmail=self.gmail)

    def _claim(self, session_id: int, _has_user_text: bool):
        session = self.store.chat_get(session_id)
        if session is None:
            raise ChatError(f"unknown session {session_id}")
        if session.state == "running":
            raise ChatError("a run is already in progress")
        if session.state == "awaiting_approval":
            raise ChatError("approval required before continuing; use approve")
        claimed = self.store.chat_cas(
            session_id,
            session.version,
            messages=session.messages,
            pending_approvals=session.pending_approvals,
            state="running",
        )
        if claimed is None:
            raise ChatError("session changed concurrently; retry")
        session.version = claimed
        return session

    def _persist_output(self, session, result, *, claimed_version: int | None = None) -> TurnResult:
        version = claimed_version if claimed_version is not None else session.version
        messages_json = serialize_messages(result.all_messages())
        output = result.output
        if isinstance(output, DeferredToolRequests):
            pending = pending_to_dict(output)
            new_version = self.store.chat_cas(
                session.id, version, messages=messages_json, pending_approvals=pending, state="awaiting_approval"
            )
            if new_version is None:
                raise ChatError("lost session race while persisting approvals")
            return TurnResult(session.id, new_version, "awaiting_approval", pending=pending)
        new_version = self.store.chat_cas(
            session.id, version, messages=messages_json, pending_approvals=None, state="idle"
        )
        if new_version is None:
            raise ChatError("lost session race while persisting reply")
        return TurnResult(session.id, new_version, "idle", reply=str(output))

    def _finish(self, session, *, state: str, error: str) -> None:
        self.store.chat_cas(
            session.id, session.version, messages=session.messages, pending_approvals=None, state=state
        )


def _rebuild_requests(pending: dict | None) -> DeferredToolRequests:
    if not pending:
        raise ChatError("session has no pending approvals")
    parts = [
        ToolCallPart(tool_name=item["tool_name"], args=item["args"], tool_call_id=item["tool_call_id"])
        for item in pending.get("approvals", [])
    ]
    external_parts = [
        ToolCallPart(tool_name=item["tool_name"], args=item["args"], tool_call_id=item["tool_call_id"])
        for item in pending.get("calls", [])
    ]
    return DeferredToolRequests(calls=external_parts, approvals=parts, metadata=pending.get("metadata", {}))


def pending_actions_for_ui(pending: dict | None) -> list[dict]:
    """Flatten pending approvals for the approval form (approve/deny only)."""
    if not pending:
        return []
    actions = []
    for item in pending.get("approvals", []):
        args = item["args"]
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        actions.append({"tool_call_id": item["tool_call_id"], "tool_name": item["tool_name"], "args": args})
    return actions
