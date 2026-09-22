# 0010. Deterministic seed data with a user pool and a hot poll
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
The execution plan requires a seed script: because of `UNIQUE(poll_id, user_id)`, 200 virtual users in lab 5 can't
vote with one account — they'd get 409 instead of real load. Demos also need realistic data.

## Decision
- 500 users `userNNN@example.com` / `Password123!` (one PBKDF2 hash computed once and reused — hashing 500 times is
  slow).
- 50 polls: ~70% active, ~15% closed, ~15% draft, 2–5 options, authors among the first 20 users, random votes with
  `vote_count` kept equal to the number of vote rows.
- Poll #1 is the "hot poll": active, no votes, `allowVoteChange = true`, ends in +1 year — target for the write
  scenario.
- Fixed random seed (`Seed:RandomSeed = 42`): every cold start yields identical data.
- Configurable via `Seed__Enabled`, `Seed__Users`, `Seed__Polls` (compose env / `.env`).

## Consequences
- Bug found and fixed: closed polls could get `ends_at < starts_at` (CHECK violation); now
  `ends_at = created_at + 1..19 h`.
- Verified on cold start: 500 users, 50 polls, 4953 votes, `SUM(vote_count) = COUNT(votes)`.
