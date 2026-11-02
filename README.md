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
  evals/
    scoring.py         E1 scorer: frozen §9.3 spec (SCORER_VERSION pins it)
    gate.py            regression gate: drop > max(2 pts, 2×baseline std) fails, in points
    loader.py          suite + predictions loaders
    e1.py              E1 runner CLI (score / record baseline / gate)
  synth/               label-first synthetic suites (gold declared first, bodies written around it)
  app/                 FastAPI shell (M0); pages, chat, /sync land in M1+
evals/data/            generated suites (checked in)
evals/baselines/       pinned baseline metrics (checked in)
tests/                 unit tests; DB tests skip without DATABASE_URL
```

## Quickstart

```bash
uv sync
uv run pytest                              # unit tests (no DB/keys needed)
uv run python -m email_task_agent.synth.build_suites    # (re)generate evals/data/*.json
uv run python -m email_task_agent.evals.e1              # E1 smoke run (null extractor)
uv run uvicorn email_task_agent.app.main:app --reload   # http://127.0.0.1:8000/healthz
```

Copy `.env.example` to `.env` for DATABASE_URL / OPENAI_API_KEY (needed from M1 on).

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

- [x] **M0** (this commit): repo scaffold, schema migration, evidence module, E1 scorer +
      gate + runner, label-first synthetic starter suites, FastAPI shell, unit tests.
- [ ] **M1**: approval flow first (§8.2: state machine, idempotent writes, Playwright tests),
      then Gmail OAuth + sync, extraction pipeline (Validate stage uses `evidence.py`),
      reconciliation, task list / calendar pages, chat with HTMX.
- [ ] **M2**: E2/E1-U suites recorded, agent tools + E3/E4 evals, public demo instance.
