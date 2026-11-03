#!/bin/sh
# Space entrypoint: embedded demo Postgres + FastAPI + Next.js in one container.
# The demo database lives INSIDE the container (synthetic data only, D8) — no
# external database dependency, so nothing can deregister or throttle us.
# A container restart re-initializes it; seeding is idempotent.
set -e

PGDATA=/data/pgdata
BIN=$(ls -d /usr/lib/postgresql/*/bin | head -n 1)

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  rm -rf "$PGDATA"
  mkdir -p "$PGDATA"
  chown postgres:postgres "$PGDATA"
  # -E UTF8 + --no-locale: migrations contain § comments; the container default
  # locale would initdb a SQL_ASCII cluster and psycopg refuses to encode them.
  su postgres -s /bin/sh -c "$BIN/initdb -D $PGDATA -U postgres -A trust -E UTF8 --no-locale" >/dev/null
fi
su postgres -s /bin/sh -c "$BIN/pg_ctl -D $PGDATA -l /tmp/pg.log -o '-c listen_addresses=127.0.0.1' start" >/dev/null
until su postgres -s /bin/sh -c "$BIN/pg_isready -h 127.0.0.1 -p 5432" >/dev/null 2>&1; do
  sleep 1
done
su postgres -s /bin/sh -c "createdb -h 127.0.0.1 eta" 2>/dev/null || true

export DATABASE_URL="postgresql://postgres@127.0.0.1:5432/eta"

# FastAPI backend on localhost:8000 (migrate+seed run in its background thread),
# then the Next.js server owns the public port.
(cd /app && /app/.venv/bin/uvicorn email_task_agent.app.main:app_factory --factory --host 127.0.0.1 --port 8000 &)
until python3 -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" 2>/dev/null; do
  sleep 1
done
exec /web/node_modules/.bin/next start -H 0.0.0.0 -p 7860
