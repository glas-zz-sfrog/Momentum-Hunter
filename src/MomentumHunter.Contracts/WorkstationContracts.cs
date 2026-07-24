namespace MomentumHunter.Contracts;

public enum WorkspaceKind
{
    Live,
    Replay,
    Review,
}

public enum PaneKind
{
    Hunter,
    Chart,
    TradePlan,
    Activity,
    Diagnostics,
    MarketClock,
    Research,
    Watchlist,
    Automation,
    Orders,
    Positions,
    ReplayEvents,
    ReviewOutcomes,
    ShadowReview,
}

public enum LinkGroup
{
    Unlinked,
    A,
    B,
    C,
    D,
}

public enum DockRegion
{
    Left,
    Center,
    Right,
    Bottom,
    Floating,
}

public enum EnvironmentMode
{
    Simulation,
    Replay,
    Review,
}

public enum WindowDisplayState
{
    Normal,
    Maximized,
}

public enum ReadinessState
{
    ReadyForSimulation,
    NeedsEvidence,
    StaleData,
    Blocked,
}

public enum HealthState
{
    Healthy,
    Degraded,
    Unavailable,
}

public enum SimulationResultState
{
    Completed,
    Blocked,
    Unavailable,
}

public enum ChartDataState
{
    Available,
    Stale,
    InsufficientData,
    Unavailable,
}

public sealed record CatalystSummary(string Headline, string SourceLabel, DateTimeOffset ObservedAt);

public sealed record DataLineage(string SourceLabel, DateTimeOffset AsOf, string Summary);

public sealed record CandidateSnapshot(
    string Symbol,
    string Company,
    decimal? LastPrice,
    decimal? ChangePercent,
    long? Volume,
    decimal? RelativeVolume,
    string Catalyst,
    ReadinessState Readiness,
    string QualityLabel,
    DateTimeOffset ObservedAt,
    int Score = 0,
    string FloatOrLiquidity = "Unavailable",
    CatalystSummary? CatalystSummary = null,
    DataLineage? DataLineage = null,
    string? SourceReadinessLabel = null)
{
    public string OperatorState => !string.IsNullOrWhiteSpace(SourceReadinessLabel)
        ? SourceReadinessLabel
        : Readiness switch
    {
        ReadinessState.ReadyForSimulation => "Ready",
        ReadinessState.NeedsEvidence => "Repair",
        ReadinessState.StaleData => "Stale",
        _ => "Blocked",
    };
}

public sealed record CandleSnapshot(
    DateTimeOffset Timestamp,
    decimal Open,
    decimal High,
    decimal Low,
    decimal Close,
    long Volume);

public sealed record ChartSnapshot(
    int SchemaVersion,
    string Symbol,
    string Interval,
    ChartDataState State,
    DateTimeOffset ObservedAt,
    DateTimeOffset AsOf,
    string Summary,
    DataLineage DataLineage,
    IReadOnlyList<CandleSnapshot> Candles);

public sealed record ReadinessCheck(string Name, bool Passed, string Detail);

public sealed record ReadinessSnapshot(
    ReadinessState State,
    IReadOnlyList<ReadinessCheck> Checks,
    string Summary);

public sealed record TradeLevel(string Name, decimal Price, string Detail);

public sealed record RiskDecision(bool Allowed, string State, string Summary, IReadOnlyList<string> Reasons);

public sealed record TradePlanSnapshot(
    string Symbol,
    decimal Entry,
    decimal Stop,
    decimal Target,
    decimal RiskPerShare,
    int SimulatedQuantity,
    decimal RewardToRisk,
    ReadinessState Readiness,
    IReadOnlyList<ReadinessCheck> Checks,
    string PrimaryAction,
    DataLineage DataLineage,
    IReadOnlyList<TradeLevel>? Levels = null,
    RiskDecision? RiskDecision = null)
{
    public string EntryDisplay => Entry > 0m ? Entry.ToString("C2") : "Unavailable";

    public string StopDisplay => Stop > 0m ? Stop.ToString("C2") : "Unavailable";

    public string TargetDisplay => Target > 0m ? Target.ToString("C2") : "Unavailable";

    public string RewardToRiskDisplay => RewardToRisk > 0m ? RewardToRisk.ToString("N2") : "Unavailable";
}

public sealed record ActivityEvent(
    DateTimeOffset Timestamp,
    string Category,
    string Message,
    string Symbol,
    HealthState State);

public sealed record AlertEvent(DateTimeOffset Timestamp, string Symbol, string State, string Summary);

public sealed record OutcomeSnapshot(string Symbol, DateTimeOffset ObservedAt, string Outcome, string Summary);

public sealed record ExecutionAuditSnapshot(string AuditId, EnvironmentMode Mode, string State, string Summary, DateTimeOffset RecordedAt);

public sealed record ReplaySnapshot(string ReplayId, DateTimeOffset AsOf, string Symbol, string Interval, string Summary);

