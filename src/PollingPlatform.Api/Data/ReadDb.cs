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
public sealed class ReadDb(AppDbContext primary, ReplicaContextOptions replica) : IAsyncDisposable
{
    private AppDbContext? replicaContext;

    /// <summary>Контекст для читання, що допускає відставання від Primary.</summary>
    public AppDbContext Eventual => replica.Options is { } options
        ? replicaContext ??= new AppDbContext(options)
        : primary;

    public ValueTask DisposeAsync() => replicaContext?.DisposeAsync() ?? ValueTask.CompletedTask;
}
