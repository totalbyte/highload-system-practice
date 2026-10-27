using System.Text.Json;
using System.Text.Json.Serialization;
using StackExchange.Redis;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Кеш результатів у Redis — спільний для всіх інстансів (лаба 2, ADR 0026). Інвалідація, зроблена
/// одним інстансом, одразу видна іншим; у пам'яті процесу кеш не тримає нічого, лише посилання
/// на спільне з'єднання, тому singleton тут безпечний.
/// </summary>
public class ResultsCache(IConnectionMultiplexer redis, ILogger<ResultsCache> logger)
{
    /// <summary>
    /// Основний механізм актуальності — явна інвалідація при голосі, publish, close і delete.
    /// TTL лишається страховкою на випадок пропущеної інвалідації; обґрунтування його величини — лаба 4.
    /// </summary>
    private static readonly TimeSpan Ttl = TimeSpan.FromSeconds(10);

    // Статус рядком, як в API: значення в Redis читабельне з redis-cli і не залежить від порядку членів enum.
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) }
    };

    /// <summary>Недоступний Redis тут не перехоплюється: без fallback на БД (лаба 4) це 503 для клієнта (ADR 0027).</summary>
    public async Task<CachedPollResults?> GetAsync(long pollId)
    {
        var value = await redis.GetDatabase().StringGetAsync(Key(pollId));
        return value.IsNull ? null : JsonSerializer.Deserialize<CachedPollResults>((byte[])value!, Json);
    }

    /// <summary>Best-effort: відповідь уже порахована з БД, віддати її краще, ніж 503 через недоступний кеш.</summary>
    public async Task SetAsync(long pollId, CachedPollResults entry)
    {
        try
        {
            await redis.GetDatabase().StringSetAsync(
                Key(pollId), JsonSerializer.SerializeToUtf8Bytes(entry, Json), new Expiration(Ttl));
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            logger.LogWarning("Results cache unavailable, poll {PollId} not cached: {Error}", pollId, ex.Message);
        }
    }

    /// <summary>
    /// Best-effort: викликається вже після коміту зміни в БД, тож збій кешу не повинен перетворювати успішний
    /// голос чи publish на помилку для клієнта (той би повторив запит і отримав 409 на записаний голос).
    /// Застарілий запис, якщо він уцілів, зникне за TTL (ADR 0027).
    /// </summary>
    public async Task InvalidateAsync(long pollId)
    {
        try
        {
            await redis.GetDatabase().KeyDeleteAsync(Key(pollId));
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            logger.LogWarning("Results cache unavailable, results:{PollId} not invalidated; a stale entry expires within {Ttl} s: {Error}",
                pollId, Ttl.TotalSeconds, ex.Message);
        }
    }

    private static bool IsUnavailable(Exception ex) => ex is RedisConnectionException or RedisTimeoutException;

    private static string Key(long pollId) => $"results:{pollId}";
}
