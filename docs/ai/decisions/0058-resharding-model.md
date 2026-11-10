# 0058. Lab 7: resharding model — modulo vs consistent hashing vs virtual buckets; buckets stay the default, migration described, not built
**Status:** Accepted · **Date:** 2026-11-10 · **Author:** Participant 2

## Context
Lab 7 (2.5) asks for a model of growing the cluster (2 → 3 or 4 shards), the problem of naive `key % N` (nearly all data
moves) and a justification of consistent hashing / virtual nodes (≈ 1/N moves). The router's default is `Buckets` (64
virtual buckets, ADR 0055).

## Decision
- **`scripts/resharding-model.py`:** on ids 1..K compares `key % N`, `hash % N`, a consistent-hash ring with 1 and with 100
  virtual nodes per shard, and 64 virtual buckets with a minimal-change bucket map (a new shard takes 64 / M buckets from
  the shards that have more). Prints the moved share for 2 → 3, 3 → 4, 2 → 4, 4 → 5 next to the ideal (M − N) / M, and the
  balance after 2 → 3. `--live` weights the real polls of both shards by their rows (poll + options + votes).
- **Buckets stay the default strategy:** moved share ≈ ideal, balance 1.04, and the key → bucket function never changes —
  only the table does, so resharding is a data move per bucket, not a rehash of everything. Easier to reason about and to
  operate than a ring (the table is explicit; a ring's ownership depends on every point).
- **No live migration in the lab:** the procedure (new shard → copy buckets → short write freeze and catch-up → switch the
  map on every instance → delete old rows) is documented; the bucket map would first have to be stored explicitly instead
  of being derived round robin from the shard count.

## Consequences
- Measured on 100 000 ids: `key % N` 66.7 / 75.0 / 50.0 / 80.0 % for 2 → 3 / 3 → 4 / 2 → 4 / 4 → 5 (= N / (N + 1) for
  N → N + 1); `hash % N` the same; ring with 1 vnode 63.6 / 2.1 / 65.6 / 40.3 % and 64 % of keys on one shard after 2 → 3;
  ring with 100 vnodes 36.4 / 25.2 / 49.9 / 18.8 %; buckets 32.6 / 24.9 / 50.1 / 18.6 % (ideal 33.3 / 25 / 50 / 20).
- Live (286 polls, 13 138 rows, 2 → 3): modulo would move 67.1 % of rows, buckets 36.3 %, ring with 100 vnodes 34.3 %.
- Report: `docs/lab7/resharding.md`.
