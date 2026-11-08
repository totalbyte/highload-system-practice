using System.Text.Json.Serialization;
using FluentValidation;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi;
using PollingPlatform.Api.Auth;
using PollingPlatform.Api.Common;
using PollingPlatform.Api.Common.Diagnostics;
using PollingPlatform.Api.Common.ErrorHandling;
using PollingPlatform.Api.Data;
using PollingPlatform.Api.Data.Seeding;
using PollingPlatform.Api.Domain;
using PollingPlatform.Api.Polls;
using PollingPlatform.Api.Results;
using PollingPlatform.Api.Votes;
using StackExchange.Redis;

var builder = WebApplication.CreateBuilder(args);

// --- Persistence ---
var postgresConnectionString = builder.Configuration.GetConnectionString("Postgres")
    ?? throw new InvalidOperationException("Connection string 'Postgres' is not configured.");

// Accessor лише читає статичний AsyncLocal, тому один екземпляр можна створити ще до побудови DI.
var httpContextAccessor = new HttpContextAccessor();
builder.Services.AddSingleton<IHttpContextAccessor>(httpContextAccessor);

builder.Services.AddDbContext<AppDbContext>((services, options) => options
    .UseNpgsql(
        postgresConnectionString,
        // Повтор при транзієнтних збоях (напр. «мертві» з'єднання в пулі після рестарту Postgres).
        // Наслідок: явні транзакції треба загортати в db.Database.CreateExecutionStrategy().ExecuteAsync(...).
        npgsql => npgsql.EnableRetryOnFailure(maxRetryCount: 3, maxRetryDelay: TimeSpan.FromSeconds(2), errorCodesToAdd: null))
    .UseSnakeCaseNamingConvention()
    .AddInterceptors(
        new DbNodeInterceptor(httpContextAccessor, DbNodes.Primary),
        new DbNodeGuardInterceptor(services.GetRequiredService<DbNodeMonitor>(), DbNodes.Primary)));

// Репліка для читань, що допускають відставання (лаба 6, ADR 0050). Без рядка підключення або з Enabled=false усі
// читання лишаються на Primary — це конфігурація Single Primary для порівняння в 2.6.
var replicaConnectionString = builder.Configuration.GetValue("ReadReplica:Enabled", true)
    && builder.Configuration.GetConnectionString("PostgresReplica") is { Length: > 0 } configuredReplica
        ? configuredReplica
        : null;

// Без повторів EF, на відміну від Primary: для читання є інший вузол (ADR 0052), тож 13–19 с очікування нічого не дають.
builder.Services.AddSingleton(services => new ReplicaContextOptions(replicaConnectionString is null
    ? null
    : new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql(replicaConnectionString)
        .UseSnakeCaseNamingConvention()
        .AddInterceptors(
            new DbNodeInterceptor(httpContextAccessor, DbNodes.Replica),
            new DbNodeGuardInterceptor(services.GetRequiredService<DbNodeMonitor>(), DbNodes.Replica))
        .Options));
builder.Services.AddSingleton<StickySessions>();
builder.Services.AddScoped<ReadDb>();

builder.Services.AddSingleton(services => new DbNodeMonitor(
    postgresConnectionString,
    replicaConnectionString,
    TimeSpan.FromSeconds(builder.Configuration.GetValue("HealthChecks:DbTimeoutSeconds", 2)),
    services.GetRequiredService<ILogger<DbNodeMonitor>>()));
builder.Services.AddHostedService(services => services.GetRequiredService<DbNodeMonitor>());

builder.Services.Configure<SeedOptions>(builder.Configuration.GetSection(SeedOptions.SectionName));
builder.Services.AddScoped<DataSeeder>();

// --- Redis: спільне сховище для всіх інстансів (лаба 2) ---
var redisConnectionString = builder.Configuration.GetConnectionString("Redis")
    ?? throw new InvalidOperationException("Connection string 'Redis' is not configured.");

// Одне з'єднання на процес (multiplexer потокобезпечний) — його ділять кеш результатів і ключі DataProtection.
// Підключаємось одразу при старті, а abortConnect=false у рядку підключення не дає застосунку впасти,
// якщо Redis ще недоступний: клієнт перепідключиться сам.
var redisOptions = ConfigurationOptions.Parse(redisConnectionString);
// Fail-fast (лаба 4, ADR 0043): поки з'єднання немає, команда одразу падає, а не чекає в черзі клієнта до таймауту
// (у лабі 2 це ~5 с на кожен запит, що торкається Redis). Кеш — не джерело правди: читання тоді йде прямо в БД.
redisOptions.BacklogPolicy = BacklogPolicy.FailFast;
// Межа для команди, коли з'єднання формально живе, а Redis не відповідає (завис, мережа). Звичайна відповідь —
// частки мілісекунди, тож 1 с — це вже відмова, і читання переходить на БД замість очікування 5 с за замовчуванням.
redisOptions.SyncTimeout = redisOptions.AsyncTimeout = 1000;
var redis = ConnectionMultiplexer.Connect(redisOptions);
builder.Services.AddSingleton<IConnectionMultiplexer>(redis);

// Ключі DataProtection за замовчуванням лежать у файловій системі контейнера — у кожного інстансу свої, і
// захищене одним інстансом (cookie, antiforgery) не розшифрує інший. Спільне сховище і однакова назва застосунку
// дають усім інстансам один набір ключів (аудит стану лаби 2, ADR 0023).
builder.Services.AddDataProtection()
    .SetApplicationName("polling-platform")
    .PersistKeysToStackExchangeRedis(redis, "DataProtection-Keys");

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

// Кеш результатів — у Redis через спільний IConnectionMultiplexer (ADR 0026); сам ResultsCache стану не має.
builder.Services.AddSingleton<ResultsCache>();
// Об'єднання одночасних промахів проти Cache Stampede (ADR 0044); тримає лише запити, що виконуються зараз.
builder.Services.AddSingleton<ResultsSingleFlight>();

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
builder.Services.AddHealthChecks().AddCheck<DbNodesHealthCheck>("database");

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
app.UseDbNodeHeader();
app.UseArtificialDelay();

if (app.Configuration.GetValue("Swagger:Enabled", true))
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseAuthentication();
app.UseAuthorization();
app.UseStickyAfterWrite();

app.MapControllers();
app.MapHealthChecks("/health", new HealthCheckOptions
{
    ResponseWriter = (context, report) => context.Response.WriteAsJsonAsync(new
    {
        status = report.Status.ToString(),
        instance = context.RequestServices.GetRequiredService<InstanceIdentity>().Id,
        checks = report.Entries.ToDictionary(e => e.Key, e => e.Value.Status.ToString()),
        detail = report.Entries.Values.Select(e => e.Description).FirstOrDefault(d => d is not null),
        durationMs = report.TotalDuration.TotalMilliseconds
    })
});

await app.InitializeDatabaseAsync();
await app.RunAsync();

// Для WebApplicationFactory в інтеграційних тестах.
public partial class Program;
