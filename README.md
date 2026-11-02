# email-task-agent

Prototype agent per the implementation plan (rev 5): Gmail threads in, deduplicated
status-tracked tasks out, plus an approval-gated chat agent over your own task data.

Replaces the [automated-task-manager](https://huggingface.co/spaces/rsm-wew068/automated-task-manager)
prototype: no graph database (append-only `task_events` log instead), no vector RAG
(whole thread in context + typed SQL tools), single-user instances.

## Architecture (from the plan)

- **Stack**: Python 3.13, Pydantic AI 2.x, FastAPI + Jinja2/HTMX, Neon Postgres (plain SQL, psycopg 3).
- **Sync** (`POST /sync`, optional 15-min cron): Gmail `history.list` from `last_history_id`
  → group by thread → per thread: extract → validate → reconcile → persist.
- **Extraction**: one structured LLM call per thread (`output_type=ThreadExtraction`);
  Validate stage checks evidence quotes against thread text, owner ∈ participants, due date parses.
- **Reconciliation** (§7.3): no auto-merge on title similarity — updates must reference a shown
  task ID and cite a sentence from a *new* email; duplicates and low-confidence updates go to a
  suggestions review queue; merges happen only on acceptance.
- **Agent** (§8): typed read tools (auto) + external write tools (`requires_approval=True`);
  chat runs end with `DeferredToolRequests`, resume via `POST /chat/approve`.
- **Instances** (D8): public demo = synthetic mailbox only, write tools stubbed; private = your
  Gmail via OAuth, refresh token outside the repo.

## Layout

```
migrations/            plain SQL schema (001_init: §6 tables + suggestions + thread_messages)
src/email_task_agent/
  evidence.py          frozen quote location + overlap machinery (shared by eval scorer and runtime validator)
  models/extraction.py ThreadExtraction contract (Pydantic AI output_type)
  pipeline/
    dates.py           rule-based due-date resolution (labeling-convention rules)
    validate.py        Validate stage: quotes locate, owner ∈ participants, updates cite NEW emails
    reconcile.py       §7.3: repeat-drop, suggestions-not-merges, recurring rule, low-confidence queue
    extract.py         one structured LLM call per thread (whole thread in context)
    sync.py            history.list -> group -> cap -> per-thread pipeline -> persist
  store.py             SQL store (psycopg) + Store protocol; chat CAS + idempotent actions
  memory.py            in-memory Store twin (tests / keyless demo; same semantics)
  gmail/               real Gmail client (history.list, MIME->text) + OAuth script
  agent/chat.py        chat tools: SQL reads (auto), update_task (undoable), external writes (requires_approval)
  chat/service.py      §8.2 four-state machine, version-checked CAS, DeferredToolRequests resume
  web/                 HTMX templates
  app/main.py          FastAPI routes: tasks, calendar, chat, /sync, suggestions, re-extract
  demo/seed.py         idempotent demo seeding from the checked-in suites
  evals/               scoring.py, gate.py, loader.py, e1.py, e2.py (recorded 100%), e1u.py (wrong links)
  synth/               label-first synthetic suites
evals/data/            generated suites (checked in)
evals/baselines/       pinned baseline metrics (checked in)
tests/                 unit + chat + web + Playwright browser tests; DB tests skip without DATABASE_URL
```

## Quickstart

```bash
uv sync
uv run pytest                                            # 91 tests incl. real-browser §8.2 suite
uv run python -m email_task_agent.synth.build_suites     # (re)generate evals/data/*.json
uv run python -m email_task_agent.evals.e1               # E1 smoke run (null extractor)
uv run python -m email_task_agent.evals.e2               # E2: 8/8 recorded reconciliation scenarios
uv run python -m email_task_agent.evals.e1u              # E1-U wrong-link harness
uv run uvicorn email_task_agent.app.main:app_factory --reload  # http://127.0.0.1:8000
```

Running the server without any env vars starts the **keyless demo instance**:
in-memory store seeded from the synthetic suites — browse tasks/calendar,
use the review queue, and chat against a scripted model by setting nothing;
with `OPENAI_API_KEY` set, the chat runs on a real model (demo writes stay
stubbed). For the **private instance**: set `DATABASE_URL` (Neon) +
`OPENAI_API_KEY`, `INSTANCE_MODE=private`, then `python scripts/auth_gmail.py`
(see its docstring) and press *Sync now*.

Copy `.env.example` to `.env` for DATABASE_URL / OPENAI_API_KEY.

## E1 eval workflow (§9.3)

```bash
# after an extraction run writes predictions JSON:
uv run python -m email_task_agent.evals.e1 --predictions run.json --runs 3 \
    --record-baseline evals/baselines/e1_baseline.json
# later, on any prompt/model/scorer change:
uv run python -m email_task_agent.evals.e1 --predictions run.json --runs 3 \
    --gate evals/baselines/e1_baseline.json     # exit 1 = regression
```

The scorer and gate are **versioned code** (`SCORER_VERSION`): any change to matching,
normalization, or thresholds is a spec change — bump the version, re-record the baseline,
and say so in the PR. Task scope for gold labeling (§9.2, rev 5 decision): a task counts when
the mailbox owner owns it or asked someone for it.

## Status / milestones

- [x] **M0**: repo scaffold, schema migration, evidence module, E1 scorer +
      gate + runner, label-first synthetic starter suites, FastAPI shell, unit tests.
- [x] **M1**: approval flow first (§8.2: four-state machine with version-checked CAS,
      at-most-once external writes gated by tool_call_id rows, six Playwright browser
      scenarios: approve / deny / double-submit / reload / two-actions-one-turn /
      crash-after-API-call retry), Gmail OAuth + sync (`history.list` with 404→full-sync
      fallback, per-run cap, per-thread transactional persist), extraction pipeline
      (Validate reuses `evidence.py`), §7.3 reconciliation (repeat-drop, suggestions
      queue, merge-on-accept + split undo), task list / calendar / chat pages with HTMX,
      E2 (8 recorded scenarios, 100%) and E1-U harnesses, CI, Dockerfile.
- [ ] **M2**: grow E1 to 40 threads (~100 gold with the private golden set), real-model
      E1 baseline + bake-off (D3 model prices unverified), E3/E4 agent evals on a real
      model, public demo deployment, Gmail/Calendar/Tasks end-to-end on the private
      instance.

## Honest deviations from the plan

- **Calendar** is a server-rendered month grid (Jinja + a few lines of Python), not
  FullCalendar — keeps the Python-only, zero-JS-dependency property; swap in
  FullCalendar later if interaction is wanted.
- **Auth is deferred** for single-user instances (bind to localhost / private network);
  the public demo holds synthetic data only (D8) and sync is a manual button. The plan's
  Google sign-in gate is an M2 item if the demo is exposed.
- **At-most-once external writes**: the `actions` row flips to `approved` immediately
  before the external call, so a crash in that window makes the retry *refuse to resend*
  (the user is told to check Gmail/Calendar/Tasks). Possibly-skipped beats
  possibly-duplicated; closing the window fully needs an idempotency header the Gmail
  draft API doesn't offer.
- **Streaming**: v0 has none by design (§8.2); each chat turn is request/response with a
  spinner (CSS `hx-indicator`-style).
