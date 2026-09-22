using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using Npgsql;
using PollingPlatform.Api.Common.Exceptions;

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
            _ when IsTransient(exception) => new ProblemDetails
            {
                Status = StatusCodes.Status503ServiceUnavailable,
                Title = "Service Unavailable",
                Detail = "The database is temporarily unavailable. Please retry."
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
    /// Недоступна або перевантажена БД — це 503, а не 500: інфраструктурний збій, після якого
    /// запит має сенс повторити. У лабі 3 за цим кодом балансувальник вимикає вузол з пулу,
    /// у лабі 5 — k6 відрізняє інфраструктурну відмову від помилки застосунку.
    /// EF уже вичерпав власні повтори (EnableRetryOnFailure), тож сюди доходять стійкі збої.
    /// </summary>
    private static bool IsTransient(Exception exception) => exception switch
    {
        NpgsqlException { IsTransient: true } => true,
        TimeoutException => true,
        _ => exception.InnerException is { } inner && IsTransient(inner)
    };
}
