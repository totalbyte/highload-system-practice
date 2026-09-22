# 0003. Visibility: foreign drafts → 404, unlisted polls, 403 for management
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
The design doc has an `isPublic` flag and draft status but doesn't define who sees what.

## Decision
- A draft is visible only to its author. For anyone else every endpoint returns **404** (not 403), so the existence
  of someone else's draft is not revealed.
- `isPublic = false` means "unlisted": excluded from `GET /api/polls` for other users, but reachable by id.
- The list shows `(isPublic AND status != draft) OR creatorId = currentUser` — authors see all their own polls.
- Managing (publish/close/delete) someone else's non-draft poll → **403**.
- Read endpoints (`GET /api/polls`, `GET /api/polls/{id}`) allow anonymous access; a token, if present, is used to
  apply the author rules.

## Consequences
- Results/voting endpoints should apply the same rules (foreign draft → 404) for consistency.
