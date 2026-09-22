# Contracts: API, database, cross-participant interfaces

Update this file whenever the API, the schema, or code another participant depends on changes.

## API (implemented)

| Method | Endpoint | Auth | Success | Errors | Owner |
|---|---|---|---|---|---|
| POST | `/api/auth/register` | — | 201 | 409, 422 | P1 |
| POST | `/api/auth/login` | — | 200 `{accessToken, tokenType, expiresAt}` | 401, 422 | P1 |
| GET | `/api/auth/me` | JWT | 200 | 401 | P1 |
| POST | `/api/polls` | JWT | 201 + Location, status `draft` | 401, 422 | P1 |
| GET | `/api/polls?status=&creatorId=&page=1&pageSize=20` | optional | 200 `{items, page, pageSize, totalCount}` | 400, 422 | P1 |
| GET | `/api/polls/{id}` | optional | 200 (with options, **without** vote counts) | 404 | P1 |
| PATCH | `/api/polls/{id}/publish` | author | 200 | 403, 404, 409 | P1 |
| PATCH | `/api/polls/{id}/close` | author | 200 | 403, 404, 409 | P1 |
| DELETE | `/api/polls/{id}` | author | 204 | 403, 404, 409 | P1 |
| GET | `/health` | — | 200 / 503 `{status, instance, checks, durationMs}` | | P1 |
| POST | `/api/polls/{id}/vote` | JWT | 201 new vote / 200 changed or repeated; `{pollId, optionId, votedAt}` | 401, 404, 409, 422 | P2 |
| GET | `/api/polls/{id}/results` | optional | 200 `{pollId, title, status, totalVotes, generatedAt, options[]}` | 404 | P2 |

- Every response carries `X-Instance-ID` (container hostname or env `INSTANCE_ID`).
- Errors are RFC 7807 `application/problem+json` with `traceId`; 422 adds `errors: {field: [messages]}`.
- Enums in JSON are camelCase strings (`"draft"`, `"active"`, `"closed"`).
- Create validation: title 1..200, description ≤2000, 2..20 options, unique case-insensitively, each 1..200,
  `endsAt` > now, `startsAt` < `endsAt`. List: `page` ≥1, `pageSize` 1..100.
- Visibility: someone else's draft → 404; `isPublic=false` → hidden from the list but reachable by id; authors see
  all their own polls in the list (ADR 0003).

| Code | Meaning |
|---|---|
| 400 | Unparseable request (broken JSON, wrong type, unknown enum value in query) |
| 401 | Missing/invalid token; wrong credentials |
| 403 | Managing someone else's (non-draft) poll |
| 404 | Poll doesn't exist, or it's someone else's draft |
| 409 | Invalid status transition; duplicate email/username; duplicate vote; voting outside `startsAt`…`endsAt` |
| 422 | Field validation failed |
| 503 | Transient DB failure that outlived EF's retries (ADR 0016) |

**Voting rules (ADR 0014, 0015):** `{optionId}` body; the unique index `(poll_id, user_id)` — not the pre-check — is
what guarantees one vote per user; an option from another poll → 404 `PollOptionNotFoundException`; before
`startsAt` → 409 `PollNotStartedException`, after `endsAt` → 409 `PollVotingEndedException` (status may still be
`active`); wrong status → 409 `InvalidPollStateException`. With `allowVoteChange = true` a different option returns
200 and moves both counters, the same option is idempotent 200.

**Results (ADR 0015):** aggregated from `options.vote_count`; `generatedAt` does not change while the cached copy is
served; the cache entry also holds `CreatorId`, so visibility is decided without a DB query.

## Database schema

Defined by EF migrations in `src/PollingPlatform.Api/Data/Migrations` (current: `InitialSchema`).

| Table | Columns | Constraints / indexes |
|---|---|---|
| `users` | id, username(50), email(254, lower-cased), password_hash, created_at | PK, UNIQUE(email), UNIQUE(username) |
| `polls` | id, title(200), description(2000)?, creator_id, status(16), is_public, allow_vote_change, starts_at?, ends_at, created_at | FK creator_id→users RESTRICT; CHECK status IN (draft, active, closed); CHECK `starts_at IS NULL OR starts_at < ends_at`; idx(creator_id), idx(status, created_at) |
| `options` | id, poll_id, text(200), position, vote_count DEFAULT 0 | FK→polls CASCADE; UNIQUE(poll_id, position); CHECK vote_count ≥ 0 |
| `votes` | id, poll_id, option_id, user_id, created_at | FK→polls CASCADE, →options CASCADE, →users RESTRICT; **UNIQUE(poll_id, user_id)**; idx(option_id), idx(user_id) |

- `UNIQUE(poll_id, user_id)` also serves lookups of votes by `poll_id`; `UNIQUE(poll_id, position)` serves lookups of
  options by `poll_id`.
- The DB does **not** guarantee that a vote's option belongs to the vote's poll (no composite FK) — the voting
  service must check it.
- `options.vote_count` is a denormalized counter; it must stay equal to the number of `votes` rows for that option.

## What Participant 1 provides to Participant 2

- `User.GetUserId()` / `User.FindUserId()` — `Auth/ClaimsPrincipalExtensions.cs`.
- Exception base classes — `Common/Exceptions/AppExceptions.cs`. Create `PollClosedException` and
  `DuplicateVoteException` deriving from `ConflictException` (409); the global handler maps them automatically.
- `validator.ValidateOrThrowAsync(request, ct)` — `Common/Validation/ValidatorExtensions.cs`.
- Execution-strategy pattern for transactions — `Data/Seeding/DataSeeder.cs` (ADR 0008).
- Unique-violation handling pattern — `Auth/AuthService.cs` (`RegisterAsync`).
- Hot poll #1 in the seed for load tests (ADR 0010).

## What Participant 2 provides to Participant 1

- `VoteService` (`Votes/`) — voting; `ResultsService` (`Results/`) — aggregated results.
- `ResultsCache` (`Results/ResultsCache.cs`, singleton) — `Get` / `Set` / `Invalidate(pollId)`. **Any code that
  changes votes or a poll's status must call `Invalidate`.** `PollService.CloseAsync` already does (the
  `TODO(Учасник 2)` is closed); `PollService` now takes `ResultsCache` in its constructor.
- New exceptions in `Common/Exceptions/VoteExceptions.cs`: `PollOptionNotFoundException` (404),
  `PollNotStartedException`, `PollVotingEndedException`, `DuplicateVoteException` (409).
- `GlobalExceptionHandler` now maps transient DB failures to 503 (ADR 0016).

## Open questions

None open for lab 1 — the stage 5–6 questions were settled on 2026-09-22 and recorded in ADR 0015.

Out of scope for lab 1, carried forward: rate limiting (design doc places it in Redis, lab 4) and `X-Cache:
HIT/MISS` headers (a lab 4 requirement — deliberately not added early).
