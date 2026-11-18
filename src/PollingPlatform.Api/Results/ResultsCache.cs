using System.Text.Json;
using System.Text.Json.Serialization;
using PollingPlatform.Api.Domain;
using StackExchange.Redis;

namespace PollingPlatform.Api.Results;

/// <summary>
/// Результат пошуку в кеші: запис (null — промах) і покоління, під яким його треба записати після читання з БД.
/// Покоління null — Redis недоступний: читаємо з БД і нічого не записуємо (ADR 0043).
/// <paramref name="NotFound"/> — у кеші негативний запис: опитування цього покоління в БД немає (лаба 8, ADR 0063).
/// </summary>
public readonly record struct ResultsCacheLookup(CachedPollResults? Entry, long? Generation, bool NotFound = false)
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
public class ResultsCache(IConnectionMultiplexer redis, IConfiguration configuration, ILogger<ResultsCache> logger)
{
    /// <summary>
    /// <c>ResultsCache:Enabled=false</c> — читання результатів ідуть прямо в БД (лаба 5, порівняння cache off / on, ADR 0046).
    /// Інвалідація при цьому працює далі: інакше після повторного ввімкнення кеш віддав би записи, зроблені до вимкнення.
    /// </summary>
    public bool Enabled { get; } = configuration.GetValue("ResultsCache:Enabled", true);

    /// <summary>
    /// Як промахи йдуть у БД (лаба 8, ADR 0060, 0061): <c>None</c> — кожен сам, щоб відтворити Cache Stampede для
    /// порівняння; <c>SingleFlight</c> — захист лаби 4 (одне читання на інстанс); за замовчуванням <c>Lock</c> — одне на кластер.
    /// </summary>
    public StampedeProtection Protection { get; } =
        configuration.GetValue("ResultsCache:StampedeProtection", StampedeProtection.Lock);

    /// <summary>
    /// Діагностика лаби 8 (ADR 0060): наш агрегат дешевий (1–2 мс з денормалізованого <c>vote_count</c>), тож вікно
    /// промаху коротке і stampede ледь помітний. <c>Diagnostics:ResultsLoadDelayMs</c> &gt; 0 імітує важкий агрегат —
    /// кожне читання з БД додатково тримає з'єднання стільки мілісекунд. За замовчуванням 0, як затримка лаби 3 (ADR 0036).
    /// </summary>
    public TimeSpan LoadDelay { get; } =
        TimeSpan.FromMilliseconds(configuration.GetValue("Diagnostics:ResultsLoadDelayMs", 0));

    /// <summary>
    /// Negative Caching проти Cache Penetration (лаба 8, ADR 0063): «опитування немає» теж кешується, з коротким TTL, і
    /// потік запитів до неіснуючих id не доходить до PostgreSQL. <c>ResultsCache:NegativeCaching=false</c> — режим «до».
    /// </summary>
    public bool NegativeCaching { get; } = configuration.GetValue("ResultsCache:NegativeCaching", true);

    /// <summary>
    /// Короткий, бо негативний запис — це і пам'ять Redis під кожен неіснуючий id, і (без інвалідації) час, поки нове
    /// опитування з цим id лишалося б «неіснуючим». Друге закриває інвалідація при створенні; перше обмежує TTL:
    /// пам'ять ≈ частота різних неіснуючих id × TTL.
    /// </summary>
    private static readonly TimeSpan NotFoundTtl = TimeSpan.FromSeconds(30);

    /// <summary>Значення негативного запису. Не JSON (агрегат завжди починається з <c>{</c>), тож не сплутати.</summary>
    private static readonly byte[] NotFoundMarker = "not-found"u8.ToArray();

    /// <summary>
    /// TTL — страховка на випадок втраченої інвалідації, а не механізм актуальності (ADR 0041).
    /// Активне опитування і чернетка можуть змінитися — застарілість обмежена секундами.
    /// </summary>
    private static readonly TimeSpan OpenTtl = TimeSpan.FromSeconds(10);

    /// <summary>Закрите опитування вже не зміниться: голосувати можна лише в активному, а з closed переходів немає.</summary>
    private static readonly TimeSpan ClosedTtl = TimeSpan.FromHours(1);

