namespace PollingPlatform.Api.Domain;

/// <summary>Варіант відповіді. У БД — таблиця <c>options</c>.</summary>
public class PollOption
{
    public long Id { get; set; }
    public long PollId { get; set; }
    public required string Text { get; set; }
    public int Position { get; set; }

    /// <summary>Денормалізований лічильник голосів; оновлюється в одній транзакції зі вставкою Vote.</summary>
    public int VoteCount { get; set; }

    public Poll? Poll { get; set; }
}
