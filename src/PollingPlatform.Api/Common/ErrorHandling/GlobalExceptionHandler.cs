using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;
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
}
