using System.Text.Json.Serialization;
using FluentValidation;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi;
using PollingPlatform.Api.Auth;
using PollingPlatform.Api.Common;
using PollingPlatform.Api.Common.ErrorHandling;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Data.Seeding;
using PollingPlatform.Api.Domain;
using PollingPlatform.Api.Polls;
using PollingPlatform.Api.Results;
using PollingPlatform.Api.Votes;

var builder = WebApplication.CreateBuilder(args);

// --- Persistence ---
builder.Services.AddDbContext<AppDbContext>(options => options
    .UseNpgsql(
        builder.Configuration.GetConnectionString("Postgres")
            ?? throw new InvalidOperationException("Connection string 'Postgres' is not configured."),
        // Повтор при транзієнтних збоях (напр. «мертві» з'єднання в пулі після рестарту Postgres).
        // Наслідок: явні транзакції треба загортати в db.Database.CreateExecutionStrategy().ExecuteAsync(...).
        npgsql => npgsql.EnableRetryOnFailure(maxRetryCount: 3, maxRetryDelay: TimeSpan.FromSeconds(2), errorCodesToAdd: null))
    .UseSnakeCaseNamingConvention());

builder.Services.Configure<SeedOptions>(builder.Configuration.GetSection(SeedOptions.SectionName));
builder.Services.AddScoped<DataSeeder>();

// --- Auth (stateless JWT) ---
builder.Services.AddOptions<JwtOptions>()
    .Bind(builder.Configuration.GetSection(JwtOptions.SectionName))
    .ValidateDataAnnotations()
    .ValidateOnStart();

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer();
builder.Services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme)
    .Configure<IOptions<JwtOptions>>((bearer, jwt) =>
    {
        // Залишаємо оригінальні назви claims ("sub"), без мапінгу на довгі URI з ClaimTypes.
        bearer.MapInboundClaims = false;
        bearer.TokenValidationParameters = new TokenValidationParameters
        {
            ValidIssuer = jwt.Value.Issuer,
            ValidAudience = jwt.Value.Audience,
            IssuerSigningKey = JwtTokenService.CreateSigningKey(jwt.Value.Secret),
            ClockSkew = TimeSpan.FromSeconds(30)
        };
    });
builder.Services.AddAuthorization();

builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton<IPasswordHasher<User>, PasswordHasher<User>>();
builder.Services.AddSingleton<JwtTokenService>();
builder.Services.AddScoped<AuthService>();
builder.Services.AddScoped<PollService>();
builder.Services.AddScoped<VoteService>();
builder.Services.AddScoped<ResultsService>();
builder.Services.AddValidatorsFromAssemblyContaining<Program>();

// Кеш результатів у пам'яті процесу — навмисне рішення лаби 1 (ADR 0013), ціль аудиту стану в лабі 2.
builder.Services.AddMemoryCache();
builder.Services.AddSingleton<ResultsCache>();

// --- API ---
builder.Services
    .AddControllers(options =>
        // Відсутні поля валідуються FluentValidation (→ 422), а не автоматичним [Required] (→ 400).
        // 400 лишається лише для запитів, які неможливо розпарсити (битий JSON, невірний тип).
        options.SuppressImplicitRequiredAttributeForNonNullableReferenceTypes = true)
    .AddJsonOptions(options =>
        options.JsonSerializerOptions.Converters.Add(new JsonStringEnumConverter(System.Text.Json.JsonNamingPolicy.CamelCase)));

builder.Services.AddProblemDetails(options =>
    options.CustomizeProblemDetails = ctx => ctx.ProblemDetails.Extensions["traceId"] = ctx.HttpContext.TraceIdentifier);
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();

builder.Services.AddSingleton<InstanceIdentity>();
builder.Services.AddHealthChecks().AddDbContextCheck<AppDbContext>("postgres");

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(options =>
{
    options.SwaggerDoc("v1", new OpenApiInfo { Title = "Polling Platform API", Version = "v1" });
    options.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Type = SecuritySchemeType.Http,
        Scheme = "bearer",
        BearerFormat = "JWT",
        Description = "Токен з POST /api/auth/login"
    });
    options.AddSecurityRequirement(document => new OpenApiSecurityRequirement
    {
        [new OpenApiSecuritySchemeReference("Bearer", document)] = []
    });
    options.IncludeXmlComments(Path.Combine(AppContext.BaseDirectory, $"{typeof(Program).Assembly.GetName().Name}.xml"));
});

var app = builder.Build();

app.UseExceptionHandler();
app.UseStatusCodePages();
app.UseInstanceIdHeader();

if (app.Configuration.GetValue("Swagger:Enabled", true))
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();
app.MapHealthChecks("/health", new HealthCheckOptions
{
    ResponseWriter = (context, report) => context.Response.WriteAsJsonAsync(new
    {
        status = report.Status.ToString(),
        instance = context.RequestServices.GetRequiredService<InstanceIdentity>().Id,
        checks = report.Entries.ToDictionary(e => e.Key, e => e.Value.Status.ToString()),
        durationMs = report.TotalDuration.TotalMilliseconds
    })
});

await app.InitializeDatabaseAsync();
await app.RunAsync();

// Для WebApplicationFactory в інтеграційних тестах.
public partial class Program;
