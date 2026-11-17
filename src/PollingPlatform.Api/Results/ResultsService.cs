using Microsoft.EntityFrameworkCore;
using PollingPlatform.Api.Common.Exceptions;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Domain;
using PollingPlatform.Api.Sharding;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Агреговані результати опитування — найчастіша операція читання (лайв-дашборд).
/// Рахуються з денормалізованого <c>options.vote_count</c>, а не COUNT(*) по <c>votes</c>,
/// і кешуються, щоб пікове читання не впиралося в БД.
/// </summary>
public class ResultsService(ShardContexts shards, ResultsCache cache, ResultsSingleFlight singleFlight, TimeProvider timeProvider)
{
    /// <summary>Коментар у SQL читання агрегату — його шукають скрипти лаби 8 у <c>pg_stat_statements</c>.</summary>
    public const string ResultsLoadTag = "results-load";

    public async Task<PollResultsRead> GetAsync(long pollId, long? currentUserId, CancellationToken ct)
    {
        // Кеш вимкнено для порівняльного прогону лаби 5 (ADR 0046): кожне читання — запит до БД. Лише тут результати
        // можна читати з репліки (ADR 0050): відповідь застаріє на затримку реплікації, але нікуди не збережеться.
        if (!cache.Enabled)
        {
            var direct = await shards.ReadFor(pollId).EventualAsync(currentUserId, source => LoadAsync(source, pollId, cache.LoadDelay, timeProvider, ct));
            if (direct.Response.Status == PollStatus.Draft && direct.CreatorId != currentUserId)
                throw new PollNotFoundException(pollId);
            return new PollResultsRead(direct.Response, CacheResult.Disabled);
        }

        // Cache-Aside (ADR 0041). Кеш містить і CreatorId, тому на попадання видимість перевіряється без звернення до БД.
        var lookup = await cache.GetAsync(pollId);
        var (load, source) = lookup switch
        {
            { Entry: { } cached } => (new ResultsLoad(cached, DbNodes.None), CacheResult.Hit),
            // Промах: одночасні промахи інстансу по цьому поколінню чекають одне читання з Primary (ADR 0044) — воно ж
            // записує агрегат під поколінням, прочитаним до запиту в БД (ADR 0041). Не з репліки (ADR 0050): вона ще може
            // не мати голосу, що підняв покоління, і старий агрегат потрапив би в спільний кеш під новим поколінням.
            { Generation: { } generation } => (await LoadMissAsync(pollId, generation, ct), CacheResult.Miss),
            // Redis недоступний (ADR 0043): читаємо з БД і нічого не пишемо — без покоління запис повернув би гонку з
            // лаби 2. І не об'єднуємо: без покоління не видно, чи почалося спільне читання вже після мутації.
            _ => (await LoadBypassAsync(pollId, ct), CacheResult.Bypass)
        };

        if (load.Entry.Response.Status == PollStatus.Draft && load.Entry.CreatorId != currentUserId)
            throw new PollNotFoundException(pollId);

        return new PollResultsRead(load.Entry.Response, source, load.Node);
    }

    /// <summary>
    /// Промах. Без захисту (лаба 8, режим «до») кожен промах сам іде в Primary і сам пише в кеш — так відтворюється
    /// Cache Stampede: поки перший не записав агрегат, усі, хто встиг промахнутися, рахують той самий агрегат.
    /// </summary>
    private Task<ResultsLoad> LoadMissAsync(long pollId, long generation, CancellationToken ct) =>
        cache.Protection == StampedeProtection.None
            ? LoadAndCacheAsync(shards, cache, pollId, generation, timeProvider, ct)
            : singleFlight.LoadAsync(pollId, generation, ct);

    private async Task<ResultsLoad> LoadBypassAsync(long pollId, CancellationToken ct)
    {
        var (entry, node) = await shards.ReadFor(pollId).PrimaryPreferredAsync(source => LoadAsync(source, pollId, cache.LoadDelay, timeProvider, ct));
        return new ResultsLoad(entry, node);
    }

    /// <summary>
    /// Читання для промаху: з Primary (ADR 0050), репліка — лише коли він лежить (ADR 0052): старі результати кращі за
    /// помилку. У кеш, під поколінням <paramref name="generation"/>, — лише дані Primary: якщо монітор помилився і голоси
    /// ще йдуть, агрегат із репліки отруїв би кеш (ADR 0051).
    /// </summary>
    internal static async Task<ResultsLoad> LoadAndCacheAsync(ShardContexts shards, ResultsCache cache, long pollId,
        long generation, TimeProvider timeProvider, CancellationToken ct)
    {
        var (entry, node) = await shards.ReadFor(pollId).PrimaryPreferredAsync(db => LoadAsync(db, pollId, cache.LoadDelay, timeProvider, ct));
        if (node == DbNodes.Primary)
            await cache.SetAsync(pollId, generation, entry);
        return new ResultsLoad(entry, node);
    }

    /// <summary>Агрегат з БД, без кешу. <c>GeneratedAt</c> — момент цього читання.</summary>
    internal static async Task<CachedPollResults> LoadAsync(
        AppDbContext db, long pollId, TimeSpan delay, TimeProvider timeProvider, CancellationToken ct)
    {
        // Імітація важкого агрегату (лаба 8, ADR 0060): з'єднання зайняте, як під час довгого запиту, — саме так
        // Thundering Herd вичерпує пул. Вимкнено за замовчуванням.
        if (delay > TimeSpan.Zero)
            await db.Database.ExecuteSqlAsync($"SELECT pg_sleep({delay.TotalSeconds})", ct);

        // Тег — коментар у SQL: за ним pg_stat_statements рахує звернення до БД за агрегатом (лаба 8, ADR 0060).
        var poll = await db.Polls.AsNoTracking()
            .TagWith(ResultsLoadTag)
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
