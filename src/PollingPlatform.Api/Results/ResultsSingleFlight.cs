using System.Collections.Concurrent;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Sharding;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Захист від Cache Stampede (лаба 4, ADR 0044): одночасні промахи по тому самому опитуванню й поколінню в межах
/// інстансу чекають одне спільне читання з БД, а не йдуть у PostgreSQL кожен окремо. У нас stampede виникає після
/// кожного голосу в гаряче опитування: голос скидає кеш, і всі глядачі дашборду промахуються разом.
/// Ключ — (pollId, покоління): той, хто прочитав покоління g, приєднується лише до читання, яке почалося після того, як
/// він сам прочитав g, тож гарантія «читання після мутації бачить мутацію» (ADR 0041) зберігається.
/// Стан тут — лише запити, що виконуються в цю мить; падіння інстансу нічого не губить, тому singleton безпечний.
/// </summary>
public class ResultsSingleFlight(
    IServiceScopeFactory scopes, ResultsCache cache, TimeProvider timeProvider, ILogger<ResultsSingleFlight> logger)
{
    private readonly ConcurrentDictionary<(long PollId, long Generation), Lazy<Task<ResultsLoad>>> inFlight = new();

    /// <summary>
    /// Агрегат для промаху: спільне читання з БД із записом у кеш під поколінням <paramref name="generation"/>.
    /// Скасування запиту <paramref name="ct"/> перериває лише очікування цього клієнта, а не спільне читання.
    /// </summary>
    public Task<ResultsLoad> LoadAsync(long pollId, long generation, CancellationToken ct)
    {
        var key = (pollId, generation);
        // Lazy: GetOrAdd може викликати фабрику кількох потоків, але виконається лише Value того, хто потрапив у словник.
        var flight = new Lazy<Task<ResultsLoad>>(() => LoadAndCacheAsync(key));
        var current = inFlight.GetOrAdd(key, flight);
        if (!ReferenceEquals(current, flight))
            logger.LogDebug("Results cache MISS joined an in-flight load: poll {PollId}, generation {Generation}",
                pollId, generation);
        return current.Value.WaitAsync(ct);
    }

    /// <summary>
    /// Власний scope, а не DbContext запиту, що почав читання: якщо той клієнт відключиться, ASP.NET звільнить його
    /// scope, а на результат чекають інші. З тієї ж причини — без його CancellationToken.
    /// </summary>
    private async Task<ResultsLoad> LoadAndCacheAsync((long PollId, long Generation) key)
    {
        try
        {
            await using var scope = scopes.CreateAsyncScope();
            var readDb = scope.ServiceProvider.GetRequiredService<ShardContexts>().ReadFor(key.PollId);
            // Читання з Primary (ADR 0050). Репліка — лише коли він лежить (ADR 0052): старі результати кращі за помилку.
            var (entry, node) = await readDb.PrimaryPreferredAsync(
                db => ResultsService.LoadAsync(db, key.PollId, timeProvider, CancellationToken.None));
            // Запис у кеш — до виходу з польоту: хто прочитає кеш після цього, отримає HIT, а не почне новий політ.
            // У кеш лише дані Primary: якщо монітор помилився і голоси ще йдуть, агрегат із репліки отруїв би кеш (ADR 0051).
            if (node == DbNodes.Primary)
                await cache.SetAsync(key.PollId, key.Generation, entry);
            return new ResultsLoad(entry, node);
        }
        finally
        {
            // Поки політ у словнику, інший для того самого ключа не з'явиться, тож видаляємо саме його.
            inFlight.TryRemove(key, out _);
        }
    }
}
