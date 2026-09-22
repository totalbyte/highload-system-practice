namespace PollingPlatform.Api.Data.Seeding;

public class SeedOptions
{
    public const string SectionName = "Seed";

    public bool Enabled { get; init; }
    public int Users { get; init; } = 500;
    public int Polls { get; init; } = 50;

    /// <summary>Спільний пароль усіх згенерованих користувачів (userNNN@example.com).</summary>
    public string Password { get; init; } = "Password123!";

    /// <summary>Фіксований seed генератора — однакові дані на кожному холодному старті.</summary>
    public int RandomSeed { get; init; } = 42;
}
