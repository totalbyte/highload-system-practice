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
| GET | `/health` | — | 200 / 503 `{status, instance, checks, durationMs}`, answers within 2 s (ADR 0019) | | P1 |
| POST | `/api/polls/{id}/vote` | JWT | 201 new vote / 200 changed or repeated; `{pollId, optionId, votedAt}` | 401, 404, 409, 422 | P2 |
| GET | `/api/polls/{id}/vote` | JWT | 200 `{pollId, optionId, votedAt}` — the caller's own vote (web UI, ADR 0048) | 401, 404 (not voted) | P1 (web UI) |
| GET | `/api/polls/{id}/results` | optional | 200 `{pollId, title, status, totalVotes, generatedAt, options[]}` + header `X-Cache: HIT \| MISS \| BYPASS` (ADR 0042, 0043) | 404 | P2 → P1 (lab 4) |

- Every response carries `X-Instance-ID` (container hostname or env `INSTANCE_ID`); the balancer passes it through
  unchanged. In compose (lab 3, ADR 0031) clients reach only HAProxy on http://localhost:8080 (`LB_PORT`, stats page
  http://localhost:8404/stats); `backend-1`, `backend-2` and `backend-3` (profile `scale`) publish no host ports and
  are reachable only inside `app-network` as `backend-N:8080`. HAProxy logs every request to stdout (`docker compose
  logs lb`) with the backend/server name, status and timers (`%s`, `%ST`, `%Tr`, `%Ta`), and since lab 4 the captured
  `X-Cache` response header in braces — `{HIT}` / `{MISS}` on results reads, `{}` elsewhere (ADR 0042).
- Load balancer behaviour other code relies on (ADR 0033, 0034): `/health` is the readiness check (200 = in the pool,
  503 = out; it must stay DB-only and never check Redis, ADR 0021); a node is also taken out on the first connection
  error; failed connects are retried on another node for any method, in-flight failures only for GET. HAProxy never
  treats the API's 5xx as a node failure. `POST /api/polls/{id}/vote` goes to a separate backend `be_vote`
  (Participant 2, ADR 0037): same algorithm/weights (switched together by `lb-algorithm.sh`), its own `/health` checks
  and `observe layer4` (not `track` — measured slower failover), and in-flight retries on another node (a committed
  vote retried → 409, never a double vote). When every node is out (DB down) clients get HAProxy's own
  `503 text/html`, not ProblemDetails. Default algorithm `roundrobin`, switched by `scripts/lb-algorithm.sh`.
- Web UI (ADR 0048): HAProxy sends everything except `/api/`, `/swagger`, `/health` to backend `be_web` (container
  `web`, nginx with the React build, SPA fallback to `index.html`). It has no `balance` line and its server is named
  `web`, so `lb-algorithm.sh` and the scripts reading `be_api` / `be_vote` stats ignore it.
- `docker-compose.debug.yml` (debug only, never in the standard stack) publishes `backend-1/2/3` on
  `127.0.0.1:8091/8092/8093`.
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
| 503 | Transient DB failure that outlived EF's retries (ADR 0016) — `detail` names the dependency. Since lab 4 a Redis outage no longer produces 503 on results reads: they fall back to the DB (ADR 0043); the Redis → 503 mapping stays only as a safety net |

**Voting rules (ADR 0014, 0015):** `{optionId}` body; the unique index `(poll_id, user_id)` — not the pre-check — is
what guarantees one vote per user; an option from another poll → 404 `PollOptionNotFoundException`; before
`startsAt` → 409 `PollNotStartedException`, after `endsAt` → 409 `PollVotingEndedException` (status may still be
`active`); wrong status → 409 `InvalidPollStateException`. With `allowVoteChange = true` a different option returns
200 and moves both counters, the same option is idempotent 200. Parallel requests of the **same** user are serialized
on their vote row (`FOR UPDATE`) — the last one to commit wins and the counters stay exact per option (ADR 0017).

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
- **Lab 2 (ADR 0021):** Redis service `redis:6379` in `app-network`; connection string `ConnectionStrings:Redis`
  (`redis:6379,abortConnect=false` in compose, `localhost:6379,...` for `dotnet run`); one `IConnectionMultiplexer`
  singleton in DI (`Program.cs`) — inject it, don't create another connection and don't add Redis NuGet packages.

