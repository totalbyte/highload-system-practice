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
/// </summary>
public sealed class DbNodeInterceptor(IHttpContextAccessor accessor, DbNodes node) : DbConnectionInterceptor
{
    public override void ConnectionOpened(DbConnection connection, ConnectionEndEventData eventData) =>
        accessor.HttpContext?.MarkDbNode(node);

    public override Task ConnectionOpenedAsync(
        DbConnection connection, ConnectionEndEventData eventData, CancellationToken cancellationToken = default)
    {
        accessor.HttpContext?.MarkDbNode(node);
        return Task.CompletedTask;
    }
}

public static class DbNodeHeaderExtensions
{
    public const string HeaderName = "X-DB-Node";
    private const string ItemKey = "polling:db-nodes";

    public static void MarkDbNode(this HttpContext context, DbNodes node) =>
        context.Items[ItemKey] = (context.Items[ItemKey] as DbNodes? ?? DbNodes.None) | node;

    public static IApplicationBuilder UseDbNodeHeader(this IApplicationBuilder app) =>
        app.Use((context, next) =>
        {
            context.Response.OnStarting(() =>
            {
                var value = (context.Items[ItemKey] as DbNodes? ?? DbNodes.None) switch
                {
                    DbNodes.Primary => "primary",
                    DbNodes.Replica => "replica",
                    DbNodes.None => null,
                    _ => "primary,replica"
                };
                if (value is not null)
                    context.Response.Headers[HeaderName] = value;
                return Task.CompletedTask;
            });
            return next(context);
        });
}
