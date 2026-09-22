# Backend code guide (PollingPlatform.Api)

Auto-loaded when working in this directory. Project-level context: root `CLAUDE.md` and `docs/ai/`.

## Structure

```
Program.cs                  DI, JWT, EF (retry), ProblemDetails, Swagger, /health; runs migrations + seed on startup
Dockerfile                  multi-stage (sdk:10.0 → aspnet:10.0); build context = repo root; port 8080
appsettings.json            defaults (Jwt:Secret empty → provided via env Jwt__Secret)
appsettings.Development.json  dev JWT secret, Seed:Enabled=true (used by `dotnet run`)
Domain/                     User, Poll, PollStatus (Draft/Active/Closed), PollOption (table `options`), Vote
Data/
  AppDbContext.cs
  Configurations/*.cs       Fluent API: tables, indexes, check constraints, FK/cascade
  Migrations/               EF migrations (InitialSchema, ...)
  DatabaseInitializer.cs    MigrateAsync + seed on startup
  Seeding/                  DataSeeder (deterministic, under a Postgres advisory lock), SeedOptions
Auth/                       AuthController (/api/auth/register, /login, /me), AuthService, JwtTokenService,
                            JwtOptions, AuthModels (DTOs + validators), ClaimsPrincipalExtensions
Polls/                      PollsController (/api/polls...), PollService (lifecycle), PollModels, PollValidators
Votes/                      VotesController (POST /api/polls/{id}/vote), VoteService (transaction + counter),
                            VoteModels, VoteValidators
Results/                    ResultsController (GET /api/polls/{id}/results), ResultsService, ResultsModels,
                            ResultsCache (in-process, ADR 0013 — lab 2 audit target)
Common/
  Exceptions/               AppException (carries StatusCode) + NotFound/Conflict/Unauthorized/Forbidden/Validation;
                            PollNotFoundException, InvalidPollStateException; VoteExceptions.cs (option not in poll,
                            not started, voting ended, duplicate vote)
  ErrorHandling/            GlobalExceptionHandler: IExceptionHandler → RFC 7807 ProblemDetails;
                            transient DB failures → 503 (ADR 0016)
  Validation/               validator.ValidateOrThrowAsync() → 422
  InstanceIdentity.cs       X-Instance-ID response header
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
- Anything that changes votes or a poll's status must call `ResultsCache.Invalidate(pollId)`.