public sealed record SimulationResult(
    SimulationResultState State,
    string Symbol,
    string Summary,
    RiskDecision RiskDecision,
    ExecutionAuditSnapshot Audit);

public sealed record HealthComponentSnapshot(
    string Name,
    HealthState State,
    string Summary,
    DateTimeOffset CheckedAt);

public sealed record SystemHealthSnapshot(
    IReadOnlyList<HealthComponentSnapshot> Components,
    DateTimeOffset CheckedAt);

public sealed record ReadOnlyWorkspaceSnapshot(
    int SchemaVersion,
    DateTimeOffset ObservedAt,
    string Summary,
    IReadOnlyList<CandidateSnapshot> Candidates,
    IReadOnlyList<ActivityEvent> Activity,
    SystemHealthSnapshot Health,
    ReplaySnapshot Replay,
    bool PlanningAvailable);

public sealed record SimulationWorkspaceSnapshot(
    int SchemaVersion,
    DateTimeOffset ObservedAt,
    string Summary,
    ReadOnlyWorkspaceSnapshot Workspace,
    IReadOnlyList<TradePlanSnapshot> TradePlans,
    bool PlanningAvailable);

public sealed record ShadowTradeIdentity(
    string ShadowTradeId,
    string Symbol,
    string Setup,
    string Catalyst,
    string MarketRegime,
    string Session,
    DateTimeOffset DecisionTimestamp,
    DateTimeOffset EvidenceSnapshotTimestamp,
    string TradePlanId,
    string RiskDecisionId);

public sealed record ShadowPlanReview(
    string RiskDecision,
    IReadOnlyList<string> RiskReasons,
    decimal? ProposedEntry,
    decimal? Stop,
    IReadOnlyList<decimal> Targets)
{
    public string ProposedEntryDisplay => ProposedEntry?.ToString("C4") ?? "Unavailable";
    public string StopDisplay => Stop?.ToString("C4") ?? "Unavailable";
    public string TargetsDisplay => Targets.Count == 0
        ? "Unavailable"
        : string.Join(" / ", Targets.Select(target => target.ToString("C4")));
    public string RiskReasonDisplay => RiskReasons.Count == 0 ? "No risk reason supplied." : string.Join(" | ", RiskReasons);
}

public sealed record ShadowTechnicalEvent(
    DateTimeOffset Timestamp,
    string EventType,
    string Action,
    string Result,
    string Reason);

public sealed record ShadowExecutionQuality(
    string Summary,
    IReadOnlyList<string> Factors,
    IReadOnlyList<ShadowTechnicalEvent> TechnicalCodes)
{
    public string FactorDisplay => Factors.Count == 0 ? Summary : string.Join(Environment.NewLine, Factors);
}

public sealed record ShadowExecutionReview(
    decimal? SimulatedFill,
    decimal? SpreadPercent,
    decimal? SlippageBps,
    decimal? Exit,
    string ExitReason,
    string LifecycleState,
    string LastReason,
    ShadowExecutionQuality Quality)
{
    public string SimulatedFillDisplay => SimulatedFill?.ToString("C4") ?? "No fill";
    public string SpreadDisplay => SpreadPercent is null ? "Unavailable" : $"{SpreadPercent:N2}%";
    public string SlippageDisplay => SlippageBps is null ? "Unavailable" : $"{SlippageBps:N2} bps";
    public string ExitDisplay => Exit?.ToString("C4") ?? "Open / unavailable";
}

public sealed record ShadowOutcomeReview(
    string Outcome,
    decimal? IdealPnl,
    decimal? ExecutablePnl,
    decimal? RMultiple,
    decimal? MfeDollars,
    decimal? MaeDollars,
    int? DurationSeconds)
{
    public string IdealPnlDisplay => IdealPnl?.ToString("C2") ?? "Unavailable";
    public string ExecutablePnlDisplay => ExecutablePnl?.ToString("C2") ?? "Unavailable";
    public string RMultipleDisplay => RMultiple is null ? "Unavailable" : $"{RMultiple:N2} R";
    public string MfeDisplay => MfeDollars?.ToString("C2") ?? "Unavailable";
    public string MaeDisplay => MaeDollars?.ToString("C2") ?? "Unavailable";
    public string DurationDisplay => DurationSeconds is null
        ? "Unavailable"
        : TimeSpan.FromSeconds(DurationSeconds.Value).ToString(@"hh\:mm\:ss");
}

public sealed record ShadowEvidenceLock(
    bool EvidenceFrozen,
    bool PlanFrozen,
    DateTimeOffset DecisionTimestamp,
    bool PostDecisionCorrectionOccurred,
    string AuditStatus,
    IReadOnlyList<string> Reasons)
{
    public string EvidenceFrozenLabel => EvidenceFrozen ? "Evidence frozen" : "Evidence lock failed";
    public string PlanFrozenLabel => PlanFrozen ? "Plan frozen" : "Plan lock failed";
    public string CorrectionLabel => PostDecisionCorrectionOccurred
        ? "Post-decision correction detected"
        : "No post-decision correction";
    public string ReasonDisplay => Reasons.Count == 0 ? "Immutable evidence audit passed." : string.Join(" | ", Reasons);
}

