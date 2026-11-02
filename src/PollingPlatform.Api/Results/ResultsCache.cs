using System.Text.Json;
using System.Text.Json.Serialization;
using PollingPlatform.Api.Domain;
using StackExchange.Redis;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Результат пошуку в кеші: запис (null — промах) і покоління, під яким його треба записати після читання з БД.
/// Покоління null — Redis недоступний: читаємо з БД і нічого не записуємо (ADR 0043).
/// </summary>
public readonly record struct ResultsCacheLookup(CachedPollResults? Entry, long? Generation)
{
    public static ResultsCacheLookup Unavailable => new(null, null);
}

/// <summary>
/// Кеш результатів у Redis — спільний для всіх інстансів (лаба 2, ADR 0026), Cache-Aside з поколіннями (лаба 4, ADR 0041).
/// Ключ значення — <c>polling:results:v1:{pollId}:g{покоління}</c>; лічильник покоління — <c>polling:results:gen:{pollId}</c>.
/// Інвалідація не видаляє ключ, а збільшує покоління: агрегат, прочитаний з БД до коміту зміни, ляже під старе
/// покоління, яке вже ніхто не читає. Так закрита гонка «прочитали до коміту, записали після DEL» з лаби 2.
/// У пам'яті процесу кеш не тримає нічого, лише посилання на спільне з'єднання, тому singleton тут безпечний.
/// </summary>
public class ResultsCache(IConnectionMultiplexer redis, ILogger<ResultsCache> logger)
{
    /// <summary>
    /// TTL — страховка на випадок втраченої інвалідації, а не механізм актуальності (ADR 0041).
    /// Активне опитування і чернетка можуть змінитися — застарілість обмежена секундами.
    /// </summary>
    private static readonly TimeSpan OpenTtl = TimeSpan.FromSeconds(10);

    /// <summary>Закрите опитування вже не зміниться: голосувати можна лише в активному, а з closed переходів немає.</summary>
    private static readonly TimeSpan ClosedTtl = TimeSpan.FromHours(1);

    /// <summary>Розкид TTL проти Cache Avalanche: записи, створені в одну секунду, не спливають в одну секунду.</summary>
    private const double TtlJitter = 0.2;

    // Покоління і значення за один round-trip. Ключ значення будується зі значення лічильника всередині скрипта —
    // на одному вузлі Redis це коректно; для Redis Cluster знадобився б hash tag (ADR 0041).
    private const string LookupScript = """
        local gen = redis.call('GET', KEYS[1]) or '0'
        return { gen, redis.call('GET', ARGV[1] .. gen) }
        """;

    // INCR і видалення значення попереднього покоління — атомарно. Значення, записане пізніше під старим
    // поколінням (читач стартував до інвалідації), ніхто не прочитає, і воно зникне за своїм TTL.
    private const string InvalidateScript = """
        local gen = redis.call('INCR', KEYS[1])
        redis.call('UNLINK', ARGV[1] .. (gen - 1))
        return gen
        """;

