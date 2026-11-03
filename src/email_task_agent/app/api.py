"""JSON API for the Next.js frontend (migration plan §3).

The browser never reaches these endpoints directly — the Next.js server calls
them server-side via BACKEND_URL. Semantics per §3.2:

  - Expected chat outcomes are DATA, not HTTP errors: ChatError cases return
    200 with ``error`` set (Next.js redacts thrown server-action errors in
    production, so the UI would only see a generic message otherwise).
  - Unknown chat session -> 404; chat not wired -> 503.
  - Empty ``q``/``status`` filters mean "no filter".
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from email_task_agent import __version__
from email_task_agent.app.deps import Deps
from email_task_agent.chat.service import ChatError, pending_actions_for_ui
from email_task_agent.store import SuggestionRow, TaskRow, ThreadRow

# -- view models (the contract; export_openapi.py freezes it) -----------------------


class MetaView(BaseModel):
    mode: str
    version: str
    owner_email: str
    chat_enabled: bool
    sync_enabled: bool


class TaskView(BaseModel):
    id: int
    title: str
    owner_email: str | None
    owner_name: str | None
    due_date: date | None
    status: Literal["open", "done", "cancelled"]
    needs_review: bool
    merged: bool
    thread_id: int | None
    gmail_thread_id: str | None


class SuggestionView(BaseModel):
    id: int
    kind: str
    task_id: int | None
    other_task_id: int | None
    payload: dict[str, Any]
    status: str


class ThreadView(BaseModel):
    id: int
    gmail_thread_id: str
    subject: str | None
    participants: list[str]
    last_message_at: str | None


class TaskBoardView(BaseModel):
    tasks: list[TaskView]
    suggestions: list[SuggestionView]
    threads: list[ThreadView]


class StatusUpdate(BaseModel):
    status: Literal["open", "done", "cancelled"]


class AcceptSuggestion(BaseModel):
    keep: int | None = None


class ActionResult(BaseModel):
    ok: bool


class BannerView(BaseModel):
    message: str


class ChatMessageIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class ApproveIn(BaseModel):
    version: int
    decisions: dict[str, Literal["approve", "deny"]]


class ChatMessageView(BaseModel):
    role: Literal["user", "assistant", "tool_call"]
    text: str


class ChatActionView(BaseModel):
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]


class ChatSessionView(BaseModel):
    session_id: int
    version: int
    state: Literal["idle", "running", "awaiting_approval", "failed"]
    messages: list[ChatMessageView]
    actions: list[ChatActionView]
    error: str | None = None


# -- mappers --------------------------------------------------------------------------


def _task_view(row: TaskRow, *, merged: bool = False) -> TaskView:
    return TaskView(
        id=row.id,
        title=row.title,
        owner_email=row.owner_email,
        owner_name=row.owner_name,
        due_date=row.due_date,
        status=row.status,  # type: ignore[arg-type]  # DB check constrains the enum
        needs_review=row.needs_review,
        merged=merged,
        thread_id=row.thread_id,
        gmail_thread_id=row.gmail_thread_id,
    )


def _suggestion_view(row: SuggestionRow) -> SuggestionView:
    return SuggestionView(
        id=row.id,
        kind=row.kind,
        task_id=row.task_id,
        other_task_id=row.other_task_id,
        payload=row.payload,
        status=row.status,
    )


def _thread_view(row: ThreadRow) -> ThreadView:
    return ThreadView(
        id=row.id,
        gmail_thread_id=row.gmail_thread_id,
        subject=row.subject,
        participants=row.participants,
        last_message_at=row.last_message_at.isoformat() if row.last_message_at else None,
    )


def _chat_session_view(session) -> ChatSessionView:
    messages = []
    for message in session.messages:
        for part in message.get("parts", []):
            part_kind = part.get("part_kind")
            if part_kind == "user-prompt":
                messages.append(ChatMessageView(role="user", text=str(part.get("content"))))
            elif part_kind == "text":
                messages.append(ChatMessageView(role="assistant", text=str(part.get("content"))))
            elif part_kind == "tool-call":
                args = part.get("args")
                args_text = args if isinstance(args, str) else json.dumps(args)
                messages.append(
                    ChatMessageView(role="tool_call", text=f"{part.get('tool_name')}({args_text})")
                )
    return ChatSessionView(
        session_id=session.id,
        version=session.version,
        state=session.state,  # type: ignore[arg-type]  # DB check constrains the enum
        messages=messages,
        actions=pending_actions_for_ui(session.pending_approvals),
        error=None,
    )


# -- router ---------------------------------------------------------------------------


def build_api_router(deps: Deps) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/meta", response_model=MetaView)
    def meta() -> MetaView:
        return MetaView(
            mode=deps.mode,
            version=__version__,
            owner_email=deps.owner_email,
            chat_enabled=deps.chat is not None,
            sync_enabled=deps.sync_runner is not None,
        )

    @router.get("/tasks", response_model=TaskBoardView)
    def task_board(q: str | None = None, status: str | None = None) -> TaskBoardView:
        rows = deps.store.list_tasks(q=(q or None), status=(status or None))
        merged_flags = {}
        for row in rows:
            detail = deps.store.task_detail(row.id)
            merged_flags[row.id] = bool(detail and any(e.kind == "merged" for e in detail[1]))
        return TaskBoardView(
            tasks=[_task_view(r, merged=merged_flags.get(r.id, False)) for r in rows],
            suggestions=[_suggestion_view(s) for s in deps.store.pending_suggestions()],
            threads=[_thread_view(t) for t in deps.store.list_threads()],
        )

    @router.get("/calendar", response_model=list[TaskView])
    def calendar(
        start: date = Query(...),
        end: date = Query(...),
    ) -> list[TaskView]:
        if end < start:
            raise HTTPException(status_code=422, detail="end must not be before start")
        return [_task_view(r) for r in deps.store.tasks_due_between(start, end)]

    @router.post("/tasks/{task_id}/status", response_model=TaskView)
    def set_task_status(task_id: int, body: StatusUpdate) -> TaskView:
        if not deps.store.set_task_status(task_id, body.status):
            detail = deps.store.task_detail(task_id)
            if detail is None:
                raise HTTPException(status_code=404, detail=f"unknown task {task_id}")
        row = next((r for r in deps.store.list_tasks() if r.id == task_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown task {task_id}")
        detail = deps.store.task_detail(task_id)
        merged = bool(detail and any(e.kind == "merged" for e in detail[1]))
        return _task_view(row, merged=merged)

    @router.post("/tasks/{task_id}/split", response_model=ActionResult)
    def split_task(task_id: int) -> ActionResult:
        return ActionResult(ok=deps.store.split_merge(task_id))

    @router.post("/suggestions/{suggestion_id}/accept", response_model=ActionResult)
    def accept_suggestion(suggestion_id: int, body: AcceptSuggestion | None = None) -> ActionResult:
        keep = body.keep if body else None
        return ActionResult(ok=deps.store.accept_suggestion(suggestion_id, keep_id=keep))

    @router.post("/suggestions/{suggestion_id}/reject", response_model=ActionResult)
    def reject_suggestion(suggestion_id: int) -> ActionResult:
        return ActionResult(ok=deps.store.reject_suggestion(suggestion_id))

    @router.post("/sync", response_model=BannerView)
    def sync() -> BannerView:
        if deps.sync_runner is None:
            return BannerView(message="Sync is not configured in this instance.")
        return BannerView(message=deps.sync_runner())

    @router.post("/threads/{gmail_thread_id}/reextract", response_model=BannerView)
    def reextract(gmail_thread_id: str) -> BannerView:
        if deps.reextract_runner is None:
            return BannerView(message="Re-extract is not configured in this instance.")
        return BannerView(message=deps.reextract_runner(gmail_thread_id))

    # -- chat -------------------------------------------------------------------------

    def _chat_or_503():
        if deps.chat is None:
            raise HTTPException(status_code=503, detail="chat is not configured")
        return deps.chat

    @router.post("/chat/sessions", response_model=ChatSessionView, status_code=201)
    def create_chat_session() -> ChatSessionView:
        chat = _chat_or_503()
        return _chat_session_view(chat.session(chat.create_session()))

    @router.get("/chat/sessions/{session_id}", response_model=ChatSessionView)
    def get_chat_session(session_id: int) -> ChatSessionView:
        chat = _chat_or_503()
        session = chat.session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
        return _chat_session_view(session)

    def _resolve_session(chat, session_id: int):
        session = chat.session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
        return session

    @router.post("/chat/sessions/{session_id}/messages", response_model=ChatSessionView)
    def send_chat_message(session_id: int, body: ChatMessageIn) -> ChatSessionView:
        chat = _chat_or_503()
        _resolve_session(chat, session_id)
        try:
            result = chat.run_turn(session_id, body.text)
        except ChatError as exc:
            # Expected outcome as data (§3.2): the UI shows the message and the
            # server's real current state.
            session = _resolve_session(chat, session_id)
            view = _chat_session_view(session)
            view.error = str(exc)
            return view
        session = _resolve_session(chat, session_id)
        view = _chat_session_view(session)
        if result.error:
            view.error = result.error
        return view

    @router.post("/chat/sessions/{session_id}/approve", response_model=ChatSessionView)
    def approve_chat(session_id: int, body: ApproveIn) -> ChatSessionView:
        chat = _chat_or_503()
        _resolve_session(chat, session_id)
        try:
            result = chat.approve(
                session_id,
                body.version,
                {call_id: decision == "approve" for call_id, decision in body.decisions.items()},
            )
        except ChatError as exc:
            session = _resolve_session(chat, session_id)
            view = _chat_session_view(session)
            view.error = str(exc)
            return view
        session = _resolve_session(chat, session_id)
        view = _chat_session_view(session)
        if result.stale:
            view.error = "That form was stale — showing current state; nothing was applied."
        elif result.error:
            view.error = result.error
        return view

    return router
