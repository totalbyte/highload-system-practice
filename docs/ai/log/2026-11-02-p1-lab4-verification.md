# 2026-11-02 — Participant 1 — Lab 4: full re-verification from scratch, load check, requirement audit
**Lab:** 4 · **Commits:** not committed (verified the working tree of `lab4/caching`: `d20999a` + uncommitted П1-10
single-flight and П1-7 records)

## Goal
Participant 1 asked to check the whole system again: start from zero, put it under load, run test operations and
compare the result with the lab 4 assignment point by point.

## Done
- Cold start: `docker compose --profile scale down -v` (no containers left) → `up -d --build` → `/health` 200 in 22 s;
  seed 500 users / 50 polls; Redis `save` empty; backends publish no ports, only the LB (8080 / 8404).
- All check scripts through a scratch runner (outputs kept outside the repo).
- A scratch load harness (4 phases × 15 s, 24 readers + 8 voters, keep-alive, through the LB) measuring read RPS,
  p50 / p95 / p99, the `X-Cache` split, DB loads behind the reads (distinct `generatedAt`), vote RPS, errors and max
  active Postgres sessions.
- Single-flight on 3 instances (`--profile scale`), then backend-3 removed again.
- Manual walkthrough as at the defense: `curl -i`, `redis-cli`, a vote, literally `docker stop polling-platform-redis-1`
  / `docker start`, the HAProxy log, Swagger.

## Decisions (link ADRs)
None — verification only.

## Problems & fixes
- The scratch runner started `bash` from Python, which on Windows resolved to WSL bash → `cross-instance.sh` "failed"
  in 0.2 s. Not a project issue: run directly in Git Bash it passed 8/8.

## Verified (how)
| Check | Result |
|---|---|
| smoke (runbook + cache keys / TTL) | 25/25 |
| `cross-instance.sh` | 8/8 |
| `concurrency-checks.py` | ALL PASSED |
| `cache-demo.py` | rc 0 (5 MISS / 6 HIT / 7 BYPASS) |
| `cache-latency.py` | MISS p50 3.92 / p99 8.67 ms, HIT p50 2.02 / p99 4.28 ms |
| `cache-race-check.py` | 0 of 60 (and 0 of 30 on 3 instances) |
| `cache-stampede-check.py` | 2.0 DB loads per invalidation on 2 instances, 3.1 on 3 |
| `redis-outage-check.py` | ALL PASSED |
| `kill-test.py` | ALL PASSED |
| `lb-failover.py --kill` | 0 non-2xx of 16 354 |

Load (same machine as the stack, Python client — compare phases, not absolute numbers):

| Phase | Read RPS | p50 / p95 / p99 ms | X-Cache | DB loads/s | Votes/s | Errors | Max PG active |
|---|---|---|---|---|---|---|---|
| read, cache on | 2730 | 8.1 / 16.2 / 21.5 | HIT 100 % | 0 | — | 0 | 0 |
| mixed, cache on | 1769 | 11.7 / 28.4 / 43.7 | HIT 47 %, MISS 53 % | 209 | 116 | 0 | 3 |
| read, Redis down | 1355 | 15.0 / 38.8 / 57.5 | BYPASS 100 % | 1355 | — | 0 | 12 |
| mixed, Redis down | 1323 | 16.4 / 35.3 / 47.9 | BYPASS 100 % | 1323 | 102 | 0 | 18 |

After the run: per-option counters = votes rows, results through the API = DB. Reading: with the cache the DB sees no
read at all; under voting ≈ 930 misses/s collapse into 209 DB loads/s (≈ 2 per vote = one per instance,
single-flight); without Redis every read is a DB query, read throughput halves and p95 grows ×2.4.

Manual: MISS → HIT across instances, keys `polling:results:gen:1` + `polling:results:v1:1:g20` (TTL 9), vote → gen
21 → MISS → HIT; `docker stop` → BYPASS 200, `/health` 200 in 4 ms; `docker start` → MISS → HIT; LB log shows
`{MISS}` / `{HIT}` / `{BYPASS}`; Swagger 200.

## Not done / next steps
- §3 gaps (П1-8): README «Архітектура з шаром кешу» and «Підсумок лаби 4» are still placeholders; RACI rows for lab 4.
- П1-9: `docs/lab4-guide.md`, `docs/about/lab4.md` (theory, defense script).
- Root `CLAUDE.md` is stale: quick start still lists `backend-2` on :8082 (gone since lab 3) and the rule says key
  schema / TTL / `X-Cache` / fallback "still wait for lab 4" — update in П1-8.
- Candidate for README in П1-8: the load table above (cost of degradation, single-flight effect under load).
