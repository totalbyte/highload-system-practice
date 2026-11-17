using PollingPlatform.Api.Common.Exceptions;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Sharding;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Одне читання агрегату з БД на весь кластер (лаба 8, ADR 0061). Single-flight (ADR 0044) об'єднує промахи лише в
/// межах інстансу, тож на N інстансах stampede коштує N читань. Тут перед читанням береться lock у Redis на
/// (опитування, покоління): хто взяв — читає БД і пише кеш; решта (по одному запиту з інстансу — single-flight стоїть
/// перед цим класом) перечитують кеш цього покоління, доки агрегат не з'явиться.
/// Від deadlock і вічного очікування захищають дві межі часу: lease lock (власник, що впав чи завис, звільняє його
/// сам) і загальний час очікування, після якого чекач читає БД сам.
/// </summary>
public class ResultsDistributedLock(ResultsCache cache, TimeProvider timeProvider, ILogger<ResultsDistributedLock> logger)
{
    /// <summary>
    /// Lease з великим запасом над звичайним читанням (мілісекунди навіть під stampede): довше тримає лише власник, що впав чи завис. Якщо
    /// lease спливе посеред читання, наступний візьме lock і прочитає БД ще раз — це зайве читання, а не помилка:
    /// обидва пишуть той самий агрегат під тим самим поколінням.
    /// </summary>
    public static readonly TimeSpan Lease = TimeSpan.FromSeconds(1);

    /// <summary>Більше за lease: спершу має спрацювати сплив lease, а це — остання межа, якщо Redis поводиться дивно.</summary>
    private static readonly TimeSpan MaxWait = TimeSpan.FromSeconds(2);

    /// <summary>Пауза між перевірками кешу: короткий GET у Redis від одного запиту з інстансу.</summary>
    private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(10);

    public async Task<ResultsLoad> LoadAsync(ShardContexts shards, long pollId, long generation)
    {
        var token = Guid.NewGuid().ToString("N");
        var deadline = timeProvider.GetUtcNow() + MaxWait;
        while (true)
        {
            // Спершу кеш, потім lock: запит, що запізнився (промахнувся за мить до запису), не бере вже вільний lock і
            // не читає БД вдруге — у ADR 0044 саме такі давали «2.2 замість 2».
            if (await CachedAsync(pollId, generation) is { } ready)
                return ready;

            switch (await cache.TryLockAsync(pollId, generation, token, Lease))
            {
                case LockAttempt.Acquired:
                    try
                    {
                        // Між перевіркою кешу і SET NX попередній власник міг записати агрегат і звільнити lock.
                        if (await CachedAsync(pollId, generation) is { } written)
                            return written;
                        logger.LogDebug("Results lock acquired: poll {PollId}, generation {Generation}", pollId, generation);
                        return await LoadAndCacheAsync(shards, pollId, generation);
                    }
                    finally
                    {
                        if (!await cache.ReleaseLockAsync(pollId, generation, token))
                            logger.LogWarning("Results lock lease of {Lease} s expired before the load of poll {PollId}, " +
                                              "generation {Generation} finished; another request may have loaded it too",
                                Lease.TotalSeconds, pollId, generation);
                    }

                case LockAttempt.Unavailable:
                    // Redis впав посеред промаху: чекати нічого — читаємо самі (SetAsync теж нічого не зламає).
                    return await LoadAndCacheAsync(shards, pollId, generation);
            }

            if (timeProvider.GetUtcNow() >= deadline)
            {
                logger.LogWarning("Results lock wait of {MaxWait} s exceeded: poll {PollId}, generation {Generation}; " +
                                  "loading without the lock", MaxWait.TotalSeconds, pollId, generation);
                return await LoadAndCacheAsync(shards, pollId, generation);
            }

            // Розкид паузи: чекачі з різних інстансів не б'ють у Redis синхронно.
            await Task.Delay(PollInterval + TimeSpan.FromMilliseconds(Random.Shared.Next(10)), timeProvider);
        }
    }

    /// <summary>Значення цього покоління з кешу; негативний запис (ADR 0063) — 404 тим, хто чекав, без читання БД.</summary>
    private async Task<ResultsLoad?> CachedAsync(long pollId, long generation)
    {
        var cached = await cache.GetEntryAsync(pollId, generation);
        if (cached.NotFound)
            throw new PollNotFoundException(pollId);
        return cached.Entry is { } entry ? new ResultsLoad(entry, DbNodes.None) : null;
    }

    private Task<ResultsLoad> LoadAndCacheAsync(ShardContexts shards, long pollId, long generation) =>
        ResultsService.LoadAndCacheAsync(shards, cache, pollId, generation, timeProvider, CancellationToken.None);
}
