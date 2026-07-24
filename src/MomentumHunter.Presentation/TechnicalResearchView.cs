using System.Globalization;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record TechnicalResearchOverviewView(
    TechnicalResearchState State,
    string StateLabel,
    string SymbolLabel,
    string AsOfLabel,
    string SourceLabel,
    string CountSummary,
    string Summary,
    string WarningSummary)
{
    public static TechnicalResearchOverviewView From(TechnicalResearchSnapshot? snapshot)
    {
        if (snapshot is null)
        {
            return new TechnicalResearchOverviewView(
                TechnicalResearchState.Unavailable,
                "UNAVAILABLE",
                "Symbol unavailable",
                "Source time unavailable",
                "Technical research source unavailable",
                "0 symbol events | 0 studied outcomes",
                "No technical research snapshot was supplied to this workspace.",
                "No source warnings were supplied.");
        }

        return new TechnicalResearchOverviewView(
            snapshot.State,
            snapshot.State.ToString().ToUpperInvariant(),
            TextOrFallback(snapshot.Symbol, "Symbol unavailable"),
            snapshot.AsOf is null
                ? $"Checked {snapshot.ObservedAt.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC | source time unavailable"
                : $"Source as of {snapshot.AsOf.Value.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC",
            TextOrFallback(snapshot.SourceLabel, "Technical research source unavailable"),
            $"{snapshot.SymbolEventCount} symbol events | {snapshot.SymbolStudyCount} studied outcomes | " +
            $"{snapshot.PresentEventCount} present | {snapshot.FailedStudyCount} failed studies | " +
            $"{snapshot.InsufficientDataCount} insufficient",
            TextOrFallback(snapshot.Summary, "Technical research summary unavailable."),
            snapshot.Warnings.Count == 0
                ? "No source warnings were stored."
                : string.Join(" | ", snapshot.Warnings));
    }

    private static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}

public sealed record TechnicalResearchEventRowView(
    string TimestampLabel,
    string TypeLabel,
    string TimeframeLabel,
    string StatusLabel,
    string QualityLabel,
    string SufficiencyLabel,
    string EventIdLabel,
    string MetricsLabel,
    string Notes)
{
    public static TechnicalResearchEventRowView From(TechnicalResearchEventSnapshot item) => new(
        FormatTimestamp(item.EventTimestamp, item.Timeframe),
        FriendlyType(item.EventType),
        TextOrFallback(item.Timeframe, "Timeframe unavailable").ToUpperInvariant(),
        TextOrFallback(item.Status, "Insufficient data"),
        TextOrFallback(item.QualityFlag, "UNAVAILABLE").ToUpperInvariant(),
        TextOrFallback(item.DataSufficiency, "Insufficient data"),
        TextOrFallback(item.EventId, "ID unavailable"),
        string.Join(
            " | ",
            new[]
            {
                item.TriggerPrice is null ? "Trigger unavailable" : $"Trigger {item.TriggerPrice.Value:C2}",
                Percent("Distance", item.DistanceAboveTriggerPercent),
                item.RelativeVolume is null ? "RVOL unavailable" : $"RVOL {item.RelativeVolume.Value:N2}x",
                $"Volume {BooleanLabel(item.VolumeConfirmed)}",
                $"Relative strength {BooleanLabel(item.RelativeStrengthConfirmed)}",
            }),
        TextOrFallback(item.Notes, "No event notes were stored."));

    internal static string FormatTimestamp(DateTimeOffset? timestamp, string timeframe)
    {
        if (timestamp is null)
        {
            return "Event time unavailable";
        }
        return string.Equals(timeframe, "daily", StringComparison.OrdinalIgnoreCase)
            ? timestamp.Value.ToUniversalTime().ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)
            : $"{timestamp.Value.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC";
    }

    internal static string FriendlyType(string? value)
    {
        var text = TextOrFallback(value, "Event type unavailable").Replace('_', ' ');
        return CultureInfo.InvariantCulture.TextInfo.ToTitleCase(text.ToLowerInvariant());
    }

    internal static string BooleanLabel(bool? value) => value switch
    {
        true => "YES",
        false => "NO",
        _ => "UNAVAILABLE",
    };

    internal static string Percent(string label, decimal? value) =>
        value is null ? $"{label} unavailable" : $"{label} {value.Value:+0.00;-0.00;0.00}%";

    internal static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}

public sealed record TechnicalResearchStudyRowView(
    string TimestampLabel,
    string TypeLabel,
    string TimeframeLabel,
    string StatusLabel,
    string SufficiencyLabel,
    string EventIdLabel,
    string ReturnsLabel,
    string ExcursionLabel,
    string FlagsLabel,
    string Notes)
{
    public static TechnicalResearchStudyRowView From(TechnicalResearchStudySnapshot item) => new(
        TechnicalResearchEventRowView.FormatTimestamp(item.EventTimestamp, item.Timeframe),
        TechnicalResearchEventRowView.FriendlyType(item.EventType),
        TechnicalResearchEventRowView.TextOrFallback(item.Timeframe, "Timeframe unavailable").ToUpperInvariant(),
        TechnicalResearchEventRowView.TextOrFallback(item.Status, "Insufficient data"),
        TechnicalResearchEventRowView.TextOrFallback(item.DataSufficiency, "Insufficient data"),
        TechnicalResearchEventRowView.TextOrFallback(item.EventId, "ID unavailable"),
        ReturnSummary(item),
        $"{TechnicalResearchEventRowView.Percent("MFE", item.MaxFavorableExcursionPercent)} | " +
        TechnicalResearchEventRowView.Percent("MAE", item.MaxAdverseExcursionPercent),
        $"Held {TechnicalResearchEventRowView.BooleanLabel(item.HeldAboveBreakoutLevel)} | " +
        $"Failed {TechnicalResearchEventRowView.BooleanLabel(item.FailedBackBelowBreakoutLevel)} | " +
        $"Extended {TechnicalResearchEventRowView.BooleanLabel(item.BecameExtended)} | " +
        $"Volume {TechnicalResearchEventRowView.BooleanLabel(item.VolumeConfirmed)}",
        TechnicalResearchEventRowView.TextOrFallback(item.Notes, "No study notes were stored."));

    private static string ReturnSummary(TechnicalResearchStudySnapshot item)
    {
        var returns = new[]
        {
            ("5m", item.Return5MinutePercent),
            ("15m", item.Return15MinutePercent),
            ("60m", item.Return60MinutePercent),
            ("1d", item.Return1DayPercent),
            ("5d", item.Return5DayPercent),
            ("10d", item.Return10DayPercent),
        }
        .Where(entry => entry.Item2 is not null)
        .Select(entry => TechnicalResearchEventRowView.Percent(entry.Item1, entry.Item2))
        .ToArray();
        return returns.Length == 0 ? "Forward returns unavailable" : string.Join(" | ", returns);
    }
}
