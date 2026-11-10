using System.Net.Sockets;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using PollingPlatform.Api.Common.Exceptions;

namespace PollingPlatform.Api.Data;

/// <summary>
/// Маршрутизація читань (лаба 6, ADR 0050). За замовчуванням увесь код працює з <see cref="AppDbContext"/>, тобто з
/// Primary, а цей клас запитують лише читання, яким дозволена eventual consistency. Так забута класифікація дає зайве
/// навантаження на Primary, а не застарілі дані.
/// Читання передається функцією: якщо вибраний вузол відмовить, його можна повторити на іншому (ADR 0052).
/// Контекст репліки створюється лише за потреби: більшість запитів його не торкається.
/// З лаби 7 у кожного шарду свій ReadDb (його створює ShardContexts): Primary і Replica — вузли саме цього шарду.
/// replica == null — репліка вимкнена або не задана (конфігурація Single Primary).
/// </summary>
public sealed class ReadDb(
    AppDbContext primary, DbContextOptions<AppDbContext>? replica, StickySessions sticky, DbNodeMonitor monitor, ILogger<ReadDb> logger)
    : IAsyncDisposable
{
    private AppDbContext? replicaContext;

    /// <summary>
    /// Читання, що допускає відставання від Primary. Користувач, який щойно писав, читає з Primary, щоб побачити власні
    /// зміни (ADR 0051). Анонімний запит писати не міг, тож до Redis не звертається.
    /// </summary>
    public async Task<T> EventualAsync<T>(long? userId, Func<AppDbContext, Task<T>> read)
    {
        var preferPrimary = userId is { } id && await sticky.IsStickyAsync(id);
        return (await ReadAsync(preferPrimary, read)).Value;
    }

    /// <summary>
    /// Читання, яке мусить іти на Primary, поки той живий. Репліка лише запасний шлях; вузол, що відповів, повертається,
    /// бо від нього залежить, чи можна зберегти результат (результати в кеші, ADR 0052).
    /// </summary>
    public Task<(T Value, DbNodes Node)> PrimaryPreferredAsync<T>(Func<AppDbContext, Task<T>> read) => ReadAsync(preferPrimary: true, read);

    private async Task<(T Value, DbNodes Node)> ReadAsync<T>(bool preferPrimary, Func<AppDbContext, Task<T>> read)
    {
        if (replica is null)
            return (await read(primary), DbNodes.Primary);

        // Обидва вузли шарду лежать (лаба 7, ADR 0057): спроба підключення до зупиненого вузла чекала б пошуку імені
        // через Docker DNS ~3–5 с, а відповідь однаково буде 503.
        if (!monitor.PrimaryAvailable && !monitor.ReplicaAvailable)
            throw new ShardUnavailableException("The database shard holding this poll is unavailable. Please retry later.");

        var first = (preferPrimary ? monitor.PrimaryAvailable : !monitor.ReplicaAvailable) ? DbNodes.Primary : DbNodes.Replica;
        // Монітор бачить відмову із запізненням до кількох секунд; за цей час запит рятує повтор на іншому вузлі.
        try
        {
            return (await read(Context(first)), first);
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            var second = first == DbNodes.Primary ? DbNodes.Replica : DbNodes.Primary;
            logger.LogDebug("Read fell back from {First} to {Second}: {Error}", first, second, ex.Message);
            return (await read(Context(second)), second);
        }
    }

    private AppDbContext Context(DbNodes node) => node == DbNodes.Primary ? primary : replicaContext ??= new AppDbContext(replica!);

    /// <summary>Вузол недоступний (а не помилка запиту): це читання можна повторити деінде або пропустити шард (лаба 7).</summary>
    public static bool IsUnavailable(Exception ex) => ex switch
    {
        ReadOnlyModeException or ShardUnavailableException or TimeoutException or SocketException or IOException => true,
        NpgsqlException { IsTransient: true } => true,
        // 57P01 / 57P02 / 57P03: сервер зупиняється або ще стартує.
        PostgresException { SqlState: "57P01" or "57P02" or "57P03" } => true,
        _ => ex.InnerException is { } inner && IsUnavailable(inner)
    };

    public ValueTask DisposeAsync() => replicaContext?.DisposeAsync() ?? ValueTask.CompletedTask;
}
