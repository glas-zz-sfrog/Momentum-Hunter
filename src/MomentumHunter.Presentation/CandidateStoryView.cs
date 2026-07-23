using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record CandidateStoryOverviewView(
    string State,
    string Symbol,
    string CompanyContext,
    string Status,
    string StatusDetail,
    string FirstSeen,
    string LatestSeen,
    string Move,
    string ScorePath,
    string PeakScore,
    string CaptureCount,
    string Source,
    string AsOf,
    string Summary,
    string Warnings)
{
    public static CandidateStoryOverviewView From(CandidateStorySnapshot? snapshot)
    {
        if (snapshot is null)
        {
            return new CandidateStoryOverviewView(
                "UNAVAILABLE",
                "No symbol",
                "Company and industry unavailable",
                "Insufficient data",
                "Candidate Story evidence has not loaded.",
                "Unavailable",
                "Unavailable",
                "Unavailable",
                "Unavailable",
                "Unavailable",
                "0 trusted captures",
                "Source unavailable",
                "Source time unavailable",
                "Candidate Story evidence is unavailable.",
                "No Candidate Story warnings are available.");
        }

        var companyContext = string.Join(
            " | ",
            new[] { snapshot.Company, snapshot.Sector, snapshot.Industry }
                .Where(value => !string.IsNullOrWhiteSpace(value)));
        return new CandidateStoryOverviewView(
            snapshot.State.ToString().ToUpperInvariant(),
            snapshot.Symbol,
            string.IsNullOrWhiteSpace(companyContext) ? "Company and industry unavailable" : companyContext,
            snapshot.Status,
            snapshot.StatusDetail,
            $"{snapshot.FirstSeenLabel} | {Money(snapshot.FirstPrice)}",
            $"{snapshot.LatestSeenLabel} | {Money(snapshot.LatestPrice)}",
            Percent(snapshot.MoveSinceFirstPercent),
            $"{Number(snapshot.FirstScore)} -> {Number(snapshot.LatestScore)}",
            $"{Number(snapshot.PeakScore)} | {snapshot.PeakScoreLabel}",
            $"{snapshot.TrustedCaptureCount} trusted capture{(snapshot.TrustedCaptureCount == 1 ? string.Empty : "s")}",
            snapshot.SourceLabel,
            snapshot.SourceAsOf is { } timestamp
                ? $"Source as of {timestamp:yyyy-MM-dd HH:mm zzz}"
                : "Source time unavailable",
            snapshot.Summary,
            snapshot.Warnings.Count == 0
                ? "No Candidate Story warnings were reported."
                : string.Join(Environment.NewLine, snapshot.Warnings.Select(warning => $"- {warning}")));
    }

    private static string Money(decimal? value) => value is null ? "n/a" : value.Value.ToString("C2");

    private static string Number(decimal? value) => value is null ? "n/a" : value.Value.ToString("0.#");

    private static string Percent(decimal? value) =>
        value is null ? "n/a" : $"{(value > 0 ? "+" : string.Empty)}{value:0.0}%";
}

public sealed record CandidateStoryPointRowView(
    int Sequence,
    string CapturedAt,
    string Session,
    string Price,
    string Score,
    string MoveFromFirst,
    string RelativeVolume,
    string CaptureNote,
    string LaterAnnotation,
    string SourceContext,
    string Trust)
{
    public static CandidateStoryPointRowView From(CandidateStoryPointSnapshot point) => new(
        point.Sequence,
        point.CapturedAtLabel,
        point.SessionMarker,
        point.Price is null ? "n/a" : point.Price.Value.ToString("C2"),
        point.Score is null ? "n/a" : point.Score.Value.ToString("0.#"),
        point.PriceChangeFirstPercent is null
            ? "n/a"
            : $"{(point.PriceChangeFirstPercent > 0 ? "+" : string.Empty)}{point.PriceChangeFirstPercent:0.0}%",
        point.RelativeVolume is null ? "n/a" : $"{point.RelativeVolume:0.00}x",
        point.CaptureNote,
        point.LaterAnnotation,
        $"{point.Provider} | {point.Scanner} | {point.CalendarLabel}",
        point.TrustLabel);
}
