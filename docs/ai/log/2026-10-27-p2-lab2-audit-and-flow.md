# 2026-10-27 — Participant 2 — lab 2: state audit (П2-1), stateless request flow (П2-5), "before" demo (П2-2), cache in Redis (П2-3), Redis outage (П2-4), concurrency checks (П2-6), instance loss (П2-7), final pass (П2-8)
**Lab:** 2 · **Commits:** on branch `lab2/p2-voting` — `e92f372` (drafts), `e5c3431` (drafts → README), `f75eea5` (П2-2),
`2a4e370` (П2-3), `5ef6f1c` (П2-4), `bc8ad58` (П2-6), `dadea62` (П2-7), then П2-8; lab 1 guide separately on `main` as `10fe4fd`

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

- **П2-2 (the "before" demo):** `scripts/results-cache-demo.py` — Python stdlib only, fresh polls per run, so it is
  repeatable and will be re-run unchanged after П2-3 as the "after". Scenario A: warm the cache on backend-2, vote via
  backend-1 → backend-2 keeps `totalVotes=0` with the same `generatedAt` until the TTL. Scenario B: the author previews
  a draft on backend-2, publishes via backend-1 → backend-2 answers **404** to others while backend-1 answers 200.
  Stable in 3 consecutive runs; output and explanation in README «Усунені in-memory залежності → Кеш результатів».
  Runbook: how to run it, expected before/after summary.
- Cold start for the demo: `docker compose down -v` + `up -d --build`. Host port 5433 was held by `kafka-sandbox-db-1`
  (an unrelated project, auto-started by Docker Desktop) → local gitignored `.env` with `POSTGRES_PORT=5434`; the
  team default is unchanged. Recorded in runbook troubleshooting and Participant 2's environment. Seed ran once on
  the concurrent start: 500 users, 50 polls, 0 per-option counter mismatches.

