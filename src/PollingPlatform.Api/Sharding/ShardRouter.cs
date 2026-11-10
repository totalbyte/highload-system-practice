namespace PollingPlatform.Api.Sharding;

/// <summary>Як <c>poll_id</c> перетворюється на номер шарду (лаба 7, ADR 0055).</summary>
public enum ShardStrategy
{
    /// <summary>Діапазони id: 0..RangeSize-1 — Shard A, далі — Shard B. Аналог «шард за часовим інтервалом».</summary>
    Range,
    /// <summary>id % N — найпростіше, але при зміні N переїжджає більшість даних.</summary>
    Modulo,
    /// <summary>hash(id) % N.</summary>
    Hash,
    /// <summary>hash(id) % Buckets → таблиця «бакет → шард» (Virtual Buckets).</summary>
    Buckets
}

/// <summary>
/// Детермінований Shard Router (лаба 7, 2.2): за ключем шардингу <c>poll_id</c> (ADR 0054) повертає номер шарду.
/// Відповідь залежить лише від id і конфігурації, тож усі інстанси backend маршрутизують однаково без спільного стану.
/// Стратегію не можна міняти на томі з даними: опитування лежать там, куди їх поклала стратегія при записі.
/// </summary>
public class ShardRouter
{
    private readonly int[] bucketMap;

    public ShardRouter(IConfiguration configuration)
    {
        ShardCount = Math.Max(1, configuration.GetValue("Sharding:ShardCount", 2));
        Strategy = configuration.GetValue("Sharding:Strategy", ShardStrategy.Buckets);
        RangeSize = Math.Max(1, configuration.GetValue("Sharding:RangeSize", 1000));
        BucketCount = Math.Max(1, configuration.GetValue("Sharding:Buckets", 64));

        // За замовчуванням бакети розкладені по шардах по колу: 0 → A, 1 → B, 2 → A ... При решардингу змінюється лише
        // ця таблиця, і переїжджають тільки рядки перепризначених бакетів (лаба 7, 2.5).
        bucketMap = new int[BucketCount];
        for (var bucket = 0; bucket < BucketCount; bucket++)
            bucketMap[bucket] = bucket % ShardCount;
    }

    public int ShardCount { get; }
    public ShardStrategy Strategy { get; }
    public int RangeSize { get; }
    public int BucketCount { get; }

    public int ShardFor(long pollId)
    {
        if (ShardCount == 1)
            return 0;

        switch (Strategy)
        {
            case ShardStrategy.Range:
                return (int)Math.Min(pollId / RangeSize, ShardCount - 1);
            case ShardStrategy.Modulo:
                return (int)(pollId % ShardCount);
            case ShardStrategy.Hash:
                return (int)(Hash(pollId) % (ulong)ShardCount);
            default:
                return bucketMap[BucketFor(pollId)];
        }
    }

    public int BucketFor(long pollId) => (int)(Hash(pollId) % (ulong)BucketCount);

    /// <summary>Ім'я шарду для заголовка X-Shard і логів: 0 → A, 1 → B.</summary>
    public static string Name(int shard) => ((char)('A' + shard)).ToString();

    /// <summary>
    /// Фіналізатор MurmurHash3 (fmix64): сусідні id дають зовсім різні хеші. Не string.GetHashCode — той у .NET
    /// випадковий для кожного процесу, і два інстанси маршрутизували б по-різному. Той самий код є в scripts/shardlib.py.
    /// </summary>
    public static ulong Hash(long key)
    {
        var k = (ulong)key;
        k ^= k >> 33;
        k *= 0xff51afd7ed558ccdUL;
        k ^= k >> 33;
        k *= 0xc4ceb9fe1a85ec53UL;
        k ^= k >> 33;
        return k;
    }
}
