namespace PollingPlatform.Api.Domain;

public class Vote
{
    public long Id { get; set; }
    public long PollId { get; set; }
    public long OptionId { get; set; }
    public long UserId { get; set; }
    public DateTimeOffset CreatedAt { get; set; }

    public Poll? Poll { get; set; }
    public PollOption? Option { get; set; }
    public User? User { get; set; }
}
