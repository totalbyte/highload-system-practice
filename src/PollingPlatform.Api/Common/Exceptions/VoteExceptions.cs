namespace PollingPlatform.Api.Common.Exceptions;

/// <summary>Варіант відповіді не належить цьому опитуванню (складеного FK у БД немає — перевіряє сервіс).</summary>
public class PollOptionNotFoundException(long pollId, long optionId)
    : NotFoundException($"Option {optionId} was not found in poll {pollId}.");

/// <summary>Опитування активне, але голосування ще не почалося (now &lt; StartsAt).</summary>
public class PollNotStartedException(long pollId, DateTimeOffset startsAt)
    : ConflictException($"Cannot vote in poll {pollId}: voting starts at {startsAt:O}.");

/// <summary>
/// Час голосування вичерпано (now >= EndsAt). Статус при цьому може лишатися active:
/// фонового закривача немає, тому дати перевіряються на кожен голос.
/// </summary>
public class PollVotingEndedException(long pollId, DateTimeOffset endsAt)
    : ConflictException($"Cannot vote in poll {pollId}: voting ended at {endsAt:O}.");

/// <summary>Користувач уже голосував, а зміна голосу для цього опитування заборонена.</summary>
public class DuplicateVoteException(long pollId)
    : ConflictException($"You have already voted in poll {pollId}.");
