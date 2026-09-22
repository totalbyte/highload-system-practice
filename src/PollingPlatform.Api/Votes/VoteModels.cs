namespace PollingPlatform.Api.Votes;

public record CastVoteRequest(long? OptionId);

public record CastVoteResponse(long PollId, long OptionId, DateTimeOffset VotedAt);

/// <summary><paramref name="Created"/> розрізняє новий голос (201) і зміну чи повтор наявного (200).</summary>
public record CastVoteResult(long PollId, long OptionId, DateTimeOffset VotedAt, bool Created);
