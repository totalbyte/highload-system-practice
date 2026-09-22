# Architecture Decision Records

One decision per file, `NNNN-short-title.md`, numbered sequentially. Never delete or rewrite an accepted ADR —
if a decision changes, add a new ADR and set the old one's status to `Superseded by NNNN`.

| # | Decision | Status |
|---|---|---|
| [0001](0001-tech-stack.md) | Tech stack: C# / ASP.NET Core 10 + EF Core + PostgreSQL | Accepted |
| [0002](0002-poll-lifecycle-publish.md) | Poll lifecycle Draft → Active → Closed with an explicit `publish` endpoint | Accepted |
| [0003](0003-visibility-rules.md) | Visibility: foreign drafts → 404, unlisted polls, 403 for management | Accepted |
| [0004](0004-atomic-status-transitions.md) | Status changes via conditional UPDATE/DELETE | Accepted |
| [0005](0005-error-handling.md) | 400 vs 422, `AppException` hierarchy, ProblemDetails | Accepted |
| [0006](0006-stateless-jwt-auth.md) | Stateless JWT auth, PBKDF2 passwords | Accepted |
| [0007](0007-database-conventions.md) | bigint ids, snake_case, status as string, batched inserts | Accepted |
| [0008](0008-ef-retry-strategy.md) | EF retry strategy; transactions inside the execution strategy | Accepted |
| [0009](0009-startup-migrations-and-seed-locking.md) | Migrations + seed on startup, seed under an advisory lock | Accepted |
| [0010](0010-seed-data.md) | Deterministic seed data with a user pool and a hot poll | Accepted |
| [0011](0011-local-environment.md) | Host port 5433, GSS off, Swagger in Production | Accepted |
| [0012](0012-instance-id-and-health.md) | `X-Instance-ID` header and `/health` from lab 1 | Accepted |
| [0013](0013-lab1-in-process-results-cache.md) | Lab 1 results cache in process memory, on purpose | Accepted (to be superseded in lab 2/4) |
| [0014](0014-vote-transaction-and-counter.md) | Vote in one transaction; unique index as source of truth; SQL-level counter | Accepted |
| [0015](0015-vote-and-results-api-shape.md) | Vote and results API shape | Accepted |
| [0016](0016-transient-db-errors-503.md) | Transient database errors map to 503 | Accepted |

Template:

```markdown
# NNNN. Title
**Status:** Proposed | Accepted | Superseded by NNNN · **Date:** YYYY-MM-DD · **Author:** Participant N
## Context
## Decision
## Consequences
```
