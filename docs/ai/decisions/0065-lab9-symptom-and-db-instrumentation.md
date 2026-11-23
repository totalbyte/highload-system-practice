# 0065. Lab 9: symptom = catalog fan-out saturating the replicas; `pg_stat_statements` with planning time on every node
**Status:** Accepted · **Date:** 2026-11-18 · **Author:** Participant 2

## Context
Lab 9 (2.1) asks to pick a measured degradation from labs 5–8 and to state 2–3 testable hypotheses. Lab 7 (ADR 0059)
measured the catalog `GET /api/polls` on two shards: saturated at 10 VUs / ≈ 410 RPS, both replicas at 98–101 % of their
one core, p95 853 ms at 200 VUs, ×1.1 from a second shard — for a table with a few dozen rows per shard. Lab 8 enabled
`pg_stat_statements` on the Primaries only, while the catalog is read on the replicas (ADR 0050).

## Decision
- **Symptom:** the catalog saturates the replicas far below what such small queries should cost (≈ 2.3 ms of replica CPU
  per request at ≈ 410 RPS).
- **Hypotheses:** H1 inefficient plan (full scan, sort); H2 N+1 in SQL (correlated `count(options)` per row); H3 every
  request is parsed and planned again (no prepared statements); H4 connection pool (churn or waiting); H5 the backend
  itself (CPU, GC, serialization, merge of the fan-out).
- **Instrumentation of the database:** `shared_preload_libraries=pg_stat_statements` also on both replicas (the extension
  object comes from the Primary through WAL, the library is loaded per node) and `pg_stat_statements.track_planning=on` on
  all four nodes, so planning time is reported separately from execution. Both stay on: the overhead is small and the
  lecturer can inspect them at the defense.

## Consequences
- First measurement (50 VUs, replica A, 33 s): planning 12.8 s vs execution 9.1 s; EXPLAIN ANALYZE of the page query:
  Planning 2.95 ms, Execution 0.54 ms, index `ix_polls_status_created_at` used; 60 stable client sessions. H3 the lead,
  H1 and H4 likely refuted — confirmed with the full evidence in ADR 0067 / 0068.
- Plan by stages: `docs/lab9/plan.md`.
