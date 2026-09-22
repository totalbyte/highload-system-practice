using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Query;
using PollingPlatform.Api.Common.Exceptions;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Polls;

/// <summary>
/// Життєвий цикл опитування: створення, перегляд, публікація, закриття, видалення.
/// Правила видимості: чернетку бачить лише автор; непублічні (IsPublic = false) опитування
/// не показуються в загальному списку, але доступні за прямим id.
/// </summary>
public class PollService(AppDbContext db, TimeProvider timeProvider)
{
    public async Task<PollDetailsResponse> CreateAsync(long userId, CreatePollRequest request, CancellationToken ct)
    {
        var poll = new Poll
        {
            Title = request.Title!.Trim(),
            Description = string.IsNullOrWhiteSpace(request.Description) ? null : request.Description.Trim(),
            CreatorId = userId,
            Status = PollStatus.Draft,
            IsPublic = request.IsPublic,
            AllowVoteChange = request.AllowVoteChange,
            StartsAt = request.StartsAt,
            EndsAt = request.EndsAt!.Value,
            CreatedAt = timeProvider.GetUtcNow(),
            Options = request.Options!
                .Select((text, index) => new PollOption { Text = text.Trim(), Position = index + 1 })
                .ToList()
        };

        // Одна транзакція, один SaveChanges: EF відправляє INSERT опитування і всіх варіантів батчем,
        // а не окремим round-trip на кожен варіант (див. bottleneck N+1 у README).
        db.Polls.Add(poll);
        await db.SaveChangesAsync(ct);

        return await GetAsync(poll.Id, userId, ct);
    }

    public async Task<PagedResponse<PollSummaryResponse>> ListAsync(PollListQuery query, long? currentUserId, CancellationToken ct)
    {
        var polls = db.Polls.AsNoTracking()
            .Where(p => (p.IsPublic && p.Status != PollStatus.Draft) || p.CreatorId == currentUserId);

        if (query.Status is { } status)
            polls = polls.Where(p => p.Status == status);
        if (query.CreatorId is { } creatorId)
            polls = polls.Where(p => p.CreatorId == creatorId);

        var totalCount = await polls.CountAsync(ct);
        var items = await polls
            .OrderByDescending(p => p.CreatedAt).ThenByDescending(p => p.Id)
            .Skip((query.Page - 1) * query.PageSize)
            .Take(query.PageSize)
            .Select(p => new PollSummaryResponse(
                p.Id, p.Title, p.Status, p.IsPublic, p.CreatorId, p.Creator!.Username,
                p.Options.Count, p.StartsAt, p.EndsAt, p.CreatedAt))
            .ToListAsync(ct);

        return new PagedResponse<PollSummaryResponse>(items, query.Page, query.PageSize, totalCount);
    }

    public async Task<PollDetailsResponse> GetAsync(long pollId, long? currentUserId, CancellationToken ct)
    {
        var poll = await db.Polls.AsNoTracking()
            .Where(p => p.Id == pollId)
            .Select(p => new PollDetailsResponse(
                p.Id, p.Title, p.Description, p.Status, p.IsPublic, p.AllowVoteChange,
                p.CreatorId, p.Creator!.Username, p.StartsAt, p.EndsAt, p.CreatedAt,
                p.Options.OrderBy(o => o.Position).Select(o => new OptionResponse(o.Id, o.Text, o.Position)).ToList()))
            .FirstOrDefaultAsync(ct);

        if (poll is null || (poll.Status == PollStatus.Draft && poll.CreatorId != currentUserId))
            throw new PollNotFoundException(pollId);

        return poll;
    }

