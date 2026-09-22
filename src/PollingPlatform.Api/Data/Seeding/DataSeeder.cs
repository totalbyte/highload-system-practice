using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using PollingPlatform.Api.Domain;

namespace PollingPlatform.Api.Data.Seeding;

/// <summary>
/// Генерує тестові дані для демо та навантажувальних тестів (лаба 5):
/// пул користувачів userNNN@example.com зі спільним паролем та набір опитувань з голосами.
/// Опитування #1 («гаряче») — активне, без голосів, з allowVoteChange: ціль для write-сценарію.
/// </summary>
public class DataSeeder(
    AppDbContext db,
    IPasswordHasher<User> passwordHasher,
    IOptions<SeedOptions> options,
    TimeProvider timeProvider,
    ILogger<DataSeeder> logger)
{
    // Довільна константа для pg_advisory_xact_lock: серіалізує сідінг між інстансами, що стартують одночасно.
    private const long SeedLockKey = 7_140_001;

    private static readonly string[] Topics =
    [
        "Улюблена мова програмування", "Найкращий редактор коду", "Формат навчання", "Час для пар",
        "Кава чи чай", "Найкраща СУБД", "Хмарний провайдер", "Операційна система", "Тема диплома",
        "Фреймворк для фронтенду", "Місце для хакатону", "Музика під час кодингу"
    ];

    private static readonly string[] OptionWords =
    [
        "C#", "Go", "Python", "Rust", "TypeScript", "Java", "PostgreSQL", "Redis", "MongoDB", "Linux",
        "Windows", "macOS", "Так", "Ні", "Ранок", "Вечір", "Онлайн", "Офлайн", "Кава", "Чай", "AWS", "Azure", "GCP"
    ];

    public async Task SeedAsync(CancellationToken ct = default)
    {
        // Retry-стратегія EF не може сама повторити явну транзакцію — повторюємо весь блок цілком.
        var strategy = db.Database.CreateExecutionStrategy();
        await strategy.ExecuteAsync(SeedOnceAsync, ct);
    }

    private async Task SeedOnceAsync(CancellationToken ct)
    {
        var o = options.Value;
        db.ChangeTracker.Clear(); // прибрати сутності з невдалої попередньої спроби

        await using var tx = await db.Database.BeginTransactionAsync(ct);
        await db.Database.ExecuteSqlAsync($"SELECT pg_advisory_xact_lock({SeedLockKey})", ct);

        if (await db.Users.AnyAsync(ct))
        {
            logger.LogInformation("Seed skipped: database already contains data");
            return;
        }

        var random = new Random(o.RandomSeed);
        var now = timeProvider.GetUtcNow();

        // PBKDF2 навмисно повільний (~десятки мс), тому хешуємо спільний пароль один раз, а не 500 разів.
        var passwordHash = passwordHasher.HashPassword(null!, o.Password);
        var users = Enumerable.Range(1, o.Users)
            .Select(i => new User
            {
                Username = $"user{i:D3}",
                Email = $"user{i:D3}@example.com",
                PasswordHash = passwordHash,
                CreatedAt = now.AddDays(-30)
            })
            .ToList();
        db.Users.AddRange(users);
        await db.SaveChangesAsync(ct);

        var polls = new List<Poll>(o.Polls) { CreateHotPoll(users[0], now) };
        for (var i = 1; i < o.Polls; i++)
            polls.Add(CreateRandomPoll(i, users, random, now));

        db.Polls.AddRange(polls);
        await db.SaveChangesAsync(ct);

        var votes = new List<Vote>();
        foreach (var poll in polls.Skip(1).Where(p => p.Status != PollStatus.Draft))
            votes.AddRange(CreateVotes(poll, users, random, now));

        db.Votes.AddRange(votes);
        await db.SaveChangesAsync(ct);
        await tx.CommitAsync(ct);

        logger.LogInformation("Seeded {Users} users, {Polls} polls, {Votes} votes", users.Count, polls.Count, votes.Count);
    }

    private static Poll CreateHotPoll(User creator, DateTimeOffset now) => new()
    {
        Title = "Гаряче опитування: яка лаба найцікавіша?",
        Description = "Ціль для навантажувального write-сценарію (POST /vote).",
        CreatorId = creator.Id,
        Status = PollStatus.Active,
        IsPublic = true,
        AllowVoteChange = true,
        StartsAt = now.AddDays(-1),
        EndsAt = now.AddYears(1),
        CreatedAt = now.AddDays(-1),
        Options = new[] { "Stateless", "Horizontal Scaling", "Distributed Caching", "Load Testing" }
            .Select((text, i) => new PollOption { Text = text, Position = i + 1 })
            .ToList()
    };

    private static Poll CreateRandomPoll(int index, List<User> users, Random random, DateTimeOffset now)
    {
        // ~70% активних, ~15% закритих, ~15% чернеток.
        var roll = random.NextDouble();
        var status = roll < 0.70 ? PollStatus.Active : roll < 0.85 ? PollStatus.Closed : PollStatus.Draft;
        var createdAt = now.AddDays(-random.Next(1, 30)).AddMinutes(-random.Next(0, 1440));

        var optionTexts = OptionWords.OrderBy(_ => random.Next()).Take(random.Next(2, 6)).ToList();

        return new Poll
        {
            Title = $"{Topics[random.Next(Topics.Length)]} #{index}",
            Description = random.NextDouble() < 0.5 ? "Згенероване опитування для тестування." : null,
            // Автори — перші 20 користувачів, щоб фільтр за creatorId повертав змістовні списки.
            CreatorId = users[random.Next(Math.Min(20, users.Count))].Id,
            Status = status,
            IsPublic = random.NextDouble() < 0.9,
            AllowVoteChange = random.NextDouble() < 0.3,
            StartsAt = status == PollStatus.Draft ? null : createdAt,
            // createdAt щонайменше добу тому, тож закрите опитування завершилось у минулому і після старту.
            EndsAt = status == PollStatus.Closed ? createdAt.AddHours(random.Next(1, 20)) : now.AddDays(random.Next(1, 60)),
            CreatedAt = createdAt,
            Options = optionTexts.Select((text, i) => new PollOption { Text = text, Position = i + 1 }).ToList()
        };
    }

    private static IEnumerable<Vote> CreateVotes(Poll poll, List<User> users, Random random, DateTimeOffset now)
    {
        var voters = users.OrderBy(_ => random.Next()).Take(random.Next(0, users.Count / 2));
        foreach (var voter in voters)
        {
            var option = poll.Options[random.Next(poll.Options.Count)];
            option.VoteCount++; // лічильник узгоджений з кількістю рядків у votes
            yield return new Vote
            {
                PollId = poll.Id,
                OptionId = option.Id,
                UserId = voter.Id,
                CreatedAt = now.AddMinutes(-random.Next(1, 10_000))
            };
        }
    }
}
