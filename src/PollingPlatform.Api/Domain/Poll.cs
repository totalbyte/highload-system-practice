namespace PollingPlatform.Api.Domain;

public class Poll
{
    public long Id { get; set; }
    public required string Title { get; set; }
    public string? Description { get; set; }
    public long CreatorId { get; set; }

    /// <summary>
    /// Копія імені автора (лаба 7, ADR 0054): users лежить лише на Shard A, тож JOIN polls → users став би розподіленим.
    /// Ім'я користувача в цьому API змінити не можна, тому копія не застаріває.
    /// </summary>
    public required string CreatorUsername { get; set; }
    public PollStatus Status { get; set; } = PollStatus.Draft;
    public bool IsPublic { get; set; } = true;
    public bool AllowVoteChange { get; set; }

    /// <summary>Початок голосування. null — голосування стартує одразу після публікації.</summary>
    public DateTimeOffset? StartsAt { get; set; }

    public DateTimeOffset EndsAt { get; set; }
    public DateTimeOffset CreatedAt { get; set; }

    public List<PollOption> Options { get; set; } = [];
    public List<Vote> Votes { get; set; } = [];
}
