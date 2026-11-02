"""FastAPI app skeleton (plan §5): pages, chat, /sync land in M1+; M0 ships the
shell and a health endpoint so hosting works end to end.
"""

from __future__ import annotations

from fastapi import FastAPI

from email_task_agent import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="email-task-agent", version=__version__)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
