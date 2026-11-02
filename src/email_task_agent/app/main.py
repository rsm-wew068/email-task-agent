"""FastAPI app: pages, chat, /sync (plan §5). Jinja2 + HTMX, no streaming (v0).

Dependency injection keeps the whole app testable: create_app() takes a
Deps object (store, chat service, sync runner); build_default_app() wires the
real thing from settings — Neon Postgres + OpenAI when configured, otherwise
an in-memory seeded demo instance (mode=demo, external writes stubbed).
"""

from __future__ import annotations

import calendar as pycalendar
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from email_task_agent import __version__
from email_task_agent.chat.service import ChatError, ChatService, pending_actions_for_ui

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "web" / "templates"


@dataclass
class Deps:
    store: object
    mode: str  # demo | private
    owner_email: str
    chat: ChatService | None = None
    sync_runner: Callable[[], str] | None = None  # returns a banner message
    reextract_runner: Callable[[str], str] | None = None


def create_app(deps: Deps) -> FastAPI:
    app = FastAPI(title="email-task-agent", version=__version__)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def render(request: Request, name: str, **context):
        context.setdefault("mode", deps.mode)
        return templates.TemplateResponse(request=request, name=name, context=context)

    # -- pages ----------------------------------------------------------------------

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "version": __version__, "mode": deps.mode}

    def _merged_flags(task_rows) -> dict[int, bool]:
        flags = {}
        for row in task_rows:
            detail = deps.store.task_detail(row.id)
            flags[row.id] = bool(detail and any(e.kind == "merged" for e in detail[1]))
        return flags

    @app.get("/", response_class=HTMLResponse)
    def tasks_page(request: Request, q: str | None = None, status: str | None = None):
        rows = deps.store.list_tasks(q=q, status=status)
        return render(
            request,
            "tasks.html",
            tasks=rows,
            merged_recently=_merged_flags(rows),
            suggestions=deps.store.pending_suggestions(),
            threads=deps.store.list_threads(),
            q=q,
            status=status,
        )

    @app.get("/calendar", response_class=HTMLResponse)
    def calendar_page(request: Request, month: str | None = None):
        today = date.today()
        if month:
            year, mon = (int(part) for part in month.split("-"))
            anchor = date(year, mon, 1)
        else:
            anchor = today.replace(day=1)
        weeks_raw = pycalendar.Calendar(firstweekday=0).monthdatescalendar(anchor.year, anchor.month)
        month_tasks = deps.store.tasks_due_between(weeks_raw[0][0], weeks_raw[-1][-1])
        by_date: dict[date, list] = {}
        for row in month_tasks:
            by_date.setdefault(row.due_date, []).append(row)
        weeks = [
            [
                {
                    "day": day.day if day.month == anchor.month else None,
                    "in_month": day.month == anchor.month,
                    "is_today": day == today,
                    "tasks": by_date.get(day, []),
                }
                for day in week
            ]
            for week in weeks_raw
        ]
        prev = date(anchor.year - 1, 12, 1) if anchor.month == 1 else anchor.replace(month=anchor.month - 1)
        nxt = date(anchor.year + 1, 1, 1) if anchor.month == 12 else anchor.replace(month=anchor.month + 1)
        return render(
            request,
            "calendar.html",
            weeks=weeks,
            month_label=anchor.strftime("%B %Y"),
            prev_month=prev.strftime("%Y-%m"),
            next_month=nxt.strftime("%Y-%m"),
        )

    # -- task actions -----------------------------------------------------------------

    @app.post("/tasks/{task_id}/status", response_class=HTMLResponse)
    def set_status(request: Request, task_id: int, status: str = Form(...)):
        if status in {"open", "done", "cancelled"}:
            deps.store.set_task_status(task_id, status)
        row = next((r for r in deps.store.list_tasks() if r.id == task_id), None)
        if row is None:
            return HTMLResponse("<tr><td colspan=5>gone</td></tr>")
        return render(request, "_task_row.html", task=row, merged_recently={})

    @app.post("/tasks/{task_id}/split", response_class=HTMLResponse)
    def split_task(request: Request, task_id: int):
        deps.store.split_merge(task_id)
        return render(
            request,
            "_review_queue.html",
            suggestions=deps.store.pending_suggestions(),
        )

    @app.post("/suggestions/{suggestion_id}/accept", response_class=HTMLResponse)
    def accept_suggestion(request: Request, suggestion_id: int, keep: int | None = Form(None)):
        deps.store.accept_suggestion(suggestion_id, keep_id=keep)
        return render(request, "_review_queue.html", suggestions=deps.store.pending_suggestions())

    @app.post("/suggestions/{suggestion_id}/reject", response_class=HTMLResponse)
    def reject_suggestion(request: Request, suggestion_id: int):
        deps.store.reject_suggestion(suggestion_id)
        return render(request, "_review_queue.html", suggestions=deps.store.pending_suggestions())

    # -- sync -------------------------------------------------------------------------

    @app.post("/sync", response_class=HTMLResponse)
    def sync(request: Request):
        if deps.sync_runner is None:
            message = "Sync is not configured in this instance."
        else:
            message = deps.sync_runner()
        return f"<span class=\"muted\">{message}</span>"

    @app.post("/threads/{gmail_thread_id}/reextract", response_class=HTMLResponse)
    def reextract(request: Request, gmail_thread_id: str):
        if deps.reextract_runner is None:
            message = "Re-extract is not configured in this instance."
        else:
            message = deps.reextract_runner(gmail_thread_id)
        return f"<span class=\"muted\">{message}</span>"

    # -- chat (v0: request/response, no streaming) -------------------------------------

    def _chat_history(messages: list[dict]) -> list[dict]:
        """Serialized ModelMessages -> simple display rows."""
        out: list[dict] = []
        for message in messages:
            for part in message.get("parts", []):
                part_kind = part.get("part_kind")
                if part_kind == "user-prompt":
                    content = part.get("content")
                    out.append({"role": "user", "text": str(content)})
                elif part_kind == "text":
                    out.append({"role": "bot", "text": str(part.get("content"))})
                elif part_kind == "tool-call":
                    args = part.get("args")
                    args_text = args if isinstance(args, str) else json.dumps(args)
                    out.append({"role": "bot", "text": f"🔧 {part.get('tool_name')}({args_text})"})
        return out

    def _session_id(request: Request, form_session_id: str | None) -> int:
        raw = form_session_id or request.cookies.get("chat_session")
        if raw and raw.isdigit() and deps.chat is not None and deps.chat.session(int(raw)) is not None:
            return int(raw)
        return deps.chat.create_session()

    def _chat_panel_context(session_row, *, error: str | None = None) -> dict:
        pending = session_row.pending_approvals
        return {
            "session_id": session_row.id,
            "version": session_row.version,
            "state": session_row.state,
            "messages": _chat_history(session_row.messages),
            "actions": pending_actions_for_ui(pending),
            "error": error,
        }

    @app.get("/chat", response_class=HTMLResponse)
    def chat_page(request: Request):
        if deps.chat is None:
            return render(
                request,
                "chat.html",
                messages=[{"role": "bot", "text": "Chat needs OPENAI_API_KEY (or a configured model)."}],
                state="idle", session_id=0, version=0, actions=[], error=None,
            )
        session_id = _session_id(request, None)
        session = deps.chat.session(session_id)
        response = render(request, "chat.html", **_chat_panel_context(session))
        response.set_cookie("chat_session", str(session_id))
        return response

    @app.post("/chat", response_class=HTMLResponse)
    async def chat_post(request: Request, message: str = Form(""), session_id: str = Form("")):
        import anyio

        sid = _session_id(request, session_id)
        try:
            # run_sync needs its own event loop: offload to a worker thread.
            result = await anyio.to_thread.run_sync(lambda: deps.chat.run_turn(sid, message))
        except ChatError as exc:
            session = deps.chat.session(sid)
            response = render(request, "_chat_panel.html", **_chat_panel_context(session, error=str(exc)))
            response.set_cookie("chat_session", str(sid))
            return response
        session = deps.chat.session(sid)
        context = _chat_panel_context(session)
        if result.error:
            context["error"] = result.error
        response = render(request, "_chat_panel.html", **context)
        response.set_cookie("chat_session", str(sid))
        return response

    @app.post("/chat/approve", response_class=HTMLResponse)
    async def chat_approve(request: Request):
        import anyio

        form = await request.form()
        sid = int(form.get("session_id", "0"))
        version = int(form.get("version", "-1"))
        decisions = {
            key.removeprefix("decision_"): value == "approve"
            for key, value in form.multi_items()
            if key.startswith("decision_")
        }
        try:
            result = await anyio.to_thread.run_sync(
                lambda: deps.chat.approve(sid, version, decisions)
            )
        except ChatError as exc:
            session = deps.chat.session(sid)
            response = render(request, "_chat_panel.html", **_chat_panel_context(session, error=str(exc)))
            return response
        session = deps.chat.session(sid)
        context = _chat_panel_context(session)
        if result.stale:
            context["error"] = "That form was stale — showing current state; nothing was applied."
        if result.error:
            context["error"] = result.error
        return render(request, "_chat_panel.html", **context)

    return app


