# 2026-11-02 — Participant 1 — Lab 4: full re-verification from scratch, load check, requirement audit, П1-8 docs, П1-9 defense material
**Lab:** 4 · **Commits:** verification ran on `d20999a` + the then-uncommitted П1-10, committed by Participant 1 as
`314d5bc`; П1-8, П1-9 not committed

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
- П1-8: README «Архітектура з шаром кешу» (mermaid flowchart of the cache layer + sequence diagram: HIT, MISS via
  single-flight, BYPASS, invalidation by a vote; component → role → ADR table) and «Підсумок лаби 4» (requirement →
  what was done → evidence, the load table below, the from-scratch check, defense commands); RACI rows for lab 4;
  stack line. Root `CLAUDE.md`: quick start through HAProxy (no :8082), stack line (HAProxy instead of Nginx), the
  "no improvements ahead of the lab" rule now says lab 4 is done and points to lab 5, lab 4 task list in the map.
- П1-9: `docs/lab4-guide.md` (cheat sheet, defense script for the 4 procedure items, theory: stampede and the
  rejected alternatives, avalanche, LRU vs LFU with why `volatile-lru` suits generation keys, expiration vs
  invalidation, cache penetration; Q&A about our design; troubleshooting) and `docs/about/lab4.md` (requirement → done
  → evidence, simplified diagram, live demo). Linked from README (top and lab 4 intro) and the `CLAUDE.md` map. README
  summary row on eviction now says `volatile-lru` (ADR 0041 still lists both — the guide explains the choice).
- Dry run of the guide from a cold start (≈ 75 s of machine time) found two problems, fixed: the manual `redis-cli`
  commands of step 1 found nothing after the demo (its step 3 restarts Redis, which comes back empty) — reordered
  ("read first"); `redis-outage-check.py` failed its first check and `cache-demo.py` showed BYPASS instead of a cold
  MISS when started within ~2 s of a Redis restart (backends still reconnecting) — both now wait on poll #1 until four
  reads in a row are not BYPASS.
- Manual walkthrough as at the defense: `curl -i`, `redis-cli`, a vote, literally `docker stop polling-platform-redis-1`
  / `docker start`, the HAProxy log, Swagger.

## Decisions (link ADRs)
None — verification only.

## Problems & fixes
- Review of the new docs (GitHub-style render: marked + github-markdown-css + mermaid 10.9.1 at 1280 px, plus a
  table-column check and a fact check against code and measurements). Fixed:
  - README component flowchart was `LR` with three backends × duplicated edges: natural width ≈ 2500 px, i.e. text at
    ≈ 37 % on a GitHub-width page — redrawn `TB` with one "backend-N" block holding the cache layer (≈ 1350 px, ≈ 70 %);
    it now also shows that the single-flight load writes the entry (`SF → ResultsCache`). Sequence diagram: TTL "+ 0–20 %".
  - Guide: `cache-stampede-check.py` does not log in (only `cache-race-check.py` uses seed users 2…481);
    `docker compose up -d redis` does not recreate an unchanged container → `--force-recreate` (checked: the Redis
    image declares no volume, so a recreated container has no `dump.rdb`); "outside only the LB" was wrong — Redis,
    PostgreSQL and pgAdmin publish ports, only the API is LB-only; full port list in the prerequisites;
    `redis-outage-check.py` takes ≈ 6 s, not 10; which scripts read Redis directly and what each prints without it.
  - Lecturer page: vote latency during the outage "tens of ms (up to ~200)", the log excerpt marked as an example.
  - README: "smoke 25/25" referred to a scratch script that is not in the repo → "smoke test from the runbook".
- Rendering the mermaid diagrams from a local `file://` page did not run JS in the browser pane → served the scratch
  page over `python -m http.server` on 127.0.0.1: mermaid 10.9.1 rendered both diagrams (`ok 2 svg`).
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

П1-8: both mermaid diagrams render (mermaid 10.9.1 in the browser pane); relative links in README and `CLAUDE.md` —
none broken; smoke 25/25 after the edits.

Docs review: 56 tables in README / guide / lecturer page / task list — every row has the header's column count; 3
mermaid diagrams render without errors (natural widths 1350 / 1181 px + the sequence diagram); relative links and the
README anchor intact; smoke 25/25; after `--force-recreate` of Redis the backends reconnected by themselves (HIT).

П1-9: both scripts pass when started right after `docker stop` / `docker start` of Redis (2 × outage check, demo);
corrected step-1 commands return `g0` with TTL 9; the lecturer-page diagram renders (regrouped into a subgraph to
avoid duplicated edge labels); links incl. the README anchor intact; smoke 25/25.

Manual: MISS → HIT across instances, keys `polling:results:gen:1` + `polling:results:v1:1:g20` (TTL 9), vote → gen
21 → MISS → HIT; `docker stop` → BYPASS 200, `/health` 200 in 4 ms; `docker start` → MISS → HIT; LB log shows
`{MISS}` / `{HIT}` / `{BYPASS}`; Swagger 200.

## Not done / next steps
- PR `lab4/caching` → `main`, review by Participant 2; rehearsal by `docs/lab4-guide.md`; after the defense `labs/lab4-summary.md`.
