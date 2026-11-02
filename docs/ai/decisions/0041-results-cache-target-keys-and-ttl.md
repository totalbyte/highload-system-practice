# 0041. Lab 4: cache only `GET /results`; generation-based keys; TTL by poll status with jitter
**Status:** Accepted (amends 0026; implemented in lab 4 П1-3) · **Date:** 2026-11-02 · **Author:** Participant 1

## Context
Since lab 2 `GET /api/polls/{id}/results` is cached in Redis (ADR 0026): key `results:{pollId}`, TTL 10 s, `DEL` on
vote / publish / close / delete. Lab 4 asks to justify what is cached (2.1), to design a collision-free key schema and
a TTL policy (2.4), and that **the next read after a mutation is guaranteed fresh** (2.5). Two things in the lab 2
design fall short:

- **The invalidation race (ADR 0026, accepted gap).** Reader R misses, reads the aggregate from PostgreSQL *before* a
  vote commits; the vote commits and `DEL`s the key; R then `SET`s its pre-vote aggregate. Every later read hits that
  stale entry for up to the TTL, although the voter already got 201.
- **The TTL is one number with no rationale**, the same for a poll that is still being voted on and for a closed one
  whose results can never change.

### Which endpoint to cache (2.1)

| Endpoint | Reads vs writes | Acceptable staleness | Cost without cache | Key variants / invalidation points | Verdict |
|---|---|---|---|---|---|
| `GET /polls/{id}/results` | Highest read rate in the system: every dashboard viewer polls it every 1–2 s, thousands per hot poll; writes = votes to that poll | Seconds are fine for a live dashboard; the voter's own read must see the vote | One query (poll + ≤ 20 options by PK) and an in-app sum — cheap per request, but it takes a pool connection while vote transactions queue on row locks (bottlenecks №2, №3) | One per poll (visibility is checked after the read, `CreatorId` is in the entry); 4 mutation points, all in our code | **Cache** |
| `GET /polls/{id}` | Roughly once per voter (open the page, then vote); changes only on publish / close | Status must flip promptly (the vote button) | Poll + creator + options join, similar cost | One per poll; publish / close | Not now: not on the high-load path (`POST /vote` reads the poll itself, not this endpoint). Candidate if lab 5 profiling shows it |
| `GET /polls?status=&creatorId=&page=&pageSize=` | Moderate: browsing the catalog, not the peak scenario (voters of a hot poll come by a direct link) | Tens of seconds are fine — a new poll may appear in the catalog a little later | Heavier than results: `COUNT(*)` grows with the number of polls, plus a page with a `users` join and an option count | The public view changes **only on publish / close** (create makes a draft, only drafts can be deleted, nothing is editable), so one generation counter could invalidate every page; keys need a params hash (status, creatorId, page, pageSize). **But visibility is per caller:** an author also sees own drafts and unlisted polls, so a shared entry fits only anonymous callers, or needs an extra DB query to prove the caller has none | **No** — not on the high-load path, and a shared entry would serve only part of the traffic. Candidate if lab 5 shows the catalog in the profile: cache the anonymous view, key `polling:polls:list:v1:g{gen}:{params_hash}`, TTL ≈ 30 s, `INCR` on publish / close |
| `GET /auth/me` | Once per session | — | PK lookup | Per user | **No** — trivial query, per-user data |
| `POST /auth/login` | Write-like (credential check) | — | Deliberately CPU-heavy PBKDF2 | — | **No** — caching credential checks is a security hole |
| `POST /vote`, `POST/PATCH/DELETE /polls` | Writes | — | — | — | **No** — mutations; they *invalidate* |
| Reads inside `POST /vote` (poll status and dates, the option belongs to the poll) | Thousands of identical reads of one poll during the peak; the data changes only on publish / close | **None** for the status: a stale `active` admits a vote into a closed poll — a broken business rule, not an old number | Two PK lookups, fractions of a millisecond | One per poll; publish / close | **No** — the vote's bottleneck is the row lock on `vote_count` (lab 3 П2-6: 26–29 of ≈ 30 sessions in `Lock`), not these reads: risk without gain. Keeping the counter itself in Redis (write-behind) would attack the lock, but makes Redis the source of truth — a different pattern, out of scope |
| `/health` | LB probe every 2 s | None — it must reflect the live DB state | `SELECT 1` | — | **Never** |

## Decision

