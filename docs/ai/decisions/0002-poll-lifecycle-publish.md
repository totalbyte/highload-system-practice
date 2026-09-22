# 0002. Poll lifecycle Draft → Active → Closed with an explicit `publish` endpoint
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
The design doc defines statuses draft/active/closed, allows voting only in `active` and deleting only in `draft`,
but has no endpoint that moves a poll from draft to active. Alternatives: create polls as active immediately (makes
draft and DELETE meaningless) or derive status from dates (status becomes computed, harder to reason about).

## Decision
- `POST /api/polls` always creates a `draft`.
- `PATCH /api/polls/{id}/publish` (author only): `draft → active`.
- `PATCH /api/polls/{id}/close` (author only): `active → closed` (early closing).
- `DELETE /api/polls/{id}` (author only): only in `draft`.
- `StartsAt` is nullable: `null` means voting starts at publish time — `publish` sets it to `now`.
  `EndsAt` is required and must be in the future both at creation and at publish.
- `close` does not modify `EndsAt` (setting it to `now` could violate `starts_at < ends_at` for polls that haven't
  started yet).

## Consequences
- One extra business endpoint beyond the design doc (8 poll/vote endpoints in total when voting lands).
- There is no background job: a poll stays `active` after `ends_at` passes. Voting must check dates, not only status.
