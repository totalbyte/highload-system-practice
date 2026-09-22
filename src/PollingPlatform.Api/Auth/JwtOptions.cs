using System.ComponentModel.DataAnnotations;

namespace PollingPlatform.Api.Auth;

public class JwtOptions
{
    public const string SectionName = "Jwt";

    [Required] public string Issuer { get; init; } = "polling-platform";
    [Required] public string Audience { get; init; } = "polling-platform-clients";

    /// <summary>Симетричний ключ HMAC-SHA256; для HS256 потрібно щонайменше 32 байти.</summary>
    [Required, MinLength(32)] public string Secret { get; init; } = "";

    [Range(1, 7 * 24 * 60)] public int LifetimeMinutes { get; init; } = 60;
}
