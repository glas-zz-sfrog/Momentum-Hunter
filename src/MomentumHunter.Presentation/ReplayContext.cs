using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record ReplayContextView(
    string StatusLabel,
    string ReplayIdLabel,
    string SymbolLabel,
    string IntervalLabel,
    string AsOfLabel,
    string Summary)
{
    public static ReplayContextView From(ReplaySnapshot? snapshot)
    {
        if (snapshot is null)
        {
            return new ReplayContextView(
                "UNAVAILABLE",
                "Replay identity unavailable",
                "Symbol not selected",
                "Interval unavailable",
                "Replay time unavailable",
                "Replay context is unavailable.");
        }

        var replayId = TextOrFallback(snapshot.ReplayId, "UNAVAILABLE");
        var status = replayId.Equals("UNAVAILABLE", StringComparison.OrdinalIgnoreCase)
            ? "UNAVAILABLE"
            : replayId.Equals("NOT_SELECTED", StringComparison.OrdinalIgnoreCase)
                ? "NOT SELECTED"
                : "AVAILABLE";

        return new ReplayContextView(
            status,
            replayId,
            TextOrFallback(snapshot.Symbol, "Symbol not selected"),
            TextOrFallback(snapshot.Interval, "Interval unavailable"),
            $"{snapshot.AsOf.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC",
            TextOrFallback(snapshot.Summary, "No replay summary was supplied."));
    }

    private static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}
