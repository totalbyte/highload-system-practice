using Microsoft.AspNetCore.Mvc;
using PollingPlatform.Api.Auth;

namespace PollingPlatform.Api.Results;

[ApiController]
[Route("api/polls")]
[Produces("application/json")]
public class ResultsController(ResultsService resultsService) : ControllerBase
{
    /// <summary>Агреговані результати опитування (голоси та відсотки по варіантах).</summary>
    [HttpGet("{id:long}/results")]
    [ProducesResponseType<PollResultsResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status404NotFound)]
    public Task<PollResultsResponse> Get(long id, CancellationToken ct) =>
        resultsService.GetAsync(id, User.FindUserId(), ct);
}