## What Participant 2 provides to Participant 1

- `VoteService` (`Votes/`) — voting; `ResultsService` (`Results/`) — aggregated results.
- `ResultsCache` (`Results/ResultsCache.cs`, singleton, **in Redis since lab 2** — ADR 0026; generations since lab 4
  — ADR 0041) — `Task<ResultsCacheLookup> GetAsync(pollId)` (entry or null + the generation read) /
  `Task SetAsync(pollId, generation, entry)` (write under the generation from `GetAsync`, never the current one) /
  `Task InvalidateAsync(pollId)` (unchanged signature, so the callers did not change).
- `ResultsSingleFlight` (`Results/ResultsSingleFlight.cs`, singleton, ADR 0044) — `LoadAsync(pollId, generation, ct)`:
  concurrent misses of one instance for the same (poll, generation) share one DB load (own DI scope, no shared
  cancellation), which also writes the entry. Used by `ResultsService` for MISS only, never for BYPASS. Waiters answer
  `X-Cache: MISS` too — MISS means "not from Redis", not "this request queried the DB".
  **Any code that changes votes or a poll's status must `await InvalidateAsync`** — invalidation is now visible to
  every instance. `PollService` takes `ResultsCache` in its constructor and invalidates in `PublishAsync`,
  `CloseAsync` and `DeleteAsync` (publish/delete were added on 2026-09-30 after the review found stale draft entries).
- Redis format (ADR 0041), for debugging with `docker compose exec redis redis-cli`: generation counter
  `polling:results:gen:{pollId}` (integer, missing = 0, no TTL; invalidation = `INCR` + `UNLINK` of the previous
  generation's value, one Lua script); value `polling:results:v1:{pollId}:g{generation}` = `CachedPollResults` as JSON
  (camelCase, enum as string); TTL by the status in the entry — active / draft 10 s, closed 1 h, each + 0–20 % jitter.
  E.g. `GET polling:results:gen:1` → `n`, then `TTL polling:results:v1:1:g<n>`; `SCAN 0 MATCH polling:results:*`.
  Redis down (ADR 0043, supersedes 0027): `GetAsync` returns `ResultsCacheLookup.Unavailable` (generation `null`) →
  `ResultsService` reads PostgreSQL, answers 200 with `X-Cache: BYPASS` and does not write to Redis; `SetAsync` and
  `InvalidateAsync` log a warning and return, so a committed vote/publish/close/delete still answers with its success
  code. Callers need no try/catch. The Redis client is fail-fast (`BacklogPolicy.FailFast`, 1 s timeouts) and Redis
  runs without persistence (`--save ""`) — it comes back empty after a restart.
- New exceptions in `Common/Exceptions/VoteExceptions.cs`: `PollOptionNotFoundException` (404),
  `PollNotStartedException`, `PollVotingEndedException`, `DuplicateVoteException` (409).
- `GlobalExceptionHandler` maps transient DB failures (ADR 0016) and Redis connection failures/timeouts (ADR 0027)
  to 503.
- Lab 3 experiments (ADR 0036): setting `Diagnostics:ArtificialDelayMs` (env `Diagnostics__ArtificialDelayMs`) delays
  every request except `/health` on that instance; default 0 = middleware not registered. One line in `Program.cs`
  (`app.UseArtificialDelay()` after `UseInstanceIdHeader`). Never set it in `docker-compose.yml` — only in a local,
  gitignored `docker-compose.override.yml`.

## Open questions

None open for lab 1 — the stage 5–6 questions were settled on 2026-09-22 and recorded in ADR 0015.

Out of scope for lab 1, carried forward: rate limiting (design doc places it in Redis, lab 4) and `X-Cache:
HIT/MISS` headers (a lab 4 requirement — deliberately not added early).
