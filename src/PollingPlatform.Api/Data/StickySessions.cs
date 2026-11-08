using PollingPlatform.Api.Auth;
using StackExchange.Redis;

namespace PollingPlatform.Api.Data;

/// <summary>
/// Read-After-Write через Session Sticky Routing (лаба 6, ADR 0051): після успішного запису всі eventual-читання цього
/// користувача протягом TTL ідуть на Primary. Позначка лежить у Redis, а не в пам'яті процесу: наступний запит
/// балансувальник може віддати іншому інстансу (stateless, лаба 2).
/// TTL має перевищувати затримку реплікації: це компроміс механізму, виміряний у scripts/stale-read-demo.py.
/// </summary>
public class StickySessions(IConnectionMultiplexer redis, IConfiguration configuration, ILogger<StickySessions> logger)
{
    /// <summary><c>0</c> вимикає механізм: так демо показує Stale Read у самого автора запису.</summary>
    private readonly TimeSpan ttl = TimeSpan.FromSeconds(configuration.GetValue("ReadAfterWrite:StickyTtlSeconds", 5));

    public bool Enabled => ttl > TimeSpan.Zero;

    /// <summary>
    /// Best-effort, як інвалідація кешу (ADR 0043): запис уже закомічено, і збій Redis не повинен зробити його помилкою
    /// для клієнта. Захист при цьому не втрачається: поки Redis недоступний, <see cref="IsStickyAsync"/> відповідає true.
    /// </summary>
    public async Task MarkAsync(long userId)
    {
        try
        {
            await redis.GetDatabase().StringSetAsync(Key(userId), 1, new Expiration(ttl));
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            logger.LogWarning("Sticky mark not stored for user {UserId}, Redis unavailable: {Error}", userId, ex.Message);
        }
    }

    /// <summary>
    /// Redis недоступний — true: не можна знати, чи писав користувач щойно, тож безпечний вибір — Primary.
    /// Ціна помилки в цей бік — зайве навантаження на Primary, а не застарілі дані.
    /// </summary>
    public async ValueTask<bool> IsStickyAsync(long userId)
    {
        if (!Enabled)
            return false;
        try
        {
            return await redis.GetDatabase().KeyExistsAsync(Key(userId));
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            // Debug: під час збою це рядок на кожне читання; сам збій видно з Warning при записах.
            logger.LogDebug("Sticky check for user {UserId} falls back to the primary, Redis unavailable: {Error}", userId, ex.Message);
            return true;
        }
    }

    private static bool IsUnavailable(Exception ex) => ex is RedisConnectionException or RedisTimeoutException;

    private static string Key(long userId) => $"polling:sticky:{userId}";
}

public static class StickySessionsExtensions
{
    /// <summary>
    /// Ставить позначку за кожну успішну мутацію автентифікованого користувача, в одному місці, а не в кожному сервісі.
    /// OnStarting, а не код після next(): клієнт не отримає відповідь раніше за позначку, інакше його наступне читання
    /// могло б випередити її і піти на репліку. Має стояти після UseAuthentication: потрібен користувач із токена.
    /// </summary>
    public static IApplicationBuilder UseStickyAfterWrite(this IApplicationBuilder app)
    {
        var sticky = app.ApplicationServices.GetRequiredService<StickySessions>();
        if (!sticky.Enabled)
            return app;

        return app.Use((context, next) =>
        {
            if (!HttpMethods.IsGet(context.Request.Method) && !HttpMethods.IsHead(context.Request.Method)
                && context.User.FindUserId() is { } userId)
            {
                context.Response.OnStarting(() =>
                    context.Response.StatusCode is >= 200 and < 300 ? sticky.MarkAsync(userId) : Task.CompletedTask);
            }
            return next(context);
        });
    }
}
