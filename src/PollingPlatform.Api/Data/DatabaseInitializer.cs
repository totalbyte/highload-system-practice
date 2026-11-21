using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using PollingPlatform.Api.Data.Seeding;
using PollingPlatform.Api.Sharding;

namespace PollingPlatform.Api.Data;

public static class DatabaseInitializer
{
    // Довільна константа для pg_advisory_lock: міграції одного шарду виконує лише один інстанс за раз (див. нижче).
    private const long MigrationLockKey = 7_140_002;

    /// <summary>
    /// Застосовує EF-міграції і (опційно) сід при старті — стек піднімається без ручних кроків.
    /// Кілька інстансів можуть стартувати одночасно на чистій БД: міграції й сід серіалізує advisory lock
    /// (docs/ai/decisions/0009, 0022, 0070).
    /// </summary>
    public static async Task InitializeDatabaseAsync(this WebApplication app)
    {
        await using var scope = app.Services.CreateAsyncScope();
        var services = scope.ServiceProvider;
        var logger = services.GetRequiredService<ILogger<AppDbContext>>();

        if (app.Configuration.GetValue("Database:MigrateOnStartup", true))
        {
            // Схема однакова на всіх шардах (лаба 7): кожен отримує ті самі міграції.
            var shards = services.GetRequiredService<ShardContexts>();
            for (var shard = 0; shard < shards.Count; shard++)
            {
                logger.LogInformation("Applying database migrations to shard {Shard}...", ShardRouter.Name(shard));
                await MigrateUnderLockAsync(shards.Primary(shard));
            }
        }

        if (services.GetRequiredService<IOptions<SeedOptions>>().Value.Enabled)
            await services.GetRequiredService<DataSeeder>().SeedAsync();
    }

    /// <summary>
    /// Блокування історії міграцій провайдера виявилося недостатнім (лаба 9, ADR 0070): на холодному старті два інстанси
    /// інколи обидва виконували ShardPollAggregate на Shard A, і другий падав на вже видаленому FK. Сесійний advisory lock
    /// на з'єднанні, яке тримає відкритим сам контекст, пропускає до MigrateAsync по одному інстансу; другий бачить уже
    /// застосовані міграції. Якщо інстанс упаде, PostgreSQL зніме lock разом із його сесією.
    /// </summary>
    private static async Task MigrateUnderLockAsync(AppDbContext db)
    {
        await db.Database.OpenConnectionAsync();
        try
        {
            await db.Database.ExecuteSqlAsync($"SELECT pg_advisory_lock({MigrationLockKey})");
            await db.Database.MigrateAsync();
        }
        finally
        {
            await db.Database.ExecuteSqlAsync($"SELECT pg_advisory_unlock({MigrationLockKey})");
            await db.Database.CloseConnectionAsync();
        }
    }
}
