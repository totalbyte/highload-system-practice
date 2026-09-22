namespace PollingPlatform.Api.Common;

/// <summary>
/// Ідентифікатор екземпляра сервісу для заголовка X-Instance-ID (лаби 2–3).
/// За замовчуванням — hostname контейнера; можна перевизначити змінною INSTANCE_ID.
/// </summary>
public sealed class InstanceIdentity(IConfiguration configuration)
{
    public const string HeaderName = "X-Instance-ID";

    public string Id { get; } = configuration["INSTANCE_ID"] is { Length: > 0 } id ? id : Environment.MachineName;
}

public static class InstanceIdentityExtensions
{
    public static IApplicationBuilder UseInstanceIdHeader(this IApplicationBuilder app)
    {
        var instanceId = app.ApplicationServices.GetRequiredService<InstanceIdentity>().Id;
        return app.Use((context, next) =>
        {
            context.Response.OnStarting(() =>
            {
                context.Response.Headers[InstanceIdentity.HeaderName] = instanceId;
                return Task.CompletedTask;
            });
            return next(context);
        });
    }
}
