using Microsoft.EntityFrameworkCore;
using Npgsql;
using PollingPlatform.Api.Common.Exceptions;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Domain;
using PollingPlatform.Api.Results;

namespace PollingPlatform.Api.Votes;

/// <summary>
/// Голосування — пікова операція системи (High-Load сценарій: масовий наплив голосів в одне опитування).
/// Вставка голосу і оновлення денормалізованого лічильника <c>options.vote_count</c> виконуються
/// в одній транзакції, інакше лічильник розійдеться з кількістю рядків у <c>votes</c>.
/// </summary>
public class VoteService(AppDbContext db, ResultsCache resultsCache, TimeProvider timeProvider)
{
    public async Task<CastVoteResult> CastAsync(long pollId, long userId, long optionId, CancellationToken ct)
    {
        var allowVoteChange = await LoadVotablePollAsync(pollId, userId, ct);

        // Складеного FK (poll_id, option_id) у схемі немає, тому належність варіанта перевіряємо явно.
        var optionExists = await db.Options.AnyAsync(o => o.Id == optionId && o.PollId == pollId, ct);
        if (!optionExists)
            throw new PollOptionNotFoundException(pollId, optionId);

        var now = timeProvider.GetUtcNow();
        var strategy = db.Database.CreateExecutionStrategy();
        var result = await strategy.ExecuteAsync(
            token => CastOnceAsync(pollId, userId, optionId, allowVoteChange, now, token), ct);

        resultsCache.Invalidate(pollId);
        return result;
    }

    /// <summary>
    /// Перевіряє, що опитування існує, видиме користувачу, активне і в межах часового вікна.
    /// Повертає <c>AllowVoteChange</c> — єдине, що потрібно далі.
    /// </summary>
    private async Task<bool> LoadVotablePollAsync(long pollId, long userId, CancellationToken ct)
    {
        var poll = await db.Polls.AsNoTracking()
            .Where(p => p.Id == pollId)
            .Select(p => new { p.CreatorId, p.Status, p.StartsAt, p.EndsAt, p.AllowVoteChange })
            .FirstOrDefaultAsync(ct);

        // Чужа чернетка не розкривається навіть фактом існування (ADR 0003).
        if (poll is null || (poll.Status == PollStatus.Draft && poll.CreatorId != userId))
            throw new PollNotFoundException(pollId);
        if (poll.Status != PollStatus.Active)
            throw new InvalidPollStateException(pollId, poll.Status, "vote in");

        var now = timeProvider.GetUtcNow();
        if (poll.StartsAt is { } startsAt && now < startsAt)
            throw new PollNotStartedException(pollId, startsAt);
        // Статус може лишатися active після EndsAt — фонового закривача немає.
        if (now >= poll.EndsAt)
            throw new PollVotingEndedException(pollId, poll.EndsAt);

        return poll.AllowVoteChange;
    }

    private sealed record ExistingVote(long Id, long OptionId, DateTimeOffset CreatedAt);

    private async Task<CastVoteResult> CastOnceAsync(
        long pollId, long userId, long optionId, bool allowVoteChange, DateTimeOffset now, CancellationToken ct)
    {
        db.ChangeTracker.Clear(); // прибрати сутності з невдалої попередньої спроби retry-стратегії
        await using var tx = await db.Database.BeginTransactionAsync(ct);

        var existing = await db.Votes
            .Where(v => v.PollId == pollId && v.UserId == userId)
            .Select(v => new ExistingVote(v.Id, v.OptionId, v.CreatedAt))
            .FirstOrDefaultAsync(ct);

        CastVoteResult result;
        if (existing is null)
        {
            result = await InsertVoteAsync(pollId, userId, optionId, now, ct);
        }
        else if (!allowVoteChange)
        {
            throw new DuplicateVoteException(pollId);
        }
        else if (existing.OptionId == optionId)
        {
            // Ідемпотентність: повтор того самого голосу не чіпає лічильники (безпечно при retry під навантаженням).
            result = new CastVoteResult(pollId, optionId, existing.CreatedAt, Created: false);
        }
        else
        {
            await db.Votes.Where(v => v.Id == existing.Id)
                .ExecuteUpdateAsync(s => s
                    .SetProperty(v => v.OptionId, optionId)
                    .SetProperty(v => v.CreatedAt, now), ct);

            await ChangeVoteCountAsync(existing.OptionId, -1, ct);
            await ChangeVoteCountAsync(optionId, +1, ct);
            result = new CastVoteResult(pollId, optionId, now, Created: false);
        }

        await tx.CommitAsync(ct);
        return result;
    }

    private async Task<CastVoteResult> InsertVoteAsync(
        long pollId, long userId, long optionId, DateTimeOffset now, CancellationToken ct)
    {
        db.Votes.Add(new Vote { PollId = pollId, OptionId = optionId, UserId = userId, CreatedAt = now });
        try
        {
            await db.SaveChangesAsync(ct);
        }
        catch (DbUpdateException ex) when (ex.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation })
        {
            // Два одночасні голоси того самого користувача: перевірку вище пройшли обидва, унікальний
            // індекс (poll_id, user_id) пропустив лише один. Саме індекс, а не перевірка, є гарантією
            // «один голос на користувача».
            throw new DuplicateVoteException(pollId);
        }

        await ChangeVoteCountAsync(optionId, +1, ct);
        return new CastVoteResult(pollId, optionId, now, Created: true);
    }

    /// <summary>
    /// Інкремент на рівні SQL (<c>vote_count = vote_count + delta</c>), а не load-modify-save:
    /// паралельні голоси не перетирають чужі зміни (lost update).
    /// </summary>
    private Task ChangeVoteCountAsync(long optionId, int delta, CancellationToken ct) =>
        db.Options.Where(o => o.Id == optionId)
            .ExecuteUpdateAsync(s => s.SetProperty(o => o.VoteCount, o => o.VoteCount + delta), ct);
}
