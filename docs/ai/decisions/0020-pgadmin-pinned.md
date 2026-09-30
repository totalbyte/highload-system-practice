# 0020. pgAdmin 4 in the `tools` profile, pinned to `9.17.0`, server pre-registered
**Status:** Accepted · **Date:** 2026-09-30 · **Author:** Participant 1

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
- `docker/pgadmin/servers.json` pre-registers "polling (docker)" (`postgres:5432`, db/user `polling`); the password is
  entered once in the UI. pgAdmin settings persist in the `pgadmin-data` volume. Port `PGADMIN_PORT` (5050).

## Consequences
- Verified 2026-09-30: UI up on :5050, "Added 1 Server(s)" in the logs, connection from the pgAdmin container to
  PostgreSQL 17.11 works.
- If `POSTGRES_USER`/`POSTGRES_DB` are changed in `.env`, update `servers.json` too (it has no env substitution);
  already registered servers live in `pgadmin-data` — `docker volume rm polling-platform_pgadmin-data` to re-import.
- pgAdmin takes connections from the same `max_connections` budget (ADR 0018).
