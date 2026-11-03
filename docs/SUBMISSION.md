# Case study 1 — email-task-agent

Rachel Wang · [rsm-wew068/email-task-agent](https://github.com/rsm-wew068/email-task-agent) ·
Live demo: https://rsm-wew068-email-task-agent.hf.space (public, synthetic data, clearly labeled)

## The problem

**1. Commitments made in email don't become tracked work.** Project decisions, deadlines, and asks live
in my inbox; the to-do list lives somewhere else. So I flag emails, re-type the important ones into a task
app, and rely on memory for the rest — and follow-ups slip. Anyone whose work arrives as email
(operators, accountants, founders, engineers) experiences this daily. My mid-2025 attempt at fixing it
(a Gmail→tasks tool) still demanded manual triage and silently rewrote the list.

**2. The same facts get re-keyed between systems.** Invoices, receipts, and statements arrive as email
attachments and get manually re-entered into the system of record; mismatches surface weeks later at
reconciliation. Small teams I've watched work this way lose hours and catch errors late.

**3. Small services die on transient third-party failures.** While building this prototype, its own demo
crash-looped because a free-tier database pooler briefly deregistered us, and a model provider throttled
mid-demo. Whoever runs a small service on free infrastructure experiences this; the cost is unreliable
software and lost trust.

### The one I explored, and why

I chose **problem 1**. It is the problem I have the most direct evidence for: I built a tool for it once
and still hit the gap it leaves. The failure is concrete and checkable — a missed commitment either
surfaces in the task list with its source sentence or it doesn't. And it is genuinely agent-shaped:
understanding "can you send the revised draft by Friday?" requires language reasoning, but acting on it
must never be automatic — which makes an approval gate the natural design, not a compliance bolt-on.

Ahead of problem 2 because document re-keying needs a heavier, separate build (parsing attachments,
system-of-record integrations) before anything is demonstrable; ahead of problem 3 because it is an
operations lesson, not a product — I folded it into this prototype's architecture instead (the app never
blocks on its database at boot and fails over between model providers at runtime).

**Observed:** my own triage behavior; the 2025 prototype's usage and failure modes; extraction mistakes
caught during this build's evaluations (duplicate tasks, updates citing stale evidence).
**Assumed:** that this is prevalent and painful for other people (I have not run a survey); that a
machine-derived task list can earn enough trust to be acted on; that one approval click per action costs
less than manual triage.

## Approach

**Today:** people flag emails, keep a parallel to-do app, and rely on memory; task apps require re-entry;
fully automatic mail agents act silently and merge aggressively. **A better outcome** is a task list
derived from the mailbox that is trustworthy enough to act from: every task carries its evidence quote,
updates must cite *new* mail, and nothing is written externally or merged without the owner.

**Direction:** LLM extraction with a validation-and-reconciliation stage, plus an approval-gated chat
agent over the same data. **The smallest useful first step — the one I built:** one core workflow,
realistic input to meaningful output:

> mailbox threads → extracted, deduplicated, evidence-backed task list → chat agent that answers from
> that data and executes an action (draft, calendar event, task) only after explicit approval.

**The credible alternative I did not choose:** a fully automatic agent — my 2025 attempt — that extracts
and acts end-to-end with no gate. It feels faster, but a wrong merge or a silent external write destroys
exactly the trust the product depends on, and it is unrecoverable. Plain rules (sender/keyword filters)
were the conventional-software alternative; they cannot parse intent or dates and break on phrasing. The
approval gate costs one click and makes every failure visible and undoable, which I judged worth more
than the friction it adds.

**Where AI, conventional software, and process change each sit:** AI where language is the problem — one
structured extraction call per thread, and the chat agent's reasoning and tool use. Conventional software
where reliability is the problem — a plain-SQL store, an append-only event log, a four-state approval
state machine with version-checked transitions (a double click or a second tab is a server-verified
no-op), idempotency keys so an external write is never sent twice, and eval baselines that fail CI on
regression. Process change: the human approval step itself.

**How this connects to the broader opportunity:** if extraction quality holds up under measurement, the
same pipeline extends to real Gmail sync and real external writes (already implemented, unexercised on
the demo), then scheduled sync and multiple mailboxes — the derived task list becomes the durable layer
the inbox never was.

**What I'd need to learn, and what would make me stop:** extraction accuracy on real mail (grow the eval
suite from 12 to 40 threads with a private golden set); whether approvals feel like control or friction;
cost per synced thread. If extraction can't beat a "star every thread with a date" heuristic on the
golden set, or suggestions need editing more often than not, the approval overhead isn't justified and
the problem isn't worth solving this way.

## Prototype

The live demo completes the workflow end to end: browse the task board and calendar derived from a
synthetic mailbox (labeled as such), then use the chat agent — ask *"what needs follow-up?"* and it reads
your task data through typed SQL tools; ask it to draft a reply and it stops at an approval card with the
full arguments. **Approve** executes (external writes are stubbed in demo mode and labeled), **Deny**
declines with an explicit "not created" reply.

**Representative use case:** board review → chat: grounded answer citing task IDs → draft request →
approval → executed action recorded in the event log.

**Difficult and invalid-input cases, demonstrable in the demo:**
- A duplicate task and a low-confidence update become **review-queue suggestions** instead of silent
  merges; accepting a merge is undoable via split.
- **Stale approvals:** approving the same form from a second tab is rejected by a server-side version
  check — no double send.
- **Malformed decisions** (missing or unknown tool-call ids) are rejected with an exact requirement, not
  partially executed.
- The app **boots and serves with its database unreachable** (offline banner, self-heals) — the failure
  mode that motivated this submission's architecture.

**Implemented:** extraction pipeline (extract → validate evidence → reconcile, no auto-merge), SQL store
with event log, approval state machine, chat agent with tools, eval harnesses with pinned baselines
(E1/E1-U/E2), Next.js UI, CI, one-container deployment. **Mocked (labeled):** the demo mailbox is
synthetic; demo external writes produce ids but touch nothing; with no LLM key a scripted mock model runs
the whole approval flow. **Deferred:** authentication (demo holds synthetic data only), streaming, and
the real Gmail connection on a private instance (OAuth code present).

Setup, dependencies, sample data, and example inputs/outputs are in the
[README](https://github.com/rsm-wew068/email-task-agent#readme) — the keyless demo runs with two
commands, no accounts or keys.

## Time spent and AI usage

**Time spent:** about 4 hours of hands-on design, build, and evaluation time (a deliberate use of AI
tooling compressed the calendar time; see below).

**AI usage:** I wrote the implementation plan and reviewed every change; an AI coding agent (ZCode)
implemented modules against it, and I corrected its output throughout — review findings that changed
shipped behavior include the deny-path string-coercion bug it introduced, the demo seeder's over-broad
guard, and the UI's stale-form handling. I checked outputs with mechanisms rather than reading: 135
tests (unit, API, real-Postgres, Playwright end-to-end), eval suites with pinned, versioned baselines
(E2 8/8 recorded scenarios), type and contract-drift checks in CI, and live verification of real-model
chat, extraction, and provider failover. **Reused prior work:** my 2025 prototype's failure modes
(graph store and vector RAG that the problem didn't need, ungated writes) are the design's negative
space; everything else is standard open source (FastAPI, Pydantic AI, Next.js, psycopg, Playwright).

**What I would investigate next:** growing the extraction eval to 40 threads with a private golden set
and a model bake-off; agent evals for multi-turn chat scenarios; and connecting real Gmail on a private
instance to measure the full loop's accuracy and cost. (Track in `docs/FUTURE_PLAN.md`.)
