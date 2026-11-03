# email-task-agent

Gmail threads in, deduplicated status-tracked tasks out, plus an approval-gated chat
agent over your own task data.

**Live demo** (public, synthetic data only): https://rsm-wew068-email-task-agent.hf.space —
chat runs on DeepSeek via the HF Inference Providers router, with automatic failover to
OpenRouter when HF throttles or runs out of credits. Capped at 100 turns/day.

## Try the demo

- Browse the **tasks board and inbox threads** — a synthetic mailbox persisted in a
  real Postgres (embedded in the demo container), 11 tasks / 23 threads at seed time.
- Ask the **chat agent** something like *"what needs follow-up?"* — it reads your task
  data via typed SQL tools and proposes actions (draft an email, create a task) as
  approval cards. **Approve** executes (external writes are stubbed in demo mode),
  **Deny** declines; double clicks and second tabs get the server's stale-version
  answer instead of double-applying.
- The demo restarts clean: the embedded database reseeds on boot, so there is nothing
  to pause, wake, or deregister.

## Architecture

```
Browser ──(pages + server actions)──▶ Next.js 16 (web/) ──(typed fetch, BACKEND_URL)──▶ FastAPI /api/*
                                                                            ├── Store: Postgres | in-memory demo
                                                                            ├── ChatService: approval state machine
                                                                            └── Gmail / Calendar / Tasks via approved tools
```

- **Backend**: Python 3.13, Pydantic AI 2.x, FastAPI serving `/healthz` + `/api/*` only,
  Postgres via plain SQL (psycopg 3). The browser never reaches it directly, so no
  CORS and the backend can be made private later.
- **Frontend**: Next.js 16 App Router in `web/` — server components read, server actions
  write, Tailwind 4. Contract: FastAPI response models → `openapi.json` →
  `openapi-typescript` → `openapi-fetch`, with a CI drift check.
- **Chat**: request/response (no streaming), backend-owned approval state machine. The React panel relays decisions with the version it rendered, so stale
  approvals are rejected server-side.
- **Sync** (`POST /api/sync`): Gmail `history.list` from `last_history_id` → group by
  thread → per thread: extract → validate → reconcile → persist (capped per run).
- **Extraction**: one structured LLM call per thread; Validate checks evidence quotes
  against thread text (frozen `evidence.py`, shared with the E1 scorer), owner ∈
  participants, due date parses.
- **Reconciliation**: no auto-merge — updates must reference a shown task ID and
  cite a sentence from a *new* email; duplicates and low-confidence updates become
  suggestions; merges happen only on acceptance and are undoable via split.
- **Instances**: public demo = synthetic mailbox, write tools stubbed; private =
  your Gmail via OAuth, refresh token outside the repo.

## Layout

```
migrations/            plain SQL schema + suggestions + thread_messages
src/email_task_agent/
  evidence.py          frozen quote location + overlap (shared by E1 scorer and Validate)
  models/extraction.py ThreadExtraction contract (Pydantic AI output_type)
  pipeline/            dates, validate, reconcile, extract, sync
  store.py             SQL store + Store protocol; chat CAS; idempotent actions
  memory.py            in-memory Store twin (tests / keyless demo)
  gmail/               Gmail client (history.list, MIME→text) + OAuth script
  agent/chat.py        tools: SQL reads (auto), update_task (undoable), external writes (requires_approval)
  chat/service.py      four-state approval machine, version-checked CAS, DeferredToolRequests resume
  app/api.py           JSON API (the frontend contract)
  app/main.py          app factory + default wiring
  demo/seed.py         idempotent demo seeding from checked-in suites
  synth/               label-first synthetic suites
scripts/export_openapi.py   regenerates web/openapi.json (CI drift check)
web/                   Next.js 16 app (server components + server actions)
evals/data|baselines/  generated suites + pinned baselines (checked in)
tests/                 unit + API + 9 Next.js e2e (Playwright vs next start)
deploy/                HF Space image + entrypoint (the public demo)
```

## Quickstart (two processes)

```bash
uv sync                          # backend deps
npm --prefix web ci              # frontend deps
npm --prefix web run gen:api     # regenerate typed client from web/openapi.json

# terminal 1 — backend on :8000 (keyless = in-memory seeded demo)
uv run uvicorn email_task_agent.app.main:app_factory --factory --reload

# terminal 2 — frontend on :3000
npm --prefix web run dev         # BACKEND_URL defaults to http://127.0.0.1:8000
```

