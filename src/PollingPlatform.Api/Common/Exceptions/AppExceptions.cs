namespace PollingPlatform.Api.Common.Exceptions;

/// <summary>
/// Базовий клас бізнес-винятків. Кожен виняток знає свій HTTP-статус,
/// тому централізований обробник мапить їх без switch по типах.
/// </summary>
public abstract class AppException(int statusCode, string title, string message) : Exception(message)
{
    public int StatusCode { get; } = statusCode;
    public string Title { get; } = title;
}

public class NotFoundException(string message)
    : AppException(StatusCodes.Status404NotFound, "Not Found", message);

public class ConflictException(string message)
    : AppException(StatusCodes.Status409Conflict, "Conflict", message);

public class UnauthorizedException(string message)
    : AppException(StatusCodes.Status401Unauthorized, "Unauthorized", message);

public class ForbiddenException(string message)
    : AppException(StatusCodes.Status403Forbidden, "Forbidden", message);

public class ValidationException(IDictionary<string, string[]> errors)
    : AppException(StatusCodes.Status422UnprocessableEntity, "Validation Failed", "One or more validation errors occurred.")
{
    public IDictionary<string, string[]> Errors { get; } = errors;
}
