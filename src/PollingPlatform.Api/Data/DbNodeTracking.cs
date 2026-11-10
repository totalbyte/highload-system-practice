using System.Data.Common;
using Microsoft.EntityFrameworkCore.Diagnostics;

namespace PollingPlatform.Api.Data;

/// <summary>Вузли БД, яких торкнувся запит.</summary>
[Flags]
public enum DbNodes
{
    None = 0,
    Primary = 1,
    Replica = 2
}

/// <summary>
/// Позначає вузол у момент відкриття з'єднання (лаба 6, ADR 0050). Заголовок X-DB-Node показує, куди запит справді ходив,
/// а не куди мав піти за задумом: неправильна маршрутизація одразу буде видна, а HIT кешу лишиться без заголовка.
/// З лаби 7 так само позначає шард: заголовок X-Shard (ADR 0055).
/// </summary>
public sealed class DbNodeInterceptor(IHttpContextAccessor accessor, DbNodes node, string shard) : DbConnectionInterceptor
{
    public override void ConnectionOpened(DbConnection connection, ConnectionEndEventData eventData) => Mark();

    public override Task ConnectionOpenedAsync(
        DbConnection connection, ConnectionEndEventData eventData, CancellationToken cancellationToken = default)
    {
        Mark();
        return Task.CompletedTask;
    }

    private void Mark()
    {
        if (accessor.HttpContext is not { } context)
            return;
        context.MarkDbNode(node);
        context.MarkShard(shard);
    }
}

public static class DbNodeHeaderExtensions
{
    public const string HeaderName = "X-DB-Node";
    public const string ShardHeaderName = "X-Shard";
    private const string ItemKey = "polling:db-nodes";

    /// <summary>
    /// Куди ходив запит. Створюється на початку запиту і змінюється під lock: каталог (лаба 7) читає шарди паралельно,
    /// а HttpContext.Items — звичайний словник, не потокобезпечний.
    /// </summary>
    private sealed class Marks
    {
        public DbNodes Nodes;
        public readonly SortedSet<string> Shards = [];
    }

    public static void MarkDbNode(this HttpContext context, DbNodes node)
    {
        if (context.Items[ItemKey] is not Marks marks)
            return;
        lock (marks)
            marks.Nodes |= node;
    }

    /// <summary>Шарди, яких торкнувся запит: один для операцій з опитуванням, усі — для каталогу (fan-out).</summary>
    public static void MarkShard(this HttpContext context, string shard)
    {
        if (context.Items[ItemKey] is not Marks marks)
            return;
        lock (marks)
            marks.Shards.Add(shard);
    }

    public static IApplicationBuilder UseDbNodeHeader(this IApplicationBuilder app) =>
        app.Use((context, next) =>
        {
            var marks = new Marks();
            context.Items[ItemKey] = marks;
            context.Response.OnStarting(() =>
            {
                lock (marks)
                {
                    var value = marks.Nodes switch
                    {
                        DbNodes.Primary => "primary",
                        DbNodes.Replica => "replica",
                        DbNodes.None => null,
                        _ => "primary,replica"
                    };
                    if (value is not null)
                        context.Response.Headers[HeaderName] = value;
                    if (marks.Shards.Count > 0)
                        context.Response.Headers[ShardHeaderName] = string.Join(",", marks.Shards);
                }
                return Task.CompletedTask;
            });
            return next(context);
        });
}
