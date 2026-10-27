# 2026-10-27 — Participant 2 — lab 2: state audit (П2-1) and stateless request flow (П2-5)
**Lab:** 2 · **Commits:** not committed (branch `lab2/p2-voting`, local only)

## Goal
Pull the lab 2 task split and Participant 1's review fixes, then start the Participant 2 tasks that do not depend on
the `lab2/p1-infra` branch (Redis + two instances): П2-1 and П2-5.

## Done
- Local `main` was 9 commits behind `origin/main` and the pull clashed with uncommitted lab 1 edits (guide links in
  `README.md` / `CLAUDE.md`, a log line). Stashed them (`-u`), fast-forwarded, popped — merged cleanly, nothing
  duplicated. They are still uncommitted and travel with the working copy onto `lab2/p2-voting`.
- Created the local branch `lab2/p2-voting` from the fresh `main` (proposed convention, not yet confirmed — С-1).
- **П2-1:** state audit of `Votes/`, `Results/`, `Common/ErrorHandling/`, `VoteExceptions.cs` and their DI
  registrations, done against the code (grep for `static`, locks, `Concurrent*`, `IMemoryCache`, timers, files,
  sessions; review of every registration lifetime) — not copied from the indicative table in `participant-2.md`.
- **П2-5:** stateless request flow for `POST /vote`: the four 2.3 requirements mapped to the code, a mermaid sequence
  diagram (target state after П2-3), the per-option invariant, and what happens if an instance dies mid-request.
- Both drafts were first kept in `docs/lab2/p2-readme-drafts.md` (commit `e92f372`), because the lab 2 README
  skeleton was still to come with П1-1. After `lab2/p1-infra` was merged (PR #2), `main` was merged into
  `lab2/p2-voting` (no conflicts), both drafts moved into the README skeleton («Аудит стану → Голосування й
  результати», «Stateless Request Flow») and the drafts file was deleted.
- README bottleneck #2 no longer says the cache moves to Redis "in lab 4" — it moves in lab 2 (П2-3); lab 4 is
  Cache-Aside, key schema, TTL rationale and DB fallback (as Participant 1 pointed out).

## Decisions (link ADRs)
None — no non-obvious technical decision yet. Drafts-file placement is a temporary workflow choice, noted above.

## Problems & fixes
Audit findings missing from the indicative table, recorded in the drafts file:
1. The cached entry holds the poll `Status`, so across instances not only the numbers go stale — after a publish on
   one instance the other keeps answering **404** to non-authors for up to 10 s. Better hidden-affinity demo for П2-2.
2. `GlobalExceptionHandler` is a **singleton** (`AddExceptionHandler`), not scoped — safe (no mutable fields), but
   С-4's grep will flag it.
3. The read-before-commit / cache-after-invalidation race stays after the move to Redis (lab 4 topic).
4. A commit whose acknowledgement is lost is retried (EF strategy or client on the other instance) and answered 409 —
   stored exactly once; expected behaviour for П2-7.

Lab 1 leftover, fixed: `docs/lab1-guide.md` claimed the 40-vote check proved "no lost updates", but ADR 0017 showed
the vote-change race that check missed (it compared SUMs). The guide was brought in line with all review fixes
(ADR 0017–0019, invalidation on publish/close/delete, pgAdmin, per-option check) and committed **separately to
`main`** as `10fe4fd` together with the guide links and the README bottleneck #2 wording; `lab2/p2-voting` was
fast-forwarded onto it, so the lab 2 PR stays free of lab 1 changes.

## Verified (how)
Documentation only, no code changed — no build or smoke test needed. Every claim in the audit and the flow was
checked against the current `VoteService.cs`, `ResultsService.cs`, `ResultsCache.cs`, `PollService.cs`,
`GlobalExceptionHandler.cs` and `Program.cs` on `origin/main` `320ca8e`.

## Not done / next steps
- П2-2, П2-3 blocked until `lab2/p1-infra` is merged; П2-2 strictly before П2-3.
- С-1: confirm the proposals in `docs/lab2/participant-*.md` with Participant 1.
- After П2-3: re-check the П2-5 invalidation step against the code; move both drafts into README.
