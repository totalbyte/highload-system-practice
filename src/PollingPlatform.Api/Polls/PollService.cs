using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Query;
using PollingPlatform.Api.Common.Exceptions;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Domain;
using PollingPlatform.Api.Results;
using PollingPlatform.Api.Sharding;

namespace PollingPlatform.Api.Polls;

/// <summary>
/// Життєвий цикл опитування: створення, перегляд, публікація, закриття, видалення.
/// Правила видимості: чернетку бачить лише автор; непублічні (IsPublic = false) опитування
/// не показуються в загальному списку, але доступні за прямим id.
/// Каталог і деталі читаються через <see cref="ReadDb"/> (eventual consistency, ADR 0050); усе, що приймає рішення перед
/// записом або повертає результат запису, — лише з Primary.
/// Опитування лежать на шардах за poll_id (лаба 7, ADR 0054): операція з одним опитуванням іде на один шард через
/// <see cref="ShardContexts"/>, а каталог опитує всі шарди (Scatter-Gather). <paramref name="db"/> — Shard A: users і poll_ids.
/// </summary>
public class PollService(AppDbContext db, ShardContexts shards, ResultsCache resultsCache, TimeProvider timeProvider)
{
    public async Task<PollDetailsResponse> CreateAsync(long userId, CreatePollRequest request, CancellationToken ct)
    {
        // Ім'я автора копіюється в опитування (ADR 0054), щоб каталогу не був потрібен JOIN з users на іншому вузлі.
        var username = await db.Users.Where(u => u.Id == userId).Select(u => u.Username).FirstOrDefaultAsync(ct)
            ?? throw new UnauthorizedException("The user from the token no longer exists.");

        // Id — з глобальної послідовності на Shard A, і лише за ним роутер вибирає шард. Номер, узятий запитом, що потім
        // упав, просто пропадає: дірки в id нічого не ламають.
        var pollId = await NextPollIdAsync(ct);

        var poll = new Poll
        {
            Id = pollId,
            Title = request.Title!.Trim(),
            Description = string.IsNullOrWhiteSpace(request.Description) ? null : request.Description.Trim(),
            CreatorId = userId,
            CreatorUsername = username,
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
        var shard = shards.PrimaryFor(pollId);
        shard.Polls.Add(poll);
        await shard.SaveChangesAsync(ct);

        return await LoadDetailsAsync(shard, poll.Id, userId, ct);
    }

    /// <summary>
    /// Каталог — Cross-Shard запит (лаба 7, 2.4): кожен шард паралельно віддає свою частину, далі злиття тут.
    /// Шард не знає, які опитування є на інших, тому для сторінки N кожен повертає перші N × PageSize рядків, а сторінку
    /// вирізаємо вже зі злитого списку. Ціна росте з номером сторінки й кількістю шардів — це і є оверхед fan-out.
    /// Шард, у якого не відповідає жоден вузол, пропускається (ADR 0057): каталог — eventual-читання, і неповний список
    /// кращий за 503 для всіх, поки опитування живого шарду доступні. Яких шардів бракує, видно в UnavailableShards.
    /// </summary>
    public async Task<CatalogPage> ListAsync(PollListQuery query, long? currentUserId, CancellationToken ct)
    {
        var tasks = new List<Task<(int TotalCount, List<PollSummaryResponse> Items)?>>();
        for (var shard = 0; shard < shards.Count; shard++)
            tasks.Add(LoadShardPartAsync(shard, query, currentUserId, ct));
        var parts = await Task.WhenAll(tasks);

        var totalCount = 0;
        var all = new List<PollSummaryResponse>();
        var unavailable = new List<string>();
        for (var shard = 0; shard < parts.Length; shard++)
        {
            if (parts[shard] is not { } part)
            {
                unavailable.Add(ShardRouter.Name(shard));
                continue;
            }
            totalCount += part.TotalCount;
            all.AddRange(part.Items);
        }
        // Не відповів жоден шард — це вже не неповний каталог, а відмова: та сама 503, що й до лаби 7.
        if (unavailable.Count == shards.Count)
            throw new ShardUnavailableException("No database shard is available. Please retry later.");

        // Той самий порядок, що й на кожному шарді: нові спочатку, при однаковому часі — більший id.
        var items = all
            .OrderByDescending(p => p.CreatedAt).ThenByDescending(p => p.Id)
            .Skip((query.Page - 1) * query.PageSize)
            .Take(query.PageSize)
            .ToList();

        return new CatalogPage(new PagedResponse<PollSummaryResponse>(items, query.Page, query.PageSize, totalCount), unavailable);
    }

    private async Task<(int TotalCount, List<PollSummaryResponse> Items)?> LoadShardPartAsync(
        int shard, PollListQuery query, long? currentUserId, CancellationToken ct)
    {
        try
        {
            return await shards.Read(shard).EventualAsync(currentUserId, source => LoadListPartAsync(source, query, currentUserId, ct));
        }
        catch (Exception ex) when (ReadDb.IsUnavailable(ex))
        {
            return null;
        }
    }

    private static async Task<(int TotalCount, List<PollSummaryResponse> Items)> LoadListPartAsync(
        AppDbContext source, PollListQuery query, long? currentUserId, CancellationToken ct)
    {
        var polls = source.Polls.AsNoTracking()
            .Where(p => (p.IsPublic && p.Status != PollStatus.Draft) || p.CreatorId == currentUserId);

        if (query.Status is { } status)
            polls = polls.Where(p => p.Status == status);
        if (query.CreatorId is { } creatorId)
            polls = polls.Where(p => p.CreatorId == creatorId);

        var totalCount = await polls.CountAsync(ct);
        var items = await polls
            .OrderByDescending(p => p.CreatedAt).ThenByDescending(p => p.Id)
            .Take(query.Page * query.PageSize)
            .Select(p => new PollSummaryResponse(
                p.Id, p.Title, p.Status, p.IsPublic, p.CreatorId, p.CreatorUsername,
                p.Options.Count, p.StartsAt, p.EndsAt, p.CreatedAt))
            .ToListAsync(ct);

        return (totalCount, items);
    }

    public Task<PollDetailsResponse> GetAsync(long pollId, long? currentUserId, CancellationToken ct) =>
        shards.ReadFor(pollId).EventualAsync(currentUserId, source => LoadDetailsAsync(source, pollId, currentUserId, ct));

    private static async Task<PollDetailsResponse> LoadDetailsAsync(
        AppDbContext source, long pollId, long? currentUserId, CancellationToken ct)
    {
        var poll = await source.Polls.AsNoTracking()
            .Where(p => p.Id == pollId)
            .Select(p => new PollDetailsResponse(
                p.Id, p.Title, p.Description, p.Status, p.IsPublic, p.AllowVoteChange,
                p.CreatorId, p.CreatorUsername, p.StartsAt, p.EndsAt, p.CreatedAt,
                p.Options.OrderBy(o => o.Position).Select(o => new OptionResponse(o.Id, o.Text, o.Position)).ToList()))
            .FirstOrDefaultAsync(ct);

        if (poll is null || (poll.Status == PollStatus.Draft && poll.CreatorId != currentUserId))
            throw new PollNotFoundException(pollId);

        return poll;
    }

    /// <summary>Draft → Active. Якщо StartsAt не задано, голосування стартує з моменту публікації.</summary>
    public async Task<PollDetailsResponse> PublishAsync(long pollId, long userId, CancellationToken ct)
    {
        var shard = shards.PrimaryFor(pollId);
        var poll = await GetOwnedPollStateAsync(shard, pollId, userId, ct);
        if (poll.Status != PollStatus.Draft)
            throw new InvalidPollStateException(pollId, poll.Status, "publish");

        var now = timeProvider.GetUtcNow();
        if (poll.EndsAt <= now)
            throw new ConflictException($"Cannot publish poll {pollId}: its end date has already passed.");

        await TransitionAsync(shard, pollId, PollStatus.Draft, PollStatus.Active, "publish", ct,
            s => s.SetProperty(p => p.StartsAt, p => p.StartsAt ?? now));
        await resultsCache.InvalidateAsync(pollId);

        return await LoadDetailsAsync(shard, pollId, userId, ct);
    }

    /// <summary>Active → Closed: дострокове закриття, лише автор.</summary>
    public async Task<PollDetailsResponse> CloseAsync(long pollId, long userId, CancellationToken ct)
    {
        var shard = shards.PrimaryFor(pollId);
        var poll = await GetOwnedPollStateAsync(shard, pollId, userId, ct);
        if (poll.Status != PollStatus.Active)
            throw new InvalidPollStateException(pollId, poll.Status, "close");

        await TransitionAsync(shard, pollId, PollStatus.Active, PollStatus.Closed, "close", ct);
        // Кешована відповідь містить статус опитування, тож після закриття вона застаріла.
        await resultsCache.InvalidateAsync(pollId);

        return await LoadDetailsAsync(shard, pollId, userId, ct);
    }

    /// <summary>Видалення дозволене лише для чернеток — у них ще немає голосів.</summary>
    public async Task DeleteAsync(long pollId, long userId, CancellationToken ct)
    {
        var shard = shards.PrimaryFor(pollId);
        var poll = await GetOwnedPollStateAsync(shard, pollId, userId, ct);
        if (poll.Status != PollStatus.Draft)
            throw new InvalidPollStateException(pollId, poll.Status, "delete");

        // Умова на статус у самому DELETE захищає від гонки з паралельним publish.
        var deleted = await shard.Polls
            .Where(p => p.Id == pollId && p.Status == PollStatus.Draft)
            .ExecuteDeleteAsync(ct);

        if (deleted == 0)
            throw await StateChangedConcurrentlyAsync(shard, pollId, "delete", ct);

        await resultsCache.InvalidateAsync(pollId);
    }

    private Task<long> NextPollIdAsync(CancellationToken ct) =>
        db.Database.SqlQueryRaw<long>($"SELECT nextval('{AppDbContext.PollIdSequence}') AS \"Value\"").SingleAsync(ct);

    private sealed record PollState(long CreatorId, PollStatus Status, DateTimeOffset EndsAt);

    /// <summary>Перевіряє існування опитування і те, що поточний користувач — його автор.</summary>
    private static async Task<PollState> GetOwnedPollStateAsync(AppDbContext shard, long pollId, long userId, CancellationToken ct)
    {
        var poll = await shard.Polls.AsNoTracking()
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
    private static async Task TransitionAsync(
        AppDbContext shard, long pollId, PollStatus from, PollStatus to, string operation, CancellationToken ct,
        Action<UpdateSettersBuilder<Poll>>? extraSetters = null)
    {
        var updated = await shard.Polls
            .Where(p => p.Id == pollId && p.Status == from)
            .ExecuteUpdateAsync(s =>
            {
                s.SetProperty(p => p.Status, to);
                extraSetters?.Invoke(s);
            }, ct);

        if (updated == 0)
            throw await StateChangedConcurrentlyAsync(shard, pollId, operation, ct);
    }

    private static async Task<Exception> StateChangedConcurrentlyAsync(AppDbContext shard, long pollId, string operation, CancellationToken ct)
    {
        var status = await shard.Polls.Where(p => p.Id == pollId).Select(p => (PollStatus?)p.Status).FirstOrDefaultAsync(ct);
        return status is null ? new PollNotFoundException(pollId) : new InvalidPollStateException(pollId, status.Value, operation);
    }
}
