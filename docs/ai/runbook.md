# Runbook: running, testing, troubleshooting

## Run with Docker (normal way)

Docker Desktop must be running (on Participant 1's machine it does not start automatically).

```bash
docker compose up -d --build          # backend + postgres; migrations + seed run on backend startup
docker compose logs -f backend
docker compose restart postgres       # data survives (named volume pgdata)
docker compose down -v                # wipe everything, including data → next `up` is a cold start
docker compose --profile tools up -d  # + Adminer (DB web UI) on :8081
```

| What | Address |
|---|---|
| API | http://localhost:8080 |
| Swagger UI | http://localhost:8080/swagger (spec: `/swagger/v1/swagger.json`) |
| Health | http://localhost:8080/health |
| Postgres from the host | `localhost:5433`, db/user/password `polling` (container-internal port is 5432) |
| Adminer | http://localhost:8081 (server `postgres`) |

All settings have defaults in `docker-compose.yml`; override them via `.env` (see `.env.example`).
Cold start from `down -v` to healthy takes ≈13 s (measured 2026-09-22).

## Run the backend locally (without Docker for the backend)

```bash
docker compose up -d postgres
dotnet run --project src/PollingPlatform.Api   # http://localhost:5094/swagger, Development environment
```

Development settings (`appsettings.Development.json`) supply the JWT secret and enable the seed.

## Migrations

```bash
dotnet ef migrations add <Name> --project src/PollingPlatform.Api -o Data/Migrations
```

Applied automatically on startup (`Database:MigrateOnStartup=true`). Preview SQL:
`dotnet ef migrations script --idempotent --project src/PollingPlatform.Api`.

## Seed data

Runs on startup when `Seed:Enabled=true` (default in compose) **and** the `users` table is empty. Deterministic
(`Seed:RandomSeed=42`) — every cold start produces the same data.

- 500 users `user001@example.com` … `user500@example.com` (usernames `user001` …), password `Password123!`.
- 50 polls: ~70% active, ~15% closed, ~15% draft; authors are the first 20 users; ≈4953 votes;
  `SUM(options.vote_count) = COUNT(votes)`.
- **Poll #1 (hot poll):** active, no votes, `allowVoteChange=true`, ends in +1 year — target for lab 5 writes.

## Smoke test (run after every change)

```bash
B=http://localhost:8080
curl -i $B/health                                   # 200, X-Instance-ID header, {"status":"Healthy",...}
T=$(curl -s -X POST $B/api/auth/login -H "Content-Type: application/json" \
     -d '{"email":"user001@example.com","password":"Password123!"}' | python -c "import sys,json;print(json.load(sys.stdin)['accessToken'])")
curl -s -X POST $B/api/polls -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
     -d '{"title":"Smoke","options":["A","B"],"endsAt":"2030-01-01T00:00:00Z"}'   # 201, status "draft"
curl -s "$B/api/polls?status=active&pageSize=2"     # 200, paged list
curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/api/polls -H "Content-Type: application/json" -d '{}'  # 401
docker compose restart postgres && sleep 3 && curl -s -o /dev/null -w "%{http_code}\n" $B/api/polls/1   # 200, not 500
```

Voting and results (create a poll, publish it, take `P` = its id and `O` = `options[0].id` from the response):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/api/polls/$P/vote -H "Authorization: Bearer $T" \
     -H "Content-Type: application/json" -d "{\"optionId\":$O}"     # 201 first vote, 409 on a repeat
curl -s $B/api/polls/$P/results                                     # totalVotes/percentage; note generatedAt
curl -s $B/api/polls/$P/results                                     # same generatedAt → served from the cache
curl -s -X PATCH $B/api/polls/$P/close -H "Authorization: Bearer $T" >/dev/null
curl -s $B/api/polls/$P/results | grep -o '"status":"[a-z]*"'       # "closed" → close invalidated the cache
```

**Counter consistency** (must always hold — `options.vote_count` mirrors the `votes` rows):

```bash
docker compose exec -T postgres psql -U polling -d polling -tAc \
  "SELECT (SELECT COALESCE(SUM(vote_count),0) FROM options) = (SELECT COUNT(*) FROM votes)"   # t
```

**Concurrency check** (the core claim of the project — run it after touching the vote path): log in as N different
seed users, fire their votes into the hot poll in parallel, then re-run the consistency query above. 40 parallel
votes were verified on 2026-09-22 with no lost updates. Strip `\r` from tokens read out of a file (see quirks).

Full demo scenario with error cases: `requests/polls.http` (VS Code REST Client / Rider / Visual Studio).
No automated tests yet (`public partial class Program;` is kept for future `WebApplicationFactory` tests).

## Troubleshooting / known quirks

| Symptom | Cause / fix |
|---|---|
| Cyrillic becomes `????` when sent with curl from Git Bash on Windows | Shell encoding, not the server. Use Swagger, `.http`, Postman, or `curl --data-binary @file.json` with a UTF-8 file |
| Every request returns 400 when the token comes from a file written by Python on Windows | Python writes CRLF; the `\r` inside the `Authorization` header breaks the request. Pipe tokens through `tr -d '\r'` |
| `GET /results` still shows an old total | The in-process cache has a 10 s TTL as a safety net; a vote or a close invalidates it immediately. With two instances the caches diverge on purpose (ADR 0013) |
| Can't reach the container DB on 5432 / connected to the wrong DB | Participant 1's machine runs a local Windows PostgreSQL service on 5432 — the container is on **5433** (ADR 0011) |
| `fail: ... SELECT migration_id FROM "__EFMigrationsHistory"` on first start | Expected: the history table doesn't exist yet. Not an error |
| Warning about DataProtection keys "not persisted outside of the container" | Harmless (we use JWT, not DataProtection); note it for the lab 2 state audit |
| `The Entity Framework tools version '10.0.5' is older than ...` | Harmless; `dotnet tool update -g dotnet-ef` |
| `failed to connect to the docker API` | Docker Desktop isn't running |
| First request after a DB restart fails | Should not happen (EF retry strategy, ADR 0008); if it does, check the retry config |
| `~$...docx` files appear in `docs/` | Word lock files while a document is open; ignored by `.gitignore` |

## Environment on Participant 2's machine

Windows 11, .NET SDK 10.0.202, Docker 28.5.1 (Docker Desktop does not start automatically here either — launch it
before `docker compose`), Git Bash, Python 3 **with `python-docx`** (so `.docx` files can be generated/read
directly, unlike on Participant 1's machine); no `pandoc`. Local Postgres on 5432 is not an issue here, but the
container stays on 5433 for both of us (ADR 0011).

## Environment on Participant 1's machine

Windows 10, .NET SDK 8.0 / 10.0.201 / 10.0.301, global `dotnet-ef` 10.0.5, Docker 29.3.1, Compose v5.1.1, Go, Node,
Python 3.13 (no `python-docx`, no `pandoc`, no `zip` in Git Bash), k6.
