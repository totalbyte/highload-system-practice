namespace PollingPlatform.Api.Domain;

public class User
{
    public long Id { get; set; }
    public required string Username { get; set; }
    public required string Email { get; set; }
    public required string PasswordHash { get; set; }
    public DateTimeOffset CreatedAt { get; set; }

    public List<Poll> Polls { get; set; } = [];
}
