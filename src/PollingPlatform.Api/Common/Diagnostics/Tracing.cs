using Npgsql;
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using StackExchange.Redis;

namespace PollingPlatform.Api.Common.Diagnostics;

/// <summary>
/// Розподілене трасування (лаба 9, ADR 0066): один HTTP-запит → спани ASP.NET Core, кожного SQL-запиту Npgsql і кожної
/// команди Redis, експорт по OTLP у Jaeger. Так видно, з чого складається загальний час відповіді: backend, кеш, СУБД
/// і паралельні запити до шардів у каталозі. Вимкнене за замовчуванням — експорт спанів сам коштує CPU і заважав би A/B.
/// </summary>
public static class Tracing
{
    public static void AddTracing(this IServiceCollection services, IConfiguration configuration, IConnectionMultiplexer redis)
    {
        if (!configuration.GetValue("Tracing:Enabled", false))
            return;

        var endpoint = new Uri(configuration["Tracing:OtlpEndpoint"] ?? "http://jaeger:4317");
        var ratio = configuration.GetValue("Tracing:SampleRatio", 1.0);

        services.AddOpenTelemetry()
            .ConfigureResource(resource => resource.AddService(
                "polling-api", serviceInstanceId: configuration["INSTANCE_ID"] ?? Environment.MachineName))
            .WithTracing(tracing => tracing
                .SetSampler(new HttpRootSampler(ratio))
                // /health HAProxy питає щосекунди: тисячі однакових трас лише заважали б знайти потрібну.
                .AddAspNetCoreInstrumentation(options => options.Filter = context => context.Request.Path != "/health")
                .AddNpgsql()
                .AddRedisInstrumentation(redis)
                .AddOtlpExporter(options => options.Endpoint = endpoint));
    }

    /// <summary>
    /// Траса починається лише з HTTP-запиту. Монітор вузлів БД (лаба 6) щосекунди робить SELECT 1 поза будь-яким запитом —
    /// без цього фільтра кожна така перевірка стала б окремою трасою. Дочірні спани беруть рішення батька.
    /// </summary>
    private sealed class HttpRootSampler(double ratio) : Sampler
    {
        private readonly TraceIdRatioBasedSampler sampler = new(ratio);

        public override SamplingResult ShouldSample(in SamplingParameters parameters)
        {
            if (parameters.ParentContext.TraceId != default)
                return new SamplingResult(parameters.ParentContext.TraceFlags.HasFlag(System.Diagnostics.ActivityTraceFlags.Recorded));
            if (parameters.Kind != System.Diagnostics.ActivityKind.Server)
                return new SamplingResult(SamplingDecision.Drop);
            return sampler.ShouldSample(parameters);
        }
    }
}
