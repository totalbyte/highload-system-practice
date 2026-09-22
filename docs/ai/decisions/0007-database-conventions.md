# 0007. bigint ids, snake_case, status as string, batched inserts
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Decision
- Primary keys are `bigint` identity (easy to type in curl/demos), not GUIDs.
- Table/column names are snake_case via `UseSnakeCaseNamingConvention()`, matching the design doc
  (`users`, `polls`, `options`, `votes`, `vote_count`). The C# entity for options is `PollOption`.
- `polls.status` is stored as a lower-case string with a CHECK constraint (readable in SQL, safe to reorder the enum).
- Integrity in the DB: FKs, `UNIQUE(poll_id, user_id)`, `UNIQUE(poll_id, position)`, CHECK `vote_count >= 0`,
  CHECK `starts_at IS NULL OR starts_at < ends_at`.
- Creating a poll saves the poll and all options in one `SaveChanges`, which EF sends as a batch — addresses the
  N+1 bottleneck from the design doc.

## Consequences
- The DB does not enforce "option belongs to the voted poll" (no composite FK) — the vote service checks it.