### Keys
- **Value:** `polling:results:v1:{pollId}:g{generation}` — JSON of `CachedPollResults` (format unchanged since ADR 0026).
- **Generation counter:** `polling:results:gen:{pollId}` — integer, missing = 0, **no TTL**.
- Segments follow `domain:entity:format:id:state`: `polling` (application; Redis also holds `DataProtection-Keys`,
  ADR 0023), `results` (entity), `v1` (value format — bump it when `CachedPollResults` changes shape, so instances of
  different versions during a rolling deploy never deserialize each other's JSON; old entries just expire),
  `{pollId}`, `g{generation}`. All variable segments are integers between fixed literals, so keys cannot collide.
- **No `params_hash`:** the response depends on nothing but the poll id — no query parameters, and it is the same for
  every caller (draft visibility is decided after the read from `CreatorId` in the entry, ADR 0015). If the endpoint
  ever gets parameters, they become a hash segment after `{pollId}`.
- The old `results:{pollId}` keys are not read any more; at most one per poll survives an upgrade, for ≤ 10 s.

### Invalidation by generation (fixes the race)
- **Invalidate** (after the DB commit, at the same four call sites): atomically `INCR` the counter and `UNLINK` the
  previous generation's value (Lua script). The new generation has no value yet → the next read misses.
- **Read:** get the counter and the value of that generation in one round-trip (Lua script).
- **Miss:** read the aggregate from PostgreSQL, then `SET … EX` it under the generation **read before the DB query**,
  not the current one.
- Why this closes the race: a mutation commits at C and increments at I > C, then answers the client. A reader that
  read the generation before I writes under the old generation, which no later read looks at. A reader that read it
  after I queries the DB after C, so its data already includes the mutation. Hence **every read that starts after a
  mutation's response sees that mutation**. Between C and I (≈ 1 ms, before the client has the response) a read may
  still get the previous value — that is the ordinary "read concurrent with a write" case, not staleness.
- A late write under an old generation leaves an orphan value that nobody reads; it expires with its TTL. Under peak
  voting this is at most "reads per second × TTL" small keys.
- Counters have no TTL on purpose: a counter that expired while a value of its generation lived could make a reader
  fall back to an old generation. They cost one small key per mutated poll. If Redis ever gets `maxmemory`, the policy
  must be `volatile-lru` / `volatile-lfu`, which never evicts keys without TTL (counters, DataProtection keys).
- The scripts build the value key from the counter inside Lua — fine on our single Redis node (ADR 0021); Redis
  Cluster would need both keys in one hash slot (`{pollId}` hash tag), out of scope.

### TTL by the poll status the entry was computed with, plus jitter
| Status in the entry | TTL | Why |
|---|---|---|
| `active` | 10 s + 0–20 % | Explicit invalidation keeps it fresh; the TTL only bounds staleness when an invalidation is lost (Redis blip, ADR 0027). Seconds are acceptable for a dashboard; a minute is not. Shorter brings little: during voting invalidations come far more often than any TTL, and a quiet poll costs one DB read per 10 s |
| `draft` | 10 s + 0–20 % | Only the author reads it; publish and delete invalidate. Nothing to gain from keeping it longer |
| `closed` | 1 h + 0–20 % | Results are final: votes require `active`, `closed` has no outgoing transitions, only drafts can be deleted. The TTL only bounds memory; recomputing once an hour costs nothing |

- The long TTL goes **only to data that can no longer change**. An entry computed while the poll was active keeps the
  10 s TTL even if the poll closes a moment later; if that close's invalidation is lost, the stale entry lives ≤ 12 s.
- **Jitter** (uniform 0–20 % on top, `Random.Shared`) against Cache Avalanche: after a Redis restart or a cold start
  many entries are written within the same second and, with a fixed TTL, would expire in the same second too, sending
  one synchronized wave of reads to PostgreSQL. With jitter, expiry spreads over 2 s (active) / 12 min (closed).
- An `active` poll past `endsAt` stays `active` (no background closer) and keeps the 10 s TTL — correct, just not
  optimal.

## Consequences
- 2.5 holds by construction, not by TTL: after a vote's 201 every read through any instance shows it.
- **Verified 2026-11-02** with `scripts/cache-race-check.py` (60 rounds × 8 simultaneous votes for one option, 12
  readers polling `GET /results` throughout, control read after each round; through the LB, two instances). Lab 2
  code (`DEL`): stale aggregate in **every one of 5 runs** — 2, ≥ 3, ≥ 3, 5 and 4 rounds of 60, always 1–2 votes
  behind. Generations: **0 of 60 in 5 runs** (3.4–4.1k concurrent reads each). A single vote per round never
  reproduced it (0 of 200 on both builds): the race needs a second invalidation while a reader that missed after
  the first one is still between its DB read and its `SET`. Also checked: `TTL` 11 s on a draft entry, 3906 s on a
  closed one; publish → counter 1 and `g0` gone; both instances serve the same `generatedAt`;
  `concurrency-checks.py`, `cross-instance.sh` 8/8 and `redis-outage-check.py` (lab 2 behaviour, until П1-5) pass.
- A read costs one Redis round-trip as before; an invalidation also one. The `ResultsCache` API
  (`GetAsync` / `SetAsync` / `InvalidateAsync`) can keep its shape, with the generation carried from `GetAsync` to
  `SetAsync`; `PollService` / `VoteService` need no change.
- Debugging with `redis-cli` changes: `GET polling:results:gen:1`, then `GET polling:results:v1:1:g<n>` /
  `TTL polling:results:v1:1:g<n>`; `SCAN 0 MATCH polling:results:*` lists everything. Runbook and contracts are
  updated in П1-8.
- Not addressed here (deliberate, lab 4 scope): Cache Stampede — every vote to a hot poll invalidates its entry, so all
  concurrent readers miss together and go to PostgreSQL. Deferred by Participant 1 on 2026-11-02; explained in theory
  at the defense, revisit before П1-8. Redis-down behaviour (fallback to the DB, fail-fast) is П1-5, its own ADR.
