namespace PollingPlatform.Api.Domain;

public class Poll
{
    public long Id { get; set; }
    public required string Title { get; set; }
    public string? Description { get; set; }
    public long CreatorId { get; set; }
    public PollStatus Status { get; set; } = PollStatus.Draft;
    public bool IsPublic { get; set; } = true;
    public bool AllowVoteChange { get; set; }

    /// <summary>Початок голосування. null — голосування стартує одразу після публікації.</summary>
    public DateTimeOffset? StartsAt { get; set; }

    public DateTimeOffset EndsAt { get; set; }
    public DateTimeOffset CreatedAt { get; set; }

    public User? Creator { get; set; }
    public List<PollOption> Options { get; set; } = [];
    public List<Vote> Votes { get; set; } = [];
}
