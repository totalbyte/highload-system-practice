using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Results;

public record OptionResultResponse(long Id, string Text, int Position, int Votes, double Percentage);

/// <summary>
/// <paramref name="GeneratedAt"/> — момент, коли агрегат порахували з БД. При повторному запиті
/// значення не змінюється, поки віддається кешована відповідь.
/// </summary>
public record PollResultsResponse(
    long PollId,
    string Title,
    PollStatus Status,
    int TotalVotes,
    DateTimeOffset GeneratedAt,
    IReadOnlyList<OptionResultResponse> Options);

/// <summary>Кешований агрегат разом із даними, потрібними для перевірки видимості без звернення до БД.</summary>
public record CachedPollResults(long CreatorId, PollResultsResponse Response);
