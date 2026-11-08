# Runbook: running, testing, troubleshooting

## Run with Docker (normal way)

Docker Desktop must be running (on Participant 1's machine it does not start automatically).

```bash
docker compose up -d --build          # lb (HAProxy) + backend-1 + backend-2 + postgres + postgres-replica + redis; migrations + seed on backend startup
docker compose --profile scale up -d  # + backend-3; HAProxy picks it up by itself (~9 s), no lb restart
docker compose logs -f backend-1 backend-2
docker compose logs -f lb             # HAProxy: one line per request with the server that served it, status, timers
docker compose kill -s USR2 lb        # reload haproxy/haproxy.cfg after editing it (no rebuild, no restart, ~0.4 s)
docker compose restart postgres       # data survives (named volume pgdata)
docker compose down -v                # wipe everything, including data → next `up` is a cold start
docker compose --profile tools up -d  # + Adminer on :8081 (pgAdmin 4 on :5050 starts with the normal `up`)
```

| What | Address |
|---|---|
| API through the load balancer (HAProxy) | http://localhost:8080 (`LB_PORT`); instances alternate, see `X-Instance-ID` |
| HAProxy statistics (per-server state, requests, response times) | http://localhost:8404/stats (`LB_STATS_PORT`); CSV: `/stats;csv` |
| Swagger UI | http://localhost:8080/swagger (spec: `/swagger/v1/swagger.json`) |
| Health | http://localhost:8080/health (answered by whichever instance the balancer picks) |
| A backend instance directly | not exposed (lab 3, ADR 0031); `docker compose exec`/logs only |
| Postgres from the host | Primary `localhost:5433`, Replica `localhost:5435` (`POSTGRES_REPLICA_PORT`, read-only), db/user/password `polling` (container-internal port is 5432) |
| Redis | `localhost:6379` (`REDIS_PORT`); `docker compose exec redis redis-cli` |
| Adminer | http://localhost:8081 (server `postgres`) |
| pgAdmin 4 | http://localhost:5050 — no login (desktop mode); server "polling (docker)" is pre-registered from the inline `configs.pgadmin_servers` in `docker-compose.yml`; enter DB password `polling` once and tick "Save password". Starts in ~40 s (ADR 0020) |

All settings have defaults in `docker-compose.yml`; override them via `.env` (see `.env.example`). `DB_MAX_POOL_SIZE`
(default 30) caps the Npgsql pool of one backend instance — keep *instances × pool ≤ 90* (ADR 0018, 0032); two
instances use at most 60, three 90 (verified under load). For 4+ instances set `DB_MAX_POOL_SIZE` = floor(90 / N) in
`.env` (4 → 22) instead of raising `max_connections`. The app role `polling` is a superuser, so PostgreSQL's 3 reserved
slots do not protect psql/pgAdmin from the backends — the 10 spare slots do. All instances are built from one image
and differ only in `INSTANCE_ID` (ADR 0021); they publish no host ports — only `lb` does (ADR 0031). Cold start from `down -v` to the first 200 through the balancer
took 25 s including the (cached) image build on 2026-10-28; until the backends listen, HAProxy answers its own 503.

**Lab 2 tools vs the balancer:** `scripts/cross-instance.sh` and `requests/cross-instance.http` go through the
balancer since П1-5 (both addresses default to :8080; HAProxy picks the instance). Participant 2's Python scripts still
default to `backend-2` on :8082 until П2-7. Direct access to one instance, for debugging or the historical lab 2
"before" demo, only with the debug overlay (ports bound to `127.0.0.1`):

```bash
docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d   # + backend-1 :8091, backend-2 :8092 (backend-3 :8093)
I1=http://localhost:8091 I2=http://localhost:8092 bash scripts/cross-instance.sh
docker compose up -d                                                     # back to the standard stack, ports gone
```

## Web UI (ADR 0048)

The standard `docker compose up -d --build` also builds `web` (React + Vite build served by nginx); open
http://localhost:8080 — pages from `web`, `/api` from the backends through the same HAProxy. Log in with a seed user
(`user001@example.com` / `Password123!`). The poll page shows which backend answered the results read and its
`X-Cache` (HIT / MISS / BYPASS) — handy at lab 3–4 demos. Favorites live in the browser's localStorage only.

Frontend development with hot reload (needs Node 20.19+; the Docker stack must be up for the API):

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api and /health to :8080 (API_URL to override)
npm run build                               # type-check + production build into frontend/dist
docker compose up -d --build web            # rebuild only the web container after changes
```

## Load balancer (lab 3)

Config `haproxy/haproxy.cfg` (ADR 0031, 0033, 0034). Health checks: `GET /health` every 2 s (`fastinter 500ms` while a
node changes state), `fall 2` / `rise 2`, `timeout check 3s`; passive `observe layer4` takes a node out on the first
connection error; `retries 2` + `option redispatch 1`; in-flight GETs are retried (`retry-on conn-failure
empty-response`), other methods only on connection failure. No layer-7 observation and no retries on 5xx (the API's
honest 503 would take the whole pool out).

```bash
bash scripts/lb-algorithm.sh                  # current algorithm and weights
bash scripts/lb-algorithm.sh leastconn        # roundrobin | leastconn | weighted (3:1 on backend-1) | source
python scripts/lb-distribution.py             # 300 GET /health → split by X-Instance-ID next to the stats-page counters
python scripts/lb-failover.py [--kill]        # GET stream; stop/kill backend-2 at 3 s, start at 10 s; 5xx, detection, return
```

`lb-algorithm.sh` edits `haproxy/haproxy.cfg`, validates it with `haproxy -c` inside the `lb` container (restores the
file on failure), then reloads with SIGUSR2 — no rebuild, no container restart, 0 client errors (checked under
`load.py`). It changes a tracked file: run `bash scripts/lb-algorithm.sh roundrobin` after a demo. Expected (2026-10-28,
two instances): RR 50/50, leastconn ≈ 50/50 for sequential requests, weighted 75/25, source 0/100 (all host traffic
comes from one Docker gateway address). `lb-failover.py`: 0 non-2xx in 4 runs (2 × stop, 2 × kill), node out after
0.3–0.5 s, back ~6–8 s after `start` (mostly ASP.NET startup).

After a reload the stats page shows `UP 1/3`-style states until the new worker's first check (≤ 2 s) — cosmetic.

## Replication (lab 6)

`postgres` is the Primary, `postgres-replica` a read-only asynchronous streaming replica (ADR 0049). The replica makes
its own `pg_basebackup` on an empty volume, so a normal `up` needs no manual steps. **A volume created before lab 6 needs
`docker compose down -v` once** (the role and the slot are created only on an empty data directory).

```bash
python scripts/replication-check.py [--pause]   # topology, seed on both nodes, INSERT / UPDATE / DELETE reach the replica, writes rejected; exit code 0 = passed
docker compose exec -T postgres psql -U polling -d polling -c "SELECT state, sync_state, sent_lsn, replay_lsn, replay_lag FROM pg_stat_replication"
docker compose exec -T postgres psql -U polling -d polling -c "SELECT slot_name, active, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes FROM pg_replication_slots"
docker compose exec -T postgres-replica psql -U polling -d polling -c "SELECT pg_is_in_recovery(), pg_last_wal_replay_lsn()"
```

Expected (2026-11-08): one row `streaming | async`, slot `replica_1` active, `replay_lag` ≈ 12 ms on an idle stack (it is
empty when nothing was written recently). After `docker compose restart postgres` the replica reconnects in ≈ 2 s; after
`stop` / `start` of the replica it catches up through the slot without a new base backup.

**Read/write routing (ADR 0050):** `python scripts/rw-routing-check.py [--pause] [--reads 300]` checks every operation against
its expected node by `X-DB-Node`, then compares PostgreSQL's own transaction counters during catalog reads (measured: replica
≈ 4 per read, primary only background; the script waits 11 s because idle sessions publish statistics with a delay of up to 10 s). `curl -si localhost:8080/api/polls/1 | grep -i x-db-node` → `replica`; results: MISS →
`primary`, HIT → no header. All reads on the Primary (Single Primary): `READ_REPLICA_ENABLED=false docker compose up -d
backend-1 backend-2`; the same command without the variable switches back. Until stage 4 a stopped replica fails catalog
and details reads with 503 after ≈ 10 s. `dotnet run` has no replica connection string and uses only the Primary.

**Stale Read and Read-After-Write (ADR 0051):** `python scripts/stale-read-demo.py [--pause] [--lag 3]` (≈ 1 min, restores the
lag and the backends in `finally`). Expected: anonymous reader 404 from the replica, author 200 from the Primary on both
instances, then the same without protection and with lag over the TTL; `ALL PASSED`. By hand:
`docker compose exec -T postgres-replica psql -U polling -d polling -c "ALTER SYSTEM SET recovery_min_apply_delay = '3s'"`, then
`-c "SELECT pg_reload_conf()"` as a separate call (`ALTER SYSTEM` cannot share a transaction); back: `ALTER SYSTEM RESET
recovery_min_apply_delay` and reload. **Always reset it**: with the delay left on, any later check of fresh data fails. Under
artificial lag `cross-instance.sh` shows 7 of 8: step 5 reads anonymously, so its stale 404 is correct. Sticky state:
`docker compose exec redis redis-cli PTTL polling:sticky:<userId>`.

To verify a cold start without wiping the local data, use a separate project: `COMPOSE_PROJECT_NAME=polling-lab6 docker
compose up -d --build` (the scripts call `docker compose`, so they follow the variable); remove it with the same variable
and `down -v`. The default project's containers must be stopped first: the host ports are the same.

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
since lab 4 (ADR 0041) `docker compose exec redis redis-cli GET polling:results:gen:1` → the generation `n`, then
`TTL polling:results:v1:1:g<n>` → ≤ 12 after a read of an active poll (≤ 4320 for a closed one); after a vote the
generation is `n + 1` and `g<n>` is gone.

**Invalidation race (lab 4, П1-3, ADR 0041):** `python scripts/cache-race-check.py [--rounds 60] [--burst 8]
[--readers 12]` (stdlib only, via the LB, ~25 s, fresh poll each run, uses seed users 2…481). Each round: 8
simultaneous votes for one option while 12 readers poll the results; then a control read must show exactly the
committed number of votes. Expected: `0 of 60`, exit code 0. With the lab 2 `DEL` invalidation it found 2–5 stale
rounds of 60 in every run.

**Cache demo for the defense (lab 4, П1-6):** `python scripts/cache-demo.py [--pause]` (via the LB, ~15 s, stdlib
only; reads Redis state directly on `localhost:6379`, env `REDIS`). Runs the three procedure items in a row: MISS →
HIT → HIT; vote → generation +1 → MISS with the new count → HIT; close → MISS `closed` with TTL ≈ 1 h; then
`docker compose stop redis` → BYPASS 200, a vote 201 visible on the next read, `/health` 200; `start redis` → a few
BYPASS reads while the client reconnects (~2.5 s), then MISS (`gen=0`, Redis empty) → HIT. It always starts Redis
again in `finally`. `--pause` waits for Enter before each step.

**Cache stampede (lab 4, П1-10, ADR 0044):** `python scripts/cache-stampede-check.py [--poll 1] [--readers 100]
[--rounds 20]` (~5 s). Each round: `INCR` of the poll's generation in Redis, then 100 simultaneous reads through the LB
(connections opened beforehand); DB loads = distinct `generatedAt` in the answers. Expected with single-flight ≈ one per
instance (2.1–2.4 on 2 instances, max 3), exit code 0; without it it was 6.7–14.4 on average, up to 98 of 100.

**Cold vs hot latency (lab 4, П1-6):** `python scripts/cache-latency.py [--poll 1] [--pairs 500] [--warmup 50]`
(~10 s). Each pair: `INCR polling:results:gen:<poll>` straight into Redis (= an invalidation), then a read that must be
`MISS` and one that must be `HIT`; one keep-alive connection through the LB. Measured 2026-11-02 on poll #1, idle
stack, 3 runs: MISS p50 ≈ 3.8 ms / p99 6.5–8.2 ms, HIT p50 ≈ 2.0 ms / p99 ≈ 3.7 ms (× 1.9). Numbers several times
higher usually mean the stack is still warming up or another load is running.

**Cache source (lab 4, П1-4, ADR 0042):** `curl -si localhost:8080/api/polls/1/results | grep -i x-cache` → `MISS`
on the first read after a cold start or a mutation, `HIT` after that. The LB log shows it for every request:
`docker compose logs lb | grep results` → `... be_api/backend-2 0/0/0/5/5 200 ... {HIT} "GET /api/polls/1/results ..."`.
Per-operation backend logs (`HIT` / `MISS` / `STORE` with TTL / `INVALIDATE n -> n+1`) are at Debug:
`CACHE_LOG_LEVEL=Debug docker compose up -d` (recreates the backends), then `docker compose logs -f backend-1 backend-2
| grep "Results cache"`; plain `docker compose up -d` switches them off again.

**Instance loss through the balancer (lab 2 П2-7 → lab 3 П2-4, ADR 0037):** `python scripts/kill-test.py` (from the
repo root; `--stop` for a graceful stop instead of SIGKILL). 800 votes (400 users × 2 fresh polls, 32 threads) go to
the balancer (`API`, default `http://127.0.0.1:8080`); after 10 % it runs `docker compose kill backend-1`. The client
does not know the instances: any 5xx or broken connection counts as an error the user would see; after an error it
retries the same vote once (201, or 409 if the first attempt had committed). Prints who answered (`X-Instance-ID`),
the errors with their timing, how long until HAProxy marked backend-1 DOWN in `be_vote` and in `be_api` (stats CSV on
`LB_STATS`, default `http://127.0.0.1:8404/stats;csv`), and what PostgreSQL saw. Checks: **no client errors**, every
vote 201 / 409-on-retry, vote rows = users, per-option counters, results through the balancer = DB; then `docker
compose start backend-1`, back UP in HAProxy and serving the same results. A 409 as the first answer is fine — HAProxy
retried a vote that had committed on the killed node. Expected (2026-10-28, 6 kill + 1 stop runs after a cold start):
0 client errors, DOWN in `be_vote` after ≈ 1 s, back UP after 4–5 s, ≈ 6.5 s per run. Before `be_vote` the same
run gave 6 × 502 (П1-3 config) or 52 errors (П1-1 config) — see README «Відмова вузла: запис». Always starts
backend-1 again in `finally`. Uses `127.0.0.1`: on Windows a refused connection to `localhost` takes ~4 s.

**Redis outage (lab 2 П2-4 → lab 4 П1-5, ADR 0043):** `python scripts/redis-outage-check.py` (from the repo root; it
runs `docker compose stop/start redis` itself and always starts Redis again in `finally`). Both `API1` / `API2` default
to the balancer. It first waits until the cache is reachable on both instances (right after a Redis restart the
backends reconnect for ~2 s and serve `BYPASS`; `cache-demo.py` does the same). Expected since lab 4: with Redis down results **200 with `X-Cache: BYPASS` in well under 1 s** (read
from PostgreSQL; lab 2 answered 503 after ~5 s), vote 201 stored once and visible on the next read, publish 200 and the
poll visible to others, `/health` 200 (both nodes stay UP), counters consistent; after start — the first read is
**MISS** (Redis came back empty: it runs with `--save ""`), fresh, no backend restart. ~10 s per run. A **HIT** with
an old `totalVotes` after the restart means Redis loaded a `dump.rdb` — check `redis-cli CONFIG GET save` (must be
empty).
`concurrency-checks.py` also defaults both addresses to the balancer (HAProxy splits the requests);
`results-cache-demo.py` needs direct instance access — run it with `docker-compose.debug.yml` and
`API1=http://127.0.0.1:8091 API2=http://127.0.0.1:8092`.

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
One generator process tops out at ≈ 1.8k rps for `read`; to load the system harder run several in parallel
(`for k in 1 2 3; do python scripts/load.py ... & done; wait`) and add up their rps — three gave ≈ 4.8k.

**Scale-out runs (lab 3, П2-5):** containers have no CPU limits, so on one machine a second instance adds no
hardware — one `backend-1` alone served ≈ 5k cached reads/s on 5.6 of 24 cores, and 1 / 2 / 3 instances gave the same
rps. To model "one instance = one server" put `cpus: 1.0` on every backend in the local
`docker-compose.override.yml` (same file as the slow instance; delete it afterwards) and `docker compose --profile
scale up -d`. Measure from the second run — the first one after a restart includes the JIT warm-up. Results and the
bottleneck analysis: README «Scale-out» / «Наступний bottleneck». During write runs, what the DB waits on:
`docker compose exec -T postgres psql -U polling -d polling -tAc "SELECT coalesce(wait_event_type,'cpu') || '=' ||
count(*) FROM pg_stat_activity WHERE state = 'active' AND backend_type = 'client backend' AND pid <> pg_backend_pid()
GROUP BY wait_event_type"` (`Lock=26` of ≈ 30 = row-lock queue on the hot `vote_count` rows).

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

## Load testing (lab 5)

Details and file list: `load-tests/README.md`. k6 runs in Docker inside `app-network` (no local k6 needed), on its own
cores; the stack must be started **with the overlay** so the limits apply (ADR 0045).

```bash
export MSYS_NO_PATHCONV=1
C="-f docker-compose.yml -f load-tests/docker-compose.loadtest.yml"
docker compose down -v && docker compose $C up -d --build      # fresh stack, limits + cpusets
bash load-tests/run.sh scenario-a-read mytag                  # one scenario + resources; LEVELS=10,50 STEP=20 to shorten
python load-tests/report.py load-tests/results/scenario-a-read-mytag-*.json
bash load-tests/series.sh                                     # the whole series, ≈ 55 min, fresh stack per run (ADR 0047)
```

- Run every measured scenario on a **fresh stack** — scenario C creates thousands of polls and B hundreds of thousands
  of hot-row updates per run; the next run would measure a different database.
- Cache off for a comparison: `RESULTS_CACHE_ENABLED=false docker compose $C up -d backend-1 backend-2` →
  `X-Cache: DISABLED`; back: the same command without the variable.
- Absolute numbers depend on what else the host is doing (≈ 2× between a night and a morning series) — compare runs of
  one series only. Raw results: `load-tests/results/` (gitignored).
- Git Bash: keep `MSYS_NO_PATHCONV=1`, otherwise `/scripts/...` paths inside the k6 container get rewritten.

## Troubleshooting / known quirks

| Symptom | Cause / fix |
|---|---|
| Cyrillic becomes `????` when sent with curl from Git Bash on Windows | Shell encoding, not the server. Use Swagger, `.http`, Postman, or `curl --data-binary @file.json` with a UTF-8 file |
| Every request returns 400 when the token comes from a file written by Python on Windows | Python writes CRLF; the `\r` inside the `Authorization` header breaks the request. Pipe tokens through `tr -d '\r'` |
| `GET /results` still shows an old total | The cache (Redis, shared by all instances, ADR 0026) is invalidated by a vote, publish, close or delete, with a TTL by status as a safety net (ADR 0041). Since lab 4 invalidation bumps a generation, so a read that started after the vote's response always sees it; `scripts/cache-race-check.py` must report `0 of 60`. A stale value up to ≈ 12 s is possible only if Redis failed during the invalidation (ADR 0027). If instances disagree, run `scripts/results-cache-demo.py`: a **YES** means something went back to a per-process cache |
| `postgres-replica` keeps restarting; its log has `pg_basebackup: error` about `pg_hba.conf`, the role or the slot | The Primary's volume was created before lab 6, so `primary-init.sh` never ran. `docker compose down -v` once (ADR 0049); the rest of the stack works meanwhile |
| Replica log: `requested WAL segment ... has already been removed` / the slot's `wal_status` is `lost` | The replica was down longer than `max_slot_wal_keep_size` (1 GB) allows and needs a new base backup: `docker compose down -v` (ADR 0049) |
| Can't reach the container DB on 5432 / connected to the wrong DB | Participant 1's machine runs a local Windows PostgreSQL service on 5432 — the container is on **5433** (ADR 0011) |
| `fail: ... SELECT migration_id FROM "__EFMigrationsHistory"` on first start | Expected: the history table doesn't exist yet. Not an error |
| `fail: ... CREATE TABLE IF NOT EXISTS "__EFMigrationsHistory"` (Postgres: `pg_type_typname_nsp_index`) on a cold start | Both instances created the history table at the same instant; the provider ignores it and the migration still runs once (ADR 0022). Not an error |
| Warning "No XML encryptor configured. Key … may be persisted to storage in unencrypted form" | Expected: DataProtection keys live unencrypted in Redis, shared by all instances (ADR 0023). The old "not persisted outside of the container" warning must no longer appear |
| `The Entity Framework tools version '10.0.5' is older than ...` | Harmless; `dotnet tool update -g dotnet-ef` |
| `failed to connect to the docker API` | Docker Desktop isn't running |
| `503 Service Unavailable` HTML page from HAProxy right after `up`; `backend 'be_api' has no server available!` in `docker compose logs lb` | The backends are still applying migrations / seeding and not listening yet. Wait a few seconds (the stats page shows them DOWN → UP) |
| `curl localhost:8082` → connection refused | Expected since lab 3: backends publish no ports; use the balancer on 8080 (ADR 0031) |
| A request takes ~1 s instead of ~20 ms right after a backend was stopped / killed | Expected (ADR 0033): it hit the dead node and was retried on another one (`+1` in the retries field of the `lb` log line). The node is out of the pool within ~0.5 s |
| `git status` shows `haproxy/haproxy.cfg` modified after a demo | `scripts/lb-algorithm.sh` edits it: `bash scripts/lb-algorithm.sh roundrobin` (or `git checkout haproxy/haproxy.cfg` + `docker compose kill -s USR2 lb`) |
| `backend-3` stays `MAINT (resolution)` on the stats page | It is not running (profile `scale`): `docker compose --profile scale up -d` |
| A killed/stopped backend stays down despite `restart: unless-stopped` | Expected: a manual `docker kill` / `docker stop` disables the restart policy until the next manual start; the policy only covers a process that exits on its own. `docker compose start backend-1` |
| `X-Cache: BYPASS` on `GET /results`; `warn: …ResultsCache` "not invalidated" in the logs | Redis is down. Expected (ADR 0043): reads go straight to PostgreSQL (200, no Redis timeout wait), writes still succeed. `docker compose start redis` — recovers by itself, no backend restart. Requests taking ~1 s each instead means Redis is reachable but not answering (hung / paused): the 1 s client timeout, then the same fallback |
| `Bind for 127.0.0.1:5433 failed: port is already allocated` on `up` | Another container or service holds the host port (on Participant 2's machine: `kafka-sandbox-db-1` from an unrelated project, auto-started by Docker Desktop). Put `POSTGRES_PORT=5434` in `.env` (gitignored) and `docker compose up -d` again — only host tools (psql, pgAdmin from the host) see the change; the backends talk to `postgres:5432` inside the network |
| First request after a DB restart fails | Should not happen (EF retry strategy, ADR 0008); if it does, check the retry config |
| `FATAL: sorry, too many clients already` (psql, Adminer, pgAdmin or the API) | The backend pools together exceed PostgreSQL `max_connections` (100). Check `DB_MAX_POOL_SIZE` × number of instances ≤ 90 (ADR 0018, 0032); with 4+ instances lower `DB_MAX_POOL_SIZE` in `.env` |
| How many connections each instance holds | `docker compose exec -T postgres psql -U polling -d polling -tAc "SELECT client_addr, count(*) FROM pg_stat_activity WHERE client_addr IS NOT NULL GROUP BY 1"` — one row per backend container, ≤ `DB_MAX_POOL_SIZE` each |
| API requests take ~13–19 s and then return 503 while the DB is down | Expected for the first ~4.6 s: EF retries (ADR 0008) plus ~3.3 s Docker DNS lookups for the stopped `postgres` container. `/health` answers 503 within 2 s (ADR 0019) |
| `503 text/html` "No server is available to handle this request" from HAProxy while the DB is down | Expected (ADR 0033): every `/health` is 503, so ~4.6 s after the DB goes down the whole pool is out and HAProxy answers in ~3 ms instead of the API's 503 ProblemDetails. Back ~2.3 s after `docker compose start postgres` |
| `/health` says "PostgreSQL did not respond within the timeout" | The probe hit its 2 s timeout (`HealthChecks:DbTimeoutSeconds`) — typically the DB container is stopped (its DNS name no longer resolves). Start it; `/health` returns 200 within a second |
| `~$...docx` files appear in `docs/` | Word lock files while a document is open; ignored by `.gitignore` |

## Environment on Participant 2's machine

Windows 11, .NET SDK 10.0.202, Docker 28.5.1 (Docker Desktop does not start automatically here either — launch it
before `docker compose`), Git Bash, Python 3 **with `python-docx`** (so `.docx` files can be generated/read
directly, unlike on Participant 1's machine); no `pandoc`. Host port 5433 is taken here by a container of an
unrelated project, so a local `.env` sets `POSTGRES_PORT=5434` (from 2026-10-27); the default 5433 stays for the team
(ADR 0011).

## Environment on Participant 1's machine

Windows 10, i5-9300H (4 cores / 8 threads), 16 GB RAM; Docker Desktop's VM sees 8 CPUs and 7.7 GB, so the 24-core cpuset
layout of `load-tests/docker-compose.loadtest.yml` (lab 5, measured on Participant 2's machine) does not fit here.
.NET SDK 8.0 / 10.0.201 / 10.0.401, global `dotnet-ef` 10.0.5, Docker 29.3.1, Compose v5.1.1, Go, Node, Python 3.13 (no
`python-docx`, no `pandoc`, no `zip` in Git Bash), k6.
