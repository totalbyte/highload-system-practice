# Backend code guide (PollingPlatform.Api)

Auto-loaded when working in this directory. Project-level context: root `CLAUDE.md` and `docs/ai/`.

## Structure

```
Program.cs                  DI, JWT, EF (retry), Redis (IConnectionMultiplexer), DataProtection keys in Redis, ProblemDetails, Swagger, /health;
                            runs migrations + seed on startup
Dockerfile                  multi-stage (sdk:10.0 → aspnet:10.0); build context = repo root; port 8080
appsettings.json            defaults (Jwt:Secret empty → provided via env Jwt__Secret)
appsettings.Development.json  dev JWT secret, Seed:Enabled=true (used by `dotnet run`)
Domain/                     User, Poll, PollStatus (Draft/Active/Closed), PollOption (table `options`), Vote
Data/
  AppDbContext.cs
  Configurations/*.cs       Fluent API: tables, indexes, check constraints, FK/cascade
  Migrations/               EF migrations (InitialSchema, ...)
  DatabaseInitializer.cs    MigrateAsync + seed on startup
  ReadDb.cs                 lab 6: EventualAsync(userId, read) — the only way to the replica (ADR 0050); fallback to the other node
  DbNodeTracking.cs         lab 6: EF connection interceptor and the X-DB-Node header
  StickySessions.cs         lab 6: Read-After-Write mark in Redis and its middleware (ADR 0051)
  DbNodeMonitor.cs          lab 6: node state, Read-Only guard interceptor, /health check (ADR 0052)
  Seeding/                  DataSeeder (deterministic, under a Postgres advisory lock), SeedOptions
Sharding/                   lab 7: ShardRouter (poll_id → shard; Range / Modulo / Hash / Buckets, fmix64), Shard (Primary + Replica
                            options and monitor of one shard), ShardContexts (scoped: PrimaryFor / ReadFor(pollId), ADR 0055)
Auth/                       AuthController (/api/auth/register, /login, /me), AuthService, JwtTokenService,
                            JwtOptions, AuthModels (DTOs + validators), ClaimsPrincipalExtensions
Polls/                      PollsController (/api/polls...), PollService (lifecycle), PollModels, PollValidators
Votes/                      VotesController (POST /api/polls/{id}/vote), VoteService (transaction + counter),
                            VoteModels, VoteValidators
Results/                    ResultsController (GET /api/polls/{id}/results), ResultsService, ResultsModels,
                            ResultsCache (Redis via the shared IConnectionMultiplexer, ADR 0026; generation-based
                            keys and TTL by poll status, ADR 0041); X-Cache: HIT | MISS | BYPASS set by the controller (ADR 0042, 0043);
                            ResultsSingleFlight — one shared DB load per (poll, generation) per instance on a
                            miss, against Cache Stampede (ADR 0044)
Common/
  Exceptions/               AppException (carries StatusCode) + NotFound/Conflict/Unauthorized/Forbidden/Validation;
                            PollNotFoundException, InvalidPollStateException; VoteExceptions.cs (option not in poll,
                            not started, voting ended, duplicate vote)
  ErrorHandling/            GlobalExceptionHandler: IExceptionHandler → RFC 7807 ProblemDetails;
                            transient DB failures → 503 (ADR 0016)
  Validation/               validator.ValidateOrThrowAsync() → 422
  InstanceIdentity.cs       X-Instance-ID response header
  Diagnostics/              ArtificialDelay: UseArtificialDelay() — lab 3 slow-node experiment, off unless
                            Diagnostics:ArtificialDelayMs > 0; /health is never delayed (ADR 0036)
```

## Conventions (follow them in new code)

