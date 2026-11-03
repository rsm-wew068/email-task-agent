"""Apply pending database migrations (standalone; used for Supabase/etc. setup).

Reads DATABASE_URL from the environment / .env — the value is never printed.

  uv run python scripts/migrate.py
"""

from __future__ import annotations

import sys

from email_task_agent.config import settings
from email_task_agent.db import connect, migrate


def main() -> int:
    if not settings().database_url:
        print("DATABASE_URL is not set — put it in .env at the repo root first.")
        return 1
    conn = connect()
    applied = migrate(conn)
    if applied:
        print("Applied migrations:")
        for name in applied:
            print(f"  + {name}")
    else:
        print("Schema already up to date.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