    // Статус рядком, як в API: значення в Redis читабельне з redis-cli і не залежить від порядку членів enum.
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) }
    };

    /// <summary>
    /// Недоступний Redis — не помилка для клієнта, а <see cref="ResultsCacheLookup.Unavailable"/>: кеш лише прискорює,
    /// джерело правди — БД, тож читання йде туди (graceful degradation, ADR 0043). Завдяки fail-fast клієнта
    /// (Program.cs) це відбувається одразу, а не після таймауту.
    /// </summary>
    public async Task<ResultsCacheLookup> GetAsync(long pollId)
    {
        RedisResult[] reply;
        try
        {
            reply = (RedisResult[])(await redis.GetDatabase().ScriptEvaluateAsync(
                LookupScript, [GenerationKey(pollId)], [ValueKeyPrefix(pollId)]))!;
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            // Debug: під час збою це рядок на кожне читання; сам збій видно з Warning при записах та інвалідації.
            logger.LogDebug("Results cache BYPASS: poll {PollId}, Redis unavailable: {Error}", pollId, ex.Message);
            return ResultsCacheLookup.Unavailable;
        }

        var generation = (long)reply[0];
        var entry = reply[1].IsNull ? null : JsonSerializer.Deserialize<CachedPollResults>((byte[])reply[1]!, Json);
        // Debug, а не Information: під навантаженням це рядок на кожне читання. Увімкнути — CACHE_LOG_LEVEL=Debug.
        logger.LogDebug("Results cache {Result}: poll {PollId}, generation {Generation}",
            entry is null ? "MISS" : "HIT", pollId, generation);
        return new ResultsCacheLookup(entry, generation);
    }

    /// <summary>
    /// Записує агрегат під поколінням, прочитаним <b>до</b> звернення до БД (<see cref="GetAsync"/>), а не під поточним.
    /// Best-effort: відповідь уже порахована з БД, віддати її краще, ніж 503 через недоступний кеш.
    /// </summary>
    public async Task SetAsync(long pollId, long generation, CachedPollResults entry)
    {
        try
        {
            var ttl = TtlFor(entry.Response.Status);
            await redis.GetDatabase().StringSetAsync(
                ValueKey(pollId, generation), JsonSerializer.SerializeToUtf8Bytes(entry, Json), new Expiration(ttl));
            logger.LogDebug("Results cache STORE: poll {PollId}, generation {Generation}, status {Status}, TTL {Ttl:0.0} s",
                pollId, generation, entry.Response.Status, ttl.TotalSeconds);
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            logger.LogWarning("Results cache unavailable, poll {PollId} not cached: {Error}", pollId, ex.Message);
        }
    }

    /// <summary>
    /// Best-effort: викликається вже після коміту зміни в БД, тож збій кешу не повинен перетворювати успішний
    /// голос чи publish на помилку для клієнта (той би повторив запит і отримав 409 на записаний голос).
    /// Застарілий запис, якщо він уцілів (короткий збій без рестарту Redis), зникне за TTL активного опитування;
    /// після рестарту Redis порожній — збереження на диск вимкнене (ADR 0043).
    /// </summary>
    public async Task InvalidateAsync(long pollId)
    {
        try
        {
            var generation = (long)await redis.GetDatabase().ScriptEvaluateAsync(
                InvalidateScript, [GenerationKey(pollId)], [ValueKeyPrefix(pollId)]);
            logger.LogDebug("Results cache INVALIDATE: poll {PollId}, generation {Previous} -> {Generation}",
                pollId, generation - 1, generation);
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            logger.LogWarning("Results cache unavailable, poll {PollId} not invalidated; a stale entry expires within {Ttl} s: {Error}",
                pollId, OpenTtl.TotalSeconds * (1 + TtlJitter), ex.Message);
        }
    }

    /// <summary>
    /// TTL за статусом, з яким агрегат порахований: довгий — лише для даних, що вже не зміняться. Запис, зроблений
    /// поки опитування було активним, лишається з коротким TTL, навіть якщо опитування закрили мить потому.
    /// </summary>
    private static TimeSpan TtlFor(PollStatus status) =>
        (status == PollStatus.Closed ? ClosedTtl : OpenTtl) * (1 + Random.Shared.NextDouble() * TtlJitter);

    private static bool IsUnavailable(Exception ex) => ex is RedisConnectionException or RedisTimeoutException;

    // Схема ключів (ADR 0041): domain:entity:format:id:state. Параметрів у відповіді немає, тому й хешу параметрів немає;
    // v1 — версія формату значення: змінили CachedPollResults → v2, і інстанси різних версій не читають JSON одне одного.
    private static string GenerationKey(long pollId) => $"polling:results:gen:{pollId}";

    private static string ValueKeyPrefix(long pollId) => $"polling:results:v1:{pollId}:g";

    private static string ValueKey(long pollId, long generation) => $"{ValueKeyPrefix(pollId)}{generation}";
}
