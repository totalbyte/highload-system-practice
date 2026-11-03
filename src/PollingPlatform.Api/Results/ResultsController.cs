using Microsoft.AspNetCore.Mvc;
using PollingPlatform.Api.Auth;

namespace PollingPlatform.Api.Results;

[ApiController]
[Route("api/polls")]
[Produces("application/json")]
public class ResultsController(ResultsService resultsService) : ControllerBase
{
    /// <summary>Агреговані результати опитування (голоси та відсотки по варіантах).</summary>
    /// <remarks>Заголовок відповіді <c>X-Cache</c>: <c>HIT</c> — з Redis без звернення до БД, <c>MISS</c> — з БД, <c>BYPASS</c> — Redis недоступний, відповідь прямо з БД.</remarks>
    [HttpGet("{id:long}/results")]
    [ProducesResponseType<PollResultsResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status404NotFound)]
    public async Task<PollResultsResponse> Get(long id, CancellationToken ct)
    {
        var read = await resultsService.GetAsync(id, User.FindUserId(), ct);
        // Джерело даних видно клієнту і в лозі балансувальника (лаба 4, 2.6.1).
        Response.Headers["X-Cache"] = read.Cache.ToString().ToUpperInvariant();
        return read.Response;
    }
}
