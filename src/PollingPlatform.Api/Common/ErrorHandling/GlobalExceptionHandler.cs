using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using Npgsql;
using PollingPlatform.Api.Common.Exceptions;
using StackExchange.Redis;

namespace PollingPlatform.Api.Common.ErrorHandling;

/// <summary>
/// Мапить винятки у відповіді RFC 7807 (application/problem+json).
/// AppException → його StatusCode; усе інше → 500 без деталей реалізації.
/// </summary>
public class GlobalExceptionHandler(IProblemDetailsService problemDetailsService, ILogger<GlobalExceptionHandler> logger)
    : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext httpContext, Exception exception, CancellationToken cancellationToken)
    {
        ProblemDetails problem = exception switch
        {
            ValidationException ve => new ValidationProblemDetails(ve.Errors)
            {
                Status = ve.StatusCode,
                Title = ve.Title,
                Detail = ve.Message
            },
            AppException ae => new ProblemDetails
            {
                Status = ae.StatusCode,
                Title = ae.Title,
                Detail = ae.Message
            },
            _ when UnavailableDependency(exception) is { } dependency => new ProblemDetails
            {
                Status = StatusCodes.Status503ServiceUnavailable,
                Title = "Service Unavailable",
                Detail = $"The {dependency} is temporarily unavailable. Please retry."
            },
            _ => new ProblemDetails
            {
                Status = StatusCodes.Status500InternalServerError,
                Title = "Internal Server Error",
                Detail = "An unexpected error occurred."
            }
        };

        if (problem.Status >= 500)
            logger.LogError(exception, "Unhandled exception while processing {Method} {Path}", httpContext.Request.Method, httpContext.Request.Path);

        httpContext.Response.StatusCode = problem.Status!.Value;
        return await problemDetailsService.TryWriteAsync(new ProblemDetailsContext
        {
            HttpContext = httpContext,
            ProblemDetails = problem,
            Exception = exception
        });
    }

    /// <summary>
    /// Недоступна або перевантажена залежність — це 503, а не 500: інфраструктурний збій, після якого
    /// запит має сенс повторити. У лабі 3 за цим кодом балансувальник вимикає вузол з пулу,
    /// у лабі 5 — k6 відрізняє інфраструктурну відмову від помилки застосунку.
    /// БД (ADR 0016): EF уже вичерпав власні повтори, тож сюди доходять стійкі збої.
    /// Redis (ADR 0027): клієнт чекав на з'єднання до свого таймауту. Redis-перевірки йдуть першими,
    /// бо RedisTimeoutException — теж TimeoutException.
    /// </summary>
    private static string? UnavailableDependency(Exception exception) => exception switch
    {
        RedisConnectionException or RedisTimeoutException => "cache",
        NpgsqlException { IsTransient: true } => "database",
        TimeoutException => "database",
        _ => exception.InnerException is { } inner ? UnavailableDependency(inner) : null
    };
}
