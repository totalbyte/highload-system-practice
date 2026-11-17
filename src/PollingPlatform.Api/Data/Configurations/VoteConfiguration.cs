using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Data.Configurations;

public class VoteConfiguration : IEntityTypeConfiguration<Vote>
{
    public void Configure(EntityTypeBuilder<Vote> builder)
    {
        builder.ToTable("votes");

        builder.Property(v => v.CreatedAt).HasDefaultValueSql("now()");

        builder.HasOne(v => v.Poll)
            .WithMany(p => p.Votes)
            .HasForeignKey(v => v.PollId)
            .OnDelete(DeleteBehavior.Cascade);

        builder.HasOne(v => v.Option)
            .WithMany()
            .HasForeignKey(v => v.OptionId)
            .OnDelete(DeleteBehavior.Cascade);

        // FK votes.user_id → users прибрано в лабі 7 з тієї ж причини, що й polls.creator_id: users — на іншому вузлі.

        // Один голос від користувача на опитування. Індекс також покриває вибірки votes за poll_id.
        builder.HasIndex(v => new { v.PollId, v.UserId }).IsUnique();
    }
}
