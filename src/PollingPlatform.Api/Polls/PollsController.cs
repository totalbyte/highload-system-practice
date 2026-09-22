using FluentValidation;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PollingPlatform.Api.Auth;
using PollingPlatform.Api.Common.Validation;

namespace PollingPlatform.Api.Polls;

[ApiController]
[Route("api/polls")]
[Produces("application/json")]
public class PollsController(PollService pollService) : ControllerBase
{
    /// <summary>Створити опитування з варіантами відповідей (статус draft).</summary>
    [Authorize]
    [HttpPost]
    [ProducesResponseType<PollDetailsResponse>(StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status422UnprocessableEntity)]
    public async Task<ActionResult<PollDetailsResponse>> Create(
        CreatePollRequest request, [FromServices] IValidator<CreatePollRequest> validator, CancellationToken ct)
    {
        await validator.ValidateOrThrowAsync(request, ct);
        var poll = await pollService.CreateAsync(User.GetUserId(), request, ct);
        return CreatedAtAction(nameof(Get), new { id = poll.Id }, poll);
    }

    /// <summary>Список опитувань з фільтрами за статусом та автором (з пагінацією).</summary>
    [HttpGet]
    [ProducesResponseType<PagedResponse<PollSummaryResponse>>(StatusCodes.Status200OK)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status422UnprocessableEntity)]
    public async Task<PagedResponse<PollSummaryResponse>> List(
        [FromQuery] PollListQuery query, [FromServices] IValidator<PollListQuery> validator, CancellationToken ct)
    {
        await validator.ValidateOrThrowAsync(query, ct);
        return await pollService.ListAsync(query, User.FindUserId(), ct);
    }

    /// <summary>Деталі опитування та варіанти відповідей.</summary>
    [HttpGet("{id:long}")]
    [ProducesResponseType<PollDetailsResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status404NotFound)]
    public Task<PollDetailsResponse> Get(long id, CancellationToken ct) =>
        pollService.GetAsync(id, User.FindUserId(), ct);

    /// <summary>Опублікувати чернетку (draft → active). Лише автор.</summary>
    [Authorize]
    [HttpPatch("{id:long}/publish")]
    [ProducesResponseType<PollDetailsResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status403Forbidden)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public Task<PollDetailsResponse> Publish(long id, CancellationToken ct) =>
        pollService.PublishAsync(id, User.GetUserId(), ct);

    /// <summary>Дострокове закриття опитування (active → closed). Лише автор.</summary>
    [Authorize]
    [HttpPatch("{id:long}/close")]
    [ProducesResponseType<PollDetailsResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status403Forbidden)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public Task<PollDetailsResponse> Close(long id, CancellationToken ct) =>
        pollService.CloseAsync(id, User.GetUserId(), ct);

    /// <summary>Видалити опитування (лише у статусі draft). Лише автор.</summary>
    [Authorize]
    [HttpDelete("{id:long}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status403Forbidden)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<IActionResult> Delete(long id, CancellationToken ct)
    {
        await pollService.DeleteAsync(id, User.GetUserId(), ct);
        return NoContent();
    }
}
