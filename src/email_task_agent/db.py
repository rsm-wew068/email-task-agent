"""Thin psycopg (3) wrapper: connection factory and migration runner.

Plain SQL over an ORM, matching the plan's "plain Python functions" style.
DB-touching paths are only exercised when DATABASE_URL is set; unit tests
skip them otherwise.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from email_task_agent.config import settings

# In a wheel install (the Space image) the module lives under site-packages, so
# also accept a copy in the working directory.
_MIGRATIONS_CANDIDATES = [Path(__file__).resolve().parents[2] / "migrations", Path.cwd() / "migrations"]
MIGRATIONS_DIR = next((p for p in _MIGRATIONS_CANDIDATES if p.is_dir()), _MIGRATIONS_CANDIDATES[0])


def connect() -> psycopg.Connection:
    url = settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set; see .env.example")
    # prepare_threshold=None disables automatic prepared statements, which
    # transaction-mode poolers (Supabase's port-6543 pooler, some proxies) reject.
    return psycopg.connect(url, autocommit=False, prepare_threshold=None)


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
