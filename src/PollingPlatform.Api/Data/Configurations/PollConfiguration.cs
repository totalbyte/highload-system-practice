using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Data.Configurations;

public class PollConfiguration : IEntityTypeConfiguration<Poll>
{
    public void Configure(EntityTypeBuilder<Poll> builder)
    {
        builder.ToTable("polls", t =>
        {
            t.HasCheckConstraint("ck_polls_status", "status IN ('draft', 'active', 'closed')");
            t.HasCheckConstraint("ck_polls_dates", "starts_at IS NULL OR starts_at < ends_at");
        });

        // Id видає глобальна послідовність poll_ids на Shard A (лаба 7, ADR 0054): власний автоінкремент кожного шарду
        // роздав би однакові id, а роутеру id потрібен ще до вставки, щоб вибрати шард.
        builder.Property(p => p.Id).ValueGeneratedNever();
        builder.Property(p => p.Title).HasMaxLength(200).IsRequired();
        builder.Property(p => p.CreatorUsername).HasMaxLength(50).IsRequired();
        builder.Property(p => p.Description).HasMaxLength(2000);
        builder.Property(p => p.Status)
            .HasConversion(s => s.ToString().ToLowerInvariant(), s => Enum.Parse<PollStatus>(s, true))
            .HasMaxLength(16);
        builder.Property(p => p.CreatedAt).HasDefaultValueSql("now()");

        // FK на users немає (лаба 7): users лежить на Shard A, а опитування — на будь-якому шарді, і зовнішній ключ між
        // різними базами неможливий. Автора бере з JWT сам застосунок. Індекс лишається для фільтра «мої опитування».
        builder.HasIndex(p => p.CreatorId);

        builder.HasMany(p => p.Options)
            .WithOne(o => o.Poll)
            .HasForeignKey(o => o.PollId)
            .OnDelete(DeleteBehavior.Cascade);

        // Список опитувань фільтрується за статусом і сортується за датою створення.
        builder.HasIndex(p => new { p.Status, p.CreatedAt });
    }
}
