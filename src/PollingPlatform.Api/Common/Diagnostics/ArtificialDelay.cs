namespace PollingPlatform.Api.Common.Diagnostics;

/// <summary>
/// Штучна затримка кожного запиту — для експерименту з асиметричним навантаженням (лаба 3, ADR 0036):
/// вмикається змінною Diagnostics__ArtificialDelayMs лише на одному інстансі, щоб він став «повільним вузлом».
/// </summary>
public static class ArtificialDelayExtensions
{
    public const string SettingName = "Diagnostics:ArtificialDelayMs";

    public static IApplicationBuilder UseArtificialDelay(this IApplicationBuilder app)
    {
        var delayMs = app.ApplicationServices.GetRequiredService<IConfiguration>().GetValue(SettingName, 0);
        // За замовчуванням 0 — middleware навіть не додається, звичайний стек працює як раніше.
        if (delayMs <= 0)
            return app;

        app.ApplicationServices.GetRequiredService<ILoggerFactory>()
            .CreateLogger(typeof(ArtificialDelayExtensions))
            .LogWarning("Artificial delay of {DelayMs} ms is enabled for every request except /health", delayMs);

        var delay = TimeSpan.FromMilliseconds(delayMs);
        return app.Use(async (context, next) =>
        {
            // /health не затримуємо: вузол повільний, але живий, і не повинен випадати з пулу балансувальника
            // через таймаут перевірки.
            if (!context.Request.Path.StartsWithSegments("/health"))
            {
                // Task.Delay не займає ні CPU, ні потік — це модель «повільна залежність / I/O», а не
                // перевантажений процесор. Клієнт, що пішов, не тримає запит: чекання скасовується.
                await Task.Delay(delay, context.RequestAborted);
            }
            await next(context);
        });
    }
}
