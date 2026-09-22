using FluentValidation;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PollingPlatform.Api.Common.Validation;

namespace PollingPlatform.Api.Auth;

[ApiController]
[Route("api/auth")]
[Produces("application/json")]
public class AuthController(AuthService authService) : ControllerBase
{
    /// <summary>Реєстрація нового користувача.</summary>
    [HttpPost("register")]
    [ProducesResponseType<UserResponse>(StatusCodes.Status201Created)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status422UnprocessableEntity)]
    public async Task<ActionResult<UserResponse>> Register(
        RegisterRequest request, [FromServices] IValidator<RegisterRequest> validator, CancellationToken ct)
    {
        await validator.ValidateOrThrowAsync(request, ct);
        var user = await authService.RegisterAsync(request, ct);
        return CreatedAtAction(nameof(Me), null, user);
    }

    /// <summary>Вхід: повертає JWT access token.</summary>
    [HttpPost("login")]
    [ProducesResponseType<TokenResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status422UnprocessableEntity)]
    public async Task<ActionResult<TokenResponse>> Login(
        LoginRequest request, [FromServices] IValidator<LoginRequest> validator, CancellationToken ct)
    {
        await validator.ValidateOrThrowAsync(request, ct);
        return await authService.LoginAsync(request, ct);
    }

    /// <summary>Поточний користувач за токеном.</summary>
    [Authorize]
    [HttpGet("me")]
    [ProducesResponseType<UserResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    public Task<UserResponse> Me(CancellationToken ct) => authService.GetCurrentUserAsync(User.GetUserId(), ct);
}
