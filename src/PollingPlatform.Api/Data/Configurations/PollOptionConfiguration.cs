using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Data.Configurations;

public class PollOptionConfiguration : IEntityTypeConfiguration<PollOption>
{
    public void Configure(EntityTypeBuilder<PollOption> builder)
    {
        builder.ToTable("options", t =>
            t.HasCheckConstraint("ck_options_vote_count", "vote_count >= 0"));

        builder.Property(o => o.Text).HasMaxLength(200).IsRequired();
        builder.Property(o => o.VoteCount).HasDefaultValue(0);

        // Позиція варіанта унікальна в межах опитування; індекс також покриває пошук options за poll_id.
        builder.HasIndex(o => new { o.PollId, o.Position }).IsUnique();
    }
}
