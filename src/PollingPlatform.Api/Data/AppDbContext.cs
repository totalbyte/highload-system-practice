using Microsoft.EntityFrameworkCore;
using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Data;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public const string PollIdSequence = "poll_ids";

    public DbSet<User> Users => Set<User>();
    public DbSet<Poll> Polls => Set<Poll>();
    public DbSet<PollOption> Options => Set<PollOption>();
    public DbSet<Vote> Votes => Set<Vote>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(AppDbContext).Assembly);

        // Глобальні id опитувань (лаба 7, ADR 0054). Схема однакова на всіх шардах, але nextval викликається лише на Shard A.
        modelBuilder.HasSequence<long>(PollIdSequence);

        // Статистика запитів PostgreSQL: скільки разів агрегат результатів читали з БД під Cache Stampede (лаба 8,
        // ADR 0060). Бібліотеку вантажить сам сервер (shared_preload_libraries у compose), тут — лише view для читання.
        modelBuilder.HasPostgresExtension("pg_stat_statements");
    }
}
