# 2026-09-22 — Participant 2 — voting core (stages 5–8)
**Lab:** 1 · **Commits:** not committed

## Goal
Implement Participant 2's half of lab 1 on top of Participant 1's platform: voting, results with the in-process
cache, the error-handling review, and the bottleneck analysis in the README.

## Done
- **Stage 5 — `POST /api/polls/{id}/vote`** (`Votes/`): `VoteService`, `VotesController`, `CastVoteRequest`
  validator. One transaction inside the execution strategy; SQL-level `vote_count = vote_count + delta`; unique
  index as the guarantee of one vote per user; explicit option-ownership check; vote change and idempotent repeat
  for `allowVoteChange = true`.
- **Stage 6 — `GET /api/polls/{id}/results`** (`Results/`): `ResultsService`, `ResultsController`, `ResultsCache`
  (`IMemoryCache`, 10 s TTL + explicit invalidation). Aggregates from `options.vote_count`. The cached entry holds
  `CreatorId`, so visibility costs no DB query on a hit.
- New exceptions in `Common/Exceptions/VoteExceptions.cs`; `Program.cs` registers the two services, `AddMemoryCache`
  and the `ResultsCache` singleton.
- **`PollService.CloseAsync`**: the `TODO(Учасник 2)` is closed — it invalidates the cache and now takes
  `ResultsCache` in its constructor.
- **Stage 7:** `GlobalExceptionHandler` maps transient DB failures to 503 (recursive `InnerException` check).
- **Stage 8:** full bottleneck analysis in the README (4 points, Component / Root Cause / Symptoms, each with its
  current mitigation state), plus a High-Load scenario section and an updated C4 diagram showing the cache inside
  the backend container.
- `requests/polls.http`: vote, results (twice, to show the cache), duplicate vote, foreign option, missing
  `optionId`, no token, vote in a closed poll, and the hot-poll vote-change sequence.
- `runbook.md`: smoke test extended with voting/results, the counter-consistency query and the concurrency check;
  new quirks (CRLF in tokens, cache TTL); Participant 2's environment.
- **`.gitattributes`** added: the repo had none, so line endings depended on each machine's `core.autocrlf` —
  a standing source of whole-file diffs once two people commit. No renormalization was needed (all tracked text
  files were already LF in the index). Flagged for Participant 1 in `status.md`.

## Decisions (link ADRs)
- [0014](../decisions/0014-vote-transaction-and-counter.md) — transaction, unique index as source of truth,
  SQL-level counter.
- [0015](../decisions/0015-vote-and-results-api-shape.md) — API shape; the four open questions from `contracts.md`
  were settled with the team before coding.
- [0016](../decisions/0016-transient-db-errors-503.md) — transient DB errors → 503.

## Problems & fixes
- Smoke-test artifacts, not product bugs: JSON serializes `100.0` as `100` (compare as float), and the hot-poll
  assertions failed on a second run because `user001` already had a vote — the test now registers a fresh user per
  run.
- The concurrency check first returned 40× 400: Python on Windows writes CRLF, and the `\r` inside the
  `Authorization` header broke the request. Fixed with `tr -d '\r'` — same family as the curl/Cyrillic quirk already
  in the runbook.

## Verified (how)
Against the Docker stack (`docker compose up -d --build`):
- Runbook smoke test plus a vote/results script — all green: 201 first vote, 409 duplicate, 404 foreign option,
  422 missing `optionId`, 401 without a token, correct totals and percentages, same `generatedAt` on a cache hit,
  status `closed` in results right after close (invalidation), 409 voting into a closed poll, vote change and
  idempotent repeat on the hot poll, draft results 404 for anonymous / 200 for the author.
- Counter consistency in SQL: `SUM(options.vote_count) = COUNT(votes)` → true.
- **Concurrency:** 40 distinct users voting into the hot poll in parallel — no lost updates, the hot option's
  counter matches `COUNT(votes)` exactly.
- `docker compose restart postgres` → results and voting return 200 (EF retry strategy holds).
- `dotnet build` clean: 0 warnings, 0 errors.

## Not done / next steps
- Stage 10 (defense rehearsal) — needs both participants: cold start from `docker compose down -v` and a full
  run-through of `requests/polls.http`.
- Nothing is committed; Participant 1 reviews and commits.
- Deliberately not done ahead of their labs: moving the cache out of process (lab 2), `X-Cache` headers and
  Cache-Aside formalities (lab 4), rate limiting (lab 4).