Open http://127.0.0.1:3000. With an LLM key set, the chat runs live:
`HF_TOKEN` → **deepseek-ai/DeepSeek-V4.1-Flash-1017** via the HF Inference Providers
router (primary), and `OR_API_KEY` → **deepseek/deepseek-v4.1-flash-1017** (OpenRouter)
as **runtime failover** — a provider-level failure on HF (throttled, out of credits,
down) retries that same request on OpenRouter automatically. Tool errors and malformed
requests are never retried on the fallback (they are our bug, not the provider's).
Demo-mode writes stay stubbed. Private instance: set `DATABASE_URL`, run
`python scripts/auth_gmail.py`, press *Sync now*.

### Where to put the API key

Everything lives in **`.env` at the repo root** (gitignored — copy from `.env.example`):

```bash
HF_TOKEN=<your HF access token>               # primary: HF Inference Providers
OR_API_KEY=<your OpenRouter key>              # failover: used when HF throttles/runs out
# LLM_BASE_URL=...                            # override endpoint; any OpenAI-compatible host works
# CHAT_MODEL=...                              # defaults shown; override for a bake-off
# EXTRACTION_MODEL=...
DATABASE_URL=postgresql://...                  # any managed Postgres; without it: in-memory demo
INSTANCE_MODE=private                          # only meaningful with DATABASE_URL
```

`DATABASE_URL` accepts any standard Postgres (Neon, Supabase, Render, Railway all
work); exact connection strings and pooler notes are in `.env.example`. Migrations
apply automatically when the backend starts. Restart the backend after editing `.env`.

### Sample data and an example exchange

The demo mailbox is checked in (`evals/data/demo_mailbox.json` + the gold labels in
`evals/data/e1_test.json`); any backend seeds it at boot (11 tasks / 23 threads /
1 review suggestion). A minimal example against the running backend:

```bash
curl -s -X POST localhost:8000/api/chat/sessions -d '{}' | jq .session_id   # -> 1
curl -s -X POST localhost:8000/api/chat/sessions/1/messages \
     -H 'content-type: application/json' -d '{"text":"What needs follow-up?"}' | jq '.state, .messages[-1].text'
# -> "idle"  (an answer grounded in the task list)
curl -s -X POST localhost:8000/api/chat/sessions/1/messages \
     -H 'content-type: application/json' -d '{"text":"Draft a follow-up to Kate"}' \
     | jq .state
# -> "awaiting_approval"  (.actions[0] holds the full proposed draft to review)
curl -s -X POST localhost:8000/api/chat/sessions/1/approve \
     -H 'content-type: application/json' \
     -d '{"version":8,"decisions":{"mock-draft-1":"approve"}}' | jq '.state, .messages[-1].text'
# -> "idle"  "Created (id=demo-create_gmail_draft-…)"  (demo writes are stubbed and labeled)
```

Use the `version` and `tool_call_id` values from the `awaiting_approval` response —
the ones above are from a fresh seed. Invalid inputs are rejected with data, not
500s: a stale `version` returns the current session unchanged, and decisions that
don't cover exactly the pending tool calls return an error message.

## Deployment (Hugging Face Space)

The public demo is **one HF Space running everything in a single container**: an
embedded Postgres (initialized by `deploy/space-entrypoint.sh`), FastAPI on
`127.0.0.1:8000`, and Next.js on `0.0.0.0:7860` (`deploy/hf-space.Dockerfile`, Docker
SDK, `app_port: 7860`; `/healthz` and `/api/*` are proxied through Next.js to the
backend).

- Space secrets/variables: `HF_TOKEN` (chat primary), `OR_API_KEY` (chat failover),
  `INSTANCE_MODE=demo`. **No external database**: the demo holds its synthetic data in the embedded Postgres, and boot never blocks on it — migrate+seed run in a
  retrying background thread (pages render an offline banner until they land, then
  self-heal).
- Chat is capped at `DEMO_DAILY_TURN_CAP` (100) turns/day across all visitors; writes
  stay stubbed in demo mode.
- The image is self-contained — verify changes locally with
  `docker build -f deploy/hf-space.Dockerfile .` before pushing to the Space.
- A private instance is the same image pointed at a managed Postgres (`DATABASE_URL`)
  plus the Gmail token (`GMAIL_TOKEN_JSON`) — see `.env.example`.

## Checks

```bash
uv run pytest                                       # 135 tests incl. 9 Next.js e2e
uv run ruff check .
npm --prefix web run typecheck                      # tsc --noEmit
npm --prefix web run build                          # production build (e2e needs it)
uv run python scripts/export_openapi.py && \
  npm --prefix web run gen:api && \
  git diff --exit-code web/openapi.json web/src/lib/api-schema.ts   # contract drift
uv run python -m email_task_agent.evals.e1          # E1 smoke
uv run python -m email_task_agent.evals.e2          # E2: 8/8 recorded scenarios
uv run python -m email_task_agent.evals.e1u         # E1-U wrong-link harness
```

E1 baselines are versioned code (`SCORER_VERSION`): re-record with
`--record-baseline evals/baselines/e1_baseline.json`, gate with
`--gate evals/baselines/e1_baseline.json` (exit 1 = regression). Changes to matching,
normalization, or thresholds bump the version and re-record in the same PR.
