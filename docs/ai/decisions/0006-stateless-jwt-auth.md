# 0006. Stateless JWT auth, PBKDF2 passwords
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
"One vote per user" needs authenticated users from day one. Lab 2 requires that any instance can serve any request
without sticky sessions; server-side sessions would have to be rewritten then.

## Decision
- HS256 JWT issued by `POST /api/auth/login`; claims `sub` (user id), `unique_name`, `jti`. Secret from
  `Jwt__Secret` (≥32 chars, validated on startup), lifetime `Jwt__LifetimeMinutes` (default 60). No refresh tokens.
- `MapInboundClaims = false`, so the user id is read from the `"sub"` claim (`User.GetUserId()`).
- Passwords hashed with ASP.NET Identity's `PasswordHasher<User>` (PBKDF2). Emails normalized to lower case.
  Login returns the same 401 for "no such user" and "wrong password".

## Consequences
- Verified: a token stays valid after a backend restart (nothing stored server-side).
- Login is deliberately CPU-heavy: in lab 5, log in once in k6 `setup()` and reuse tokens.
- All instances must share the same `Jwt__Secret`.
