using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Common.Exceptions;

public class PollNotFoundException(long pollId)
    : NotFoundException($"Poll {pollId} was not found.");

/// <summary>Операція недопустима в поточному статусі опитування (напр. видалення активного).</summary>
public class InvalidPollStateException(long pollId, PollStatus actual, string operation)
    : ConflictException($"Cannot {operation} poll {pollId}: poll is {actual.ToString().ToLowerInvariant()}.");
