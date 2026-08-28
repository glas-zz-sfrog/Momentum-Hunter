using System.Globalization;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public enum DisplayFreshnessState
{
    New,
    Recent,
    Seen,
    Unavailable,
}

public sealed record DisplayFreshnessView(
    DisplayFreshnessState DisplayFreshnessState,
    TimeSpan? DisplayAttentionAge,
    string DisplayFreshnessLabel)
{
    public static DisplayFreshnessView From(DateTimeOffset? factualTimestamp, DateTimeOffset now)
    {
        if (factualTimestamp is not { } timestamp || timestamp > now)
        {
            return new(DisplayFreshnessState.Unavailable, null, "AGE —");
        }

        var age = now - timestamp;
        if (age < TimeSpan.FromMinutes(30))
        {
            return new(DisplayFreshnessState.New, age, $"NEW {(int)age.TotalMinutes}m");
        }
        if (age < TimeSpan.FromHours(2))
        {
            return new(DisplayFreshnessState.Recent, age, $"RECENT {(int)age.TotalMinutes}m");
        }

        return new(DisplayFreshnessState.Seen, age, $"SEEN {timestamp.ToLocalTime():HH:mm}");
    }
}

public sealed record DisplayMiniChartSeries(
    CommandCenterEvidenceState State,
    string StateLabel,
    string Symbol,
    IReadOnlyList<CommandCenterMiniChartPointSnapshot> Points,
    DateTimeOffset? TransitionTimestamp,
    string SourceLabel,
    string Limitation)
{
    public static DisplayMiniChartSeries From(
        string symbol,
        IReadOnlyDictionary<string, CommandCenterMiniChartSeriesSnapshot> charts,
        DateTimeOffset? transitionTimestamp = null)
    {
        if (!charts.TryGetValue(symbol, out var chart))
        {
            return new(
                CommandCenterEvidenceState.Unavailable,
                "HISTORY UNAVAILABLE",
                symbol,
                [],
                transitionTimestamp,
                "Stored history source unavailable",
                "No bounded stored-history series was supplied for this symbol.");
        }

        return new(
            chart.State,
            chart.State switch
            {
                CommandCenterEvidenceState.Available => "2D · 15m",
                CommandCenterEvidenceState.Partial => "PARTIAL · 15m",
                _ => "HISTORY UNAVAILABLE",
            },
            chart.Symbol,
            chart.Points,
            transitionTimestamp,
            chart.SourceLabel,
            chart.Limitation);
    }
}

public sealed record CommandCenterRankedRowView(
    string StableCandidateIdentity,
    int SourceRank,
    string Symbol,
    string Company,
    int? Score,
    string RelativeVolumeLabel,
    string CatalystSummary,
    string PriceLabel,
    string ChangeLabel,
    string PopulationLabel,
    DateTimeOffset? DisplayFirstSurfacedAt,
    DateTimeOffset? DisplayStateChangedAt,
    DisplayFreshnessView DisplayFreshness,
    DisplayMiniChartSeries DisplayMiniChart,
    string DataLineage)
{
    public string ScoreLabel => Score?.ToString(CultureInfo.InvariantCulture) ?? "—";

    public static CommandCenterRankedRowView From(
        CommandCenterRankedCandidateSnapshot row,
        IReadOnlyDictionary<string, CommandCenterMiniChartSeriesSnapshot> charts,
        DateTimeOffset now)
    {
        var populations = new List<string>();
        if (!string.IsNullOrWhiteSpace(row.RadarMemberIdentity))
        {
            populations.Add("RADAR");
        }
        if (row.AcceptedDispositionIds.Count > 0)
        {
            populations.Add("ACCEPTED");
        }
        if (row.RejectedDispositionIds.Count > 0)
        {
            populations.Add("REJECTED");
        }

        return new(
            row.StableCandidateIdentity,
            row.SourceRank,
            row.Symbol,
            row.Company,
            row.Score,
            row.RelativeVolume is { } rvol ? $"{rvol:N1}x" : "—",
            row.CatalystSummary,
            row.LastPrice is { } price ? price.ToString("C2", CultureInfo.CurrentCulture) : "—",
            row.ChangePercent is { } change ? $"{change:+0.00;-0.00;0.00}%" : "—",
            populations.Count == 0 ? "NO POPULATION JOIN" : string.Join(" · ", populations),
            row.FirstSurfacedAt,
            row.StateChangedAt,
            DisplayFreshnessView.From(row.StateChangedAt ?? row.FirstSurfacedAt, now),
            DisplayMiniChartSeries.From(row.MiniChartSymbolKey, charts),
            row.DataLineage);
    }
}

