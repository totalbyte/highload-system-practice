using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using PollingPlatform.Api.Common.Exceptions;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Auth;

public class AuthService(
    AppDbContext db,
    IPasswordHasher<User> passwordHasher,
    JwtTokenService tokenService,
    TimeProvider timeProvider)
{
    public async Task<UserResponse> RegisterAsync(RegisterRequest request, CancellationToken ct)
    {
        var username = request.Username!.Trim();
        var email = NormalizeEmail(request.Email!);

        if (await db.Users.AnyAsync(u => u.Email == email || u.Username == username, ct))
            throw new ConflictException("A user with this email or username already exists.");

        var user = new User
        {
            Username = username,
            Email = email,
            PasswordHash = "",
            CreatedAt = timeProvider.GetUtcNow()
        };
        user.PasswordHash = passwordHasher.HashPassword(user, request.Password!);

        db.Users.Add(user);
        try
        {
            await db.SaveChangesAsync(ct);
        }
        catch (DbUpdateException ex) when (ex.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation })
        {
            // Гонка двох паралельних реєстрацій: перевірку вище пройшли обидві, унікальний індекс пропустив лише одну.
            throw new ConflictException("A user with this email or username already exists.");
        }

        return ToResponse(user);
    }

    public async Task<TokenResponse> LoginAsync(LoginRequest request, CancellationToken ct)
    {
        var email = NormalizeEmail(request.Email!);
        var user = await db.Users.AsNoTracking().FirstOrDefaultAsync(u => u.Email == email, ct);

        // Однакова відповідь для «немає користувача» і «неправильний пароль» — не розкриваємо, які email зареєстровані.
        if (user is null || passwordHasher.VerifyHashedPassword(user, user.PasswordHash, request.Password!) == PasswordVerificationResult.Failed)
            throw new UnauthorizedException("Invalid email or password.");

        var (token, expiresAt) = tokenService.CreateToken(user);
        return new TokenResponse(token, "Bearer", expiresAt);
    }

    public async Task<UserResponse> GetCurrentUserAsync(long userId, CancellationToken ct)
    {
        var user = await db.Users.AsNoTracking().FirstOrDefaultAsync(u => u.Id == userId, ct)
                   ?? throw new UnauthorizedException("User from the access token no longer exists.");
        return ToResponse(user);
    }

    private static string NormalizeEmail(string email) => email.Trim().ToLowerInvariant();

    private static UserResponse ToResponse(User user) => new(user.Id, user.Username, user.Email, user.CreatedAt);
}
