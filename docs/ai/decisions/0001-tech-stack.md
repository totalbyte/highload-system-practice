# 0001. Tech stack: C# / ASP.NET Core 10 + EF Core + PostgreSQL
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** team (recorded by Participant 1)

## Context
The design doc left the stack as "TBD". Candidates considered: Node.js/TypeScript, Python/FastAPI, Go, C#/.NET.
Both participants must understand the whole codebase for the defenses.

## Decision
- Backend: C# / ASP.NET Core 10, controller-based Web API, `net10.0`.
- Persistence: EF Core 10 + Npgsql, PostgreSQL 17 (`postgres:17-alpine`) with a named volume.
- Validation: FluentValidation. Auth: JWT Bearer. API docs: Swashbuckle (Swagger UI).
- Containerization: Docker Compose. Later labs: Redis (2/4), Nginx (3), k6 (5).
- `Microsoft.AspNetCore.OpenApi` was removed from the template because it pulled in `Microsoft.OpenApi 2.0.0` with a
  known high-severity vulnerability (NU1903); Swashbuckle brings 2.7.5.

## Consequences
- EF migrations are the schema source of truth (lab requirement: migrations/DDL scripts).
- The System Design .docx was updated with the chosen stack.
