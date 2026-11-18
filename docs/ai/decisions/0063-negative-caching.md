# 0063. Lab 8: Negative Caching of missing polls in the results cache
**Status:** Accepted · **Date:** 2026-11-17 · **Author:** Participant 1

## Context
Lab 8 (2.6) asks to show Cache Penetration — a stream of requests to ids that do not exist (`GET /entity/9999999`),
each of which misses the cache and reaches the database — and to protect against it with Negative Caching or a Bloom
filter. Before this change `GET /api/polls/{id}/results` for a missing id cached nothing: every request missed Redis,
went through single-flight / lock and read the shard's Primary, then 404.

## Decision
- **Negative entry in the same value key**: `polling:results:v1:{id}:g{gen}` = `not-found` (not JSON, an aggregate
  always starts with `{`), TTL 30 s ± jitter (ADR 0062). The lookup script is unchanged (one round-trip); `GetAsync`
  returns `NotFound`, the service answers 404 without the DB. Waiters under the lock (ADR 0061) also see the entry and
  answer 404 instead of taking the lock and reading again.
- Only a **Primary** answer is cached as "not found", as with aggregates (ADR 0052): a replica may not have a poll
  that was just created.
- **Poll creation invalidates its id** (`PollService.CreateAsync` → `InvalidateAsync` after the insert). Ids come from
  the global sequence `poll_ids`, so the next poll's id is predictable and may already have a negative entry; the new
  generation makes it unreachable at once — the same generation argument as ADR 0041 (a reader that read the old
  generation before the insert committed may still write "not found" under it, nobody reads it). Delete already
  invalidated.
- Drafts are not "missing": an existing draft is cached as an aggregate with its `CreatorId`, and someone else gets
  404 from the visibility check (ADR 0003), the author 200.
- **Switch** `ResultsCache:NegativeCaching` (env `RESULTS_NEGATIVE_CACHING`, default true); false = the "before".
- **No Bloom filter** (agreed: by the assignment, "Negative Caching or Bloom filter"); its role and the cheaper
  alternative for our sequential ids (`id > last_value of poll_ids` is certainly missing) are theory for the defense.
- 404 still carries no `X-Cache` header: the exception handler clears the response (ADR 0005); the proof is the DB
  count, and a Debug log line `NEGATIVE HIT`.

## Consequences
Measured 2026-11-17, `load-tests/penetration.sh` (lab 8 stand, 200 VUs, 30 s, real aggregate, 0 % errors — 404 is the
expected answer):

| Stream | Negative caching | DB lookups / requests | RPS | p95 | p99 | Redis keys / memory added |
|---|---|---|---|---|---|---|
| 100 missing ids in a loop | off | 12 082 / 22 465 (53.8 %) | 744 | 545 ms | 861 ms | 0 |
| 100 missing ids in a loop | **on** | **171 / 44 131 (0.39 %)** | **1468** | **320 ms** | **550 ms** | +51 keys, +13 KiB |
| a new id on every request | off | 16 337 / 16 337 (100 %) | 540 | 835 ms | 1222 ms | 0 |
| a new id on every request | on | 14 054 / 14 054 (100 %) | 465 | 1108 ms | 1548 ms | +13 999 keys, +1.5 MiB |

- Without negative caching only about half of the stream reached the DB, not all of it: concurrent misses of the same
  id already share one lookup in single-flight / lock (the 404 is shared). With it the DB sees ≈ one lookup per id per
  TTL (100 ids × ~1.7 TTL periods ≈ 171), throughput doubles.
- `scripts/negative-cache-check.py`: 150 reads of 9999999 → 1 DB load, entry `not-found` with PTTL ≤ 36 s; the next
  sequence id read before creation → 404 + entry, after creation the author gets 200 at once; deleted draft → 404.
- **Limit — unique ids:** every id is new, so the negative cache never hits, the DB still gets 100 % and Redis grows by
  one key (~106 bytes) per request: memory ≈ rate of distinct missing ids × TTL (465 req/s × 30 s ≈ 14 k keys ≈
  1.5 MiB here; 10 k req/s would be ≈ 300 k keys ≈ 32 MiB). Redis has no `maxmemory` in compose, so only the TTL
  bounds it. The fixes are a Bloom filter / id-range check before the cache and rate limiting — not built.
