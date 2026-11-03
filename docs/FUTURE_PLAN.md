# Future plan

What the prototype does next (the implementation plan's M2), and the limitations we
are carrying deliberately — each with the fix we would apply given more time. Several
of these are honest deviations from the original plan; they are listed here rather
than hidden.

## Next up

- **Grow E1**: 40 threads (~100 gold labels once the private golden set is labeled),
  then a real-model baseline and the D3 extraction-model bake-off (same contract,
  competing models, one gate).
- **E3/E4 agent evals**: scripted multi-turn chat scenarios — approval UX, wrong-tool
  refusals, idempotent retries — recorded like E2.
- **Private instance end-to-end**: real Gmail → Calendar/Tasks writes against the
  owner's own account. The OAuth flow and external-write tools exist; demo mode stubs
  the writes (D8), so this is configuration plus a guarded rollout, not new code.
- **Persistent demo data**: the public demo reseeds its embedded database on restart,
  which is right for a demo but means visitor-created sessions don't survive redeploys.
  A managed Postgres (`DATABASE_URL`) is already supported for that.

## Known limitations (honest deviations from the plan)

- **Auth deferred** for single-user instances; the public demo holds synthetic data
  only (D8). Dev scripts bind `127.0.0.1` on purpose and the backend is reachable only
  server-side (via the Next.js server), so nothing is exposed today — but before ever
  hosting a private instance on a network, add authentication (an ID token checked by
  the Next.js server, plus IAM on the host).
- **At-most-once external writes**: the `actions` row flips to `approved` immediately
  before the external call, so a crash in that window makes the retry *refuse to
  resend*. Possibly-skipped beats possibly-duplicated; a future version would move the
  flip into the tool call with an idempotency key.
- **Chat streaming** is out of scope (plan §9): each turn is request/response. The
  run-scoped event log + SSE design is unchanged future work.
- **Calendar** uses a custom month grid (~40 lines TS) instead of FullCalendar — v7's
  package split is currently mismatched; revisit when `@fullcalendar/daygrid` catches up.
- **Demo spend guard is blunt**: one shared 100 turns/day cap across all visitors
  protects against unbounded LLM cost; a production deployment would add per-visitor
  limits and a provider-side spend cap.
