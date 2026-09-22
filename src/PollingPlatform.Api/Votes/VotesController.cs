using FluentValidation;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PollingPlatform.Api.Auth;
using PollingPlatform.Api.Common.Validation;

namespace PollingPlatform.Api.Votes;

[ApiController]
[Route("api/polls")]
[Produces("application/json")]
public class VotesController(VoteService voteService) : ControllerBase
{
    /// <summary>Проголосувати в опитуванні: 201 — новий голос, 200 — змінений або повторний той самий.</summary>
    [Authorize]
    [HttpPost("{id:long}/vote")]
    [ProducesResponseType<CastVoteResponse>(StatusCodes.Status201Created)]
    [ProducesResponseType<CastVoteResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status422UnprocessableEntity)]
    public async Task<ActionResult<CastVoteResponse>> Cast(
        long id, CastVoteRequest request, [FromServices] IValidator<CastVoteRequest> validator, CancellationToken ct)
    {
        await validator.ValidateOrThrowAsync(request, ct);

        var result = await voteService.CastAsync(id, User.GetUserId(), request.OptionId!.Value, ct);
        var response = new CastVoteResponse(result.PollId, result.OptionId, result.VotedAt);

        return result.Created ? StatusCode(StatusCodes.Status201Created, response) : Ok(response);
    }
}
