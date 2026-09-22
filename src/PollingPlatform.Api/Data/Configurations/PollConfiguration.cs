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

        builder.Property(p => p.Title).HasMaxLength(200).IsRequired();
        builder.Property(p => p.Description).HasMaxLength(2000);
        builder.Property(p => p.Status)
            .HasConversion(s => s.ToString().ToLowerInvariant(), s => Enum.Parse<PollStatus>(s, true))
            .HasMaxLength(16);
        builder.Property(p => p.CreatedAt).HasDefaultValueSql("now()");

        builder.HasOne(p => p.Creator)
            .WithMany(u => u.Polls)
            .HasForeignKey(p => p.CreatorId)
            .OnDelete(DeleteBehavior.Restrict);

        builder.HasMany(p => p.Options)
            .WithOne(o => o.Poll)
            .HasForeignKey(o => o.PollId)
            .OnDelete(DeleteBehavior.Cascade);

        // Список опитувань фільтрується за статусом і сортується за датою створення.
        builder.HasIndex(p => new { p.Status, p.CreatedAt });
    }
}
