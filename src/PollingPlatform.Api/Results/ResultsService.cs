using Microsoft.EntityFrameworkCore;
using PollingPlatform.Api.Common.Exceptions;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Агреговані результати опитування — найчастіша операція читання (лайв-дашборд).
/// Рахуються з денормалізованого <c>options.vote_count</c>, а не COUNT(*) по <c>votes</c>,
/// і кешуються, щоб пікове читання не впиралося в БД.
/// </summary>
public class ResultsService(AppDbContext db, ResultsCache cache, TimeProvider timeProvider)
{
    public async Task<PollResultsResponse> GetAsync(long pollId, long? currentUserId, CancellationToken ct)
    {
        // Кеш містить і CreatorId, тому на попадання видимість перевіряється без звернення до БД.
        var entry = cache.Get(pollId) ?? await LoadAndCacheAsync(pollId, ct);

        if (entry.Response.Status == PollStatus.Draft && entry.CreatorId != currentUserId)
            throw new PollNotFoundException(pollId);

        return entry.Response;
    }

    private async Task<CachedPollResults> LoadAndCacheAsync(long pollId, CancellationToken ct)
    {
        var poll = await db.Polls.AsNoTracking()
            .Where(p => p.Id == pollId)
            .Select(p => new
            {
                p.CreatorId,
                p.Title,
                p.Status,
                Options = p.Options.OrderBy(o => o.Position)
                    .Select(o => new { o.Id, o.Text, o.Position, o.VoteCount })
                    .ToList()
            })
            .FirstOrDefaultAsync(ct);

        if (poll is null)
            throw new PollNotFoundException(pollId);

        var totalVotes = poll.Options.Sum(o => o.VoteCount);
        var options = poll.Options
            .Select(o => new OptionResultResponse(
                o.Id, o.Text, o.Position, o.VoteCount,
                totalVotes == 0 ? 0 : Math.Round(o.VoteCount * 100.0 / totalVotes, 2)))
            .ToList();

        var entry = new CachedPollResults(
            poll.CreatorId,
            new PollResultsResponse(pollId, poll.Title, poll.Status, totalVotes, timeProvider.GetUtcNow(), options));

        cache.Set(pollId, entry);
        return entry;
    }
}
