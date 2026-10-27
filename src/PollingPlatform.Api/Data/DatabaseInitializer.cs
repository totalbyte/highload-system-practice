using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using PollingPlatform.Api.Data.Seeding;

namespace PollingPlatform.Api.Data;

public static class DatabaseInitializer
{
    /// <summary>
    /// Застосовує EF-міграції і (опційно) сід при старті — стек піднімається без ручних кроків.
    /// Кілька інстансів можуть стартувати одночасно на чистій БД: міграції серіалізує провайдер
    /// (LOCK TABLE історії міграцій), сід — advisory lock (docs/ai/decisions/0009, 0022).
    /// </summary>
    public static async Task InitializeDatabaseAsync(this WebApplication app)
    {
        await using var scope = app.Services.CreateAsyncScope();
        var services = scope.ServiceProvider;
        var logger = services.GetRequiredService<ILogger<AppDbContext>>();

        if (app.Configuration.GetValue("Database:MigrateOnStartup", true))
        {
            logger.LogInformation("Applying database migrations...");
            await services.GetRequiredService<AppDbContext>().Database.MigrateAsync();
        }

        if (services.GetRequiredService<IOptions<SeedOptions>>().Value.Enabled)
            await services.GetRequiredService<DataSeeder>().SeedAsync();
    }
}
