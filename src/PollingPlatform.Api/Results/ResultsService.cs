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
public class ResultsService(AppDbContext db, ResultsCache cache, ResultsSingleFlight singleFlight, TimeProvider timeProvider)
{
    public async Task<PollResultsRead> GetAsync(long pollId, long? currentUserId, CancellationToken ct)
    {
        // Cache-Aside (ADR 0041). Кеш містить і CreatorId, тому на попадання видимість перевіряється без звернення до БД.
        var lookup = await cache.GetAsync(pollId);
        var (entry, source) = lookup switch
        {
            { Entry: { } cached } => (cached, CacheResult.Hit),
            // Промах: одночасні промахи інстансу по цьому поколінню чекають одне читання з БД (ADR 0044) — воно ж
            // записує агрегат під поколінням, прочитаним до запиту в БД (ADR 0041).
            { Generation: { } generation } => (await singleFlight.LoadAsync(pollId, generation, ct), CacheResult.Miss),
            // Redis недоступний (ADR 0043): читаємо з БД і нічого не пишемо — без покоління запис повернув би гонку з
            // лаби 2. І не об'єднуємо: без покоління не видно, чи почалося спільне читання вже після мутації.
            _ => (await LoadAsync(db, pollId, timeProvider, ct), CacheResult.Bypass)
        };

        if (entry.Response.Status == PollStatus.Draft && entry.CreatorId != currentUserId)
            throw new PollNotFoundException(pollId);

        return new PollResultsRead(entry.Response, source);
    }

    /// <summary>Агрегат з БД, без кешу. <c>GeneratedAt</c> — момент цього читання.</summary>
    internal static async Task<CachedPollResults> LoadAsync(
        AppDbContext db, long pollId, TimeProvider timeProvider, CancellationToken ct)
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

        return new CachedPollResults(
            poll.CreatorId,
            new PollResultsResponse(pollId, poll.Title, poll.Status, totalVotes, timeProvider.GetUtcNow(), options));
    }
}
