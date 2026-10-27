# 0023. DataProtection keys in Redis, shared by all instances
**Status:** Accepted · **Date:** 2026-10-27 · **Author:** Participant 1

## Context
ASP.NET Core always registers DataProtection. Without configuration each process generates its own key ring in the
container filesystem (`/home/app/.aspnet/DataProtection-Keys`) and logs a warning that it "may not be persisted
outside of the container". We don't protect anything with it today (auth is a JWT, ADR 0006), but the lab 2 state
audit looks exactly for this kind of state: file-based and per instance. Anything protected by one instance (auth
cookies, antiforgery tokens, `IDataProtector` payloads) could not be read by the other one, and the keys disappear
with the container — a hidden instance affinity waiting for the first feature that uses them.

## Decision
- `AddDataProtection().SetApplicationName("polling-platform").PersistKeysToStackExchangeRedis(redis,
  "DataProtection-Keys")` in `Program.cs`, package `Microsoft.AspNetCore.DataProtection.StackExchangeRedis` 10.0.12,
  reusing the single `IConnectionMultiplexer` from ADR 0021. The same application name on every instance is what lets
  them share one key ring.
- Redis rather than PostgreSQL (`PersistKeysToDbContext`): no schema change/migration, and the data is not business
  state — losing it costs nothing while DataProtection is unused.

## Consequences
- Verified 2026-10-27: after a cold start Redis holds one list `DataProtection-Keys` with one key, created by one
  instance and picked up by the other; after recreating both backend containers (empty filesystem) there is still one
  key and no DataProtection warning in the logs. Smoke test 11/11 on both instances.
- Redis has no volume (ADR 0021), so `docker compose down` / a Redis restart drops the key ring and a new key is
  generated. Acceptable while nothing is protected with it; if cookies or antiforgery tokens appear, give Redis
  persistence or move the keys to PostgreSQL in a new ADR.
- The "No XML encryptor configured" warning remains: keys are stored unencrypted in Redis. Fine for a local course
  project; a real deployment would add `ProtectKeysWith…` (certificate / key vault).
