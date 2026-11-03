"""Thin psycopg (3) wrapper: connection factory and migration runner.

Plain SQL over an ORM, matching the plan's "plain Python functions" style.
DB-touching paths are only exercised when DATABASE_URL is set; unit tests
skip them otherwise.
"""

from __future__ import annotations

import time
from pathlib import Path

import psycopg

from email_task_agent.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def connect() -> psycopg.Connection:
    url = settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set; see .env.example")
    # prepare_threshold=None disables automatic prepared statements, which
    # transaction-mode poolers (Supabase's port-6543 pooler, some proxies)
    # reject. Any managed Postgres — Neon, Supabase, Render, Railway — works.
    return psycopg.connect(url, autocommit=False, prepare_threshold=None)


def connect_with_retries(
    attempts: int = 6,
    base_delay: float = 2.0,
    *,
    _sleep=time.sleep,
) -> psycopg.Connection:
    """connect(), retrying with backoff — for STARTUP only.

    Managed poolers (Supavisor) occasionally fail tenant lookup for a few
    seconds (ENOTFOUND). A crash here kills the container boot, so a deployed
    Space flaps between "app starting" and crash instead of riding it out.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return connect()
        except Exception as error:  # noqa: BLE001 - re-raised after the final attempt
            last = error
            delay = min(base_delay * (2**attempt), 30.0)
            print(f"startup connect failed ({error}); retrying in {delay:.0f}s", flush=True)
            _sleep(delay)
    raise last  # type: ignore[misc]


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations in filename order; returns applied names."""
    with conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists schema_migrations (
                name text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        cur.execute("select name from schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

    ran: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        conn.execute(path.read_text())
        with conn.cursor() as cur:
            cur.execute("insert into schema_migrations (name) values (%s)", (path.name,))
        ran.append(path.name)
    conn.commit()
    return ran
