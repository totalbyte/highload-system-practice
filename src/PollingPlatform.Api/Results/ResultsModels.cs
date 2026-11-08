using PollingPlatform.Api.Data;
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

/// <summary>Звідки взята відповідь — значення заголовка <c>X-Cache</c> (лаба 4, 2.6.1).</summary>
public enum CacheResult
{
    /// <summary>Знайдено в Redis, БД не зачіпалась.</summary>
    Hit,

    /// <summary>У Redis не було — прочитано з БД і покладено в кеш.</summary>
    Miss,

    /// <summary>Redis недоступний — прочитано прямо з БД, у кеш нічого не записано (fallback, ADR 0043).</summary>
    Bypass,

    /// <summary>Кеш вимкнено конфігурацією (<c>ResultsCache:Enabled=false</c>) — прочитано з БД (лаба 5, ADR 0046).</summary>
    Disabled
}

/// <summary><paramref name="Node"/> — вузол БД, що дав дані, якщо читання йшло в обхід кешу чи об'єднувалося з чужим.</summary>
public record PollResultsRead(PollResultsResponse Response, CacheResult Cache, DbNodes Node = DbNodes.None);

/// <summary>Результат спільного читання при промаху кешу: дані й вузол, з якого їх прочитано.</summary>
public record ResultsLoad(CachedPollResults Entry, DbNodes Node);
