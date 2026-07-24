using System.Globalization;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record SavedWatchlistItemViewModel(
    string RankLabel,
    string Symbol,
    string CompanyLabel,
    string ScoreLabel,
    string PriceChangeLabel,
    string VolumeLabel,
    string ClassificationLabel,
    string FreshnessLabel,
    string SavedAtLabel,
    string HeadlineLabel,
    string NotesLabel)
{
    public static SavedWatchlistItemViewModel From(SavedWatchlistItemSnapshot item) => new(
        $"#{item.SourceRank}",
        item.Symbol,
        TextOr(item.Company, "Company unavailable"),
        item.Score is { } score ? $"Stored score {score}" : "Stored score unavailable",
        PriceChange(item.Price, item.PercentChange),
        Volume(item.Volume, item.RelativeVolume),
        Classification(item.Sector, item.Industry),
        TextOr(item.Freshness, "Freshness unavailable"),
        item.SavedAt is { } savedAt
            ? $"Saved {savedAt.ToUniversalTime():yyyy-MM-dd HH:mm} UTC"
            : "Saved time unavailable",
        TextOr(item.FreshestHeadline, "No stored headline"),
        TextOr(item.UserNotes, "No operator notes stored"));

    private static string PriceChange(decimal? price, decimal? percentChange)
    {
        var priceLabel = price is { } value
            ? value.ToString("C2", CultureInfo.CurrentCulture)
            : "Price unavailable";
        var changeLabel = percentChange is { } change
            ? $"{change.ToString("+0.0;-0.0;0.0", CultureInfo.InvariantCulture)}%"
            : "change unavailable";
        return $"{priceLabel} | {changeLabel}";
    }

    private static string Volume(long? volume, decimal? relativeVolume)
    {
        var volumeLabel = volume is { } value
            ? value.ToString("N0", CultureInfo.InvariantCulture)
            : "unavailable";
        var relativeVolumeLabel = relativeVolume is { } rvol
            ? $"{rvol:N2}x"
            : "unavailable";
        return $"Volume {volumeLabel} | RVOL {relativeVolumeLabel}";
    }

    private static string Classification(string sector, string industry)
    {
        var values = new[] { sector, industry }
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .ToArray();
        return values.Length > 0 ? string.Join(" | ", values) : "Sector and industry unavailable";
    }

    private static string TextOr(string value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}
