# 0013. Lab 1 results cache in process memory, on purpose
**Status:** Accepted (expected to be superseded in lab 2/4) · **Date:** 2026-09-22 · **Author:** team plan
(recorded by Participant 1; implementation by Participant 2)

## Context
The execution plan: lab 2 is a state audit that must show stateful constructs being removed. If everything were
stateless from the start, there would be nothing to demonstrate.

## Decision
`GET /api/polls/{id}/results` (stage 6) caches results in the backend's process memory in lab 1, with invalidation on
vote and on close.

## Consequences
- With two instances (lab 2) the caches diverge — a deliberate, demonstrable problem. Lab 2 moves it to Redis; lab 4
  formalizes Cache-Aside, key schema, TTL and fallback. Record that change as a new ADR superseding this one.
- Agents must not "fix" this early.
