using Microsoft.Extensions.Caching.Memory;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Кеш результатів у пам'яті процесу — навмисне рішення лаби 1 (ADR 0013): саме він є об'єктом
/// аудиту стану в лабі 2, де переїде в Redis. Не виносити раніше, ніж цього вимагає лаба.
/// </summary>
public class ResultsCache(IMemoryCache cache)
{
    /// <summary>
    /// Основний механізм актуальності — явна інвалідація при голосі та закритті опитування.
    /// TTL лишається страховкою: у лабі 2 з кількома інстансами він обмежує розбіжність кешів,
    /// бо інвалідація доходить лише до того інстанса, який обробив запис.
    /// </summary>
    private static readonly TimeSpan Ttl = TimeSpan.FromSeconds(10);

    public CachedPollResults? Get(long pollId) => cache.Get<CachedPollResults>(Key(pollId));

    public void Set(long pollId, CachedPollResults entry) => cache.Set(Key(pollId), entry, Ttl);

    public void Invalidate(long pollId) => cache.Remove(Key(pollId));

    private static string Key(long pollId) => $"results:{pollId}";
}
