# 0047. Lab 5: every measured run starts on a fresh stack with the same seed
**Status:** Accepted · **Date:** 2026-11-03 · **Author:** Participant 1, Participant 2

## Context
The first full series (2026-11-02) ran all configurations one after another on the same database. The comparison came
out wrong: scenario A on 3 instances gave ≈ 3.6–4.5k RPS against ≈ 9.5k on 2 instances, with 40–65 active PostgreSQL
sessions and all 90 connections busy, but fewer DB transactions per second. The cause was the data, not the instance
count: scenario C creates a poll in 20 % of its iterations, so after the C runs `polls` had grown from 50 to 17 370
rows and the catalog / details queries of scenario A got heavier; scenario B had applied ≈ 833k updates to the hot
`options` rows. Every later run measured a different database.

## Decision
- `load-tests/series.sh` brings the stack down with volumes and up again before **each** measured run
  (`down -v` → `up -d --build` → wait until the pool is UP; then stop `backend-2` or start `backend-3` for the 1- / 3-
  instance runs, restart with `RESULTS_CACHE_ENABLED=false` for the cache-off run). Every run sees the same seed:
  500 users, 50 polls, hot poll #1 with no votes.
- The first series is kept as `load-tests/results/run1/` (ignored by Git) only as the evidence for this ADR.

## Consequences
- ≈ 30 s of cold start per run; the full series takes ≈ 55 min.
- Within one run the data still changes (B adds votes, C adds polls) — that is part of the scenario and identical for
  every configuration.
- Comparing runs is now comparing configurations, which is what 2.6 asks for ("тотожні умови").
