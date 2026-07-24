using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record ActivityEventView(
    string TimestampLabel,
    string CategoryLabel,
    string Message,
    string ScopeLabel,
    HealthState State,
    string StateLabel)
{
    public static ActivityEventView From(ActivityEvent activity) => new(
        $"{activity.Timestamp.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC",
        TextOrFallback(activity.Category, "Event"),
        TextOrFallback(activity.Message, "No event detail was supplied."),
        TextOrFallback(activity.Symbol, "Workspace"),
        activity.State,
        activity.State.ToString().ToUpperInvariant());

    private static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}
