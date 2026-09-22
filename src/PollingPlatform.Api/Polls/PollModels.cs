using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Polls;

public record CreatePollRequest(
    string? Title,
    string? Description,
    List<string>? Options,
    DateTimeOffset? EndsAt,
    DateTimeOffset? StartsAt = null,
    bool IsPublic = true,
    bool AllowVoteChange = false);

public class PollListQuery
{
    /// <summary>Фільтр за статусом: draft / active / closed.</summary>
    public PollStatus? Status { get; init; }

    /// <summary>Фільтр за автором.</summary>
    public long? CreatorId { get; init; }

    public int Page { get; init; } = 1;
    public int PageSize { get; init; } = 20;
}

public record OptionResponse(long Id, string Text, int Position);

public record PollSummaryResponse(
    long Id,
    string Title,
    PollStatus Status,
    bool IsPublic,
    long CreatorId,
    string CreatorUsername,
    int OptionsCount,
    DateTimeOffset? StartsAt,
    DateTimeOffset EndsAt,
    DateTimeOffset CreatedAt);

public record PollDetailsResponse(
    long Id,
    string Title,
    string? Description,
    PollStatus Status,
    bool IsPublic,
    bool AllowVoteChange,
    long CreatorId,
    string CreatorUsername,
    DateTimeOffset? StartsAt,
    DateTimeOffset EndsAt,
    DateTimeOffset CreatedAt,
    IReadOnlyList<OptionResponse> Options);

public record PagedResponse<T>(IReadOnlyList<T> Items, int Page, int PageSize, int TotalCount);
