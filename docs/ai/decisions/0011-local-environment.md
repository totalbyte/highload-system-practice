# 0011. Host port 5433, GSS off, Swagger in Production
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Decision
- The Postgres container is published on host port **5433** (`POSTGRES_PORT`), because Participant 1's machine runs a local
  Windows PostgreSQL service on 5432 — host tools would silently connect to the wrong server. Inside the Docker
  network the backend still uses `postgres:5432`. `appsettings.json` (for `dotnet run`) points to `localhost:5433`.
- `Gss Encryption Mode=Disable` in the connection string: removes `libgssapi_krb5.so.2` noise from container logs.
- Swagger UI is enabled in Production too (`Swagger:Enabled=true`) — needed for the defense demo.
- The backend container runs as the non-root user from the base image; HTTP only, port 8080.

## Consequences
- If a teammate's machine has nothing on 5432, 5433 still works; override via `.env` if needed.
