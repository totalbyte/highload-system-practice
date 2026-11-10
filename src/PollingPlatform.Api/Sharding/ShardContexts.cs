using PollingPlatform.Api.Data;

namespace PollingPlatform.Api.Sharding;

/// <summary>
/// Доступ до шардів у межах одного запиту (лаба 7, ADR 0055). Сервіс опитувань не вибирає базу сам: він передає
/// <c>poll_id</c>, а роутер повертає контекст потрібного шарду. Контексти створюються лише за потреби, тож запит
/// до одного опитування відкриває з'єднання лише з одним шардом.
/// Для Shard A повертається той самий <see cref="AppDbContext"/>, що й для таблиці users, — один контекст на базу.
/// </summary>
public sealed class ShardContexts(
    AppDbContext shardA, IReadOnlyList<Shard> shards, ShardRouter router, StickySessions sticky, ILogger<ReadDb> logger)
    : IAsyncDisposable
{
    private readonly AppDbContext?[] primaries = new AppDbContext?[shards.Count];
    private readonly ReadDb?[] reads = new ReadDb?[shards.Count];

    public int Count => shards.Count;

    public int ShardOf(long pollId) => router.ShardFor(pollId);

    /// <summary>Primary шарду, якому належить опитування: усі записи і строгі читання.</summary>
    public AppDbContext PrimaryFor(long pollId) => Primary(ShardOf(pollId));

    /// <summary>Читання з шарду опитування з маршрутизацією Primary / Replica з лаби 6.</summary>
    public ReadDb ReadFor(long pollId) => Read(ShardOf(pollId));

    public AppDbContext Primary(int shard)
    {
        if (shard == 0)
            return shardA;
        return primaries[shard] ??= new AppDbContext(shards[shard].PrimaryOptions);
    }

    public ReadDb Read(int shard) =>
        reads[shard] ??= new ReadDb(Primary(shard), shards[shard].ReplicaOptions, sticky, shards[shard].Monitor, logger);

    public async ValueTask DisposeAsync()
    {
        foreach (var read in reads)
        {
            if (read is not null)
                await read.DisposeAsync();
        }
        // primaries[0] — це shardA, його звільняє DI.
        for (var i = 1; i < primaries.Length; i++)
        {
            if (primaries[i] is { } context)
                await context.DisposeAsync();
        }
    }
}
