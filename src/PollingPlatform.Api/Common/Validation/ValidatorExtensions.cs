using FluentValidation;
using AppValidationException = PollingPlatform.Api.Common.Exceptions.ValidationException;

namespace PollingPlatform.Api.Common.Validation;

public static class ValidatorExtensions
{
    /// <summary>Валідує запит і кидає <see cref="AppValidationException"/> (→ 422) зі списком помилок по полях.</summary>
    public static async Task ValidateOrThrowAsync<T>(this IValidator<T> validator, T instance, CancellationToken ct = default)
    {
        var result = await validator.ValidateAsync(instance, ct);
        if (result.IsValid)
            return;

        var errors = result.Errors
            .GroupBy(e => e.PropertyName)
            .ToDictionary(g => g.Key, g => g.Select(e => e.ErrorMessage).ToArray());

        throw new AppValidationException(errors);
    }
}
