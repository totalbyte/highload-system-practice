# 0066. Lab 9: distributed tracing with OpenTelemetry → Jaeger, off by default, HTTP-rooted sampling
**Status:** Accepted · **Date:** 2026-11-18 · **Author:** Participant 2

## Context
Lab 9 (2.2) asks to decompose the total latency of a request into service, cache and database parts with distributed
tracing (OpenTelemetry / Jaeger / Zipkin). The catalog request fans out to both shards in parallel (ADR 0055), so one
request has several database calls whose times overlap.

## Decision
- **Instrumentation in the backend** (`Common/Diagnostics/Tracing.cs`): OpenTelemetry with ASP.NET Core (server span),
  Npgsql (`Npgsql.OpenTelemetry`, one span per SQL statement with the text and the node) and StackExchange.Redis (beta
  package, one span per command); OTLP gRPC export.
- **Jaeger `jaegertracing/jaeger:2.12.0`** (v2, in-memory storage), UI on `localhost:16686`, compose profile `tracing`:
  a normal `docker compose up` does not start it.
- **Off by default** (`TRACING_ENABLED=false`): creating and exporting spans costs CPU and would bias the A/B measurements.
  `TRACING_SAMPLE_RATIO` (default 1.0) for runs under load.
- **Sampler:** a trace starts only from an HTTP server span; root spans of other kinds are dropped — otherwise the node
  monitor's `SELECT 1` every second (ADR 0052) would be a separate trace each time. `/health` is filtered out too.
- **`profiling/traces.py`** sends sequential catalog or results requests (optionally while k6 runs), reads the traces through
  the Jaeger API and reports the median / p95 of the whole request, the SQL wall time (union of the overlapping per-shard
  intervals), the Redis time and the rest of the backend; it saves one full trace per run as `trace-<kind>-<label>.json`.

## Consequences
- First measurement 2026-11-18, sequential requests on an idle stack only — it hid the problem (8.0 ms, SQL 5.1 ms). Redone
  2026-11-23 after the PR review, one core per database node, `traces.py --kind catalog|results --label idle|load`
  (`*/traces-*.md`, `*/trace-*.json`), median:
  - catalog idle: 3.94 ms, SQL wall 2.22, backend 1.69 (before) → 3.52 / 1.81 / 1.60 ms (after);
  - **catalog under 50 VUs (k6 running, its requests traced too):** 34.9 ms, SQL wall 34.3, backend 0.7 → 23.3 / 22.7 / 0.6 ms;
    one statement on replica A 1.6 → 1.1 ms, on replica **B 16.4 → 11.1 ms** — B is the shard the fan-out waits for;
  - results (Cache-Aside, lab 4) idle: 0.79 ms, Redis 0.36 ms, most requests never reach PostgreSQL (HIT) — the cache
    component, which the catalog does not have.
- An SQL span covers the whole round trip (send, parse, plan, execute, receive), so a trace shows where the time goes but
  cannot split planning from execution; that split comes from `pg_stat_statements` (ADR 0067).
- Packages: `OpenTelemetry.Extensions.Hosting`, `.Instrumentation.AspNetCore`, `.Exporter.OpenTelemetryProtocol` 1.21.0,
  `Npgsql.OpenTelemetry` 10.0.3, `OpenTelemetry.Instrumentation.StackExchangeRedis` 1.21.0-beta.1 (only a beta exists).
