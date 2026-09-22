# 0004. Status changes via conditional UPDATE/DELETE
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
With load-modify-save, two concurrent requests (e.g. publish + delete, or close + close) could both pass the status
check and both apply. Under multiple instances (labs 2–3) this is a real race.

## Decision
- First read the poll's state (for precise 404/403/409 errors), then apply the change with a condition on the current
  status in the same SQL statement: `UPDATE polls SET status = @to WHERE id = @id AND status = @from`
  (`ExecuteUpdateAsync`), or `DELETE ... WHERE id = @id AND status = 'draft'` (`ExecuteDeleteAsync`).
- 0 affected rows → someone changed the poll in between → re-read and return 404/409.
- Implemented in `PollService.TransitionAsync` / `DeleteAsync`.

## Consequences
- No lost updates without explicit locks or transactions; works identically across instances.
- `ExecuteUpdate` bypasses the change tracker — don't mix it with tracked entities of the same poll in one request.