    /// <summary>
    /// Розкид TTL проти Cache Avalanche (лаба 4; формула <c>Base ± Random</c> — лаба 8, ADR 0062): записи, створені в одну
    /// секунду, не спливають в одну секунду. Частка від базового TTL, 0.2 → ±20 %. <c>ResultsCache:TtlJitter=0</c> вимикає
    /// розкид — лише для демонстрації лавини.
    /// </summary>
    private readonly double ttlJitter = Math.Clamp(configuration.GetValue("ResultsCache:TtlJitter", 0.2), 0, 0.9);

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
        var lookup = Parse(reply[1].IsNull ? null : (byte[])reply[1]!, generation);
        // Debug, а не Information: під навантаженням це рядок на кожне читання. Увімкнути — CACHE_LOG_LEVEL=Debug.
        logger.LogDebug("Results cache {Result}: poll {PollId}, generation {Generation}",
            lookup.NotFound ? "NEGATIVE HIT" : lookup.Entry is null ? "MISS" : "HIT", pollId, generation);
        return lookup;
    }

    private static ResultsCacheLookup Parse(byte[]? value, long generation) => value switch
    {
        null => new ResultsCacheLookup(null, generation),
        _ when value.AsSpan().SequenceEqual(NotFoundMarker) => new ResultsCacheLookup(null, generation, NotFound: true),
        _ => new ResultsCacheLookup(JsonSerializer.Deserialize<CachedPollResults>(value, Json), generation)
    };

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
    /// Негативний запис: опитування <paramref name="pollId"/> у БД немає (лаба 8, ADR 0063). Під тим самим поколінням, що
    /// й агрегат: якщо опитування з цим id створять, створення збільшить покоління, і запис більше ніхто не прочитає.
    /// </summary>
    public async Task SetNotFoundAsync(long pollId, long generation)
    {
        if (!NegativeCaching)
            return;
        try
        {
            var ttl = NotFoundTtl * (1 + (2 * Random.Shared.NextDouble() - 1) * ttlJitter);
            await redis.GetDatabase().StringSetAsync(ValueKey(pollId, generation), NotFoundMarker, new Expiration(ttl));
            logger.LogDebug("Results cache STORE NOT FOUND: poll {PollId}, generation {Generation}, TTL {Ttl:0.0} s",
                pollId, generation, ttl.TotalSeconds);
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            logger.LogWarning("Results cache unavailable, missing poll {PollId} not cached: {Error}", pollId, ex.Message);
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
                pollId, OpenTtl.TotalSeconds * (1 + ttlJitter), ex.Message);
        }
    }

    /// <summary>
    /// Значення конкретного покоління — для тих, хто чекає чужого читання під lock (лаба 8, ADR 0061). Не перечитує
    /// лічильник покоління: чекач прийшов із поколінням, прочитаним до інвалідації, і бере лише агрегат цього покоління.
    /// Entry null без NotFound — значення ще немає або Redis недоступний.
    /// </summary>
    public async Task<ResultsCacheLookup> GetEntryAsync(long pollId, long generation)
    {
        try
        {
            var value = await redis.GetDatabase().StringGetAsync(ValueKey(pollId, generation));
            return Parse(value.IsNull ? null : (byte[])value!, generation);
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            return ResultsCacheLookup.Unavailable;
        }
    }

    /// <summary>
    /// Distributed lock на читання агрегату (лаба 8, ADR 0061): <c>SET key token NX PX lease</c>. Ключ містить покоління —
    /// так само, як single-flight (ADR 0044), щоб читання після мутації не чекало агрегату, порахованого до неї.
    /// Lease обмежує час: власник, що впав чи завис, звільняє lock сам, без deadlock.
    /// </summary>
    public async Task<LockAttempt> TryLockAsync(long pollId, long generation, string token, TimeSpan lease)
    {
        try
        {
            return await redis.GetDatabase().StringSetAsync(LockKey(pollId, generation), token, lease, When.NotExists)
                ? LockAttempt.Acquired
                : LockAttempt.Busy;
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            logger.LogWarning("Results lock unavailable, poll {PollId}: loading without the lock: {Error}", pollId, ex.Message);
            return LockAttempt.Unavailable;
        }
    }

    // Видаляє lock, лише якщо він досі наш: після спливу lease ключ міг уже взяти інший інстанс, і простий DEL зняв би
    // чужий lock — третій запит пішов би в БД паралельно з другим.
    private const string ReleaseScript = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
        return 0
        """;

    /// <summary>False — lock уже не наш: lease сплив, поки йшло читання (його бачить лог, а не клієнт).</summary>
    public async Task<bool> ReleaseLockAsync(long pollId, long generation, string token)
    {
        try
        {
            return (long)await redis.GetDatabase().ScriptEvaluateAsync(
                ReleaseScript, [LockKey(pollId, generation)], [token]) == 1;
        }
        catch (Exception ex) when (IsUnavailable(ex))
        {
            // Не звільнили — lock зникне сам за lease.
            return false;
        }
    }

    /// <summary>
    /// TTL за статусом, з яким агрегат порахований: довгий — лише для даних, що вже не зміняться. Запис, зроблений
    /// поки опитування було активним, лишається з коротким TTL, навіть якщо опитування закрили мить потому.
    /// </summary>
    private TimeSpan TtlFor(PollStatus status) =>
        (status == PollStatus.Closed ? ClosedTtl : OpenTtl) * (1 + (2 * Random.Shared.NextDouble() - 1) * ttlJitter);

    private static bool IsUnavailable(Exception ex) => ex is RedisConnectionException or RedisTimeoutException;

    // Схема ключів (ADR 0041): domain:entity:format:id:state. Параметрів у відповіді немає, тому й хешу параметрів немає;
    // v1 — версія формату значення: змінили CachedPollResults → v2, і інстанси різних версій не читають JSON одне одного.
    private static string GenerationKey(long pollId) => $"polling:results:gen:{pollId}";

    private static string ValueKeyPrefix(long pollId) => $"polling:results:v1:{pollId}:g";

    private static string ValueKey(long pollId, long generation) => $"{ValueKeyPrefix(pollId)}{generation}";

    private static string LockKey(long pollId, long generation) => $"polling:results:lock:{pollId}:g{generation}";
}
