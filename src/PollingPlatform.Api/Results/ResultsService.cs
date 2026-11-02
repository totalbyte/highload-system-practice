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
    public async Task<PollResultsRead> GetAsync(long pollId, long? currentUserId, CancellationToken ct)
    {
        // Cache-Aside (ADR 0041). Кеш містить і CreatorId, тому на попадання видимість перевіряється без звернення до БД.
        var lookup = await cache.GetAsync(pollId);
        var source = lookup switch
        {
            { Generation: null } => CacheResult.Bypass,
            { Entry: null } => CacheResult.Miss,
            _ => CacheResult.Hit
        };
        var entry = lookup.Entry ?? await LoadAndCacheAsync(pollId, lookup.Generation, ct);

        if (entry.Response.Status == PollStatus.Draft && entry.CreatorId != currentUserId)
            throw new PollNotFoundException(pollId);

        return new PollResultsRead(entry.Response, source);
    }

    /// <summary>
    /// Промах: читання з БД і запис під поколінням <paramref name="generation"/>, прочитаним до цього запиту.
    /// Якщо поки ми читали, зміна встигла закомітитись і інвалідувати кеш, наш запис ляже під старе покоління і не
    /// буде прочитаний — наступний читач піде в БД і побачить зміну.
    /// Без покоління (Redis недоступний) лише читаємо: записати без нього означало б повернути гонку з лаби 2.
    /// </summary>
    private async Task<CachedPollResults> LoadAndCacheAsync(long pollId, long? generation, CancellationToken ct)
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

        if (generation is { } readGeneration)
            await cache.SetAsync(pollId, readGeneration, entry);
        return entry;
    }
}
