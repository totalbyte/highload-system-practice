# 0017. Serialize vote changes with a row lock; lock option rows in ascending id order
**Status:** Accepted (amends 0014) · **Date:** 2026-09-30 · **Author:** Participant 1

## Context
The review of stage 5 (`log/2026-09-22-p1-lab1-review.md`, problem 1) found a race in the vote-change path of
ADR 0014. Under Read Committed, N parallel change requests of the same user all read the same old `option_id`
before any of them committed, so the old option got −1 N times:
- on a fresh poll (small counters) 23 of 40 parallel changes returned **500** — the counter would have gone
  negative and `CHECK (vote_count >= 0)` rejected it;
- on poll #1 (large counters) the same race **silently** skewed per-option counters (e.g. 38 stored vs 50 real).

`SUM(vote_count) = COUNT(votes)` still held in both cases (every change is −1/+1), which is why the SUM-based check
in ADR 0014 did not catch it. A second, latent risk: two users changing in opposite directions (A→B and B→A) lock
the two option rows in opposite orders — a textbook deadlock.

## Decision
- Inside the vote transaction the user's existing vote is read with
  `SELECT * FROM votes WHERE poll_id = @p AND user_id = @u FOR UPDATE` (`db.Votes.FromSql(...)`, composed with a
  projection). Parallel requests of the same user now queue on that row; after the first commits, the next one
  re-reads the **updated** `option_id` (PostgreSQL re-evaluates locked rows under Read Committed).
- When a vote moves, the two `options` rows are updated in **ascending id order**, so any two transactions acquire
  option-row locks in the same order and cannot deadlock.
- Counters are still changed only with SQL-level `vote_count = vote_count ± 1` (ADR 0014 unchanged there).
- First votes are untouched: they insert a new row, there is nothing to lock yet; the unique index still decides
  (ADR 0014 — two simultaneous *first* votes of one user: one 201, one 409).

## Consequences
- Verified 2026-09-30: 40 parallel changes by one user on a fresh poll and on poll #1 → all 200, per-option
  `vote_count = COUNT(votes)`, exactly one vote row; 100 users making opposite changes at once → all 200, counters
  exact, no deadlocks in the Postgres or backend logs.
- The lock is per user per poll, so it adds no contention between different voters; the hot-row contention of
  bottleneck #1 is unchanged.
- **Verify counters per option, never only by SUM:**
  `SELECT count(*) FROM options o WHERE o.vote_count <> (SELECT count(*) FROM votes v WHERE v.option_id = o.id)` → 0.
