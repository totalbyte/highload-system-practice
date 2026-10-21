# 0020. pgAdmin 4 in the `tools` profile, pinned to `9.17.0`, server pre-registered
**Status:** Accepted, amended 2026-09-30 (pgAdmin moved out of the `tools` profile, see the end) · **Date:** 2026-09-30 · **Author:** Participant 1

## Context
The team wanted pgAdmin to browse the database, pinned to a concrete stable version instead of `latest`. pgAdmin 4
has no LTS line: it ships a 9.x release roughly every month (as of 2026-09-30 the newest was `9.18.0`, released
2026-09-17).

## Decision
- Image `dpage/pgadmin4:9.17.0` — an exact tag, one release behind the newest, so `docker compose pull` never
  changes the version silently. Upgrade deliberately by editing the tag.
- Same `tools` profile as Adminer: `docker compose --profile tools up -d`; the graded `docker compose up` stays
  backend + postgres only (pgAdmin needs ~40 s to start).
- Desktop mode (`PGADMIN_CONFIG_SERVER_MODE=False`, no master password): no login screen — local development only.
  `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` still exist because the image requires them.
- The server list is an inline Compose config (`configs.pgadmin_servers.content` in `docker-compose.yml`, mounted as
  `/pgadmin4/servers.json`) — no extra folder or file in the repo. It pre-registers "polling (docker)"
  (`postgres:5432`); `MaintenanceDB`/`Username` come from `${POSTGRES_DB}`/`${POSTGRES_USER}`, so a changed `.env`
  is picked up automatically. The DB password is entered once in the UI.
- pgAdmin settings persist in the `pgadmin-data` volume. Port `PGADMIN_PORT` (5050).

## Consequences
- Verified 2026-09-30: UI up on :5050, "Added 1 Server(s)" in the logs, connection from the pgAdmin container to
  PostgreSQL 17.11 works.
- pgAdmin imports the server list only on its first start with an empty `pgadmin-data` volume; after changing it run
  `docker compose --profile tools down` and `docker volume rm polling-platform_pgadmin-data` to re-import.
- Inline `configs.content` needs Docker Compose ≥ 2.23 (both participants have newer versions).
- pgAdmin takes connections from the same `max_connections` budget (ADR 0018).

## Amendment (2026-09-30): pgAdmin starts with the normal `docker compose up`
At Participant 1's request pgAdmin was taken out of the `tools` profile (Adminer stays there). It does not slow down
the graded cold start: `up -d` returns once containers are created, pgAdmin boots in parallel (~40 s) and the backend
does not depend on it. It still competes for the `max_connections` budget (ADR 0018).
