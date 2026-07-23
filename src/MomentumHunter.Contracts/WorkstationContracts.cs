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

public enum AlertEvidenceState
{
    Available,
    Empty,
    Unavailable,
}

public enum TechnicalResearchState
{
    Available,
    Stale,
    Partial,
    Empty,
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
    string? SourceReadinessLabel = null,
    IReadOnlyList<string>? OpportunityNotes = null)
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

public sealed record TechnicalResearchEventSnapshot(
    string EventId,
    DateTimeOffset? EventTimestamp,
    string EventType,
    string Timeframe,
    string Status,
    string QualityFlag,
    string DataSufficiency,
    decimal? TriggerPrice,
    decimal? DistanceAboveTriggerPercent,
    decimal? RelativeVolume,
    bool? VolumeConfirmed,
    bool? RelativeStrengthConfirmed,
    string Notes);

public sealed record TechnicalResearchStudySnapshot(
    string EventId,
    DateTimeOffset? EventTimestamp,
    string EventType,
    string Timeframe,
    string Status,
    string DataSufficiency,
    decimal? Return5MinutePercent,
    decimal? Return15MinutePercent,
    decimal? Return60MinutePercent,
    decimal? Return1DayPercent,
    decimal? Return5DayPercent,
    decimal? Return10DayPercent,
    decimal? MaxFavorableExcursionPercent,
    decimal? MaxAdverseExcursionPercent,
    bool? HeldAboveBreakoutLevel,
    bool? FailedBackBelowBreakoutLevel,
    bool? BecameExtended,
    bool? VolumeConfirmed,
    string Notes);

public sealed record TechnicalResearchSnapshot(
    int SchemaVersion,
    string Symbol,
    TechnicalResearchState State,
    DateTimeOffset ObservedAt,
    DateTimeOffset? AsOf,
    string Summary,
    string SourceLabel,
    int GlobalEventCount,
    int GlobalStudyCount,
    int SymbolEventCount,
    int SymbolStudyCount,
    int PresentEventCount,
    int FailedStudyCount,
    int InsufficientDataCount,
    IReadOnlyList<string> Warnings,
    IReadOnlyList<TechnicalResearchEventSnapshot> Events,
    IReadOnlyList<TechnicalResearchStudySnapshot> Studies);

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

public sealed record AlertEvent(
    string AlertId,
    DateTimeOffset? Timestamp,
    string Symbol,
    string AlertType,
    string State,
    string Summary);

public sealed record OutcomeSnapshot(
    string AlertId,
    string Symbol,
    DateTimeOffset? AlertTimestamp,
    string Status,
    string Classification,
    string Summary);

public sealed record AlertEvidenceSnapshot(
    AlertEvidenceState State,
    DateTimeOffset AsOf,
    string Summary,
    int TotalAlertCount,
    int ActiveAlertCount,
    int RecordedOutcomeCount,
    int UnscorableOutcomeCount,
    IReadOnlyList<AlertEvent> ActiveAlerts,
    IReadOnlyList<OutcomeSnapshot> Outcomes);

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
    AlertEvidenceSnapshot AlertEvidence,
    ReplaySnapshot Replay,
    bool PlanningAvailable);

public sealed record SimulationWorkspaceSnapshot(
    int SchemaVersion,
    DateTimeOffset ObservedAt,
    string Summary,
    ReadOnlyWorkspaceSnapshot Workspace,
    IReadOnlyList<TradePlanSnapshot> TradePlans,
    bool PlanningAvailable);

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
