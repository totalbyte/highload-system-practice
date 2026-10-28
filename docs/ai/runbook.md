# Runbook: running, testing, troubleshooting

## Run with Docker (normal way)

Docker Desktop must be running (on Participant 1's machine it does not start automatically).

```bash
docker compose up -d --build          # backend-1 + backend-2 + postgres + redis; migrations + seed run on backend startup
docker compose logs -f backend-1 backend-2
docker compose restart postgres       # data survives (named volume pgdata)
docker compose down -v                # wipe everything, including data → next `up` is a cold start
docker compose --profile tools up -d  # + Adminer on :8081 (pgAdmin 4 on :5050 starts with the normal `up`)
```

| What | Address |
|---|---|
| API, instance `backend-1` | http://localhost:8080 (`API_PORT`) |
| API, instance `backend-2` | http://localhost:8082 (`API2_PORT`) |
| Swagger UI | http://localhost:8080/swagger (spec: `/swagger/v1/swagger.json`), same on :8082 |
| Health | http://localhost:8080/health, http://localhost:8082/health |
| Postgres from the host | `localhost:5433`, db/user/password `polling` (container-internal port is 5432) |
| Redis | `localhost:6379` (`REDIS_PORT`); `docker compose exec redis redis-cli` |
| Adminer | http://localhost:8081 (server `postgres`) |
| pgAdmin 4 | http://localhost:5050 — no login (desktop mode); server "polling (docker)" is pre-registered from the inline `configs.pgadmin_servers` in `docker-compose.yml`; enter DB password `polling` once and tick "Save password". Starts in ~40 s (ADR 0020) |

All settings have defaults in `docker-compose.yml`; override them via `.env` (see `.env.example`). `DB_MAX_POOL_SIZE`
(default 30) caps the Npgsql pool of one backend instance — keep *instances × pool ≤ 97* (ADR 0018); two instances
use at most 60. Both instances are built from one image and differ only in `INSTANCE_ID` and host port (ADR 0021).
Cold start from `down -v` to healthy takes ≈11–13 s (measured 2026-09-22 and 2026-09-30).

## Run the backend locally (without Docker for the backend)

```bash
docker compose up -d postgres redis
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
- 50 polls: ~70% active, ~15% closed, ~15% draft; authors are the first 20 users; 5596 votes; each poll takes one of
  12 topics with its own matching options (e.g. "Хмарний провайдер #1" → AWS / Azure / GCP);
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

**Counter consistency** (must always hold — `options.vote_count` mirrors the `votes` rows). Check it **per option**:
a vote change is −1/+1, so a race can skew individual options while the global SUM still matches (ADR 0017).

```bash
docker compose exec -T postgres psql -U polling -d polling -tAc \
  "SELECT count(*) FROM options o WHERE o.vote_count <> (SELECT count(*) FROM votes v WHERE v.option_id = o.id)"   # 0
```

Local data already skewed by an old bug can be repaired (data only, not schema) with
`UPDATE options o SET vote_count = (SELECT count(*) FROM votes v WHERE v.option_id = o.id)` — or `docker compose down -v`.

**Concurrency checks** (the core claim of the project — run after touching the vote path):
`python scripts/concurrency-checks.py` (from the repo root, stdlib only, ~16 s, fresh polls each run). Requests are
split between backend-1 and backend-2 and released together by a barrier; after each check it verifies per-option
counters for the whole DB and that results on both instances match the DB; at the end it scans the postgres logs for
`deadlock detected` and the backend logs for `fail:` since the run started. Exit code 0 = all passed. The three checks:
1. **Many users, first votes:** 200 different seed users vote into one fresh poll at once → all 201, no 5xx.
2. **One user, parallel changes** on an `allowVoteChange` poll: 40 requests alternating options → all 200, exactly one
   vote row for the user. Run it on a **fresh** poll too (small counters used to fail with 500 on
   `ck_options_vote_count`).
3. **Opposite changes:** half of 100 users change A→B while the other half change B→A at the same moment → all 200,
   no `deadlock detected` in `docker compose logs postgres`.

Last verified 2026-10-27 on two instances: all checks green in 4 consecutive runs. The script is known to catch the
vote-change race: with `FOR UPDATE` temporarily removed it failed with 21×500 of 40 (fresh poll) and 6×500 (poll #1).
Earlier single-instance run: 2026-09-30, 48/48 incl. a cold start; the backend held 30 connections afterwards.
Strip `\r` from tokens read out of a file (see quirks).

**Results cache across instances (lab 2, П2-2/П2-3):** `python scripts/results-cache-demo.py` (stdlib only; `API1` /
`API2` env vars override the instance URLs). Creates fresh polls each run, so it is repeatable. Scenario A: warm the
cache on backend-2, vote via backend-1, read from both. Scenario B: the author previews a draft on backend-2, publishes
via backend-1, an anonymous client reads from both. Since П2-3 (cache in Redis, ADR 0026) both summary lines
must say **no**, and step 3 of scenario A shows the same `generatedAt` on both instances; a **YES** means the cache is
per-process again (it was, by design, before П2-3: stale counts until the 10 s TTL and 404 for the just-published
poll). ~1 s per run; it waits out the TTL only when it sees stale data. Redis side:
`docker compose exec redis redis-cli TTL results:1` → ≤ 10 after a read, `EXISTS results:1` → 0 after a vote.

**Instance loss (lab 2, П2-7):** `python scripts/kill-test.py` (from the repo root; `--stop` for a graceful stop
instead of SIGKILL). 800 votes (400 users × 2 fresh polls, 32 threads) alternate between the instances; after 10 %
it runs `docker compose kill backend-1`; the client retries a failed backend-1 request on backend-2 and then sends
backend-1's share straight there. Expected: every vote 201 (or 409 on a retry whose first attempt had committed),
vote rows = users per poll, per-option counters consistent, backend-2 results = DB; then `docker compose start
backend-1`, `/health` 200 within ~3 s and the same results immediately. It also prints how many backend-1 connections
PostgreSQL saw break and how many had an open transaction (rolled back). ~20 s per run (incl. a 10 s wait to see
whether Docker restarts the container — it does not after a manual kill/stop). Always starts backend-1 again in
`finally`. Uses `127.0.0.1`: on Windows a refused connection to `localhost` takes ~4 s (IPv6, then IPv4).

**Redis outage (lab 2, П2-4, ADR 0027):** `python scripts/redis-outage-check.py` (from the repo root; it runs
`docker compose stop/start redis` itself and always starts Redis again in `finally`). Expected: results 503 while
Redis is down, vote 201 stored once, publish 200, counters consistent; after start — results 200 within ~2 s, fresh,
no backend restart. ~25 s per run.

**Load generator (lab 3, П2-2):** `python scripts/load.py --scenario read|write|mixed --threads 32 --duration 20
--runs 3` (from the repo root, stdlib only). Closed loop: each thread keeps one keep-alive connection and sends the
next request right after the previous answer. All scenarios use one fresh poll with `allowVoteChange` and 4 options;
`write` = votes / vote changes by random users out of 300 (exercises `FOR UPDATE` and the hot `vote_count` rows),
`mixed` = 80 % reads. Prints rps, p50/p95/p99/max, responses by code (5xx and connection errors separately), the
split by `X-Instance-ID` with per-instance mean/p99, a summary with the rps spread for `--runs > 1`, and after any
write scenario the per-option counter check (exit code 1 on a mismatch). Target: env `API` (default the balancer
address `http://127.0.0.1:8080`); several comma-separated URLs are split between the threads on the client side —
each thread sticks to one URL, so a slow instance simply gets fewer requests; this is **not** a balancing algorithm.
Baseline 2026-10-28 (two instances, client-side split, 32 threads × 10 s, no delay): `read` ≈ 1.9k rps, p99 ≈ 43 ms,
spread 4 %; `write` ≈ 250–320 rps, p50 ≈ 28 ms, p99 ≈ 1 s (row locks on 4 hot options), spread 20 %; counters 0.
The generator shares the CPU with the stack and Python has the GIL — compare configurations, not absolute numbers.

**Slow instance (lab 3, П2-1, ADR 0036):** a local `docker-compose.override.yml` (gitignored, picked up by
`docker compose` automatically):

```yaml
services:
  backend-2:
    environment:
      Diagnostics__ArtificialDelayMs: 200
```

`docker compose up -d backend-2` applies it; `backend-2` logs "Artificial delay of 200 ms is enabled" at startup and
every request except `/health` gets +200 ms. Delete the file and `docker compose up -d backend-2` again to switch it
off — **don't leave it lying around**, every later `docker compose up` would pick it up. The first request after a
restart is slow anyway (JIT warm-up), measure from the second one.

Full demo scenario with error cases: `requests/polls.http` (VS Code REST Client / Rider / Visual Studio).
No automated tests yet (`public partial class Program;` is kept for future `WebApplicationFactory` tests).

## Troubleshooting / known quirks

| Symptom | Cause / fix |
|---|---|
| Cyrillic becomes `????` when sent with curl from Git Bash on Windows | Shell encoding, not the server. Use Swagger, `.http`, Postman, or `curl --data-binary @file.json` with a UTF-8 file |
| Every request returns 400 when the token comes from a file written by Python on Windows | Python writes CRLF; the `\r` inside the `Authorization` header breaks the request. Pipe tokens through `tr -d '\r'` |
| `GET /results` still shows an old total | The cache (Redis, shared by all instances, ADR 0026) is invalidated by a vote, publish, close or delete, with a 10 s TTL as a safety net. A stale value for up to 10 s right after a vote is the known invalidation race (aggregate read before the commit, written after the `DEL`) — a lab 4 topic. If instances disagree, run `scripts/results-cache-demo.py`: a **YES** means something went back to a per-process cache |
| Can't reach the container DB on 5432 / connected to the wrong DB | Participant 1's machine runs a local Windows PostgreSQL service on 5432 — the container is on **5433** (ADR 0011) |
| `fail: ... SELECT migration_id FROM "__EFMigrationsHistory"` on first start | Expected: the history table doesn't exist yet. Not an error |
| `fail: ... CREATE TABLE IF NOT EXISTS "__EFMigrationsHistory"` (Postgres: `pg_type_typname_nsp_index`) on a cold start | Both instances created the history table at the same instant; the provider ignores it and the migration still runs once (ADR 0022). Not an error |
| Warning "No XML encryptor configured. Key … may be persisted to storage in unencrypted form" | Expected: DataProtection keys live unencrypted in Redis, shared by all instances (ADR 0023). The old "not persisted outside of the container" warning must no longer appear |
| `The Entity Framework tools version '10.0.5' is older than ...` | Harmless; `dotnet tool update -g dotnet-ef` |
| `failed to connect to the docker API` | Docker Desktop isn't running |
| A killed/stopped backend stays down despite `restart: unless-stopped` | Expected: a manual `docker kill` / `docker stop` disables the restart policy until the next manual start; the policy only covers a process that exits on its own. `docker compose start backend-1` |
| Requests take ~5 s; `GET /results` returns 503 "The cache is temporarily unavailable"; `warn: …ResultsCache` "not invalidated" in the logs | Redis is down. Expected (ADR 0027): the client waits its 5 s backlog timeout; reads 503, writes still succeed. `docker compose start redis` — recovers by itself, no backend restart |
| `Bind for 127.0.0.1:5433 failed: port is already allocated` on `up` | Another container or service holds the host port (on Participant 2's machine: `kafka-sandbox-db-1` from an unrelated project, auto-started by Docker Desktop). Put `POSTGRES_PORT=5434` in `.env` (gitignored) and `docker compose up -d` again — only host tools (psql, pgAdmin from the host) see the change; the backends talk to `postgres:5432` inside the network |
| First request after a DB restart fails | Should not happen (EF retry strategy, ADR 0008); if it does, check the retry config |
| `FATAL: sorry, too many clients already` (psql, Adminer, pgAdmin or the API) | The backend pools together exceed PostgreSQL `max_connections` (100). Check `DB_MAX_POOL_SIZE` × number of instances ≤ 97 (ADR 0018) |
| API requests take ~13–16 s and then return 503 while the DB is down | Expected: EF retries (ADR 0008) plus ~3.3 s Docker DNS lookups for the stopped `postgres` container. `/health` answers 503 within 2 s (ADR 0019) |
| `/health` says "PostgreSQL did not respond within the timeout" | The probe hit its 2 s timeout (`HealthChecks:DbTimeoutSeconds`) — typically the DB container is stopped (its DNS name no longer resolves). Start it; `/health` returns 200 within a second |
| `~$...docx` files appear in `docs/` | Word lock files while a document is open; ignored by `.gitignore` |

## Environment on Participant 2's machine

Windows 11, .NET SDK 10.0.202, Docker 28.5.1 (Docker Desktop does not start automatically here either — launch it
before `docker compose`), Git Bash, Python 3 **with `python-docx`** (so `.docx` files can be generated/read
directly, unlike on Participant 1's machine); no `pandoc`. Host port 5433 is taken here by a container of an
unrelated project, so a local `.env` sets `POSTGRES_PORT=5434` (from 2026-10-27); the default 5433 stays for the team
(ADR 0011).

## Environment on Participant 1's machine

Windows 10, .NET SDK 8.0 / 10.0.201 / 10.0.301, global `dotnet-ef` 10.0.5, Docker 29.3.1, Compose v5.1.1, Go, Node,
Python 3.13 (no `python-docx`, no `pandoc`, no `zip` in Git Bash), k6.
