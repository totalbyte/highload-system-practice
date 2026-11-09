using System.Data.Common;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Npgsql;
using PollingPlatform.Api.Common.Exceptions;

namespace PollingPlatform.Api.Data;

/// <summary>
/// Фоновий стан вузлів БД (лаба 6, ADR 0052): запит не чекає таймаутів і повторів EF, щоб дізнатися, що вузол лежить,
/// а одразу йде на живий вузол або отримує контрольовану 503. Стан похідний і короткоживучий: кожен інстанс перевіряє
/// вузли сам, тож у stateless-системі (лаба 2) синхронізувати тут нічого.
/// </summary>
public sealed class DbNodeMonitor : BackgroundService
{
    private const int FailuresToMarkDown = 2;
    private static readonly TimeSpan Interval = TimeSpan.FromSeconds(1);

    private readonly ILogger<DbNodeMonitor> logger;
    private readonly TimeSpan timeout;
    private readonly Node primary;
    private readonly Node? replica;

    public DbNodeMonitor(string primaryConnectionString, string? replicaConnectionString, TimeSpan timeout, ILogger<DbNodeMonitor> logger)
    {
        this.logger = logger;
        this.timeout = timeout;
        primary = new Node("primary", ProbeConnectionString(primaryConnectionString, timeout));
        replica = replicaConnectionString is null ? null : new Node("replica", ProbeConnectionString(replicaConnectionString, timeout));
    }

    public bool HasReplica => replica is not null;
    public bool PrimaryAvailable => primary.Available;
    public bool ReplicaAvailable => replica is { Available: true };

    /// <summary>
    /// Пасивний сигнал: живий запит не зміг з'єднатися. Активна перевірка помітила б це за ~4 с, а кожне читання за цей час
    /// чекало б пошуку імені (~2–3 с). Таймаут не рахується: так виглядає і зайнятий пул, тобто навантаження, а не відмова.
    /// Хибне спрацювання коштує недовго: перша вдала перевірка повертає вузол за секунду.
    /// </summary>
    public void ReportConnectionFailure(DbNodes node, Exception exception)
    {
        for (var ex = exception; ex is not null; ex = ex.InnerException)
        {
            if (ex is TimeoutException or OperationCanceledException or PostgresException { SqlState: PostgresErrorCodes.TooManyConnections })
                return;
        }
        var target = node == DbNodes.Primary ? primary : replica;
        if (target is { Available: true })
        {
            target.Available = false;
            logger.LogWarning("Database node {Node} is down (connection failed): {Error}", target.Name, exception.Message);
        }
    }

    /// <summary>
    /// Без пулу: під навантаженням усі з'єднання спільного пулу зайняті, і перевірка чекала б у черзі до таймауту,
    /// а монітор вирішив би, що здоровий Primary лежить, і заблокував би записи саме в піку.
    /// </summary>
    private static string ProbeConnectionString(string connectionString, TimeSpan timeout) =>
        new NpgsqlConnectionStringBuilder(connectionString) { Pooling = false, Timeout = (int)timeout.TotalSeconds }.ConnectionString;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(Interval);
        do
        {
            await Task.WhenAll(CheckAsync(primary, stoppingToken), replica is null ? Task.CompletedTask : CheckAsync(replica, stoppingToken));
        }
        while (await timer.WaitForNextTickAsync(stoppingToken).AsTask().ContinueWith(t => t.IsCompletedSuccessfully && t.Result, TaskScheduler.Default));
    }

    private async Task CheckAsync(Node node, CancellationToken ct)
    {
        try
        {
            // WaitAsync: пошук імені зупиненого контейнера через Docker DNS триває ~3.3 с і не реагує на скасування (ADR 0019).
            await ProbeAsync(node.ConnectionString, ct).WaitAsync(timeout, ct);
            node.Failures = 0;
            if (!node.Available)
            {
                node.Available = true;
                logger.LogWarning("Database node {Node} is back", node.Name);
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
        }
        catch (PostgresException ex) when (ex.SqlState == PostgresErrorCodes.TooManyConnections)
        {
            // Сервер відповів, отже живий: зайняті слоти — не причина вважати вузол недоступним.
            node.Failures = 0;
        }
        catch (Exception ex)
        {
            // Дві невдачі поспіль: одна затримка під навантаженням не повинна блокувати записи.
            if (++node.Failures >= FailuresToMarkDown && node.Available)
            {
                node.Available = false;
                logger.LogWarning("Database node {Node} is down: {Error}", node.Name, ex.Message);
            }
        }
    }

    private static async Task ProbeAsync(string connectionString, CancellationToken ct)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var command = new NpgsqlCommand("SELECT 1", connection);
        await command.ExecuteScalarAsync(ct);
    }

    private sealed class Node(string name, string connectionString)
    {
        private volatile bool available = true;
        public string Name => name;
        public string ConnectionString => connectionString;
        public int Failures { get; set; }
        public bool Available { get => available; set => available = value; }
    }
}

/// <summary>
/// Read-Only Mode (лаба 6, 2.5): спроба відкрити з'єднання з Primary, коли він лежить, одразу дає 503. Це покриває всі записи
/// і строгі читання одним рядком, без перевірок у кожному сервісі, і замінює 13–19 с повторів EF миттєвою відмовою.
/// Для обох вузлів передає монітору невдалі з'єднання живих запитів.
/// </summary>
public sealed class DbNodeGuardInterceptor(DbNodeMonitor monitor, DbNodes node) : DbConnectionInterceptor
{
    public override InterceptionResult ConnectionOpening(
        DbConnection connection, ConnectionEventData eventData, InterceptionResult result)
    {
        ThrowIfPrimaryDown();
        return result;
    }

    public override ValueTask<InterceptionResult> ConnectionOpeningAsync(
        DbConnection connection, ConnectionEventData eventData, InterceptionResult result, CancellationToken cancellationToken = default)
    {
        ThrowIfPrimaryDown();
        return ValueTask.FromResult(result);
    }

    public override void ConnectionFailed(DbConnection connection, ConnectionErrorEventData eventData) =>
        monitor.ReportConnectionFailure(node, eventData.Exception);

    public override Task ConnectionFailedAsync(
        DbConnection connection, ConnectionErrorEventData eventData, CancellationToken cancellationToken = default)
    {
        monitor.ReportConnectionFailure(node, eventData.Exception);
        return Task.CompletedTask;
    }

    private void ThrowIfPrimaryDown()
    {
        if (node == DbNodes.Primary && !monitor.PrimaryAvailable)
            throw new ReadOnlyModeException();
    }
}

/// <summary>
/// /health для балансувальника: вузол застосунку корисний, поки живий хоча б один вузол БД (ADR 0052). Втрата Primary не
/// виключає backend із пулу, інакше разом із записами зникло б і читання з репліки. Відповідає зі стану монітора, миттєво.
/// </summary>
public sealed class DbNodesHealthCheck(DbNodeMonitor monitor) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken)
    {
        var replicaOk = monitor.HasReplica && monitor.ReplicaAvailable;
        var result = (monitor.PrimaryAvailable, replicaOk) switch
        {
            (true, true) => HealthCheckResult.Healthy(),
            (true, false) when !monitor.HasReplica => HealthCheckResult.Healthy(),
            (true, false) => HealthCheckResult.Degraded("The replica is down: reads go to the primary."),
            (false, true) => HealthCheckResult.Degraded("The primary is down: read-only mode."),
            (false, false) => HealthCheckResult.Unhealthy("No database node is available.")
        };
        return Task.FromResult(result);
    }
}