public sealed record ShadowTradeReviewSnapshot(
    ShadowTradeIdentity Identity,
    ShadowPlanReview Plan,
    ShadowExecutionReview Execution,
    ShadowOutcomeReview Outcome,
    ShadowEvidenceLock EvidenceLock,
    string DataQualityState,
    bool EvidenceEligible,
    bool CountsTowardSample)
{
    public string ShadowTradeId => Identity.ShadowTradeId;
    public string Symbol => Identity.Symbol;
    public string Setup => Identity.Setup;
    public string Catalyst => Identity.Catalyst;
    public string MarketRegime => Identity.MarketRegime;
    public string Session => Identity.Session;
    public DateTimeOffset DecisionTimestamp => Identity.DecisionTimestamp;
    public string LifecycleState => Execution.LifecycleState;
    public string OutcomeLabel => Outcome.Outcome;
    public string EligibilityLabel => EvidenceEligible ? "ELIGIBLE" : "EXCLUDED";
    public string DateSessionLabel => $"{DecisionTimestamp:yyyy-MM-dd} / {Session}";
}

public sealed record ShadowSampleStatus(
    int MinimumRequired,
    int EligibleCompleted,
    int Completed,
    int Active,
    int Unfilled,
    int RiskRejected,
    int DataQualityInvalidated,
    int Excluded,
    bool GateSatisfied,
    string Status)
{
    public string ProgressLabel => $"Prospective Shadow Trades: {EligibleCompleted} / {MinimumRequired}";
}

public sealed record ShadowAggregateMetrics(
    string SampleStatus,
    decimal? WinRatePercent,
    decimal? AverageWin,
    decimal? AverageLoss,
    decimal? Expectancy,
    decimal? AverageR,
    decimal? MaximumDrawdown,
    decimal? ProfitFactor,
    decimal? IdealPnl,
    decimal? ExecutablePnl,
    decimal? IdealVsExecutableGap,
    string Conclusion)
{
    public string WinRateDisplay => Percent(WinRatePercent);
    public string AverageWinDisplay => Currency(AverageWin);
    public string AverageLossDisplay => Currency(AverageLoss);
    public string ExpectancyDisplay => Currency(Expectancy);
    public string AverageRDisplay => Number(AverageR, "N2", " R");
    public string MaximumDrawdownDisplay => Currency(MaximumDrawdown);
    public string ProfitFactorDisplay => Number(ProfitFactor, "N2");
    public string PerformanceGapDisplay => Currency(IdealVsExecutableGap);

    private static string Currency(decimal? value) => value?.ToString("C2") ?? "Withheld";
    private static string Percent(decimal? value) => Number(value, "N2", "%");
    private static string Number(decimal? value, string format, string suffix = "") =>
        value is null ? "Withheld" : $"{value.Value.ToString(format)}{suffix}";
}

public sealed record ShadowReviewSnapshot(
    int SchemaVersion,
    string Mode,
    string EngineVersion,
    bool Transmitting,
    string Summary,
    IReadOnlyList<ShadowTradeReviewSnapshot> Trades,
    ShadowSampleStatus Sample,
    ShadowAggregateMetrics Metrics);

public sealed record WorkspaceSnapshot(
    WorkspaceKind Workspace,
    string SelectedSymbol,
    string SelectedInterval,
    EnvironmentMode Environment,
    IReadOnlyList<CandidateSnapshot> Candidates,
    TradePlanSnapshot TradePlan,
    IReadOnlyList<ActivityEvent> Activity,
    SystemHealthSnapshot Health);

public sealed record RectGeometry(double X, double Y, double Width, double Height)
{
    public double Right => X + Width;
    public double Bottom => Y + Height;
}

public sealed record DisplayGeometry(string DisplayKey, RectGeometry WorkingArea, double DpiScale);

public sealed record PaneLayout(
    Guid InstanceId,
    PaneKind Kind,
    string Title,
    LinkGroup LinkGroup,
    string Symbol,
    string Interval,
    bool IsPinned,
    bool IsVisible,
    DockRegion DockRegion,
    int SortOrder,
    string? DisplayKey,
    RectGeometry? FloatingBounds,
    string? SoftClosedDockLayoutXml = null);

public sealed record WorkspaceLayoutSnapshot(
    int SchemaVersion,
    WorkspaceKind Workspace,
    Guid RevisionId,
    DateTimeOffset CreatedAt,
    bool IsNamedLayout,
    string? Name,
    string SelectedSymbol,
    string SelectedInterval,
    IReadOnlyList<PaneLayout> Panes,
    string Checksum,
    string? DockLayoutXml = null,
    RectGeometry? WindowBounds = null,
    bool ActivityExpanded = false,
    WindowDisplayState WindowState = WindowDisplayState.Normal);
