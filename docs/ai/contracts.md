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
| POST | `/api/polls/{id}/vote` | JWT | — | — | P2, **not implemented** |
| GET | `/api/polls/{id}/results` | — | — | — | P2, **not implemented** |

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
| 409 | Invalid status transition; duplicate email/username (P2: duplicate vote, closed poll) |
| 422 | Field validation failed |

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

## What Participant 2 must provide

**`POST /api/polls/{id}/vote` (stage 5):**
1. Poll exists (someone else's draft → 404), `status = active`, `starts_at <= now < ends_at` — status does **not**
   flip to closed automatically when `ends_at` passes.
2. `optionId` belongs to this poll.
3. In **one transaction inside the execution strategy**: INSERT into `votes` + `UPDATE options SET vote_count =
   vote_count + 1`. Repeat vote → unique violation → 409 if `allow_vote_change = false`; if `true`, change
   `option_id` and adjust both counters.
4. Invalidate the poll's results cache.

**`GET /api/polls/{id}/results` (stage 6):** aggregates from `options.vote_count`, cached **in process memory** for
lab 1 (intentional — lab 2 audit target).

**Hook in Participant 1's code:** `PollService.CloseAsync` — `TODO(Учасник 2)`: invalidate the results cache on close.

**After implementing:** add the endpoints to the API table above, to `requests/polls.http`, and to `README.md`
(remove "в роботі").

## Open questions — settle with the user before coding stages 5–6

| Question | Suggestion (not agreed) |
|---|---|
| `POST /vote` request body | `{ "optionId": 123 }` |
| `POST /vote` response | 201 for a new vote, 200 for a changed vote; body `{ pollId, optionId, votedAt }` or fresh results |
| Re-voting for the **same** option when `allowVoteChange = true` | idempotent 200, counters unchanged |
| Voting before `starts_at` / after `ends_at` | 409 (`PollClosedException`, or a separate "not started" error) |
| `GET /results` response shape | `{ pollId, status, totalVotes, options: [{ id, text, votes, percentage }] }` |
| Who can see results | same visibility as `GET /api/polls/{id}`; anonymous allowed |
| In-process cache implementation | `IMemoryCache`, short TTL + explicit invalidation on vote/close |
| Rate limiting (design doc mentions it for Redis) | out of scope for lab 1 |
| Transient DB errors in the handler | map `NpgsqlException`/timeouts to 503 instead of 500 |
