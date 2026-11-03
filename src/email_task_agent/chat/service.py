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
from pydantic_ai.tools import DeferredToolRequests, ToolDenied

from email_task_agent.agent.chat import ChatDeps, build_chat_agent
from email_task_agent.llm import provider_failure
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
        daily_turn_cap: int | None = None,
        fallback_model: Model | None = None,
    ):
        self.store = store
        self.mode = mode
        self.me = me
        self.gmail = gmail
        self.agent = agent or build_chat_agent(model)
        # Demo spend control (plan §11): None disables the cap (private instance).
        self.daily_turn_cap = daily_turn_cap
        # Runtime failover: provider-level errors on the primary (HF throttled /
        # out of credits / down) retry this same request on the fallback model.
        self.fallback_model = fallback_model

    def create_session(self) -> int:
        return self.store.chat_create()

    def session(self, session_id: int):
        return self.store.chat_get(session_id)

    # -- turns ------------------------------------------------------------------------

    def run_turn(self, session_id: int, user_text: str) -> TurnResult:
        session = self._claim(session_id, user_text is not None)
        if self.daily_turn_cap is not None and self.store.chat_turns_today() >= self.daily_turn_cap:
            # Release the claim: put the session back exactly as it was.
            restored = self.store.chat_cas(
                session_id,
                session.version,
                messages=session.messages,
                pending_approvals=session.pending_approvals,
                state=session.state,
            )
            return TurnResult(
                session_id,
                restored or session.version,
                session.state,
                error=f"Daily demo chat cap reached ({self.daily_turn_cap} turns/day) — try again tomorrow.",
            )
        self.store.record_chat_turn()
        deps = self._deps()
        try:
            result = self._run_sync(
                user_prompt=user_text,
                message_history=deserialize_messages(session.messages) or None,
                deps=deps,
            )
        except Exception as error:  # noqa: BLE001 - state must reflect the failure
            self._finish(session, state="failed", error=str(error))
            return TurnResult(session_id, session.version, "failed", error=str(error))
        return self._persist_output(session, result)

    def approve(self, session_id: int, expected_version: int, decisions: dict[str, bool]) -> TurnResult:
        """Resume a paused run (from awaiting_approval, or from failed — e.g.
        the process crashed mid-run and the user retries the same form).
        A version mismatch is a stale form: no-op."""
        session = self.store.chat_get(session_id)
        if session is None:
            raise ChatError(f"unknown session {session_id}")
        resumable = session.state in {"awaiting_approval", "failed"} and session.pending_approvals
        if not resumable or session.version != expected_version:
            return TurnResult(session_id, session.version, session.state, stale=True)

        # build_results raises a bare ValueError for unknown IDs and silently
        # accepts missing ones — require an exact match instead (review
        # finding 6): a direct server-action call can send anything.
        pending_ids = {
            item["tool_call_id"]
            for item in (
                session.pending_approvals.get("approvals", []) + session.pending_approvals.get("calls", [])
            )
        }
        if set(decisions) != pending_ids:
            raise ChatError(
                f"decisions must cover exactly the pending actions {sorted(pending_ids)}; "
                f"got {sorted(decisions)}"
            )

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
            result = self._run_sync(
                message_history=deserialize_messages(session.messages),
                deferred_tool_results=results,
                deps=deps,
            )
        except Exception as error:  # noqa: BLE001 - keep pending so the same form can be retried
            new_version = self.store.chat_cas(
                session_id,
                claimed,
                messages=session.messages,
                pending_approvals=session.pending_approvals,
                state="failed",
            )
            return TurnResult(session_id, new_version or claimed, "failed", error=str(error))
        return self._persist_output(session, result, claimed_version=claimed)

    # -- internals ----------------------------------------------------------------------

    def _run_sync(self, **kwargs):
        """agent.run_sync; on a provider-level failure of the primary model
        (throttled / out of credits / down), retry once on the fallback model.
        Programming errors and malformed requests (400) are never retried —
        they are our bug and a second provider would only mask them."""
        try:
            return self.agent.run_sync(**kwargs)
        except Exception as error:  # re-raised unless the fallback serves
            if self.fallback_model is None or not provider_failure(error):
                raise
            return self.agent.run_sync(**kwargs, model=self.fallback_model)

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
