namespace PollingPlatform.Api.Domain;

/// <summary>
/// Життєвий цикл опитування: Draft → (publish) → Active → (close) → Closed.
/// Видаляти можна лише Draft, голосувати — лише в Active.
/// </summary>
public enum PollStatus
{
    Draft,
    Active,
    Closed
}
