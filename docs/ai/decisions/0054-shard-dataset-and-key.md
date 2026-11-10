# 0054. Lab 7: shard the poll aggregate (polls, options, votes) by `poll_id`; `users` stays unsharded on Shard A
**Status:** Accepted · **Date:** 2026-11-09 · **Author:** Participant 2

## Context
Lab 7 (2.1) asks for a resource-heavy entity or aggregate to split horizontally and a justified shard key, including why a
blind surrogate key is a bad choice. The schema has four tables: `users`, `polls`, `options`, `votes`. With the seed (500
users, 50 polls) `votes` already holds ≈ 5.6k rows against 500 users, and lab 5 measured the write path as the bottleneck
(row-lock contention on the hot `options.vote_count`). Every endpoint except auth and the catalog addresses one poll by id.

Operations and how many shards each one touches under each candidate key (N = number of shards):

| Operation | `poll_id` | `user_id` | `votes.id` (surrogate) | `creator_id` |
|---|---|---|---|---|
| `POST /polls/{id}/vote` (insert + counter, one tx) | 1 | 1 for the vote, but the counter lives with the poll → 2 | vote on any shard, counter elsewhere, `UNIQUE (poll_id, user_id)` not enforceable | 1 |
| `GET /polls/{id}/results` | 1 | N | N | 1 |
| `GET /polls/{id}`, publish, close, delete | 1 | 1 (poll stored by creator) | 1 (poll by its own id) | 1 |
| `GET /polls/{id}/vote` (my vote) | 1 | 1 | N | 1 |
| `GET /polls` catalog, `?creatorId=` | N / N | N / N | N | N / **1** |
| register, login, `/me` | — (users) | — | — | — |

## Decision
- **Dataset:** the poll aggregate — `polls` with its `options` and `votes`. They are always read and written together by
  `poll_id`, and they are what grows and what takes the writes.
- **Shard key: `poll_id`.** Every hot operation (vote, results, details, my vote, lifecycle) goes to exactly one shard.
  `UNIQUE (poll_id, user_id)` and the "vote + counter" transaction stay local, so the lab 1 guarantees (one vote per
  user, no lost update on the counter) remain plain single-node ACID. Cardinality is high (one value per poll) and grows
  with the data. Only the catalog becomes a fan-out query (lab 7 2.4 needs one anyway).
- **Rejected:**
  - `votes.id` / any blind surrogate key: spreads one poll's votes over all shards — results become a fan-out on the
    hottest read, and "one vote per user" can no longer be one unique index (it would need a cross-shard check).
  - `user_id`: results become fan-out; the counter row still belongs to the poll, so a vote would touch two shards.
  - `creator_id`: low cardinality (20 authors in the seed) and a big author makes a hot shard; only "my polls" benefits.
- **`users` is not sharded.** Small, read by email at login, needs global `UNIQUE (email)` and `UNIQUE (username)` —
  sharding it by id would turn both into cross-shard checks. It stays on Shard A as an unsharded ("global") table.
- **Consequences in the schema** (implemented in stage 2):
  - FKs `polls.creator_id → users` and `votes.user_id → users` cannot cross nodes and are dropped; the API already takes
    the user id from the JWT, so integrity comes from the application.
  - The catalog's JOIN `polls → users` (author name) would be a distributed JOIN → `polls.creator_username` is copied at
    creation (usernames cannot change in this API).
  - Per-shard identity on `polls.id` would hand out the same id on every shard → ids come from one global sequence on
    Shard A, and the router needs the id before the insert anyway. `options.id` / `votes.id` stay per-shard identities:
    the API always qualifies an option by its poll, so they never meet across shards.
- **Hot key is out of scope of the key choice:** one viral poll is one key, and no hash spreads one key. Reads of it are
  already absorbed by the results cache (lab 4); writes stay a single-row contention problem (stage 3 discusses it).

## Consequences
- The router decides from `poll_id` alone; the catalog and "my polls" are the only fan-out reads.
- Shard A carries more than its share (users, the id sequence, auth traffic) — visible in the distribution matrix and
  accepted for a two-shard lab.
- An option id is unique only within its poll; clients that store bare option ids would break (the web UI does not).