- **П2-3 (cache → Redis):** `ResultsCache` rewritten on the shared `IConnectionMultiplexer` (`IDatabase`, no new
  packages): `GetAsync` / `SetAsync` (JSON, `SET … EX 10`) / `InvalidateAsync` (`DEL`); callers updated in
  `ResultsService`, `VoteService` and the three invalidation points in `PollService` (publish/close/delete — only those
  lines in Participant 1's file); `AddMemoryCache()` removed. StackExchange.Redis is **3.x**: TTL goes through the
  `Expiration` type (checked against the package's XML docs, not from memory). Docs: README «Після» with the real
  output, the Request Flow note, structure and bottleneck #2; ADR 0013 → superseded; contracts (new API + Redis
  format); runbook; both `CLAUDE.md` files; `project-context.md`.

- **П2-4 (Redis unavailable):** measured first — with Redis stopped `GET /results` gave 500 after ~5.4 s and
  `POST /vote` gave 500 after ~5.9 s **with the vote already committed** (a client retry would then get 409 for a vote
  that went through). Now: `GlobalExceptionHandler` maps `RedisConnectionException` / `RedisTimeoutException` to 503
  with a dependency-specific detail (Redis checks before the generic `TimeoutException`); `ResultsCache.SetAsync` and
  `InvalidateAsync` are best-effort (one-line warning, no rethrow) — this fixes all four invalidation points without
  touching `PollService`. New `scripts/redis-outage-check.py`; README cache subsection, contracts, runbook, code guide.

- **П2-6 (concurrency across two instances):** `scripts/concurrency-checks.py` — the three runbook checks as one
  script: requests split between backend-1/backend-2 and released by a `threading.Barrier`; after each check the
  whole-DB per-option query and results on both instances vs the DB; finally `deadlock detected` in postgres logs and
  `fail:` in backend logs since the run start. Written up in README at the end of the Request Flow section (not in
  the cross-instance subsection — that one is Participant 1's, П1-5, and would conflict with `lab2/p1-platform`).
- **Mutation check of the test itself:** `FOR UPDATE` temporarily removed from `VoteService` and the backends rebuilt
  → check 2 failed with 21×500 of 40 (fresh poll) and 6×500 (poll #1), 54 `fail:` entries — the ADR 0017 race, now
  across two processes. Lock restored (`git diff` empty for the file), rebuilt, green again.

- **П2-7 (instance loss):** `scripts/kill-test.py` — 800 votes (400 users × 2 fresh polls, 32 threads) alternating
  between the instances; `docker compose kill backend-1` after 10 % (`--stop` for a graceful stop); the client retries
  a failed backend-1 request on backend-2 and then routes backend-1's share there (passive failover, as the lab 3 LB
  will). Server-side evidence from the postgres log: broken backend-1 connections and `… with an open transaction`
  (rolled back). First version classified "cut mid-request vs refused" by exception type — wrong on Windows + Docker
  Desktop (the port proxy resets connections itself; a refused `localhost` connect takes ~4 s via IPv6 then IPv4), so
  it reported 43 mid-request cuts that were not; also crashed on an uncaught `ConnectionAbortedError` (WinError 10053).
  Reworked: postgres log as the proof, `127.0.0.1`, catch `ConnectionError` broadly, denser load. README
  «Відмовостійкість» with the output and a table of all runs; runbook entry + troubleshooting row.

- **П2-8 (final pass):** README structure lists `scripts/`; contracts — `GET /results` may return 503 (ADR 0027);
  own «Next steps» line in `status.md`; all 14 «Готово, коли» boxes of my tasks ticked in
  `docs/lab2/participant-2.md` (shared sections untouched); links in README checked. Everything re-run from a cold
  start (see Verified).

## Decisions (link ADRs)
- [0026](../decisions/0026-results-cache-in-redis.md) — results cache in Redis as is (key, JSON, TTL 10 s, `DEL`),
  async API; supersedes 0013. Enum stored as a camelCase string so the value is readable in `redis-cli`.
- [0027](../decisions/0027-redis-unavailable.md) — Redis down: reads 503, invalidation and cache writes best-effort;
  the ~5 s backlog wait is accepted for lab 2 (fail-fast + DB fallback in lab 4; the connection setup is Participant
  1's block). Extends 0016.

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
П2-8, final run from a **cold start** (`docker compose down -v` → `up -d --build`): both instances healthy in 18 s,
seed once (500 users, 50 polls); `results-cache-demo.py` «no» / «no»; `redis-outage-check.py`,
`concurrency-checks.py`, `kill-test.py` — ALL CHECKS PASSED; runbook smoke test (health 200/200, create 201, list 200,
no token 401, DB restart → 200 on both); per-option counter mismatches across the whole DB after all of it: 0.

П2-7: `scripts/kill-test.py` 3× kill + 1× stop → ALL CHECKS PASSED each time (~4.5 s of voting per run): retries on
backend-2 5/7/14 (stop: 2); PostgreSQL rolled back 1/3/10 open transactions (stop: 0 broken connections); kill run 2
had one retry answered 409 — committed on backend-1, response lost — and still exactly one row; 800/800 votes stored
once, per-option mismatches 0, backend-2 results = DB; Docker did not restart backend-1 by itself in 10 s after a
manual kill/stop; after `docker compose start` `/health` 200 in ~3.3 s and identical results on backend-1 at once.

П2-6: `scripts/concurrency-checks.py` 4 times → ALL CHECKS PASSED (200×201; 40×200 on a fresh poll and on poll #1,
one vote row each; 100×200 opposite changes, 50/50; per-option mismatches 0 and identical results on both instances
after every check; no deadlocks, no `fail:`); ~16 s per run. Fails as expected without `FOR UPDATE` (see Done).

П2-4: `scripts/redis-outage-check.py` twice → ALL CHECKS PASSED (results 503 in ~5.2 s with ProblemDetails, vote 201
in ~5.9 s stored once, publish 200 in ~5.4 s, per-option counters consistent, results 200 again ~1.6 s after
`docker compose start redis` and counting the outage vote, backend containers not restarted); the warning is one line,
no stack trace; `results-cache-demo.py` still «no» / «no».

П2-3, on the stack rebuilt with `docker compose up -d --build`: `dotnet build` clean; `results-cache-demo.py` →
«no» / «no» in 3 runs; `TTL results:1` = 9 after a read, `EXISTS` = 0 after a vote; response format unchanged
(`status` as `"active"`, `generatedAt`, percentages). Parallel checks split across backend-1/backend-2: 120 first
votes → all 201 and identical results on both; 40 changes by one user → all 200, total 1; 100 opposite changes → all
200, 50/50; per-option counter mismatches 0; no deadlocks or `fail:` entries in the logs. Runbook smoke test (create
201, list 200, no token 401, DB restart → 200 on both instances).

Earlier in the session (П2-1, П2-5 drafts):
Documentation only, no code changed — no build or smoke test needed. Every claim in the audit and the flow was
checked against the current `VoteService.cs`, `ResultsService.cs`, `ResultsCache.cs`, `PollService.cs`,
`GlobalExceptionHandler.cs` and `Program.cs` on `origin/main` `320ca8e`.

## Not done / next steps
- Participant 2's part of lab 2 is complete. Next: push `lab2/p2-voting`, open the PR into `main`; С-2 — Participant 1
  reviews it (the three `InvalidateAsync` lines in `PollService`, ADR 0027's note on the Redis backlog timeout in the
  connection setup).
- Joint after all lab 2 branches are merged: С-1 (confirm the proposals), С-3 consolidated README audit, С-4 code audit,
  С-5 cold-start defense rehearsal, С-6 `labs/lab2-summary.md`.
