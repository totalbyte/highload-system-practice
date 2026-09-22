using FluentValidation;

namespace PollingPlatform.Api.Votes;

public class CastVoteRequestValidator : AbstractValidator<CastVoteRequest>
{
    public CastVoteRequestValidator()
    {
        RuleFor(r => r.OptionId).NotNull().GreaterThan(0);
    }
}