    /// <summary>Draft → Active. Якщо StartsAt не задано, голосування стартує з моменту публікації.</summary>
    public async Task<PollDetailsResponse> PublishAsync(long pollId, long userId, CancellationToken ct)
    {
        var poll = await GetOwnedPollStateAsync(pollId, userId, ct);
        if (poll.Status != PollStatus.Draft)
            throw new InvalidPollStateException(pollId, poll.Status, "publish");

        var now = timeProvider.GetUtcNow();
        if (poll.EndsAt <= now)
            throw new ConflictException($"Cannot publish poll {pollId}: its end date has already passed.");

        await TransitionAsync(pollId, PollStatus.Draft, PollStatus.Active, "publish", ct,
            s => s.SetProperty(p => p.StartsAt, p => p.StartsAt ?? now));

        return await GetAsync(pollId, userId, ct);
    }

    /// <summary>Active → Closed: дострокове закриття, лише автор.</summary>
    public async Task<PollDetailsResponse> CloseAsync(long pollId, long userId, CancellationToken ct)
    {
        var poll = await GetOwnedPollStateAsync(pollId, userId, ct);
        if (poll.Status != PollStatus.Active)
            throw new InvalidPollStateException(pollId, poll.Status, "close");

        await TransitionAsync(pollId, PollStatus.Active, PollStatus.Closed, "close", ct);
        // TODO(Учасник 2): інвалідувати кеш результатів цього опитування.

        return await GetAsync(pollId, userId, ct);
    }

    /// <summary>Видалення дозволене лише для чернеток — у них ще немає голосів.</summary>
    public async Task DeleteAsync(long pollId, long userId, CancellationToken ct)
    {
        var poll = await GetOwnedPollStateAsync(pollId, userId, ct);
        if (poll.Status != PollStatus.Draft)
            throw new InvalidPollStateException(pollId, poll.Status, "delete");

        // Умова на статус у самому DELETE захищає від гонки з паралельним publish.
        var deleted = await db.Polls
            .Where(p => p.Id == pollId && p.Status == PollStatus.Draft)
            .ExecuteDeleteAsync(ct);

        if (deleted == 0)
            throw await StateChangedConcurrentlyAsync(pollId, "delete", ct);
    }

    private sealed record PollState(long CreatorId, PollStatus Status, DateTimeOffset EndsAt);

    /// <summary>Перевіряє існування опитування і те, що поточний користувач — його автор.</summary>
    private async Task<PollState> GetOwnedPollStateAsync(long pollId, long userId, CancellationToken ct)
    {
        var poll = await db.Polls.AsNoTracking()
            .Where(p => p.Id == pollId)
            .Select(p => new PollState(p.CreatorId, p.Status, p.EndsAt))
            .FirstOrDefaultAsync(ct);

        if (poll is null || (poll.Status == PollStatus.Draft && poll.CreatorId != userId))
            throw new PollNotFoundException(pollId);
        if (poll.CreatorId != userId)
            throw new ForbiddenException("Only the author can manage this poll.");

        return poll;
    }

    /// <summary>
    /// Атомарний перехід статусу: UPDATE ... WHERE status = @from. Якщо паралельний запит
    /// встиг змінити статус між перевіркою і оновленням, змінено 0 рядків → 409.
    /// </summary>
    private async Task TransitionAsync(
        long pollId, PollStatus from, PollStatus to, string operation, CancellationToken ct,
        Action<UpdateSettersBuilder<Poll>>? extraSetters = null)
    {
        var updated = await db.Polls
            .Where(p => p.Id == pollId && p.Status == from)
            .ExecuteUpdateAsync(s =>
            {
                s.SetProperty(p => p.Status, to);
                extraSetters?.Invoke(s);
            }, ct);

        if (updated == 0)
            throw await StateChangedConcurrentlyAsync(pollId, operation, ct);
    }

    private async Task<Exception> StateChangedConcurrentlyAsync(long pollId, string operation, CancellationToken ct)
    {
        var status = await db.Polls.Where(p => p.Id == pollId).Select(p => (PollStatus?)p.Status).FirstOrDefaultAsync(ct);
        return status is null ? new PollNotFoundException(pollId) : new InvalidPollStateException(pollId, status.Value, operation);
    }
}
