# 0015. Vote and results API shape
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 2

## Context
`contracts.md` listed open questions about the shape of the two endpoints Participant 2 owns. Settled with the team
before coding stages 5–6.

## Decision
- `POST /api/polls/{id}/vote` takes `{ "optionId": 123 }` and returns `{ pollId, optionId, votedAt }` with
  **201** for a new vote and **200** for a changed or repeated one. It does *not* return the aggregate: keeping the
  write path free of reads keeps the lab 5 write scenario clean.
- Voting outside the time window uses **two distinct exceptions**, both 409: `PollNotStartedException` (before
  `startsAt`) and `PollVotingEndedException` (after `endsAt`). A wrong *status* (draft/closed) reuses Participant 1's
  `InvalidPollStateException`.
- Repeating the same option with `allowVoteChange = true` is **idempotent 200** — safe under k6 retries and double
  clicks.
- `GET /api/polls/{id}/results` returns `{ pollId, title, status, totalVotes, generatedAt, options: [{ id, text,
  position, votes, percentage }] }`, anonymous access allowed, same visibility as `GET /api/polls/{id}`.
  `generatedAt` is the moment the aggregate was computed from the DB — on a cache hit it does not change, which is
  how the cache is demonstrated without a `X-Cache` header (that header is a lab 4 requirement).
- Percentages are rounded to 2 decimals; `0` when there are no votes.

## Consequences
- The cached entry stores `CreatorId` alongside the response, so the visibility check on a cache hit costs no DB
  query. Whatever replaces this cache in lab 2/4 must keep that property or accept a DB round-trip per read.
- 201 carries no `Location` header: there is no `GET /votes/{id}` resource to point at.