- **C# style:** file-scoped namespaces; primary constructors for DI (`public class PollService(AppDbContext db, TimeProvider timeProvider)`); `record` DTOs; nullable reference types on.
- **Folder per feature** (`Auth/`, `Polls/`, next: `Votes/`, `Results/`...), each with `*Controller`, `*Service`, `*Models`, validators. Register services in `Program.cs` (`AddScoped<...>()`); validators are auto-registered by `AddValidatorsFromAssemblyContaining<Program>()`.
- **Thin controllers:** `[ApiController]`, `[Route("api/...")]`; an action does `await validator.ValidateOrThrowAsync(request, ct)` → calls the service → returns a DTO / `CreatedAtAction` / `NoContent`. No business logic, no `try/catch`.
- **Errors:** services **throw** `AppException` subclasses; never return error codes/`IActionResult` from services. New domain error = new class in `Common/Exceptions/` deriving from `NotFoundException`, `ConflictException`, etc. The global handler maps it automatically.
- **Validation:** FluentValidation `AbstractValidator<T>`. Request DTO properties are nullable (`string?`, `long?`) so missing fields produce **422** via the validator; **400** is reserved for unparseable requests (`SuppressImplicitRequiredAttributeForNonNullableReferenceTypes = true`). No DataAnnotations on DTOs.
- **Time:** inject `TimeProvider`, use `timeProvider.GetUtcNow()`; never `DateTime.Now/UtcNow`. Timestamps are `DateTimeOffset` (`timestamptz`).
- **Current user:** `User.GetUserId()` in `[Authorize]` actions, `User.FindUserId()` (nullable) in anonymous ones.
- **EF reads:** `AsNoTracking()` + `.Select(...)` projection straight into the response DTO; no `Include` + manual mapping.
- **EF writes that depend on current state:** conditional `ExecuteUpdateAsync` / `ExecuteDeleteAsync` with the condition in `WHERE`, then check affected rows (see `PollService.TransitionAsync`). No load-modify-save for status changes.
- **Transactions:** always inside `db.Database.CreateExecutionStrategy().ExecuteAsync(...)`, and call `db.ChangeTracker.Clear()` at the start of the retried block (see `DataSeeder.SeedAsync`).
- **Unique violations:** catch `DbUpdateException` with `InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation }` → throw a `ConflictException` (see `AuthService.RegisterAsync`).
- **Swagger:** every action has `/// <summary>` and `[ProducesResponseType]` for each success/error code.
- **Schema:** Fluent configuration in `Data/Configurations/`, snake_case names come from `UseSnakeCaseNamingConvention()`; change it only via `dotnet ef migrations add <Name> --project src/PollingPlatform.Api -o Data/Migrations`.
- **Comments** explain *why*, in Ukrainian like the existing code. API error messages are in English.

## Behaviour to preserve

- Poll lifecycle `Draft → Active → Closed`; delete only drafts; publish/close only by the author (ADR 0002).
- Someone else's draft → 404; someone else's non-draft poll → 403 on management actions (ADR 0003).
- A poll can be `active` with `ends_at` in the past — there is no background closer; voting checks the dates itself
  (`PollNotStartedException` / `PollVotingEndedException`, both 409).
- One vote per user is guaranteed by `UNIQUE(poll_id, user_id)`, not by the pre-check; `options.vote_count` is
  changed only with an SQL-level `+/- delta` inside the vote transaction (ADR 0014).
- In the vote transaction the user's existing vote is read `FOR UPDATE`, and when a vote moves, the two `options`
  rows are updated in ascending id order (ADR 0017). Removing either reintroduces the counter race / deadlocks.
  Check counters **per option**, not by `SUM(vote_count) = COUNT(votes)` — the SUM hides the race.
- Anything that changes votes or a poll's status (vote, publish, close, delete) must
  `await resultsCache.InvalidateAsync(pollId)` — the cache is shared by all instances (ADR 0026). On a miss, write
  with the generation returned by `GetAsync` (read **before** the DB query), never re-read it — that is what keeps
  a pre-commit aggregate out of the cache (ADR 0041).
- Redis down (ADR 0043): `GetAsync` returns `ResultsCacheLookup.Unavailable` and the read falls back to the DB
  (`X-Cache: BYPASS`, nothing written to Redis); `InvalidateAsync` / `SetAsync` swallow connection failures and
  timeouts (they run after the DB commit — a committed vote must not look failed). Don't add try/catch around the
  calls, and don't make invalidation throw. The client is fail-fast (`Program.cs`) — don't put the backlog back.
- Misses go through `ResultsSingleFlight` keyed by (poll, generation) — never key it by poll alone and never use it for
  BYPASS: either would let a read that started after a mutation's response join an older DB load (ADR 0044).
- Inject `AppDbContext` (the Primary) by default. Use `ReadDb.EventualAsync(userId, read)` only for a read that may lag and
  is not stored anywhere: never for a check before a write, a response after a write, authentication, or a results MISS /
  BYPASS, which puts stale aggregates into the shared cache (ADR 0050; measured in 0051). Pass the current user: that is what
  makes Read-After-Write work. The sticky mark must stay in `OnStarting`, before the response leaves (ADR 0051).
- Since lab 7 a poll's data lives on its shard (ADR 0054, 0055): reach `polls` / `options` / `votes` only through
  `ShardContexts.PrimaryFor(pollId)` / `ReadFor(pollId)` (or all shards for the catalog). The bare `AppDbContext` is Shard A:
  use it only for `users` and `nextval('poll_ids')`. No JOIN from poll data to `users` (different nodes) — the author name is
  `polls.creator_username`; no FKs to `users`. New poll ids always come from `poll_ids`, never from the shard.
- `/health` answers from `DbNodeMonitor`, never through the DbContext / EF retry strategy; 503 only when both database nodes are
  down (ADR 0019, 0052). The monitor's probe must stay unpooled: on the shared pool, load would look like a dead Primary and
  block writes. Only data read from the Primary goes into the results cache (ADR 0052).
