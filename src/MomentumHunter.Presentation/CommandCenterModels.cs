using System.Globalization;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

/// <summary>
/// UI-only projection of one candidate. Rank remains the source collection
/// position and age is display metadata only; neither value changes engine
/// admission, readiness, risk, or ordering.
/// </summary>
public sealed record CommandCenterAttentionRowView(
    int Rank,
    CandidateSnapshot Candidate,
    string Symbol,
    string Company,
    string PriceLabel,
    string ChangeLabel,
    string RelativeVolumeLabel,
    string CatalystLabel,
    string OpportunityLabel,
    string EvidenceLabel,
    string EvidenceDetail,
    string AgeCategory,
    string AgeLabel,
    string AgeDetail)
{
    public string ContextLabel => $"{RelativeVolumeLabel} | {CatalystLabel}";

    public static CommandCenterAttentionRowView From(
        CandidateSnapshot candidate,
        int rank,
        DateTimeOffset now)
    {
        ArgumentNullException.ThrowIfNull(candidate);
        var age = CommandCenterAgeView.From(candidate.ObservedAt, now);
        return new CommandCenterAttentionRowView(
            rank,
            candidate,
            TextOrFallback(candidate.Symbol, "SYMBOL UNAVAILABLE"),
            TextOrFallback(candidate.Company, "Company unavailable"),
            candidate.LastPrice?.ToString("C2", CultureInfo.CurrentCulture) ?? "Price unavailable",
            candidate.ChangePercent is { } change
                ? $"{change:+0.0;-0.0;0.0}%"
                : "Change unavailable",
            candidate.RelativeVolume is { } relativeVolume
                ? $"RVOL {relativeVolume:N2}x"
                : "RVOL unavailable",
            TextOrFallback(candidate.Catalyst, "Catalyst unavailable"),
            TextOrFallback(candidate.SourceReadinessLabel, candidate.OperatorState),
            EvidenceStateLabel(candidate),
            TextOrFallback(candidate.QualityLabel, "Source quality unavailable"),
            age.Category,
            age.Label,
            age.Detail);
    }

    public static IReadOnlyList<CommandCenterAttentionRowView> ProjectSourceOrder(
        IEnumerable<CandidateSnapshot> candidates,
        DateTimeOffset now) =>
        candidates.Select((candidate, index) => From(candidate, index + 1, now)).ToArray();

    internal static string EvidenceStateLabel(ReadinessState readiness) => readiness switch
    {
        ReadinessState.ReadyForSimulation => "READY",
        ReadinessState.NeedsEvidence => "NEEDS EVIDENCE",
        ReadinessState.StaleData => "STALE",
        _ => "BLOCKED",
    };

    internal static string EvidenceStateLabel(CandidateSnapshot candidate)
    {
        var qualityLabel = candidate.QualityLabel?.Trim().ToUpperInvariant();
        return qualityLabel switch
        {
            "READY" => "READY",
            "PARTIAL" => "PARTIAL",
            "UNAVAILABLE" => "UNAVAILABLE",
            "HISTORY LOADING" => "HISTORY LOADING",
            "QUOTE STALE" => "QUOTE STALE",
            _ => EvidenceStateLabel(candidate.Readiness),
        };
    }

    internal static string TextOrFallback(string? value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}

public sealed record CommandCenterAgeView(string Category, string Label, string Detail)
{
    public static CommandCenterAgeView From(DateTimeOffset observedAt, DateTimeOffset now)
    {
        if (observedAt == DateTimeOffset.MinValue || observedAt > now)
        {
            return new CommandCenterAgeView(
                "AGE UNKNOWN",
                "AGE UNKNOWN",
                "Report observation time is missing or later than the current UI clock. This display does not affect source order or decision state.");
        }

        var age = now - observedAt;
        var detail = $"UI age from report ObservedAt {observedAt.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC; this is not discovery time and does not affect rank or readiness.";
        if (age < TimeSpan.FromMinutes(30))
        {
            return new CommandCenterAgeView("NEW", $"NEW {WholeMinutes(age)}m", detail);
        }
        if (age < TimeSpan.FromHours(2))
        {
            return new CommandCenterAgeView("RECENT", $"RECENT {WholeMinutes(age)}m", detail);
        }

        if (age >= TimeSpan.FromHours(24))
        {
            return new CommandCenterAgeView(
                "EARLIER",
                $"SEEN {observedAt.ToUniversalTime():yyyy-MM-dd}",
                detail);
        }

        var hours = (int)Math.Floor(age.TotalHours);
        var minutes = age.Minutes;
        var duration = minutes == 0 ? $"{hours}h" : $"{hours}h {minutes}m";
        return new CommandCenterAgeView("EARLIER", $"EARLIER {duration}", detail);
    }

    private static int WholeMinutes(TimeSpan value) => Math.Max(0, (int)Math.Floor(value.TotalMinutes));
}

/// <summary>
/// Explicit pair used by the Command Center so exposed opportunity wording is
/// never collapsed into evidence readiness or quality.
/// </summary>
public sealed record CommandCenterStatePairView(
    string OpportunityLabel,
    string EvidenceLabel,
    string OpportunityDetail,
    string EvidenceDetail)
{
    public static CommandCenterStatePairView From(
        CandidateSnapshot? candidate,
        ChartPaneViewModel? chart)
    {
        if (candidate is null)
        {
            return new CommandCenterStatePairView(
                "UNKNOWN",
                "UNAVAILABLE",
                "No selected-candidate opportunity wording is available.",
                "No selected-candidate evidence state is available.");
        }

        var chartDetail = chart is null
            ? "Chart evidence unavailable"
            : $"Chart {chart.DataState.ToString().ToUpperInvariant()} | {chart.ProviderStatusLabel}";
        return new CommandCenterStatePairView(
            CommandCenterAttentionRowView.TextOrFallback(candidate.SourceReadinessLabel, candidate.OperatorState),
            CommandCenterAttentionRowView.EvidenceStateLabel(candidate),
            candidate.OpportunityNotes is { Count: > 0 }
                ? string.Join(" | ", candidate.OpportunityNotes)
                : "No persisted opportunity note was supplied.",
            $"{CommandCenterAttentionRowView.TextOrFallback(candidate.QualityLabel, "Source quality unavailable")} | {chartDetail}");
    }
}

public sealed record CommandCenterDecisionView(
    string ContextLabel,
    string Symbol,
    CommandCenterStatePairView StatePair,
    string Answer,
    string DecisiveReason,
    string Blocker,
    string EntryLabel,
    string StopLabel,
    string Target1Label,
    string Target2Label,
    string SetupTypeLabel,
    string ReadinessLabel,
    string RelativeVolumeLabel,
    string MarketContextLabel,
    string WhyNow,
    string WhyTradeOrNot,
    string SafetyLabel)
{
    public const string UnavailableInCurrentReadModel = "Unavailable in current read model";

    public static CommandCenterDecisionView From(
        CandidateSnapshot? candidate,
        TradePlanSnapshot? plan,
        ChartPaneViewModel? chart)
    {
        var statePair = CommandCenterStatePairView.From(candidate, chart);
        var symbol = candidate?.Symbol ?? plan?.Symbol ?? "NO SYMBOL";
        var asOf = candidate?.ObservedAt ?? plan?.DataLineage.AsOf;
        var context = asOf is { } timestamp
            ? $"CURRENT — AS OF {timestamp.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC"
            : "CURRENT — AS OF TIME UNAVAILABLE";
        var risk = plan?.RiskDecision;
        var answer = risk is not null && !string.IsNullOrWhiteSpace(risk.State)
            ? risk.State.Trim()
            : candidate is not null
                ? statePair.OpportunityLabel
                : "DECISION EVIDENCE UNAVAILABLE";
        var decisiveReason = FirstText(
            risk?.Summary,
            risk?.Reasons.FirstOrDefault(),
            candidate?.OpportunityNotes?.FirstOrDefault(),
            "Decisive reason unavailable in current read model.");
        var blocker = risk switch
        {
            { Allowed: false } => FirstText(risk.Reasons.FirstOrDefault(), risk.Summary, "A blocker is reported without detail."),
            { Allowed: true } => "No blocker reported by the current risk evidence.",
            _ => "Blocker unavailable in current read model.",
        };
        var whyNow = candidate is null
            ? "Why-now evidence unavailable for the current selection."
            : string.Join(
                " | ",
                new[]
                {
                    $"Catalyst: {CommandCenterAttentionRowView.TextOrFallback(candidate.CatalystSummary?.Headline ?? candidate.Catalyst, "unavailable")}",
                    candidate.RelativeVolume is { } relativeVolume ? $"RVOL {relativeVolume:N2}x" : "RVOL unavailable",
                    $"Score {candidate.Score:N0}",
                });

        return new CommandCenterDecisionView(
            context,
            symbol,
            statePair,
            answer,
            decisiveReason,
            blocker,
            plan?.EntryDisplay ?? UnavailableInCurrentReadModel,
            plan?.StopDisplay ?? UnavailableInCurrentReadModel,
            plan?.TargetDisplay ?? UnavailableInCurrentReadModel,
            UnavailableInCurrentReadModel,
            UnavailableInCurrentReadModel,
            plan is null
                ? statePair.EvidenceLabel
                : CommandCenterAttentionRowView.EvidenceStateLabel(plan.Readiness),
            candidate?.RelativeVolume is { } rvol ? $"{rvol:N2}x" : UnavailableInCurrentReadModel,
            candidate is null
                ? UnavailableInCurrentReadModel
                : $"Liquidity: {CommandCenterAttentionRowView.TextOrFallback(candidate.FloatOrLiquidity, "unavailable")}",
            whyNow,
            risk is null
                ? "Why-trade / why-not evidence unavailable in current read model."
                : FirstText(risk.Summary, risk.Reasons.FirstOrDefault(), "No risk explanation was supplied."),
            "READ-ONLY RESEARCH — NO ORDER CAPABILITY");
    }

    private static string FirstText(params string?[] values) =>
        values.First(value => !string.IsNullOrWhiteSpace(value))!.Trim();
}

public sealed record CommandCenterMarketStoryView(
    string Symbol,
    string Company,
    string PriceAndChangeLabel,
    string WhyNow,
    string HistoryContextLabel,
    string SourceAndIntervalLabel)
{
    public static CommandCenterMarketStoryView From(
        CandidateSnapshot? candidate,
        ChartPaneViewModel? chart)
    {
        var price = candidate?.LastPrice?.ToString("C2", CultureInfo.CurrentCulture) ?? "Price unavailable";
        var change = candidate?.ChangePercent is { } value ? $"{value:+0.0;-0.0;0.0}%" : "Change unavailable";
        var catalyst = candidate is null
            ? "Selected-candidate story unavailable."
            : CommandCenterAttentionRowView.TextOrFallback(
                candidate.CatalystSummary?.Headline ?? candidate.Catalyst,
                "Catalyst unavailable");
        var history = chart is null
            ? "Stored market history is unavailable. No candles are synthesized or backfilled in the Command Center."
            : chart.Candles.Count == 0
                ? "No stored candles are available. The Command Center does not aggregate or backfill missing history."
                : "Existing stored history is shown before and after report observation where supplied; ObservedAt is not treated as market-history start.";
        var source = chart is null
            ? "Chart source / interval unavailable"
            : $"{chart.Pane.Interval} | {chart.ProviderStatusLabel} | {chart.TimingStatusLabel}";
        return new CommandCenterMarketStoryView(
            candidate?.Symbol ?? chart?.Pane.Symbol ?? "NO SYMBOL",
            CommandCenterAttentionRowView.TextOrFallback(candidate?.Company, "Company unavailable"),
            $"{price} | {change}",
            $"WHY NOW? {catalyst}",
            history,
            source);
    }
}

public sealed record CommandCenterTimelineItemView(
    DateTimeOffset? Timestamp,
    string TimestampLabel,
    string SourceKind,
    string Symbol,
    string Summary,
    string Detail,
    string Identity,
    string ContextLabel,
    bool HasStableHistoricalIdentity)
{
    public static IReadOnlyList<CommandCenterTimelineItemView> Compose(
        IEnumerable<ActivityEvent> activities,
        CandidateStorySnapshot? story,
        TechnicalResearchSnapshot? research,
        string selectedSymbol)
    {
        var symbol = selectedSymbol.Trim();
        var rows = new List<CommandCenterTimelineItemView>();
        rows.AddRange(activities
            .Where(item => string.IsNullOrWhiteSpace(item.Symbol)
                || string.Equals(item.Symbol, symbol, StringComparison.OrdinalIgnoreCase))
            .Select(item => new CommandCenterTimelineItemView(
                item.Timestamp,
                TimestampText(item.Timestamp),
                "ACTIVITY",
                CommandCenterAttentionRowView.TextOrFallback(item.Symbol, "WORKSPACE"),
                CommandCenterAttentionRowView.TextOrFallback(item.Message, "No activity detail was supplied."),
                $"{CommandCenterAttentionRowView.TextOrFallback(item.Category, "Event")} | {item.State.ToString().ToUpperInvariant()}",
                $"activity:{item.Timestamp.UtcTicks}:{item.Category}:{item.Symbol}",
                "RECORDED EVENT",
                false)));

        if (story is not null
            && string.Equals(story.Symbol, symbol, StringComparison.OrdinalIgnoreCase))
        {
            rows.AddRange(story.Points.Select(point => new CommandCenterTimelineItemView(
                point.CapturedAt,
                TimestampText(point.CapturedAt, point.CapturedAtLabel),
                "CANDIDATE STORY",
                story.Symbol,
                CommandCenterAttentionRowView.TextOrFallback(point.CaptureNote, point.CaptureLabel),
                StoryDetail(point),
                CommandCenterAttentionRowView.TextOrFallback(point.IdentityKey, point.CaptureId),
                "HISTORICAL EVIDENCE",
                point.CapturedAt is not null && !string.IsNullOrWhiteSpace(point.IdentityKey))));
        }

        if (research is not null
            && string.Equals(research.Symbol, symbol, StringComparison.OrdinalIgnoreCase))
        {
            rows.AddRange(research.Events.Select(item => new CommandCenterTimelineItemView(
                item.EventTimestamp,
                TimestampText(item.EventTimestamp),
                "TECHNICAL RESEARCH",
                research.Symbol,
                $"{TechnicalResearchEventRowView.FriendlyType(item.EventType)} | {CommandCenterAttentionRowView.TextOrFallback(item.Status, "Status unavailable")}",
                CommandCenterAttentionRowView.TextOrFallback(item.Notes, "No technical-event detail was supplied."),
                CommandCenterAttentionRowView.TextOrFallback(item.EventId, "Technical event identity unavailable"),
                "RECORDED EVENT",
                false)));
        }

        return rows
            .OrderByDescending(item => item.Timestamp ?? DateTimeOffset.MinValue)
            .ThenBy(item => item.SourceKind, StringComparer.Ordinal)
            .ThenBy(item => item.Identity, StringComparer.Ordinal)
            .ToArray();
    }

    private static string StoryDetail(CandidateStoryPointSnapshot point)
    {
        var later = string.IsNullOrWhiteSpace(point.LaterAnnotation)
            ? "Later annotation unavailable"
            : point.LaterAnnotation.Trim();
        return $"{point.SourceContext()} | {later} | Trust {CommandCenterAttentionRowView.TextOrFallback(point.TrustLabel, "unavailable")}";
    }

    private static string TimestampText(DateTimeOffset? timestamp, string? fallback = null) =>
        timestamp is { } value
            ? value.ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss 'UTC'", CultureInfo.InvariantCulture)
            : CommandCenterAttentionRowView.TextOrFallback(fallback, "TIME UNAVAILABLE");
}

public sealed record CommandCenterTimelineSelectionView(
    string ContextLabel,
    string Title,
    string TimestampLabel,
    string SourceLabel,
    string IdentityLabel,
    string Detail,
    string Limitation)
{
    public static CommandCenterTimelineSelectionView From(
        CommandCenterTimelineItemView? selected,
        string currentSymbol)
    {
        if (selected is null)
        {
            return new CommandCenterTimelineSelectionView(
                "CURRENT",
                $"CURRENT — {currentSymbol}",
                "Current decision remains in the Decision pane.",
                "CURRENT WORKSPACE",
                "Identity unavailable until a traceable row is selected.",
                "Select a traceable timeline row to inspect its read-only source detail. Current chart and TradePlan remain unchanged.",
                "Complete reevaluation chronology unavailable in current read model.");
        }

        var historical = selected.HasStableHistoricalIdentity;
        return new CommandCenterTimelineSelectionView(
            historical ? "HISTORICAL EVIDENCE" : "RECORDED EVIDENCE",
            selected.Summary,
            selected.TimestampLabel,
            selected.SourceKind,
            selected.Identity,
            selected.Detail,
            historical
                ? "Frozen decision details unavailable in current read model; current chart and TradePlan are not historical context."
                : "This recorded event is not a frozen prior decision. Complete reevaluation chronology unavailable in current read model.");
    }
}

/// <summary>
/// Decision-pane context for a stable Candidate Story capture. Recorded
/// activity and technical events remain timeline evidence and are never
/// presented as frozen historical decision context.
/// </summary>
public sealed record CommandCenterHistoricalDecisionContextView(
    bool IsVisible,
    string ContextLabel,
    string CapturedAtLabel,
    string SourceLabel,
    string IdentityLabel,
    string Limitation)
{
    public static CommandCenterHistoricalDecisionContextView From(CommandCenterTimelineItemView? selected)
    {
        if (selected is not { HasStableHistoricalIdentity: true })
        {
            return new CommandCenterHistoricalDecisionContextView(
                false,
                "HISTORICAL EVIDENCE",
                "Capture time unavailable",
                "Candidate Story source unavailable",
                "Stable identity unavailable",
                "No stable Candidate Story capture is selected. Current decision and TradePlan remain unchanged.");
        }

        return new CommandCenterHistoricalDecisionContextView(
            true,
            "HISTORICAL EVIDENCE",
            selected.TimestampLabel,
            selected.SourceKind,
            selected.Identity,
            "Captured Candidate Story evidence only. Frozen decision details are unavailable; the CURRENT answer, chart, and TradePlan remain unchanged.");
    }
}

public sealed record CommandCenterHealthView(
    string StatusLabel,
    string Summary,
    string CheckedAtLabel)
{
    public static CommandCenterHealthView From(HealthDiagnosticsView diagnostics) => new(
        $"DATA {diagnostics.StatusLabel}",
        diagnostics.Summary,
        diagnostics.CheckedAtLabel);
}

internal static class CandidateStoryPointSnapshotExtensions
{
    public static string SourceContext(this CandidateStoryPointSnapshot point) =>
        string.Join(
            " | ",
            new[] { point.Provider, point.Scanner, point.CalendarLabel }
                .Where(value => !string.IsNullOrWhiteSpace(value)));
}