# -- default wiring ---------------------------------------------------------------------


def build_default_app() -> FastAPI:
    """Neon + OpenAI when configured; otherwise an in-memory seeded demo."""
    import os

    from email_task_agent.config import settings

    owner_email = "alex@fernwoodlabs.com"
    model_name = os.environ.get("CHAT_MODEL", "openai:gpt-4o-mini")

    if settings().database_url:
        from email_task_agent.db import connect, migrate
        from email_task_agent.store import PostgresStore

        conn = connect()
        migrate(conn)
        store = PostgresStore(lambda: connect())
    else:
        from email_task_agent.memory import MemoryStore

        store = MemoryStore()

    from email_task_agent.demo.seed import seed_demo_instance

    seed_demo_instance(store, owner_email=owner_email)

    chat_service = None
    sync_runner = None
    reextract_runner = None

    if settings().openai_api_key:
        from email_task_agent.chat.service import ChatService

        chat_service = ChatService(store, model_name, mode=settings().instance_mode, me=owner_email)

    if settings().instance_mode == "private" and settings().openai_api_key:
        from email_task_agent.pipeline.extract import ExtractionAgent
        from email_task_agent.pipeline.sync import SyncService

        extraction = ExtractionAgent(os.environ.get("EXTRACTION_MODEL", "openai:gpt-4o-mini"))

        def make_service() -> SyncService:
            from email_task_agent.gmail.client import GmailClient, build_gmail

            return SyncService(
                store,
                GmailClient(build_gmail(".credentials/token.json"), me=owner_email),
                extraction.extract,
                owner_email=owner_email,
            )

        def run_sync() -> str:
            outcomes = make_service().run()
            done = [o for o in outcomes if not o.skipped]
            inserted = sum(len(o.inserted_task_ids) for o in done)
            return f"Synced {len(done)} threads, {inserted} new tasks, {sum(o.suggestions for o in done)} suggestions."

        def run_reextract(gmail_thread_id: str) -> str:
            from email_task_agent.pipeline.sync import reextract_thread

            outcome = reextract_thread(store, make_service().client, extraction.extract, owner_email=owner_email, gmail_thread_id=gmail_thread_id)
            return f"Re-extracted {gmail_thread_id}: {len(outcome.inserted_task_ids)} tasks, {outcome.suggestions} suggestions."

        sync_runner = run_sync
        reextract_runner = run_reextract

    deps = Deps(store=store, mode=settings().instance_mode, owner_email=owner_email, chat=chat_service, sync_runner=sync_runner, reextract_runner=reextract_runner)
    return create_app(deps)


app = None  # set by uvicorn factory: `uvicorn email_task_agent.app.main:app_factory`


def app_factory() -> FastAPI:
    return build_default_app()
