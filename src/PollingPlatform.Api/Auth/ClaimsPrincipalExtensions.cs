using System.Security.Claims;
using Microsoft.IdentityModel.JsonWebTokens;
using PollingPlatform.Api.Common.Exceptions;

namespace PollingPlatform.Api.Auth;

public static class ClaimsPrincipalExtensions
{
    /// <summary>Id автентифікованого користувача (claim "sub"), або null для анонімного запиту.</summary>
    public static long? FindUserId(this ClaimsPrincipal principal) =>
        long.TryParse(principal.FindFirstValue(JwtRegisteredClaimNames.Sub), out var id) ? id : null;

    /// <summary>Id користувача для ендпоінтів з [Authorize].</summary>
    public static long GetUserId(this ClaimsPrincipal principal) =>
        principal.FindUserId() ?? throw new UnauthorizedException("Access token does not contain a valid user id.");
}
