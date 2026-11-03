# Video walkthrough script (target ≈ 8 minutes)

One take per segment is fine; the timestamps are pacing targets, not cuts. Recording
prep is at the bottom.

| # | Segment | Time |
|---|---------|------|
| 1 | The problem | 0:00–1:00 |
| 2 | What I built | 1:00–1:30 |
| 3 | Core workflow: mailbox → task board | 1:30–3:00 |
| 4 | Core workflow: chat agent with approvals | 3:00–4:45 |
| 5 | Difficult and invalid inputs | 4:45–6:00 |
| 6 | How it works | 6:00–7:15 |
| 7 | Design decisions | 7:15–8:00 |
| 8 | Implemented / mocked / next | 8:00–8:30 |

## 1 · The problem (0:00–1:00) — talking head or the task board behind you

- "Work commitments arrive as email: 'can you send the revised draft by Friday?'.
  The to-do list lives somewhere else, so I flag emails, re-type the important ones,
  and rely on memory — and things slip."
- "This is one of three problems I considered; I chose it because I've hit it daily
  enough to build for it once before, the failure is concrete — a missed commitment —
  and it's genuinely agent-shaped: understanding the email needs a model, but acting
  on it must never be automatic."

## 2 · What I built (1:00–1:30) — share the live URL

- Open https://rsm-wew068-email-task-agent.hf.space
- "email-task-agent: Gmail threads in, a deduplicated evidence-backed task list out,
  plus a chat agent over that data which can only act through approvals."
- Point at the mode badge: "Everything here is synthetic and labeled — no real mail."

## 3 · Core workflow, part 1: mailbox → task board (1:30–3:00)

- **Tasks page**: "This board was derived from a synthetic mailbox. Every task carries
  the sentence it came from — the evidence quote — plus owner, due date, status."
- Show a couple of rows; open nothing yet. Point out the **event log** on a task
  ("every change is an append-only event, so history is auditable").
- **Review queue**: "When extraction sees a possible duplicate or a low-confidence
  update, it does NOT merge silently — it queues a suggestion with evidence for me."
- **Calendar** page: "Due dates land on the calendar, with overdue and due-today
  highlighted." Navigate back.

## 4 · Core workflow, part 2: chat agent with approvals (3:00–4:45) — the star

- **Chat** page. Type: `What needs follow-up this week?`
  - Expected: a grounded answer citing task IDs (# and titles). Narrate: "the agent
    answers by querying the task store through tools — not by guessing."
- Type: `Draft a follow-up to Kate about the revised Q3 draft.`
  - Expected: agent searches the mailbox for context, then stops at an
    **approval card** with the full `to`/`subject`/`body` it proposes. Narrate:
    "it ends its turn here. Nothing was sent — the state machine is parked at
    awaiting-approval."
- Click **Approve**. Expected: reply confirms creation with an id. Narrate:
  "in demo mode external writes are stubbed and labeled — on a private instance
  this creates a real Gmail draft. The action is recorded with an idempotency key,
  so a retry can never send it twice."
- Type: `Also schedule a call with the vendor next Tuesday.` (or any second action)
  - Click **Deny**. Expected: an explicit "not created" reply. "Denial is a
    first-class outcome, and the agent is not allowed to claim otherwise."

## 5 · Difficult and invalid inputs (4:45–6:00)

- **Duplicate handling**: back on **Tasks**, open **Review queue**. "Here's a seeded
  duplicate pair." Click **Accept** (merge) → task count drops, merged task shows a
  `merged` event → click **Split** to undo it. "Merges are undoable; silent damage
  isn't possible."
- **Stale approval**: open the chat in a **second browser window/tab** on the same
  session, ask for another draft, then approve in tab 1 and click approve in tab 2.
  Expected: the server's version check makes tab 2 a no-op. "Two tabs, one send —
  the backend owns the state; the client just relays the version it rendered."
- **Malformed input**: "Direct API calls can't skip the gate either — approve
  requests that don't cover exactly the pending actions are rejected."

## 6 · How it works (6:00–7:15) — one diagram slide

```
Browser → Next.js (server components/actions) → FastAPI /api → Postgres (plain SQL)
                                     ├── extraction: extract → validate → reconcile
                                     └── chat: Pydantic AI agent, 4-state approval machine
```

- "The browser never touches the backend; one JSON contract, type-generated for the
  frontend and drift-checked in CI."
- "Extraction is one structured call per thread, then non-AI validation: the evidence
  quote must actually appear in the thread, the owner must be a participant, the date
  must parse. Reconciliation never auto-merges."
- "The chat state machine has four states and every transition is a version-checked
  compare-and-swap — that's where double clicks and stale forms die."
- "Underneath: plain Postgres with an append-only event log. No graph database, no
  vector RAG — the whole thread fits in context."
- "The demo runs as one container on Hugging Face: embedded Postgres, FastAPI, and
  Next.js. It boots without its database and self-heals. Chat is DeepSeek via the
  HF router with automatic failover to OpenRouter, capped at 100 turns a day."

## 7 · Design decisions (7:15–8:00)

- "The credible alternative was a fully automatic agent — my 2025 attempt. Rejected:
  a silent wrong merge or write destroys the trust the product depends on. The gate
  costs one click and makes failures visible and undoable."
- "AI where language is the problem; conventional software where reliability is:
  idempotency keys, an eval harness with pinned baselines that fails CI on
  regression, typed contracts."

## 8 · Implemented / mocked / next (8:00–8:30)

- "Implemented: the full pipeline, the approval machine, evals, CI, deployment.
  Mocked and labeled: the synthetic mailbox, demo external writes, and a scripted
  model when no key is set. Deferred: auth (nothing real here), streaming, and the
  real Gmail connection on a private instance."
- "Next: grow the extraction eval to 40 threads with a golden set and a model
  bake-off, then measure the real-Gmail loop end to end."
- "Thanks — the writeup is docs/SUBMISSION.md, the README runs the demo with two
  commands and no keys."

## Recording prep

1. **Restart the Space first** (Settings → Restart or `restart_space`) so the demo
   database reseeds — board shows exactly 11 tasks / 23 threads / 1 suggestion, and
   the review queue holds the duplicate pair.
2. Rehearse the two chat prompts verbatim; if the model phrases differently, the
   narration still works (it cites tools, parks at approval).
3. Second browser profile (not incognito in the same profile) pre-opened to /chat
   for the stale-approval beat.
4. Have `docs/SUBMISSION.md` and the architecture diagram open in editor tabs for
   segments 6–7.
5. If the Space is mid-restart (offline banner), wait for the banner to clear —
   that self-heal is itself worth narrating in one sentence.
