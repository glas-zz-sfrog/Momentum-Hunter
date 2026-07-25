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
    DailyWorkflow,
    CandidateStory,
    ResearchMaturity,
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

public enum ResearchMaturityEvidenceState
{
    Available,
    Stale,
    Partial,
    Empty,
    Unavailable,
}

public enum CandidateStoryEvidenceState
{
    Available,
    Partial,
    Empty,
    Unavailable,
}

public enum DailyWorkflowEvidenceState
{
    Available,
    Stale,
    Partial,
    Empty,
    Unavailable,
}

public enum SavedWatchlistState
{
    Available,
    Stale,
    Partial,
    Empty,
    Unavailable,
}

public enum DailyWorkflowStepLevel
{
    Complete,
    Active,
    Attention,
    Blocked,
    Waiting,
    Locked,
}

public enum DailyWorkflowLight
{
    Green,
    Blue,
    Yellow,
    Red,
    Gray,
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

public sealed record SavedWatchlistItemSnapshot(
    int SourceRank,
    string Symbol,
    string Company,
    int? Score,
    decimal? Price,
    decimal? PercentChange,
    long? Volume,
    decimal? RelativeVolume,
    string Sector,
    string Industry,
    string Freshness,
    DateTimeOffset? SavedAt,
    string FreshestHeadline,
    string UserNotes);

public sealed record SavedWatchlistSnapshot(
    int SchemaVersion,
    SavedWatchlistState State,
    DateTimeOffset ObservedAt,
    DateTimeOffset? AsOf,
    string? WatchlistDate,
    string Summary,
    string SourceLabel,
    int TotalItemCount,
    int UsableItemCount,
    int DisplayedItemCount,
    IReadOnlyList<string> Warnings,
    IReadOnlyList<SavedWatchlistItemSnapshot> Items);

public sealed record CandidateStoryPointSnapshot(
    int Sequence,
    string IdentityKey,
    string CaptureId,
    DateTimeOffset? CapturedAt,
    string CapturedAtLabel,
    string CaptureLabel,
    string Session,
    string SessionMarker,
    string Provider,
    string Scanner,
    string Mode,
    string CalendarLabel,
    string TrustLabel,
    decimal? Price,
    decimal? Score,
    long? Volume,
    decimal? RelativeVolume,
    decimal? PriceChangePreviousPercent,
    decimal? PriceChangeFirstPercent,
    decimal? ScoreChangePrevious,
    string CaptureNote,
    string LaterAnnotation,
    string CaptureFactSource,
    string LaterAnnotationSource,
    IReadOnlyList<string> Warnings,
    bool Trusted);

public sealed record CandidateStorySnapshot(
    int SchemaVersion,
    string Symbol,
    CandidateStoryEvidenceState State,
    DateTimeOffset ObservedAt,
    DateTimeOffset? SourceAsOf,
    string SourceLabel,
    string Summary,
    string Company,
    string Sector,
    string Industry,
    string Status,
    string StatusDetail,
    string FirstSeenLabel,
    string LatestSeenLabel,
    string PeakScoreLabel,
    decimal? FirstPrice,
    decimal? LatestPrice,
    decimal? MoveSinceFirstPercent,
    decimal? FirstScore,
    decimal? LatestScore,
    decimal? PeakScore,
    int TrustedCaptureCount,
    int TotalPointCount,
    int DisplayedPointCount,
    IReadOnlyList<CandidateStoryPointSnapshot> Points,
    IReadOnlyList<string> Warnings,
    bool ReadOnly);

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

public sealed record DailyWorkflowReviewCounts(
    int Total,
    int Reviewed,
    int Unreviewed,
    int Interested,
    int Rejected,
    int Watchlist);

public sealed record DailyWorkflowPlanCounts(
    int Watchlist,
    int Complete,
    int Incomplete,
    int MissingTrigger,
    int MissingStop,
    int MissingInvalidation,
    int MissingMaxLoss,
    int WithoutPlan);

public sealed record DailyWorkflowOutcomeCounts(
    int CompletedNextDay,
    int CompletedFiveDay,
    int Pending);

public sealed record DailyWorkflowReadinessGate(string Name, string Status);

public sealed record DailyWorkflowNextAction(
    string Title,
    string Detail,
    DailyWorkflowStepLevel Level);

public sealed record DailyWorkflowStepSnapshot(
    string Id,
    string Name,
    DailyWorkflowStepLevel Level,
    string Status,
    DailyWorkflowLight Light,
    string Dependency,
    string Blocker,
    string Detail);

public sealed record DailyWorkflowSnapshot(
    int SchemaVersion,
    DailyWorkflowEvidenceState State,
    DateTimeOffset ObservedAt,
    DateTimeOffset? SourceAsOf,
    string SourceLabel,
    string SourceContext,
    string OperatorContextState,
    string OperatorContextLabel,
    string Summary,
    int WorkflowScore,
    string CaptureStatus,
    DailyWorkflowReviewCounts Review,
    DailyWorkflowPlanCounts Plans,
    DailyWorkflowOutcomeCounts Outcomes,
    IReadOnlyList<DailyWorkflowReadinessGate> Readiness,
    DailyWorkflowNextAction NextAction,
    IReadOnlyList<DailyWorkflowStepSnapshot> Steps,
    IReadOnlyList<string> Warnings,
    bool ReadOnly);

public sealed record ResearchMaturityAlertCounts(
    int Total,
    int Completed,
    int Pending,
    int Unscorable,
    decimal? CompletionRatePercent);

public sealed record ResearchMaturityEvidenceGate(
    int CompletedAlerts,
    int RequiredAlerts,
    string EvidenceStatus,
    string AllowedAction,
    string StrategyOptimizationStatus,
    string Reason);

public sealed record ResearchMaturityGate(
    string Name,
    string Status,
    int CurrentCompletedAlerts,
    int RequiredCompletedAlerts,
    int CompletedNeeded,
    string AllowedAction,
    bool StrategyChangeAllowed);

public sealed record ResearchMaturityQuestion(string Question, string Answer);

public sealed record ResearchMaturityTableCount(string Name, int Count);

public sealed record ResearchEvidenceCensus(
    ResearchMaturityAlertCounts Alerts,
    int Captures,
    int CandidateRows,
    int StudyEligibleCaptures,
    int QuarantinedCaptures,
    int MinuteBars,
    int MinuteBarSymbols,
    int EvidenceRuns,
    int EvidenceMetrics,
    int CandidateReviews,
    int WatchlistItems,
    int EntryPlans,
    int CompleteEntryPlans,
    int IncompleteEntryPlans,
    IReadOnlyList<ResearchMaturityTableCount> TableCounts,
    int TableCount);

public sealed record ResearchMaturitySnapshot(
    int SchemaVersion,
    ResearchMaturityEvidenceState State,
    DateTimeOffset ObservedAt,
    DateTimeOffset? SourceAsOf,
    DateTimeOffset? MaturityGeneratedAt,
    DateTimeOffset? CensusGeneratedAt,
    string SourceLabel,
    string Summary,
    string MaturityOverallStatus,
    string CensusOverallStatus,
    string SampleConfidence,
    string MeasurableEdgeStatus,
    string StrategyOptimizationStatus,
    bool StrategyChangeRecommendationsAllowed,
    ResearchMaturityAlertCounts MaturityAlerts,
    int EvidenceNeededToNextGate,
    ResearchMaturityEvidenceGate EvidenceGate,
    IReadOnlyList<ResearchMaturityGate> Gates,
    int GateCount,
    IReadOnlyList<ResearchMaturityQuestion> Questions,
    int QuestionCount,
    ResearchEvidenceCensus Census,
    IReadOnlyList<string> Warnings,
    IReadOnlyList<string> SafetyNotes,
    bool ResearchOnly,
    bool ReadOnly);

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

public sealed record ShadowSampleDefinition(
    string SampleVersion,
    string StrategyConfigurationFingerprint,
    string FillModelVersion,
    int EvidenceSchemaVersion,
    bool OfficialSampleAuthorized)
{
    public string FingerprintDisplay => StrategyConfigurationFingerprint.Length >= 12
        ? StrategyConfigurationFingerprint[..12]
        : StrategyConfigurationFingerprint;
}

public sealed record ShadowTradeReviewSnapshot(
    ShadowTradeIdentity Identity,
    ShadowPlanReview Plan,
    ShadowExecutionReview Execution,
    ShadowOutcomeReview Outcome,
    ShadowEvidenceLock EvidenceLock,
    ShadowSampleDefinition SampleDefinition,
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
    string Status,
    ShadowSampleDefinition Definition,
    string ReadinessStatus,
    bool CanStartOfficialSample,
    IReadOnlyList<string> ReadinessFindings)
{
    public string ProgressLabel => $"Prospective Shadow Trades: {EligibleCompleted} / {MinimumRequired}";
    public string ReadinessLabel => ReadinessStatus switch
    {
        "PASS" => "OFFICIAL SAMPLE • ACTIVE - AWAITING TRADE 1",
        "IN_PROGRESS" => "OFFICIAL SAMPLE • IN PROGRESS",
        _ => "SAMPLE START LOCKED",
    };
    public string DefinitionLabel =>
        $"{Definition.SampleVersion}  |  Fill {Definition.FillModelVersion}  |  Evidence v{Definition.EvidenceSchemaVersion}  |  Config {Definition.FingerprintDisplay}";
    public string ReadinessReasonDisplay => ReadinessFindings.Count == 0
        ? "The immutable official-sample definition is active; only matching prospective records can count."
        : string.Join(" | ", ReadinessFindings);
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
