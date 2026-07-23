using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record AlertEvidenceOverviewView(
    AlertEvidenceState State,
    string StateLabel,
    string AsOfLabel,
    string Summary,
    string CountSummary)
{
    public static AlertEvidenceOverviewView From(AlertEvidenceSnapshot? evidence)
    {
        if (evidence is null)
        {
            return new AlertEvidenceOverviewView(
                AlertEvidenceState.Unavailable,
                "UNAVAILABLE",
                "As-of time unavailable",
                "No alert evidence snapshot was supplied to this workspace.",
                "0 total | 0 active or pending | 0 outcomes | 0 unscorable");
        }

        return new AlertEvidenceOverviewView(
            evidence.State,
            evidence.State.ToString().ToUpperInvariant(),
            evidence.State == AlertEvidenceState.Unavailable
                ? $"Checked {evidence.AsOf.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC"
                : $"Source as of {evidence.AsOf.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC",
            TextOrFallback(evidence.Summary, "No alert evidence summary was supplied."),
            $"{evidence.TotalAlertCount} total | {evidence.ActiveAlertCount} active or pending | " +
            $"{evidence.RecordedOutcomeCount} outcomes | {evidence.UnscorableOutcomeCount} unscorable");
    }

    private static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}

public sealed record AlertEventRowView(
    string TimestampLabel,
    string SymbolLabel,
    string TypeLabel,
    string StateLabel,
    string AlertIdLabel,
    string Summary)
{
    public static AlertEventRowView From(AlertEvent alert) => new(
        FormatTimestamp(alert.Timestamp),
        TextOrFallback(alert.Symbol, "Symbol unavailable"),
        TextOrFallback(alert.AlertType, "Type unavailable"),
        TextOrFallback(alert.State, "UNAVAILABLE").ToUpperInvariant(),
        TextOrFallback(alert.AlertId, "ID unavailable"),
        TextOrFallback(alert.Summary, "No alert summary was supplied."));

    private static string FormatTimestamp(DateTimeOffset? timestamp) =>
        timestamp is null
            ? "Time unavailable"
            : $"{timestamp.Value.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC";

    private static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}

public sealed record OutcomeRowView(
    string TimestampLabel,
    string SymbolLabel,
    string StatusLabel,
    string ClassificationLabel,
    string AlertIdLabel,
    string Summary)
{
    public static OutcomeRowView From(OutcomeSnapshot outcome) => new(
        FormatTimestamp(outcome.AlertTimestamp),
        TextOrFallback(outcome.Symbol, "Symbol unavailable"),
        TextOrFallback(outcome.Status, "UNAVAILABLE").ToUpperInvariant(),
        TextOrFallback(outcome.Classification, "UNAVAILABLE").ToUpperInvariant(),
        TextOrFallback(outcome.AlertId, "ID unavailable"),
        TextOrFallback(outcome.Summary, "No outcome summary was supplied."));

    private static string FormatTimestamp(DateTimeOffset? timestamp) =>
        timestamp is null
            ? "Alert time unavailable"
            : $"Alert {timestamp.Value.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC";

    private static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}
