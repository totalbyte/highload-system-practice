using Microsoft.EntityFrameworkCore;

namespace PollingPlatform.Api.Data;

/// <summary>
/// Налаштування контексту репліки. Options == null — репліка вимкнена або не задана (конфігурація Single Primary).
/// </summary>
public sealed record ReplicaContextOptions(DbContextOptions<AppDbContext>? Options);

/// <summary>
/// Маршрутизація читань (лаба 6, ADR 0050). За замовчуванням увесь код працює з <see cref="AppDbContext"/>, тобто з
/// Primary, а цей клас запитують лише читання, яким дозволена eventual consistency. Так забута класифікація дає зайве
/// навантаження на Primary, а не застарілі дані.
/// Контекст репліки створюється лише за потреби: більшість запитів його не торкається.
/// </summary>
public sealed class ReadDb(AppDbContext primary, ReplicaContextOptions replica, StickySessions sticky) : IAsyncDisposable
{
    private AppDbContext? replicaContext;

    /// <summary>
    /// Контекст для читання, що допускає відставання від Primary. Користувач, який щойно писав, читає з Primary, щоб
    /// побачити власні зміни (ADR 0051). Анонімний запит писати не міг, тож до Redis не звертається.
    /// </summary>
    public async ValueTask<AppDbContext> ForEventualReadAsync(long? userId)
    {
        if (replica.Options is not { } options)
            return primary;
        if (userId is { } id && await sticky.IsStickyAsync(id))
            return primary;
        return replicaContext ??= new AppDbContext(options);
    }

    public ValueTask DisposeAsync() => replicaContext?.DisposeAsync() ?? ValueTask.CompletedTask;
}