public sealed record CommandCenterDispositionRowView(
    string DispositionPresentationIdentity,
    string DispositionEventId,
    string Kind,
    string Symbol,
    string SetupLabel,
    string TransitionLabel,
    string Reason,
    string OccurredAtLabel,
    DisplayFreshnessView DisplayFreshness,
    string ScoreLabel,
    string RelativeVolumeLabel,
    string PlanContextLabel,
    DisplayMiniChartSeries DisplayMiniChart,
    string DataLineage)
{
    public static CommandCenterDispositionRowView From(
        CommandCenterDispositionSnapshot disposition,
        IReadOnlyDictionary<string, CommandCenterRankedCandidateSnapshot[]> rankedBySymbol,
        IReadOnlyDictionary<string, CommandCenterMiniChartSeriesSnapshot> charts,
        DateTimeOffset now)
    {
        rankedBySymbol.TryGetValue(disposition.Symbol, out var candidates);
        var context = candidates is { Length: 1 } ? candidates[0] : null;
        var plan = context is null
            ? "CONTEXT UNAVAILABLE"
            : string.Join(
                " · ",
                new[]
                {
                    context.HypotheticalEntry is { } entry ? $"ENTRY {entry:N2}" : null,
                    context.HypotheticalStop is { } stop ? $"STOP {stop:N2}" : null,
                    context.HypotheticalTarget is { } target ? $"TARGET {target:N2}" : null,
                }.Where(value => value is not null));
        return new(
            disposition.DispositionPresentationIdentity,
            disposition.DispositionEventId,
            disposition.Kind,
            disposition.Symbol,
            string.IsNullOrWhiteSpace(disposition.SetupFamily)
                ? $"SETUP {disposition.SetupSequence}"
                : $"{disposition.SetupFamily.Replace('_', ' ')} · {disposition.SetupSequence}",
            $"{disposition.PreviousState} → {disposition.ReachedState}",
            disposition.Reason,
            disposition.OccurredAt?.ToLocalTime().ToString("HH:mm:ss") ?? "TIME —",
            DisplayFreshnessView.From(disposition.OccurredAt, now),
            context?.Score is { } score ? $"SCORE {score}" : "SCORE —",
            context?.RelativeVolume is { } rvol ? $"RVOL {rvol:N1}x" : "RVOL —",
            string.IsNullOrWhiteSpace(plan) ? "HYPOTHETICAL LEVELS UNAVAILABLE" : plan,
            DisplayMiniChartSeries.From(disposition.Symbol, charts, disposition.OccurredAt),
            disposition.DataLineage);
    }
}

public sealed record CommandCenterEventRowView(
    string EventIdentity,
    string TimeLabel,
    string Symbol,
    string EventLabel,
    string Evidence,
    string SourceKind)
{
    public static CommandCenterEventRowView From(CommandCenterLifecycleEventSnapshot item) => new(
        item.EventIdentity,
        item.OccurredAt?.ToLocalTime().ToString("HH:mm:ss") ?? "—",
        string.IsNullOrWhiteSpace(item.Symbol) ? "SYSTEM" : item.Symbol,
        string.IsNullOrWhiteSpace(item.PreviousState)
            ? item.NextState
            : $"{item.PreviousState} → {item.NextState}",
        item.Reason,
        item.SourceKind);

    public static CommandCenterEventRowView From(ActivityEvent item) => new(
        $"activity:{item.Timestamp.UtcTicks}:{item.Category}:{item.Symbol}",
        item.Timestamp.ToLocalTime().ToString("HH:mm:ss"),
        string.IsNullOrWhiteSpace(item.Symbol) ? "SYSTEM" : item.Symbol,
        item.Category,
        item.Message,
        "WORKSPACE SUMMARY");
}

public static class CommandCenterProjection
{
    public static IReadOnlyList<CommandCenterRankedRowView> Ranked(
        CommandCenterSnapshot snapshot,
        DateTimeOffset now) => snapshot.RankedCandidates
        .OrderBy(item => item.SourceRank)
        .Take(10)
        .Select(item => CommandCenterRankedRowView.From(item, snapshot.MiniChartsBySymbol, now))
        .ToArray();

    public static IReadOnlyList<CommandCenterDispositionRowView> Dispositions(
        IEnumerable<CommandCenterDispositionSnapshot> dispositions,
        CommandCenterSnapshot snapshot,
        DateTimeOffset now)
    {
        var rankedBySymbol = snapshot.RankedCandidates
            .GroupBy(item => item.Symbol, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.ToArray(), StringComparer.OrdinalIgnoreCase);
        return dispositions
            .OrderByDescending(item => item.OccurredAt ?? DateTimeOffset.MinValue)
            .Select(item => CommandCenterDispositionRowView.From(item, rankedBySymbol, snapshot.MiniChartsBySymbol, now))
            .ToArray();
    }
}
