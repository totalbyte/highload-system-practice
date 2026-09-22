using FluentValidation;

namespace PollingPlatform.Api.Polls;

public class CreatePollRequestValidator : AbstractValidator<CreatePollRequest>
{
    public const int MinOptions = 2;
    public const int MaxOptions = 20;

    public CreatePollRequestValidator(TimeProvider timeProvider)
    {
        RuleFor(r => r.Title).NotEmpty().MaximumLength(200);
        RuleFor(r => r.Description).MaximumLength(2000);

        RuleFor(r => r.Options)
            .NotNull()
            .Must(o => o!.Count is >= MinOptions and <= MaxOptions)
            .WithMessage($"Poll must have between {MinOptions} and {MaxOptions} options.")
            .Must(o => o!.Select(t => t?.Trim().ToLowerInvariant()).Distinct().Count() == o!.Count)
            .WithMessage("Options must be unique.");
        RuleForEach(r => r.Options).NotEmpty().MaximumLength(200);

        RuleFor(r => r.EndsAt)
            .NotNull()
            .GreaterThan(_ => timeProvider.GetUtcNow()).WithMessage("'EndsAt' must be in the future.");
        RuleFor(r => r.StartsAt)
            .LessThan(r => r.EndsAt).When(r => r.StartsAt is not null && r.EndsAt is not null)
            .WithMessage("'StartsAt' must be earlier than 'EndsAt'.");
    }
}

public class PollListQueryValidator : AbstractValidator<PollListQuery>
{
    public PollListQueryValidator()
    {
        RuleFor(q => q.Page).GreaterThanOrEqualTo(1);
        RuleFor(q => q.PageSize).InclusiveBetween(1, 100);
    }
}
