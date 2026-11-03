"""FastAPI backend: /healthz + the JSON API under /api (migration §2).

The browser never talks to this app — the Next.js server calls it server-side
via BACKEND_URL. Dependency injection keeps everything testable: create_app()
takes a Deps object (store, chat service, sync runner); build_default_app()
wires the real thing from settings — Neon Postgres + the configured LLM when
present, otherwise an in-memory seeded demo instance (mode=demo, external
writes stubbed).
"""

from __future__ import annotations

import itertools
import threading
import time

from fastapi import FastAPI

from email_task_agent import __version__
from email_task_agent.app.deps import Deps
from email_task_agent.store import Store

__all__ = ["Deps", "app_factory", "build_default_app", "create_app", "prepare_database"]


def prepare_database(
    store: Store,
    *,
    owner_email: str,
    attempts: int | None = None,
    _sleep=time.sleep,
) -> None:
    """Migrate + seed AFTER boot, retrying with backoff.

    Boot must never block on the database: while this loop is waiting, pages
    render the offline banner; once it lands, everything self-heals (seeding is
    idempotent per thread).
    """
    from email_task_agent.db import connect, migrate
    from email_task_agent.demo.seed import seed_demo_instance

    delay = 2.0
    for round_ in itertools.count():
        if attempts is not None and round_ >= attempts:
            raise RuntimeError(f"database unreachable after {attempts} prepare attempts")
        try:
            migrate(connect())
            seed_demo_instance(store, owner_email=owner_email)
            return
        except Exception as error:  # noqa: BLE001 - background loop keeps retrying
            print(f"database prepare failed ({error}); retrying in {delay:.0f}s", flush=True)
            _sleep(delay)
            delay = min(delay * 2, 30.0)


def create_app(deps: Deps) -> FastAPI:
    app = FastAPI(title="email-task-agent", version=__version__)

    from email_task_agent.app.api import build_api_router

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__, "mode": deps.mode}

    app.include_router(build_api_router(deps))
    return app


# -- default wiring ---------------------------------------------------------------------


def build_default_app() -> FastAPI:
    """Neon + a configured LLM when present; otherwise an in-memory seeded demo.

    Without DATABASE_URL an instance cannot be the real private one, so the
    effective mode downgrades to "demo" regardless of INSTANCE_MODE (D8: demo
    holds synthetic data only; the badge reflects what is actually wired).
    """
    from email_task_agent.config import settings

    owner_email = "alex@fernwoodlabs.com"

    if settings().database_url:
        from email_task_agent.db import connect
        from email_task_agent.store import PostgresStore

        store = PostgresStore(lambda: connect())
    else:
        from email_task_agent.memory import MemoryStore

        store = MemoryStore()
    mode = settings().instance_mode if settings().database_url else "demo"

    if settings().database_url:
        threading.Thread(
            target=prepare_database,
            args=(store,),
            kwargs={"owner_email": owner_email},
            daemon=True,
            name="db-prepare",
        ).start()
    else:
        from email_task_agent.demo.seed import seed_demo_instance

        seed_demo_instance(store, owner_email=owner_email)

    chat_service = None
    sync_runner = None
    reextract_runner = None

    from email_task_agent.chat.service import ChatService

    if settings().api_key:
        from email_task_agent.llm import model_for_purpose, openrouter_fallback

        # Demo spend control (plan §11: 100 turns/day); unlimited when private.
        cap = settings().demo_daily_turn_cap if mode == "demo" else None
        chat_service = ChatService(
            store,
            model_for_purpose("chat"),
            mode=mode,
            me=owner_email,
            daily_turn_cap=cap,
            fallback_model=openrouter_fallback(),
        )
    elif mode == "demo":
        # Keyless demo: scripted mock LLM (labeled in the UI) so the whole
        # approval flow runs with zero keys.
        from email_task_agent.llm_mock import build_mock_model

        chat_service = ChatService(store, build_mock_model(), mode=mode, me=owner_email)

    if mode == "private" and settings().api_key:
        from email_task_agent.llm import model_for_purpose
        from email_task_agent.pipeline.extract import ExtractionAgent
        from email_task_agent.pipeline.sync import SyncService

        extraction = ExtractionAgent(model_for_purpose("extraction"))

        def make_service() -> SyncService:
            from email_task_agent.gmail.client import GmailClient, build_gmail

            return SyncService(
                store,
                GmailClient(build_gmail(), me=owner_email),
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

    deps = Deps(store=store, mode=mode, owner_email=owner_email, chat=chat_service, sync_runner=sync_runner, reextract_runner=reextract_runner)
    return create_app(deps)


def app_factory() -> FastAPI:
    return build_default_app()
