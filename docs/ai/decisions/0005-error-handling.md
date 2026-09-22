# 0005. 400 vs 422, `AppException` hierarchy, ProblemDetails
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
The design doc requires a centralized exception handler mapping domain exceptions to HTTP codes
(404/409/422/401). This is stage 7, owned by Participant 2, but without it Participant 1's endpoints would return
500 instead of 404/409, so a minimal version was built early.

## Decision
- Every domain exception derives from `AppException`, which carries its own `StatusCode` and `Title`
  (`NotFoundException` 404, `ConflictException` 409, `UnauthorizedException` 401, `ForbiddenException` 403,
  `ValidationException` 422). No switch over exception types in the handler.
- `GlobalExceptionHandler` (`IExceptionHandler`) writes RFC 7807 ProblemDetails; `ValidationException` →
  `ValidationProblemDetails` with `errors`; `traceId` is added to every problem; anything else → 500 without details
  (logged). `UseStatusCodePages` gives bodies to 401/404 produced by the framework.
- **400** only for unparseable requests (broken JSON, wrong types, unknown enum). **422** for field validation via
  FluentValidation. To get missing fields to the validator: nullable DTO properties +
  `SuppressImplicitRequiredAttributeForNonNullableReferenceTypes = true`.

## Consequences
- Participant 2 adds `PollClosedException` / `DuplicateVoteException` as subclasses of `ConflictException`; no
  handler change needed.
- Open: transient DB errors currently produce 500; mapping them to 503 is a candidate improvement (stage 7).
