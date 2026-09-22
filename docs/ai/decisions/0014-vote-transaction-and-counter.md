# 0014. Vote in one transaction; the unique index is the source of truth; SQL-level counter increment
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 2

## Context
`POST /api/polls/{id}/vote` is the system's peak operation (high-load scenario: a vote spike into one poll). It must
insert a row into `votes` and keep the denormalized `options.vote_count` equal to the number of matching `votes`
rows. The schema has `UNIQUE(poll_id, user_id)` but no composite FK tying a vote's option to the vote's poll.

## Decision
- Insert and counter update run in **one explicit transaction** inside
  `db.Database.CreateExecutionStrategy().ExecuteAsync(...)` (ADR 0008), with `ChangeTracker.Clear()` at the start of
  the retried block.
- The counter is changed with `ExecuteUpdateAsync(vote_count = vote_count + delta)` — an SQL-level increment, never
  load-modify-save, so concurrent votes cannot overwrite each other (lost update).
- "One vote per user" is guaranteed by the **unique index**, not by the preceding `SELECT`: a `DbUpdateException`
  with `SqlState = UniqueViolation` becomes `DuplicateVoteException` (409). The pre-check only produces a nicer
  error on the common path.
- Option ownership (`optionId` belongs to this poll) is checked explicitly in the service, because the DB cannot
  enforce it → `PollOptionNotFoundException` (404).
- `allowVoteChange = true`: a different option updates the vote row and moves the counter (−1 old, +1 new) in the
  same transaction; the **same** option is idempotent (200, counters untouched).

## Consequences
- Verified with 40 parallel votes: `SUM(options.vote_count) = COUNT(votes)` and the hot option's counter is exact.
- Row-level lock contention on a popular option's row remains by design — it is bottleneck #1 and the expected
  saturation point of the lab 5 write scenario. Do not "fix" it with application-level locking; the lab-appropriate
  answers are batching/queueing (lab 4/5 discussion).
- Two simultaneous first votes by the *same* user on an `allowVoteChange` poll: one wins, the other gets 409 instead
  of being treated as a change. Accepted — a client retry takes the change path, and load tests use distinct users.
