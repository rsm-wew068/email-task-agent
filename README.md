# email-task-agent

Prototype agent per the implementation plan (rev 5): Gmail threads in, deduplicated
status-tracked tasks out, plus an approval-gated chat agent over your own task data.

Replaces the [automated-task-manager](https://huggingface.co/spaces/rsm-wew068/automated-task-manager)
prototype: no graph database (append-only `task_events` log instead), no vector RAG
(whole thread in context + typed SQL tools), single-user instances.

## Architecture

```
Browser ──(pages + server actions)──▶ Next.js 16 (web/) ──(typed fetch, BACKEND_URL)──▶ FastAPI /api/*
                                                                            ├── Store: Neon Postgres | in-memory demo
                                                                            ├── ChatService: §8.2 state machine
                                                                            └── Gmail / Calendar / Tasks via approved tools
```

- **Backend**: Python 3.13, Pydantic AI 2.x, FastAPI serving `/healthz` + `/api/*` only,
  Neon Postgres via plain SQL (psycopg 3). The browser never reaches it directly, so no
  CORS and the backend can be made private later.
- **Frontend**: Next.js 16 App Router in `web/` — server components read, server actions
  write, Tailwind 4. Contract: FastAPI response models → `openapi.json` →
  `openapi-typescript` → `openapi-fetch`, with a CI drift check.
- **Chat**: v0 request/response (no streaming), backend-owned approval state machine.
  The React panel renders `ChatSessionView` and relays decisions with the version it
  rendered, so double clicks and second tabs get the server's stale-form answer.
- **Sync** (`POST /api/sync`): Gmail `history.list` from `last_history_id` → group by
  thread → per thread: extract → validate → reconcile → persist (capped per run).
- **Extraction**: one structured LLM call per thread; Validate checks evidence quotes
  against thread text (frozen `evidence.py`, shared with the E1 scorer), owner ∈
  participants, due date parses.
- **Reconciliation** (§7.3): no auto-merge — updates must reference a shown task ID and
  cite a sentence from a *new* email; duplicates and low-confidence updates become
  suggestions; merges happen only on acceptance and are undoable via split.
- **Instances** (D8): public demo = synthetic mailbox, write tools stubbed; private =
  your Gmail via OAuth, refresh token outside the repo.

## Layout

```
migrations/            plain SQL schema (§6 tables + suggestions + thread_messages)
src/email_task_agent/
  evidence.py          frozen quote location + overlap (shared by E1 scorer and Validate)
  models/extraction.py ThreadExtraction contract (Pydantic AI output_type)
  pipeline/            dates, validate, reconcile (§7.3), extract, sync
  store.py             SQL store + Store protocol; chat CAS; idempotent actions
  memory.py            in-memory Store twin (tests / keyless demo)
  gmail/               Gmail client (history.list, MIME→text) + OAuth script
  agent/chat.py        tools: SQL reads (auto), update_task (undoable), external writes (requires_approval)
  chat/service.py      §8.2 four-state machine, version-checked CAS, DeferredToolRequests resume
  app/api.py           JSON API (the frontend contract)
  app/main.py          app factory + default wiring
  demo/seed.py         idempotent demo seeding from checked-in suites
  evals/               E1 scorer/gate/runner, E2 recorded 100%, E1-U wrong links
  synth/               label-first synthetic suites
scripts/export_openapi.py   regenerates web/openapi.json (CI drift check)
web/                   Next.js 16 app (server components + server actions)
evals/data|baselines/  generated suites + pinned baselines (checked in)
tests/                 unit + API + 9 Next.js e2e (Playwright vs next start)
```

## Quickstart (two processes)

```bash
uv sync                          # backend deps
npm --prefix web ci              # frontend deps
npm --prefix web run gen:api     # regenerate typed client from web/openapi.json

# terminal 1 — backend on :8000 (keyless = in-memory seeded demo)
uv run uvicorn email_task_agent.app.main:app_factory --reload

# terminal 2 — frontend on :3000
npm --prefix web run dev         # BACKEND_URL defaults to http://127.0.0.1:8000
```

Open http://127.0.0.1:3000. With an LLM key set, the chat runs live — first key in
`.env` wins: `GEMINI_API_KEY` → **gemini-3.8-flash**, `ZAI_API_KEY` → **GLM-5.3-Flash**
(demo writes stay stubbed; the demo chat is capped at 100 turns/day — plan §11). Private instance: set `DATABASE_URL` (Neon), run `python scripts/auth_gmail.py`,
press *Sync now*.

### Where to put the API key

Everything lives in **`.env` at the repo root** (gitignored — copy from `.env.example`):

```bash
GEMINI_API_KEY=<your Google AI Studio key>   # or ZAI_API_KEY for GLM-5.3-Flash
# LLM_BASE_URL=https://api.z.ai/api/paas/v4/   # the default; any OpenAI-compatible endpoint works
# CHAT_MODEL=glm-5.3-flash                     # defaults shown; override for the D3 bake-off
# EXTRACTION_MODEL=glm-5.3-flash
DATABASE_URL=postgresql://...                  # any managed Postgres; without it: in-memory demo
INSTANCE_MODE=private                          # only meaningful with DATABASE_URL
```

**DATABASE_URL works with Neon, Supabase, Render, or Railway** — plain SQL, standard
Postgres features, pooling-safe connections. Exact strings (plus examples) are in
`.env.example`; e.g. Supabase: Project → Connect → *Session pooler*, and append
`?sslmode=require`. Migrations apply automatically when the backend starts.

Restart the backend after editing `.env`; the chat page then works against GLM.

> **Private-instance security**: the dev scripts bind to `127.0.0.1` on purpose, and the
> backend is reachable only server-side. Before ever exposing the private instance to a
> network, add authentication; on a shared network another machine could otherwise call
> server actions (read tasks, approve drafts). The public demo (synthetic data only) is
> protected against unbounded LLM spend by the daily turn cap — put a spend limit at the
> provider too, and use Cloud Run ingress/IAM so only the Next.js server reaches the
> backend.

## Checks

```bash
uv run pytest                                       # 111 tests incl. 9 Next.js e2e
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

## E1 eval workflow (§9.3)

```bash
uv run python -m email_task_agent.evals.e1 --predictions run.json --runs 3 \
    --record-baseline evals/baselines/e1_baseline.json
uv run python -m email_task_agent.evals.e1 --predictions run.json --runs 3 \
    --gate evals/baselines/e1_baseline.json     # exit 1 = regression
```

Scorer and gate are **versioned code** (`SCORER_VERSION`): changes to matching,
normalization, or thresholds are a spec change — bump the version, re-record, say so in
the PR. Task scope for gold labeling (§9.2): a task counts when the mailbox owner owns
it or asked someone for it.

## Status / milestones

- [x] **M0**: schema, evidence module, E1 scorer + gate + runner, label-first suites.
- [x] **M1**: approval flow (§8.2) with Playwright proofs, Gmail sync, extraction,
      reconciliation, task/calendar/chat UI, E2 + E1-U harnesses, CI, Dockerfile.
- [x] **Frontend migration**: Jinja/HTMX → Next.js 16 (JSON API + typed client + server
      actions; HTML routes, templates and jinja2 removed after e2e went green).
- [ ] **M2**: grow E1 to 40 threads (~100 gold with the private golden set), real-model
      baseline + D3 bake-off, E3/E4 agent evals, richer demo seed (suggestions), deploy
      (Vercel + Cloud Run), Gmail/Calendar/Tasks end-to-end on the private instance.

## Honest deviations from the plan

- **Calendar**: custom month grid (~40 lines TS) instead of FullCalendar — v7's package
  split is currently mismatched; revisit when `@fullcalendar/daygrid` catches up.
- **Auth deferred** for single-user instances; the public demo holds synthetic data only
  (D8). The unauthenticated backend is acceptable only for the demo; later, Cloud Run +
  IAM with an ID token from the Next.js server closes that.
- **At-most-once external writes**: the `actions` row flips to `approved` immediately
  before the external call, so a crash in that window makes the retry *refuse to resend*.
  Possibly-skipped beats possibly-duplicated.
- **Streaming**: out of scope for the migration (plan §9); each chat turn is
  request/response, and the run-scoped event log + SSE design is unchanged future work.
