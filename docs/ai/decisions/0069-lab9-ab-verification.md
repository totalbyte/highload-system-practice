# 0069. Lab 9: A/B verification of `Max Auto Prepare` — interleaved repeats on fresh stacks, regression on writes and reads
**Status:** Accepted · **Date:** 2026-11-18 · **Author:** Participant 2

## Context
Lab 9 (2.4) asks to repeat the load test under identical conditions, to tabulate throughput, p95, p99, error rate and CPU /
memory before and after the optimization (ADR 0068), and to analyse side effects on other parts of the system. One run per
configuration drifted by tens of percent in lab 5 / 6 / 8, so single runs are not enough.

## Decision
- **`profiling/ab-series.sh`:** the lab 7 stand (`docker-compose.loadtest-shards.yml`, one core per database node), a fresh
  stack per run (ADR 0047), wait until login answers 200, then `load-tests/run.sh scenario-shards` (lab 7 k6 script) with
  the lab 5 stepped profile 10 → 200 VUs × 30 s. The only difference between "before" and "after" is `DB_MAX_AUTO_PREPARE`
  (0 / 20).
- **Catalog (the symptom):** 3 repeats per configuration, interleaved before / after, so machine drift is shared.
- **Regression:** one run each of `MODE=write` (votes, Primaries) and `MODE=read` (poll details, replicas) per configuration.
- **`profiling/ab-report.py`** → `profiling/ab-report.md`: mean per step across repeats, deltas, CPU of the four database
  nodes and the backends, backend memory, saturation point, Mermaid charts.

## Consequences
- Measured 2026-11-18 (24 vCPU, Docker Desktop), 0 % errors in every step of every run:
  - **catalog:** RPS 391 / 395 / 362 / 404 / 405 → 553 / 556 / 570 / 569 / 580 at 10 / 25 / 50 / 100 / 200 VUs
    (+41 … +58 %); p95 −17 … −35 % (233 → 151 ms at 50 VUs), p99 −17 … −36 %; saturation stays at 10 VUs but at
    553 instead of 391 RPS — the catalog is still a fan-out bound by the replicas (still ≈ 100 % at 25 and 100 VUs);
  - **write (regression):** +31 … +81 % RPS, p95 −11 … −42 % — the vote path's statements are prepared too;
  - **read (regression):** +44 … +136 % RPS, p95 −35 … −63 %; after the change the backends reach ≈ 200 % of their two
    cores — the bottleneck of this path moved from the replicas to the backend;
  - backend memory unchanged (≈ 120–166 MiB in both configurations).
- Per-step CPU is an average of `docker stats` samples every 5 s; at 50 VUs both configurations show only ≈ 65 % on the
  replicas, which disagrees with 25 and 100 VUs — likely because the samples of that step partly fall into the 5 s pause between
  steps (not verified).
  The RPS / latency numbers come from k6 and are not affected.
- No negative side effect found in the measured paths. The trade-offs of ADR 0068 (lighter reset statements, per-connection
  memory for plans, generic plans, PgBouncer transaction mode) remain the known costs.
