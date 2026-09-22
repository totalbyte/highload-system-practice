using FluentValidation;

namespace PollingPlatform.Api.Auth;

public record RegisterRequest(string? Username, string? Email, string? Password);

public record LoginRequest(string? Email, string? Password);

public record UserResponse(long Id, string Username, string Email, DateTimeOffset CreatedAt);

public record TokenResponse(string AccessToken, string TokenType, DateTimeOffset ExpiresAt);

public class RegisterRequestValidator : AbstractValidator<RegisterRequest>
{
    public RegisterRequestValidator()
    {
        RuleFor(r => r.Username).NotEmpty().Length(3, 50).Matches("^[a-zA-Z0-9_.-]+$")
            .WithMessage("Username may contain only letters, digits, '_', '.' and '-'.");
        RuleFor(r => r.Email).NotEmpty().MaximumLength(254).EmailAddress();
        RuleFor(r => r.Password).NotEmpty().Length(8, 128);
    }
}

public class LoginRequestValidator : AbstractValidator<LoginRequest>
{
    public LoginRequestValidator()
    {
        RuleFor(r => r.Email).NotEmpty();
        RuleFor(r => r.Password).NotEmpty();
    }
}
