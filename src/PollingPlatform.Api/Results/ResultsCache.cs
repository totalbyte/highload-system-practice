using System.Text.Json;
using System.Text.Json.Serialization;
using StackExchange.Redis;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Кеш результатів у Redis — спільний для всіх інстансів (лаба 2, ADR 0026). Інвалідація, зроблена
/// одним інстансом, одразу видна іншим; у пам'яті процесу кеш не тримає нічого, лише посилання
/// на спільне з'єднання, тому singleton тут безпечний.
/// </summary>
public class ResultsCache(IConnectionMultiplexer redis)
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

    public async Task<CachedPollResults?> GetAsync(long pollId)
    {
        var value = await redis.GetDatabase().StringGetAsync(Key(pollId));
        return value.IsNull ? null : JsonSerializer.Deserialize<CachedPollResults>((byte[])value!, Json);
    }

    public Task SetAsync(long pollId, CachedPollResults entry) =>
        redis.GetDatabase().StringSetAsync(Key(pollId), JsonSerializer.SerializeToUtf8Bytes(entry, Json), new Expiration(Ttl));

    public Task InvalidateAsync(long pollId) => redis.GetDatabase().KeyDeleteAsync(Key(pollId));

    private static string Key(long pollId) => $"results:{pollId}";
}
