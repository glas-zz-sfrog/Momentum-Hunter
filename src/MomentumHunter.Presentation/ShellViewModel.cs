using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

/// <summary>
/// Presentation-only state for the WPF shell. It owns no market, scoring,
/// broker, or credential behavior; all research-facing data arrives through
/// <see cref="IEngineClient"/>.
/// </summary>
public sealed partial class ShellViewModel : ObservableObject
{
    private readonly IEngineClient _engineClient;
    private readonly IReadOnlyWorkspaceClient? _readOnlyWorkspaceClient;
    private readonly ISimulationWorkspaceClient? _simulationWorkspaceClient;
    private readonly IChartWorkspaceClient? _chartWorkspaceClient;
    private readonly IShadowReviewClient? _shadowReviewClient;
    private readonly ITechnicalResearchWorkspaceClient? _technicalResearchWorkspaceClient;
    private readonly ISavedWatchlistWorkspaceClient? _savedWatchlistWorkspaceClient;
    private readonly IDailyWorkflowWorkspaceClient? _dailyWorkflowWorkspaceClient;
    private readonly ICandidateStoryWorkspaceClient? _candidateStoryWorkspaceClient;
    private readonly IResearchMaturityWorkspaceClient? _researchMaturityWorkspaceClient;
    private readonly IWorkspaceLayoutStore? _layoutStore;
    private readonly LayoutAutosaveCoordinator? _layoutAutosave;
    private LinkGroupCoordinator _linkGroups = null!;
    private string? _dockLayoutXml;
    private RectGeometry? _windowBounds;
    private WindowDisplayState _windowState;
    private SimulationWorkspaceSnapshot? _simulationWorkspaceSnapshot;
    private ShadowReviewSnapshot? _shadowReviewSnapshot;
    private readonly SemaphoreSlim _chartRefreshLock = new(1, 1);
    private readonly SemaphoreSlim _shadowRefreshLock = new(1, 1);
    private long _candidateStoryRequestVersion;

    public ShellViewModel(IEngineClient engineClient)
        : this(engineClient, layoutStore: null, readOnlyWorkspaceClient: null, simulationWorkspaceClient: null, chartWorkspaceClient: null, savedWatchlistWorkspaceClient: null, isInternalConstruction: true)
    {
    }

    public ShellViewModel(IEngineClient engineClient, IWorkspaceLayoutStore layoutStore)
        : this(engineClient, layoutStore, readOnlyWorkspaceClient: null, simulationWorkspaceClient: null, chartWorkspaceClient: null, savedWatchlistWorkspaceClient: null, isInternalConstruction: true)
    {
    }

    public ShellViewModel(IEngineClient engineClient, IReadOnlyWorkspaceClient readOnlyWorkspaceClient)
        : this(engineClient, layoutStore: null, readOnlyWorkspaceClient, simulationWorkspaceClient: null, chartWorkspaceClient: null, savedWatchlistWorkspaceClient: null, isInternalConstruction: true)
    {
    }

    public ShellViewModel(IEngineClient engineClient, ISimulationWorkspaceClient simulationWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: simulationWorkspaceClient,
            chartWorkspaceClient: null,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        IReadOnlyWorkspaceClient readOnlyWorkspaceClient)
        : this(engineClient, layoutStore, readOnlyWorkspaceClient, simulationWorkspaceClient: null, chartWorkspaceClient: null, savedWatchlistWorkspaceClient: null, isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ISimulationWorkspaceClient simulationWorkspaceClient)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: simulationWorkspaceClient,
            chartWorkspaceClient: null,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: simulationWorkspaceClient,
            chartWorkspaceClient: chartWorkspaceClient,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: simulationWorkspaceClient,
            chartWorkspaceClient: chartWorkspaceClient,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IResearchMaturityWorkspaceClient researchMaturityWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: null,
            chartWorkspaceClient: null,
            savedWatchlistWorkspaceClient: null,
            researchMaturityWorkspaceClient: researchMaturityWorkspaceClient,
            isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient,
        IResearchMaturityWorkspaceClient researchMaturityWorkspaceClient)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: simulationWorkspaceClient,
            chartWorkspaceClient: chartWorkspaceClient,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            researchMaturityWorkspaceClient: researchMaturityWorkspaceClient)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        ISavedWatchlistWorkspaceClient savedWatchlistWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: null,
            chartWorkspaceClient: null,
            savedWatchlistWorkspaceClient,
            isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient,
        ISavedWatchlistWorkspaceClient savedWatchlistWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient,
            chartWorkspaceClient,
            savedWatchlistWorkspaceClient,
            isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient,
        ISavedWatchlistWorkspaceClient savedWatchlistWorkspaceClient)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient,
            chartWorkspaceClient,
            savedWatchlistWorkspaceClient,
            isInternalConstruction: true)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        ITechnicalResearchWorkspaceClient technicalResearchWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: null,
            chartWorkspaceClient: null,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            technicalResearchWorkspaceClient: technicalResearchWorkspaceClient)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient,
        ITechnicalResearchWorkspaceClient technicalResearchWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient,
            chartWorkspaceClient,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            technicalResearchWorkspaceClient: technicalResearchWorkspaceClient)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient,
        ITechnicalResearchWorkspaceClient technicalResearchWorkspaceClient)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient,
            chartWorkspaceClient,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            technicalResearchWorkspaceClient: technicalResearchWorkspaceClient)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IDailyWorkflowWorkspaceClient dailyWorkflowWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: null,
            chartWorkspaceClient: null,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            dailyWorkflowWorkspaceClient: dailyWorkflowWorkspaceClient)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient,
        IDailyWorkflowWorkspaceClient dailyWorkflowWorkspaceClient)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient,
            chartWorkspaceClient,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            dailyWorkflowWorkspaceClient: dailyWorkflowWorkspaceClient)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        ICandidateStoryWorkspaceClient candidateStoryWorkspaceClient)
        : this(
            engineClient,
            layoutStore: null,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: null,
            chartWorkspaceClient: null,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            candidateStoryWorkspaceClient: candidateStoryWorkspaceClient)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ICandidateStoryWorkspaceClient candidateStoryWorkspaceClient)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient: null,
            chartWorkspaceClient: null,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            candidateStoryWorkspaceClient: candidateStoryWorkspaceClient)
    {
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient,
        ITechnicalResearchWorkspaceClient technicalResearchWorkspaceClient,
        ISavedWatchlistWorkspaceClient savedWatchlistWorkspaceClient,
        IDailyWorkflowWorkspaceClient dailyWorkflowWorkspaceClient,
        ICandidateStoryWorkspaceClient candidateStoryWorkspaceClient,
        IResearchMaturityWorkspaceClient researchMaturityWorkspaceClient,
        IShadowReviewClient? shadowReviewClient = null)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient,
            chartWorkspaceClient,
            savedWatchlistWorkspaceClient,
            isInternalConstruction: true,
            technicalResearchWorkspaceClient,
            dailyWorkflowWorkspaceClient,
            candidateStoryWorkspaceClient,
            researchMaturityWorkspaceClient,
            shadowReviewClient)
    {
    }

    private ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore? layoutStore,
        IReadOnlyWorkspaceClient? readOnlyWorkspaceClient,
        ISimulationWorkspaceClient? simulationWorkspaceClient,
        IChartWorkspaceClient? chartWorkspaceClient,
        ISavedWatchlistWorkspaceClient? savedWatchlistWorkspaceClient,
        bool isInternalConstruction,
        ITechnicalResearchWorkspaceClient? technicalResearchWorkspaceClient = null,
        IDailyWorkflowWorkspaceClient? dailyWorkflowWorkspaceClient = null,
        ICandidateStoryWorkspaceClient? candidateStoryWorkspaceClient = null,
        IResearchMaturityWorkspaceClient? researchMaturityWorkspaceClient = null,
        IShadowReviewClient? shadowReviewClient = null)
    {
        _engineClient = engineClient;
        _layoutStore = layoutStore;
        _readOnlyWorkspaceClient = readOnlyWorkspaceClient;
        _simulationWorkspaceClient = simulationWorkspaceClient;
        _chartWorkspaceClient = chartWorkspaceClient;
        _shadowReviewClient = shadowReviewClient;
        _technicalResearchWorkspaceClient = technicalResearchWorkspaceClient;
        _savedWatchlistWorkspaceClient = savedWatchlistWorkspaceClient;
        _dailyWorkflowWorkspaceClient = dailyWorkflowWorkspaceClient;
        _candidateStoryWorkspaceClient = candidateStoryWorkspaceClient;
        _researchMaturityWorkspaceClient = researchMaturityWorkspaceClient;
        SetRegistry(WorkspaceFactory.Create(WorkspaceKind.Live));
        IsActivityOpen = Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Activity)?.IsVisible == true;
        if (_layoutStore is not null)
        {
            _layoutAutosave = new LayoutAutosaveCoordinator(_layoutStore, CreateAutomaticLayoutSnapshot);
        }

        Candidates = [];
        AttentionRows = [];
        Activity = [];
        WhatChangedRows = [];
        Activity.CollectionChanged += (_, _) =>
        {
            OnPropertyChanged(nameof(ActivityRows));
            OnPropertyChanged(nameof(ActivityLabel));
            OnPropertyChanged(nameof(ActivityCountLabel));
            RefreshWhatChangedRows();
        };
        Candles = [];
        OpenPositions = [];
        ShadowTrades = [];
        ShadowOfficialTrades = [];
        ShadowUnfilledBlockedTrades = [];
        CommandPaletteResults = [];
        SavedWatchlistItems = [];
        OpenPositions.CollectionChanged += (_, _) => RaiseOpenPositionProperties();
        WorkspaceOptions = Enum.GetValues<WorkspaceKind>();
        IntervalOptions = ["1m", "5m", "15m", "Daily"];
        Candidates.CollectionChanged += (_, _) =>
        {
            RefreshCommandPaletteResults();
            RefreshAttentionRows();
            OnPropertyChanged(nameof(CommandPaletteScopeLabel));
        };
        RefreshCommandPaletteResults();
    }

    public ShellViewModel(
        IEngineClient engineClient,
        IWorkspaceLayoutStore layoutStore,
        ISimulationWorkspaceClient simulationWorkspaceClient,
        IChartWorkspaceClient chartWorkspaceClient,
        IShadowReviewClient shadowReviewClient)
        : this(
            engineClient,
            layoutStore,
            readOnlyWorkspaceClient: null,
            simulationWorkspaceClient,
            chartWorkspaceClient,
            savedWatchlistWorkspaceClient: null,
            isInternalConstruction: true,
            shadowReviewClient: shadowReviewClient)
    {
    }

    public PaneRegistry Registry { get; private set; } = null!;

    public ObservableCollection<CandidateSnapshot> Candidates { get; }

    public ObservableCollection<CommandCenterAttentionRowView> AttentionRows { get; }

    public ObservableCollection<ActivityEvent> Activity { get; }

    public ObservableCollection<CommandCenterTimelineItemView> WhatChangedRows { get; }

    public IReadOnlyList<ActivityEventView> ActivityRows =>
        Activity.Select(ActivityEventView.From).ToArray();

    public ObservableCollection<CandleSnapshot> Candles { get; }

    public ObservableCollection<OpenPositionView> OpenPositions { get; }

    public ObservableCollection<ShadowTradeReviewSnapshot> ShadowTrades { get; }
    public ObservableCollection<ShadowTradeReviewSnapshot> ShadowOfficialTrades { get; }
    public ObservableCollection<ShadowTradeReviewSnapshot> ShadowUnfilledBlockedTrades { get; }
    public ObservableCollection<SavedWatchlistItemViewModel> SavedWatchlistItems { get; }

    public ObservableCollection<ChartPaneViewModel> SecondaryCharts { get; } = [];

    public ObservableCollection<CommandPaletteItem> CommandPaletteResults { get; }

    public IReadOnlyList<WorkspaceKind> WorkspaceOptions { get; }

    public IReadOnlyList<string> IntervalOptions { get; }

    [ObservableProperty]
    private WorkspaceKind _workspace = WorkspaceKind.Live;

    [ObservableProperty]
    private CandidateSnapshot? _selectedCandidate;

    [ObservableProperty]
    private CommandCenterAttentionRowView? _selectedAttentionRow;

    [ObservableProperty]
    private CommandCenterTimelineItemView? _selectedTimelineItem;

    [ObservableProperty]
    private string _selectedSymbol = "NVDA";

    [ObservableProperty]
    private string _selectedInterval = "5m";

    [ObservableProperty]
    private TradePlanSnapshot? _tradePlan;

    [ObservableProperty]
    private int _tradePlanTabIndex;

    [ObservableProperty]
    private SystemHealthSnapshot? _health;

    [ObservableProperty]
    private ReplaySnapshot? _replaySession;

    [ObservableProperty]
    private AlertEvidenceSnapshot? _alertEvidence;

    [ObservableProperty]
    private TechnicalResearchSnapshot? _technicalResearch;

    [ObservableProperty]
    private DailyWorkflowSnapshot? _dailyWorkflow;

    [ObservableProperty]
    private CandidateStorySnapshot? _candidateStory;

    [ObservableProperty]
    private SimulationResult? _lastSimulationResult;

    [ObservableProperty]
    private ChartPaneViewModel? _primaryChart;

    [ObservableProperty]
    private ResearchMaturitySnapshot? _researchMaturity;

    [ObservableProperty]
    private bool _isHealthOpen;

    [ObservableProperty]
    private bool _isActivityOpen;

    [ObservableProperty]
    private bool _isDiagnosticsOpen;

    [ObservableProperty]
    private bool _isCommandPaletteOpen;

    [ObservableProperty]
    private string _commandQuery = string.Empty;

    [ObservableProperty]
    private CommandPaletteItem? _selectedCommandPaletteItem;

    [ObservableProperty]
    private string _statusMessage = "Mock engine | Local deterministic data | No provider calls";

    [ObservableProperty]
    private string _backgroundStatusLabel = "Monitoring: Starting";

    [ObservableProperty]
    private string _backgroundStatusDetail = "Waiting for background monitoring to start.";

    [ObservableProperty]
    private BackgroundCollectionStatus _backgroundCollectionStatus = new(
        BackgroundCollectionState.Starting,
        null,
        0,
        0,
        "Waiting for background monitoring to start.");

    [ObservableProperty]
    private bool _isMonitoringPaused;

    [ObservableProperty]
    private bool _isReadOnlySnapshotMode;

    [ObservableProperty]
    private bool _isPythonSimulationWorkspaceMode;

    [ObservableProperty]
    private ShadowTradeReviewSnapshot? _selectedShadowTrade;

    [ObservableProperty]
    private ShadowTradeReviewSnapshot? _activeShadowTrade;

    [ObservableProperty]
    private ShadowSampleStatus _shadowSample = new(
        30, 0, 0, 0, 0, 0, 0, 0, false,
        "Evidence collection in progress. Results are not yet sufficient for strategy conclusions.",
        new ShadowSampleDefinition(
            "engineering-preflight-v1",
            new string('0', 64),
            "prospective-fakebroker-live-mark-v2",
            1,
            false),
        "BLOCKED",
        false,
        ["Shadow review has not loaded."]);

    [ObservableProperty]
    private ShadowAggregateMetrics _shadowMetrics = new(
        "INSUFFICIENT_SAMPLE", null, null, null, null, null, null, null, null, null, null,
        "Evidence collection in progress. Results are not yet sufficient for strategy conclusions.");

    [ObservableProperty]
    private string _shadowReviewStatus = "Shadow review has not loaded.";

    [ObservableProperty]
    private IReadOnlyList<string> _shadowDateSessionOptions = ["All"];

    [ObservableProperty]
    private IReadOnlyList<string> _shadowSetupOptions = ["All"];

    [ObservableProperty]
    private IReadOnlyList<string> _shadowCatalystOptions = ["All"];

    [ObservableProperty]
    private IReadOnlyList<string> _shadowRegimeOptions = ["All"];

    [ObservableProperty]
    private IReadOnlyList<string> _shadowOutcomeOptions = ["All"];

    [ObservableProperty]
    private IReadOnlyList<string> _shadowEligibilityOptions = ["All", "ELIGIBLE", "EXCLUDED"];

    [ObservableProperty]
    private string _shadowDateSessionFilter = "All";

    [ObservableProperty]
    private string _shadowSetupFilter = "All";

    [ObservableProperty]
    private string _shadowCatalystFilter = "All";

    [ObservableProperty]
    private string _shadowRegimeFilter = "All";

    [ObservableProperty]
    private string _shadowOutcomeFilter = "All";

    [ObservableProperty]
    private string _shadowEligibilityFilter = "All";

    [ObservableProperty]
    private SavedWatchlistSnapshot? _savedWatchlist;

    public string MonitoringToggleLabel => IsMonitoringPaused ? "Resume Monitoring" : "Pause Monitoring";

    public MonitoringStatusView MonitoringStatus => MonitoringStatusView.From(BackgroundCollectionStatus);

    public EnvironmentMode Environment => Workspace switch
    {
        WorkspaceKind.Live => EnvironmentMode.Simulation,
        WorkspaceKind.Replay => EnvironmentMode.Replay,
        _ => EnvironmentMode.Review,
    };

    public string WorkspaceTitle => Workspace switch
    {
        WorkspaceKind.Live => "Current Hunter",
        WorkspaceKind.Replay => "Replay",
        _ => "Review",
    };

    public string WorkspaceNarrative => Workspace switch
    {
        WorkspaceKind.Live => "Prioritize current evidence and simulation preparation.",
        WorkspaceKind.Replay => "Inspect a historical snapshot without altering current research.",
        _ => "Review outcomes, evidence lineage, and audit detail.",
    };

    public PaneState? PrimaryChartPane => Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Chart);

    public PaneState? PrimaryTradePlanPane => Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.TradePlan);

    public PaneState? ShadowReviewPane => Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.ShadowReview);

    public PaneState? PositionsPane => Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Positions);

    public string PrimaryChartLinkLabel => PaneSyncLabel(PrimaryChartPane);

    public string PrimaryTradePlanLinkLabel => PaneSyncLabel(PrimaryTradePlanPane);

    public string EnvironmentLabel => Environment switch
    {
        _ when Workspace == WorkspaceKind.Review => "REVIEW ONLY",
        _ when IsReadOnlySnapshotMode => "READ-ONLY",
        _ when IsPythonSimulationWorkspaceMode => "SIMULATION",
        EnvironmentMode.Simulation => "SIMULATION",
        EnvironmentMode.Replay => "REPLAY ONLY",
        _ => "REVIEW ONLY",
    };

    public string EnvironmentDetail => Environment switch
    {
        _ when Workspace == WorkspaceKind.Review => "Review workspace. No broker or order actions are available.",
        _ when IsReadOnlySnapshotMode => "Persisted evidence only. Planning and order actions are unavailable.",
        _ when IsPythonSimulationWorkspaceMode => "FakeBroker simulation only. No brokerage connection.",
        EnvironmentMode.Simulation => "Local simulation only. No brokerage connection.",
        EnvironmentMode.Replay => "Historical replay only. No broker or order actions are available.",
        _ => "Review only. No broker or order actions are available.",
    };

    public string ActivityLabel => WhatChangedRows.Count == 0
        ? "What Changed"
        : $"What Changed {WhatChangedRows.Count}";

    public string UniverseCountLabel => AttentionRows.Count == 1
        ? "1 source-ordered candidate"
        : $"{AttentionRows.Count} source-ordered candidates";

    public CommandCenterDecisionView CurrentDecision =>
        CommandCenterDecisionView.From(SelectedCandidate, TradePlan, PrimaryChart);

    public CommandCenterMarketStoryView CurrentMarketStory =>
        CommandCenterMarketStoryView.From(SelectedCandidate, PrimaryChart);

    public CommandCenterTimelineSelectionView TimelineSelection =>
        CommandCenterTimelineSelectionView.From(SelectedTimelineItem, SelectedSymbol);

    public CommandCenterHistoricalDecisionContextView HistoricalDecisionContext =>
        CommandCenterHistoricalDecisionContextView.From(SelectedTimelineItem);

    public CommandCenterHealthView CommandCenterHealth =>
        CommandCenterHealthView.From(Diagnostics);

    public string WhatChangedCountLabel => WhatChangedRows.Count == 1
        ? "1 traceable row"
        : $"{WhatChangedRows.Count} traceable rows";

    public string WhatChangedLimitationLabel =>
        "PARTIAL HISTORY — complete reevaluation chronology unavailable in current read model";

    public bool HasCommandPaletteResults => CommandPaletteResults.Count > 0;

    public string CommandPaletteScopeLabel =>
        $"{Candidates.Count} current Hunter symbols | Commands: chart, positions, activity, diagnostics";

    public string CommandPaletteEmptyText
    {
        get
        {
            if (string.IsNullOrWhiteSpace(CommandQuery))
            {
                return "No current Hunter symbols or commands are available.";
            }

            var examples = string.Join(", ", Candidates.Take(3).Select(candidate => candidate.Symbol));
            var suggestion = string.IsNullOrWhiteSpace(examples)
                ? "Try chart, positions, activity, or diagnostics."
                : $"Try {examples}, or a command such as chart.";
            return $"'{CommandQuery.Trim()}' is not in the current Hunter list. {suggestion}";
        }
    }

    public string ActivityCountLabel => Activity.Count == 1 ? "1 source event" : $"{Activity.Count} source events";

    public bool HasOpenPositions => OpenPositions.Count > 0;

    public string PositionsButtonLabel => OpenPositions.Count == 0 ? "Positions" : $"Positions {OpenPositions.Count}";

    public string PositionsButtonToolTip =>
        OpenPositions.Count == 0
            ? "Open the read-only position monitor. No open FakeBroker positions are currently reported."
            : $"Open {OpenPositions.Count} FakeBroker position{(OpenPositions.Count == 1 ? string.Empty : "s")} | {OpenPositionPnlDisplay}";

    public string OpenPositionCountDisplay => OpenPositions.Count.ToString("N0");

    public string OpenPositionPnlDisplay =>
        OpenPositions.Any(position => position.UnrealizedPnl is not null)
            ? OpenPositions.Sum(position => position.UnrealizedPnl ?? 0m).ToString("C2")
            : "Unavailable";

    public string OpenPositionMarketValueDisplay =>
        OpenPositions.Any(position => position.MarketValue is not null)
            ? OpenPositions.Sum(position => position.MarketValue ?? 0m).ToString("C2")
            : OpenPositions.Count == 0
                ? "$0.00"
                : "Unavailable";

    public int OpenPositionAttentionCount =>
        OpenPositions.Count(position => position.State is "STALE" or "HALTED" or "EXIT_PENDING");

    public string OpenPositionQuoteHealthDisplay =>
        OpenPositions.Count == 0
            ? "No open marks"
            : OpenPositionAttentionCount == 0
                ? "Current"
                : $"{OpenPositionAttentionCount} need attention";

    public string PositionsModeLabel => _shadowReviewSnapshot?.Mode ?? "POSITION DATA UNAVAILABLE";

    public string PositionsSummary =>
        _shadowReviewSnapshot is null
            ? "Position evidence is unavailable. No fallback position was created."
            : OpenPositions.Count == 0
                ? "No open FakeBroker positions are present in the canonical Shadow evidence."
                : $"{OpenPositions.Count} open FakeBroker position{(OpenPositions.Count == 1 ? string.Empty : "s")} from canonical Shadow evidence.";

    public string PositionsSourceDetail =>
        "Read-only Python Engine Host snapshot. Schwab account positions are not connected, and no order controls are available.";

    public bool CanRunSimulation => !IsReadOnlySnapshotMode && TradePlan?.RiskDecision?.Allowed == true && Environment == EnvironmentMode.Simulation;

    public bool CanRunPrimaryAction =>
        !IsReadOnlySnapshotMode
        && TradePlan is not null
        && Environment == EnvironmentMode.Simulation;

    public string TradePlanSymbolLabel => TradePlan?.Symbol ?? SelectedSymbol;

    public string TradePlanRiskStatusLabel => TradePlan?.RiskDecision?.State ?? "Plan unavailable";

    public string PlanningStatus => IsReadOnlySnapshotMode
        ? "Trade planning, Risk Governor, and simulation are unavailable at this read-only boundary. Stored chart evidence is independent and cannot create a substitute plan."
        : IsPythonSimulationWorkspaceMode && TradePlan is null
            ? $"No persisted TradePlan is available for {SelectedSymbol}. Simulation is unavailable; no substitute plan was created."
        : IsPythonSimulationWorkspaceMode
            ? "Stored TradePlan and Risk Governor evidence for the selected candidate."
        : TradePlan is null
            ? "No TradePlan is available for the selected candidate."
            : "TradePlan data is supplied by the current engine client.";

    public string PrimaryActionLabel => IsReadOnlySnapshotMode
        ? "Planning Deferred"
        : TradePlan?.PrimaryAction ?? "No Plan Available";

    public string ChartSourceLabel => PrimaryChart?.SourceSummary
        ?? (UsesPythonWorkspaceBoundary
            ? "Chart evidence unavailable; no simulated candle fallback is shown."
            : "Local simulation candle data");

    public string ActivitySourceLabel => IsPythonSimulationWorkspaceMode
        ? "Activity combines persisted Python evidence with the in-memory simulation ledger."
        : IsReadOnlySnapshotMode
        ? "Activity is read from persisted Python evidence snapshots."
        : "Activity is local to this shell.";

    public string ResearchSummary => IsPythonSimulationWorkspaceMode
        ? "Candidate evidence remains persisted and read-only. TradePlan, Risk Governor, ledger, audit, and FakeBroker simulation arrive through the Python host."
        : IsReadOnlySnapshotMode
        ? "Candidate, evidence, health, and source lineage come from the Python read-only boundary. Scores and readiness labels are not recalculated here."
        : "Evidence context for the linked symbol stays available without becoming a permanent route.";

    public string CandidateEvidenceSymbolLabel => CandidateEvidence?.Symbol ?? TradePlanSymbolLabel;

    public string CandidateCatalystHeadline => TextOrUnavailable(
        string.IsNullOrWhiteSpace(CandidateEvidence?.CatalystSummary?.Headline)
            ? CandidateEvidence?.Catalyst
            : CandidateEvidence.CatalystSummary.Headline,
        "No stored catalyst summary is available.");

    public string CandidateCatalystSourceLabel => TextOrUnavailable(
        CandidateEvidence?.CatalystSummary?.SourceLabel,
        "Catalyst source unavailable");

    public string CandidateCatalystObservedAtLabel => CandidateEvidence?.CatalystSummary is { } catalyst
        ? $"Observed {catalyst.ObservedAt.ToUniversalTime():yyyy-MM-dd HH:mm} UTC"
        : "Catalyst timestamp unavailable";

    public string CandidateReadinessLabel => TextOrUnavailable(
        CandidateEvidence?.OperatorState,
        "Readiness unavailable");

    public string CandidateQualityLabel => TextOrUnavailable(
        CandidateEvidence?.QualityLabel,
        "Source quality unavailable");

    public string CandidateLiquidityLabel => TextOrUnavailable(
        CandidateEvidence?.FloatOrLiquidity,
        "Liquidity data unavailable");

    public string CandidateLineageSourceLabel => TextOrUnavailable(
        CandidateEvidence?.DataLineage?.SourceLabel,
        "Source lineage unavailable");

    public string CandidateLineageAsOfLabel => CandidateEvidence?.DataLineage is { } lineage
        ? $"As of {lineage.AsOf.ToUniversalTime():yyyy-MM-dd HH:mm} UTC"
        : "Lineage timestamp unavailable";

    public string CandidateLineageSummary => TextOrUnavailable(
        CandidateEvidence?.DataLineage?.Summary,
        "No source lineage summary was supplied.");

    public IReadOnlyList<string> CandidateOpportunityNotes =>
        CandidateEvidence?.OpportunityNotes ?? [];

    public string CandidateOpportunityNotesLabel => CandidateOpportunityNotes.Count == 0
        ? "No stored opportunity notes are available."
        : $"{CandidateOpportunityNotes.Count} persisted opportunity note{(CandidateOpportunityNotes.Count == 1 ? string.Empty : "s")}";

    public HealthDiagnosticsView Diagnostics => HealthDiagnosticsView.From(Health);

    public TechnicalResearchOverviewView TechnicalResearchOverview =>
        TechnicalResearchOverviewView.From(TechnicalResearch);

    public IReadOnlyList<TechnicalResearchEventRowView> TechnicalResearchEventRows =>
        TechnicalResearch?.Events.Select(TechnicalResearchEventRowView.From).ToArray() ?? [];

    public IReadOnlyList<TechnicalResearchStudyRowView> TechnicalResearchStudyRows =>
        TechnicalResearch?.Studies.Select(TechnicalResearchStudyRowView.From).ToArray() ?? [];

    public bool HasTechnicalResearchEvents => TechnicalResearchEventRows.Count > 0;

    public bool HasTechnicalResearchStudies => TechnicalResearchStudyRows.Count > 0;

    public string TechnicalResearchEventsEmptyLabel => TechnicalResearch?.State switch
    {
        TechnicalResearchState.Empty => $"No stored technical research events exist for {SelectedSymbol}.",
        TechnicalResearchState.Unavailable => "Technical research event evidence is unavailable.",
        _ => "No technical research event rows were supplied for this symbol.",
    };

    public string TechnicalResearchStudiesEmptyLabel => TechnicalResearch?.State switch
    {
        TechnicalResearchState.Empty => $"No stored technical outcome studies exist for {SelectedSymbol}.",
        TechnicalResearchState.Unavailable => "Technical research outcome evidence is unavailable.",
        TechnicalResearchState.Partial => "The stored outcome-study report is partial or unavailable.",
        _ => "No technical outcome-study rows were supplied for this symbol.",
    };

    public string ResearchMaturityStateLabel =>
        ResearchMaturity?.State.ToString().ToUpperInvariant() ?? "UNAVAILABLE";

    public string ResearchMaturityAsOfLabel => ResearchMaturity?.SourceAsOf is { } asOf
        ? $"Source as of {asOf:yyyy-MM-dd HH:mm} UTC"
        : "Source timestamp unavailable";

    public string ResearchMaturityProgressLabel => ResearchMaturity is { } snapshot
        ? $"Maturity sample: {snapshot.MaturityAlerts.Completed:N0} completed / "
          + $"{snapshot.EvidenceGate.RequiredAlerts:N0} required for current gate"
        : "Maturity sample unavailable";

    public string ResearchMaturityRateLabel => ResearchMaturity?.MaturityAlerts.CompletionRatePercent is { } rate
        ? $"Maturity completion: {rate:N1}% of scorable alerts"
        : "Maturity completion unavailable";

    public string ResearchCensusRateLabel => ResearchMaturity?.Census.Alerts.CompletionRatePercent is { } rate
        ? $"Census completion: {rate:N1}% of all alerts"
        : "Census completion unavailable";

    public string ResearchMaturityWarningsLabel => ResearchMaturity is { Warnings.Count: > 0 } snapshot
        ? string.Join(System.Environment.NewLine, snapshot.Warnings)
        : "No persisted warnings.";

    public string ResearchMaturitySafetyLabel => ResearchMaturity is { SafetyNotes.Count: > 0 } snapshot
        ? string.Join(System.Environment.NewLine, snapshot.SafetyNotes)
        : "Research only. Strategy changes remain locked.";

    public string ReplaySummary => ReplaySession?.Summary ?? "Replay context is unavailable.";

    public ReplayContextView ReplayContext => ReplayContextView.From(ReplaySession);

    public AlertEvidenceOverviewView AlertEvidenceOverview => AlertEvidenceOverviewView.From(AlertEvidence);

    public IReadOnlyList<AlertEventRowView> AlertRows =>
        AlertEvidence?.ActiveAlerts.Select(AlertEventRowView.From).ToArray() ?? [];

    public IReadOnlyList<OutcomeRowView> OutcomeRows =>
        AlertEvidence?.Outcomes.Select(OutcomeRowView.From).ToArray() ?? [];

    public bool HasAlertRows => AlertRows.Count > 0;

    public bool HasOutcomeRows => OutcomeRows.Count > 0;

    public string AlertRowsEmptyLabel => AlertEvidence?.State switch
    {
        AlertEvidenceState.Empty => "No alerts are stored yet.",
        AlertEvidenceState.Unavailable => "Active and pending alert evidence is unavailable.",
        _ => "No active or pending alerts are present in the stored evidence.",
    };

    public string OutcomeRowsEmptyLabel => AlertEvidence?.State switch
    {
        AlertEvidenceState.Empty => "No outcomes are stored yet.",
        AlertEvidenceState.Unavailable => "Recorded outcome evidence is unavailable.",
        _ => "No completed or unscorable outcomes are present in the stored evidence.",
    };

    public string SavedWatchlistStateLabel => SavedWatchlist?.State.ToString().ToUpperInvariant() ?? "UNAVAILABLE";

    public string SavedWatchlistSourceLabel => SavedWatchlist?.SourceLabel ?? "Saved watchlist source unavailable";

    public string SavedWatchlistCountLabel => SavedWatchlist is null
        ? "0 displayed | 0 usable | 0 stored"
        : $"{SavedWatchlist.DisplayedItemCount} displayed | {SavedWatchlist.UsableItemCount} usable | {SavedWatchlist.TotalItemCount} stored";

    public string SavedWatchlistAsOfLabel => SavedWatchlist?.AsOf is { } asOf
        ? $"Newest stored save: {asOf.ToUniversalTime():yyyy-MM-dd HH:mm} UTC"
        : "Newest stored save time unavailable";

    public string SavedWatchlistSummary => SavedWatchlist?.Summary
        ?? "UNAVAILABLE | The saved-watchlist evidence boundary has not returned a snapshot.";

    public string SavedWatchlistWarnings => SavedWatchlist?.Warnings.Count > 0
        ? string.Join(" | ", SavedWatchlist.Warnings)
        : "No source warnings reported.";

    public string SavedWatchlistEmptyState => SavedWatchlistItems.Count == 0
        ? SavedWatchlist?.State switch
        {
            SavedWatchlistState.Empty => "No persisted saved-watchlist candidates are available.",
            SavedWatchlistState.Unavailable => "Saved-watchlist evidence is unavailable. No current candidate state was inferred.",
            _ => "No saved-watchlist rows are available for display.",
        }
        : string.Empty;

    public string DailyWorkflowStateLabel =>
        DailyWorkflow?.State.ToString().ToUpperInvariant() ?? "UNAVAILABLE";

    public string DailyWorkflowSourceLabel =>
        DailyWorkflow?.SourceLabel ?? "Daily Workflow source unavailable";

    public string DailyWorkflowSourceContextLabel =>
        DailyWorkflow?.SourceContext ?? "Capture identity unavailable";

    public string DailyWorkflowAsOfLabel => DailyWorkflow?.SourceAsOf is { } timestamp
        ? $"Source as of {timestamp.UtcDateTime:yyyy-MM-dd HH:mm:ss} UTC"
        : "Source time unavailable";

    public string DailyWorkflowScoreLabel => DailyWorkflow is { } workflow
        ? $"Workflow discipline {workflow.WorkflowScore}%"
        : "Workflow discipline unavailable";

    public string DailyWorkflowReviewLabel => DailyWorkflow is { } workflow
        ? $"Reviews {workflow.Review.Reviewed}/{workflow.Review.Total} | Unreviewed {workflow.Review.Unreviewed} | "
            + $"Interested {workflow.Review.Interested} | Rejected {workflow.Review.Rejected} | Watchlist {workflow.Review.Watchlist}"
        : "Review counts unavailable";

    public string DailyWorkflowPlanLabel => DailyWorkflow is { } workflow
        ? $"Plans {workflow.Plans.Complete}/{workflow.Plans.Watchlist} complete | "
            + $"Incomplete {workflow.Plans.Incomplete} | Without plan {workflow.Plans.WithoutPlan}"
        : "Plan counts unavailable";

    public string DailyWorkflowOutcomeLabel => DailyWorkflow is { } workflow
        ? $"Outcomes: next-day {workflow.Outcomes.CompletedNextDay} | five-day {workflow.Outcomes.CompletedFiveDay} | pending {workflow.Outcomes.Pending}"
        : "Outcome counts unavailable";

    public string DailyWorkflowReadinessLabel => DailyWorkflow?.Readiness.Count > 0
        ? string.Join(" | ", DailyWorkflow.Readiness.Select(item => $"{item.Name}: {item.Status}"))
        : "Readiness evidence unavailable";

    public string DailyWorkflowWarningsLabel => DailyWorkflow?.Warnings.Count > 0
        ? string.Join(System.Environment.NewLine, DailyWorkflow.Warnings.Select(warning => $"\u2022 {warning}"))
        : "No workflow warnings were reported by the persisted evidence.";

    public CandidateStoryOverviewView CandidateStoryOverview =>
        CandidateStoryOverviewView.From(CandidateStory);

    public IReadOnlyList<CandidateStoryPointRowView> CandidateStoryRows =>
        CandidateStory?.Points.Select(CandidateStoryPointRowView.From).ToArray() ?? [];

    public bool HasCandidateStoryPoints => CandidateStoryRows.Count > 0;

    public string CandidateStoryEmptyLabel => CandidateStory?.State switch
    {
        CandidateStoryEvidenceState.Empty => $"No trusted persisted Candidate Story captures exist for {SelectedSymbol}.",
        CandidateStoryEvidenceState.Unavailable => "Candidate Story evidence is unavailable.",
        _ => "No Candidate Story points were supplied for the selected symbol.",
    };

    public RectGeometry? RestoredWindowBounds => _windowBounds;

    public string? RestoredDockLayoutXml => _dockLayoutXml;

    public WindowDisplayState RestoredWindowState => _windowState;

    private bool UsesPythonWorkspaceBoundary => IsReadOnlySnapshotMode || IsPythonSimulationWorkspaceMode;

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        if (_layoutStore is not null)
        {
            var snapshot = await _layoutStore.LoadLatestValidAsync(cancellationToken);
            if (snapshot is not null)
            {
                ApplyLayoutSnapshot(snapshot);
                StatusMessage = $"Restored {snapshot.Workspace} layout from {snapshot.CreatedAt:yyyy-MM-dd HH:mm}.";
            }
        }

        await RefreshDailyWorkflowDataAsync(cancellationToken);
        await RefreshWorkspaceDataAsync(cancellationToken);
        await RefreshResearchMaturityAsync(cancellationToken);
        await RefreshChartPaneDataAsync(cancellationToken);
        await RefreshShadowReviewAsync(cancellationToken);
    }

    public async Task SelectCandidateAsync(CandidateSnapshot candidate, CancellationToken cancellationToken = default)
    {
        SelectedCandidate = candidate;
        SelectedSymbol = candidate.Symbol;
        _linkGroups.PublishSymbol(LinkGroup.A, candidate.Symbol, SelectedInterval);
        var technicalResearchTask = RefreshTechnicalResearchAsync(candidate.Symbol, cancellationToken);
        var candidateStoryTask = RefreshCandidateStoryAsync(candidate.Symbol, cancellationToken);
        if (IsReadOnlySnapshotMode)
        {
            TradePlan = null;
            await Task.WhenAll(technicalResearchTask, candidateStoryTask, RefreshChartPaneDataAsync(cancellationToken));
            StatusMessage = "Read-only Python candidate selected. Stored chart evidence refreshed; trade planning, risk, and simulation remain unavailable.";
            RaisePresentationProperties();
            RequestLayoutSave();
            return;
        }

        if (IsPythonSimulationWorkspaceMode)
        {
            ApplySimulationTradePlan(candidate.Symbol);
            await Task.WhenAll(technicalResearchTask, candidateStoryTask, RefreshChartPaneDataAsync(cancellationToken));
            StatusMessage = "Python persisted TradePlan selected. Risk Governor evidence and read-only stored chart context are refreshed.";
            RaisePresentationProperties();
            RequestLayoutSave();
            return;
        }

        var plan = await _engineClient.GetTradePlanAsync(candidate.Symbol, cancellationToken);
        await RefreshCandlesAsync(cancellationToken);
        if (PrimaryTradePlanPane?.IsPinned != true)
        {
            TradePlan = plan;
        }

        await Task.WhenAll(technicalResearchTask, candidateStoryTask, RefreshChartPaneDataAsync(cancellationToken));
        RaisePresentationProperties();
        RequestLayoutSave();
    }

    public void ChangeInterval(string interval)
    {
        if (!IntervalOptions.Contains(interval, StringComparer.Ordinal))
        {
            throw new ArgumentOutOfRangeException(nameof(interval), interval, "The selected interval is not available in this workstation shell.");
        }

        SelectedInterval = interval;
        _linkGroups.PublishSymbol(LinkGroup.A, SelectedSymbol, interval);
        RequestLayoutSave();
    }

    public async Task ChangeIntervalAsync(string interval, CancellationToken cancellationToken = default)
    {
        ChangeInterval(interval);
        if (!UsesPythonWorkspaceBoundary)
        {
            await RefreshCandlesAsync(cancellationToken);
        }
        await RefreshChartPaneDataAsync(cancellationToken);
    }

    public void ChangeWorkspace(WorkspaceKind workspace)
    {
        if (Workspace == workspace)
        {
            return;
        }

        Workspace = workspace;
        SetRegistry(WorkspaceFactory.Create(workspace, SelectedSymbol, SelectedInterval));
        _dockLayoutXml = null;
        _windowBounds = null;
        _windowState = WindowDisplayState.Normal;
        IsActivityOpen = Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Activity)?.IsVisible == true;
        RaisePresentationProperties();
        RequestLayoutSave();
    }

    public async Task ChangeWorkspaceAsync(WorkspaceKind workspace, CancellationToken cancellationToken = default)
    {
        if (Workspace == workspace)
        {
            return;
        }

        await FlushLayoutAsync(cancellationToken);
        ChangeWorkspace(workspace);
        if (_layoutStore is not null)
        {
            var snapshot = await _layoutStore.LoadLatestValidAsync(workspace, cancellationToken);
            if (snapshot is not null)
            {
                ApplyLayoutSnapshot(snapshot);
                StatusMessage = $"Restored {workspace} workspace layout.";
            }
        }

        await RefreshWorkspaceDataAsync(cancellationToken);
        await RefreshChartPaneDataAsync(cancellationToken);
        await RefreshShadowReviewAsync(cancellationToken);
    }

    public async Task SelectShadowTradeAsync(
        ShadowTradeReviewSnapshot trade,
        CancellationToken cancellationToken = default)
    {
        SelectedShadowTrade = trade;
        SelectedSymbol = trade.Symbol;
        var sourceGroup = ShadowReviewPane?.LinkGroup ?? LinkGroup.A;
        _linkGroups.PublishSymbol(sourceGroup, trade.Symbol, SelectedInterval);
        if (PrimaryTradePlanPane?.IsPinned != true)
        {
            ApplyShadowReviewTradePlan(trade);
        }
        await RefreshChartPaneDataAsync(cancellationToken);
        TradePlanTabIndex = 1;
        Activity.Insert(
            0,
            new ActivityEvent(
                DateTimeOffset.UtcNow,
                "Test Trade Review",
                $"{trade.ShadowTradeId} selected; linked unpinned review panes now show {trade.Symbol}.",
                trade.Symbol,
                trade.EvidenceEligible ? HealthState.Healthy : HealthState.Degraded));
        OnPropertyChanged(nameof(ActivityLabel));
        StatusMessage = $"{trade.Symbol} test trade selected for read-only evidence review.";
        RaisePresentationProperties();
        RequestLayoutSave();
    }

    public async Task RestoreNamedLayoutAsync(string name, CancellationToken cancellationToken = default)
    {
        if (_layoutStore is null)
        {
            StatusMessage = "Layout storage is unavailable in this shell instance.";
            return;
        }

        var snapshot = await _layoutStore.LoadNamedAsync(Workspace, name, cancellationToken);
        if (snapshot is null)
        {
            StatusMessage = $"No saved layout named '{name}' exists for {Workspace}.";
            return;
        }

        ApplyLayoutSnapshot(snapshot);
        StatusMessage = $"Restored layout '{name}'.";
        await RefreshWorkspaceDataAsync(cancellationToken);
        await RefreshChartPaneDataAsync(cancellationToken);
    }

    public void CaptureWindowState(
        RectGeometry bounds,
        string? dockLayoutXml,
        bool activityExpanded,
        WindowDisplayState windowState = WindowDisplayState.Normal)
    {
        _windowBounds = bounds;
        _dockLayoutXml = dockLayoutXml;
        IsActivityOpen = activityExpanded;
        _windowState = windowState;
        RequestLayoutSave();
    }

    public bool SoftClosePane(Guid instanceId) => Registry.SoftClose(instanceId);

    public bool ReopenPane(Guid instanceId) => Registry.Reopen(instanceId);

    public bool RemovePane(Guid instanceId)
    {
        var removed = Registry.Remove(instanceId);
        if (removed)
        {
            var chart = SecondaryCharts.FirstOrDefault(item => item.Pane.InstanceId == instanceId);
            if (chart is not null)
            {
                SecondaryCharts.Remove(chart);
            }
        }

        return removed;
    }

    [RelayCommand]
    private void ToggleActivity()
    {
        IsActivityOpen = !IsActivityOpen;
        var activityPane = Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Activity);
        if (activityPane is not null)
        {
            activityPane.IsVisible = IsActivityOpen;
        }
    }

    [RelayCommand]
    private void ToggleHealth() => IsHealthOpen = !IsHealthOpen;

    [RelayCommand]
    private void ToggleDiagnostics()
    {
        var diagnosticsPane = Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Diagnostics);
        if (diagnosticsPane is null)
        {
            StatusMessage = "Diagnostics was removed from this workspace.";
            return;
        }

        IsDiagnosticsOpen = !IsDiagnosticsOpen;
        diagnosticsPane.IsVisible = IsDiagnosticsOpen;
    }

    [RelayCommand]
    private void ToggleCommandPalette()
    {
        if (IsCommandPaletteOpen)
        {
            CloseCommandPalette();
        }
        else
        {
            OpenCommandPalette();
        }
    }

    public void OpenCommandPalette(string? query = null)
    {
        CommandQuery = query?.Trim() ?? string.Empty;
        RefreshCommandPaletteResults();
        IsCommandPaletteOpen = true;
    }

    public void CloseCommandPalette()
    {
        IsCommandPaletteOpen = false;
        CommandQuery = string.Empty;
    }

    public CommandPaletteItem? FindExactCommandPaletteItem(string? query) =>
        CommandPaletteCatalog.FindExact(Candidates, query);

    public async Task<CommandPaletteExecution> ExecuteCommandPaletteItemAsync(
        CommandPaletteItem? item = null,
        CancellationToken cancellationToken = default)
    {
        var selected = item ?? SelectedCommandPaletteItem;
        if (selected is null)
        {
            StatusMessage = string.IsNullOrWhiteSpace(CommandQuery)
                ? "Choose a candidate or command."
                : CommandPaletteEmptyText;
            return new CommandPaletteExecution(false);
        }

        PaneState? addedPane = null;
        switch (selected.Action)
        {
            case CommandPaletteAction.OpenCandidate:
            {
                var candidate = Candidates.FirstOrDefault(candidate =>
                    string.Equals(candidate.Symbol, selected.Symbol, StringComparison.OrdinalIgnoreCase));
                if (candidate is null)
                {
                    StatusMessage = $"Candidate {selected.Symbol ?? "unknown"} is no longer available in the current evidence snapshot.";
                    RefreshCommandPaletteResults();
                    return new CommandPaletteExecution(false);
                }

                await SelectCandidateAsync(candidate, cancellationToken);
                StatusMessage = $"Opened candidate {candidate.Symbol} from the command palette.";
                break;
            }
            case CommandPaletteAction.AddChart:
                addedPane = await AddLinkedChartAsync(cancellationToken);
                StatusMessage = $"Added linked chart for {addedPane.Symbol}.";
                break;
            case CommandPaletteAction.OpenPositions:
                if (!await OpenPositionsPaneAsync(cancellationToken))
                {
                    return new CommandPaletteExecution(false);
                }
                break;
            case CommandPaletteAction.ToggleActivity:
                if (!IsActivityOpen)
                {
                    ToggleActivity();
                }
                StatusMessage = "Opened What Changed / Decision Timeline.";
                break;
            case CommandPaletteAction.ViewDiagnostics:
            {
                var diagnostics = Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Diagnostics);
                if (diagnostics is null)
                {
                    StatusMessage = "Diagnostics was removed from this workspace.";
                    return new CommandPaletteExecution(false);
                }

                IsDiagnosticsOpen = true;
                diagnostics.IsVisible = true;
                StatusMessage = "Opened workstation diagnostics.";
                break;
            }
            default:
                throw new ArgumentOutOfRangeException(nameof(selected), selected.Action, "Unsupported command palette action.");
        }

        var action = selected.Action;
        CloseCommandPalette();
        return new CommandPaletteExecution(true, action, addedPane);
    }

    public async Task<bool> OpenPositionsPaneAsync(CancellationToken cancellationToken = default)
    {
        if (PositionsPane is not { } positions)
        {
            StatusMessage = "The Positions pane is not available in this workspace.";
            return false;
        }

        positions.IsVisible = true;
        await RefreshShadowReviewDisplayAsync(cancellationToken);
        StatusMessage = OpenPositions.Count == 0
            ? "Opened Positions. No open FakeBroker positions are currently reported."
            : $"Opened Positions with {OpenPositions.Count} current FakeBroker position{(OpenPositions.Count == 1 ? string.Empty : "s")}.";
        RequestLayoutSave();
        return true;
    }

    [RelayCommand]
    private async Task TogglePrimaryChartPinAsync()
    {
        if (PrimaryChartPane is not null)
        {
            PrimaryChartPane.IsPinned = !PrimaryChartPane.IsPinned;
            if (!PrimaryChartPane.IsPinned)
            {
                PrimaryChartPane.Symbol = SelectedSymbol;
                PrimaryChartPane.Interval = SelectedInterval;
                await RefreshChartPaneDataAsync();
            }

            OnPropertyChanged(nameof(PrimaryChartLinkLabel));
        }
    }

    [RelayCommand]
    private void CyclePrimaryChartLinkGroup()
    {
        if (PrimaryChartPane is null || PrimaryChartPane.IsPinned)
        {
            return;
        }

        PrimaryChartPane.LinkGroup = PrimaryChartPane.LinkGroup switch
        {
            LinkGroup.A => LinkGroup.B,
            LinkGroup.B => LinkGroup.C,
            LinkGroup.C => LinkGroup.D,
            _ => LinkGroup.A,
        };
        OnPropertyChanged(nameof(PrimaryChartLinkLabel));
    }

    [RelayCommand]
    private async Task TogglePrimaryTradePlanPinAsync()
    {
        if (PrimaryTradePlanPane is null)
        {
            return;
        }

        PrimaryTradePlanPane.IsPinned = !PrimaryTradePlanPane.IsPinned;
        if (!PrimaryTradePlanPane.IsPinned && IsPythonSimulationWorkspaceMode)
        {
            PrimaryTradePlanPane.Symbol = SelectedSymbol;
            PrimaryTradePlanPane.Interval = SelectedInterval;
            ApplySimulationTradePlan(SelectedSymbol);
        }
        else if (!PrimaryTradePlanPane.IsPinned && !IsReadOnlySnapshotMode)
        {
            PrimaryTradePlanPane.Symbol = SelectedSymbol;
            PrimaryTradePlanPane.Interval = SelectedInterval;
            TradePlan = await _engineClient.GetTradePlanAsync(SelectedSymbol);
        }

        OnPropertyChanged(nameof(PrimaryTradePlanLinkLabel));
        OnPropertyChanged(nameof(CanRunSimulation));
    }

    public PaneState AddLinkedChart()
    {
        var pane = Registry.Create(PaneKind.Chart, "Chart", LinkGroup.B, DockRegion.Center, SelectedSymbol, SelectedInterval);
        SecondaryCharts.Add(new ChartPaneViewModel(pane, Candles));
        OnPropertyChanged(nameof(PrimaryChartLinkLabel));
        return pane;
    }

    public async Task<PaneState> AddLinkedChartAsync(CancellationToken cancellationToken = default)
    {
        var pane = Registry.Create(PaneKind.Chart, "Chart", LinkGroup.B, DockRegion.Center, SelectedSymbol, SelectedInterval);
        var snapshot = await LoadChartSnapshotAsync(pane.Symbol, pane.Interval, cancellationToken);
        SecondaryCharts.Add(new ChartPaneViewModel(pane, snapshot));
        OnPropertyChanged(nameof(PrimaryChartLinkLabel));
        return pane;
    }

    public async Task RunPrimaryActionAsync(CancellationToken cancellationToken = default)
    {
        if (IsReadOnlySnapshotMode)
        {
            StatusMessage = "This is a read-only Python evidence snapshot. Trade planning and simulation are deferred to Phase 10.";
            RaisePresentationProperties();
            return;
        }

        if (TradePlan is null)
        {
            return;
        }

        if (IsPythonSimulationWorkspaceMode)
        {
            if (!CanRunSimulation)
            {
                StatusMessage = $"Risk Governor blocked simulation: {TradePlan.RiskDecision?.Summary ?? "risk evidence is unavailable"}. No evidence was changed.";
                RaisePresentationProperties();
                RequestLayoutSave();
                return;
            }

            LastSimulationResult = await _simulationWorkspaceClient!.RunSimulationAsync(TradePlan.Symbol, cancellationToken);
            await RefreshSimulationWorkspaceDataAsync(cancellationToken);
            await RefreshChartPaneDataAsync(cancellationToken);
            StatusMessage = LastSimulationResult.Summary;
            RaisePresentationProperties();
            RequestLayoutSave();
            return;
        }

        if (CanRunSimulation)
        {
            LastSimulationResult = await _engineClient.RunSimulationAsync(TradePlan.Symbol, cancellationToken);
            StatusMessage = LastSimulationResult.Summary;
            Activity.Insert(0, new ActivityEvent(DateTimeOffset.UtcNow, "Simulation", LastSimulationResult.Summary, TradePlan.Symbol, HealthState.Healthy));
        }
        else
        {
            TradePlan = await _engineClient.ResolveMissingDataAsync(TradePlan.Symbol, cancellationToken);
            StatusMessage = TradePlan.RiskDecision?.Summary ?? "Evidence repair could not be completed.";
        }

        RaisePresentationProperties();
        RequestLayoutSave();
    }

    public async Task SaveNamedLayoutAsync(string name, CancellationToken cancellationToken = default)
    {
        if (_layoutStore is null)
        {
            StatusMessage = "Layout storage is unavailable in this shell instance.";
            return;
        }

        await _layoutStore.SaveAsync(CreateLayoutSnapshot(isNamedLayout: true, name), cancellationToken);
        StatusMessage = $"Saved layout '{name}'.";
    }

    public Task FlushLayoutAsync(CancellationToken cancellationToken = default) =>
        _layoutAutosave?.FlushAsync(cancellationToken) ?? Task.CompletedTask;

    public void UpdateBackgroundStatus(BackgroundCollectionStatus status)
    {
        BackgroundCollectionStatus = status;
        BackgroundStatusLabel = BackgroundStatusText.Label(status);
        BackgroundStatusDetail = BackgroundStatusText.Detail(status);
        IsMonitoringPaused = status.State == BackgroundCollectionState.Paused;
    }

    public void RecordBackgroundActivity(BackgroundCollectionActivity activity)
    {
        var state = activity.State switch
        {
            BackgroundCollectionState.Healthy => HealthState.Healthy,
            BackgroundCollectionState.Paused => HealthState.Healthy,
            BackgroundCollectionState.Degraded => HealthState.Degraded,
            _ => HealthState.Unavailable,
        };
        Activity.Insert(0, new ActivityEvent(activity.Timestamp, "Monitoring", activity.Message, SelectedSymbol, state));
        OnPropertyChanged(nameof(ActivityLabel));
    }

    partial void OnIsMonitoringPausedChanged(bool value) => OnPropertyChanged(nameof(MonitoringToggleLabel));

    partial void OnCommandQueryChanged(string value) => RefreshCommandPaletteResults();

    partial void OnHealthChanged(SystemHealthSnapshot? value)
    {
        OnPropertyChanged(nameof(Diagnostics));
        OnPropertyChanged(nameof(CommandCenterHealth));
    }

    partial void OnSelectedCandidateChanged(CandidateSnapshot? value)
    {
        SelectedAttentionRow = value is null
            ? null
            : AttentionRows.FirstOrDefault(row => ReferenceEquals(row.Candidate, value)
                || string.Equals(row.Symbol, value.Symbol, StringComparison.OrdinalIgnoreCase));
        RaiseCommandCenterProperties();
    }

    partial void OnSelectedSymbolChanged(string value)
    {
        RefreshWhatChangedRows();
        OnPropertyChanged(nameof(TimelineSelection));
    }

    partial void OnSelectedTimelineItemChanged(CommandCenterTimelineItemView? value)
    {
        OnPropertyChanged(nameof(TimelineSelection));
        OnPropertyChanged(nameof(HistoricalDecisionContext));
    }

    partial void OnTradePlanChanged(TradePlanSnapshot? value) =>
        OnPropertyChanged(nameof(CurrentDecision));

    partial void OnPrimaryChartChanged(ChartPaneViewModel? value)
    {
        OnPropertyChanged(nameof(CurrentDecision));
        OnPropertyChanged(nameof(CurrentMarketStory));
    }

    [RelayCommand]
    private void ReturnToCurrent() => SelectedTimelineItem = null;

    partial void OnReplaySessionChanged(ReplaySnapshot? value) => OnPropertyChanged(nameof(ReplayContext));

    partial void OnBackgroundCollectionStatusChanged(BackgroundCollectionStatus value) =>
        OnPropertyChanged(nameof(MonitoringStatus));

    partial void OnDailyWorkflowChanged(DailyWorkflowSnapshot? value)
    {
        OnPropertyChanged(nameof(DailyWorkflowStateLabel));
        OnPropertyChanged(nameof(DailyWorkflowSourceLabel));
        OnPropertyChanged(nameof(DailyWorkflowSourceContextLabel));
        OnPropertyChanged(nameof(DailyWorkflowAsOfLabel));
        OnPropertyChanged(nameof(DailyWorkflowScoreLabel));
        OnPropertyChanged(nameof(DailyWorkflowReviewLabel));
        OnPropertyChanged(nameof(DailyWorkflowPlanLabel));
        OnPropertyChanged(nameof(DailyWorkflowOutcomeLabel));
        OnPropertyChanged(nameof(DailyWorkflowReadinessLabel));
        OnPropertyChanged(nameof(DailyWorkflowWarningsLabel));
    }

    partial void OnCandidateStoryChanged(CandidateStorySnapshot? value)
    {
        OnPropertyChanged(nameof(CandidateStoryOverview));
        OnPropertyChanged(nameof(CandidateStoryRows));
        OnPropertyChanged(nameof(HasCandidateStoryPoints));
        OnPropertyChanged(nameof(CandidateStoryEmptyLabel));
        RefreshWhatChangedRows();
    }

    private void SetRegistry(PaneRegistry registry)
    {
        if (Registry is not null)
        {
            Registry.Changed -= OnRegistryChanged;
        }

        Registry = registry;
        Registry.Changed += OnRegistryChanged;
        _linkGroups = new LinkGroupCoordinator(Registry);
        SecondaryCharts.Clear();
        PrimaryChart = null;
    }

    private void OnRegistryChanged(object? sender, EventArgs e)
    {
        OnPropertyChanged(nameof(PrimaryChartPane));
        OnPropertyChanged(nameof(PrimaryChartLinkLabel));
        OnPropertyChanged(nameof(PrimaryTradePlanPane));
        OnPropertyChanged(nameof(PrimaryTradePlanLinkLabel));
        RequestLayoutSave();
    }

    private void RequestLayoutSave() => _layoutAutosave?.RequestSave();

    private void RefreshCommandPaletteResults()
    {
        var results = CommandPaletteCatalog.Filter(Candidates, CommandQuery);
        SelectedCommandPaletteItem = null;
        CommandPaletteResults.Clear();
        foreach (var result in results)
        {
            CommandPaletteResults.Add(result);
        }

        SelectedCommandPaletteItem = CommandPaletteResults.FirstOrDefault();
        OnPropertyChanged(nameof(HasCommandPaletteResults));
        OnPropertyChanged(nameof(CommandPaletteEmptyText));
    }

    private void RefreshAttentionRows()
    {
        var selectedSymbol = SelectedCandidate?.Symbol;
        AttentionRows.Clear();
        foreach (var row in CommandCenterAttentionRowView.ProjectSourceOrder(Candidates, DateTimeOffset.UtcNow))
        {
            AttentionRows.Add(row);
        }

        SelectedAttentionRow = string.IsNullOrWhiteSpace(selectedSymbol)
            ? null
            : AttentionRows.FirstOrDefault(row =>
                string.Equals(row.Symbol, selectedSymbol, StringComparison.OrdinalIgnoreCase));
        OnPropertyChanged(nameof(UniverseCountLabel));
        OnPropertyChanged(nameof(CurrentDecision));
        OnPropertyChanged(nameof(CurrentMarketStory));
    }

    private void RefreshWhatChangedRows()
    {
        var selectedIdentity = SelectedTimelineItem?.Identity;
        WhatChangedRows.Clear();
        foreach (var row in CommandCenterTimelineItemView.Compose(
                     Activity,
                     CandidateStory,
                     TechnicalResearch,
                     SelectedSymbol))
        {
            WhatChangedRows.Add(row);
        }

        SelectedTimelineItem = string.IsNullOrWhiteSpace(selectedIdentity)
            ? null
            : WhatChangedRows.FirstOrDefault(row =>
                string.Equals(row.Identity, selectedIdentity, StringComparison.Ordinal));
        OnPropertyChanged(nameof(ActivityLabel));
        OnPropertyChanged(nameof(WhatChangedCountLabel));
        OnPropertyChanged(nameof(TimelineSelection));
        OnPropertyChanged(nameof(HistoricalDecisionContext));
    }

    private void RaiseCommandCenterProperties()
    {
        OnPropertyChanged(nameof(UniverseCountLabel));
        OnPropertyChanged(nameof(CurrentDecision));
        OnPropertyChanged(nameof(CurrentMarketStory));
        OnPropertyChanged(nameof(CommandCenterHealth));
        OnPropertyChanged(nameof(WhatChangedCountLabel));
        OnPropertyChanged(nameof(WhatChangedLimitationLabel));
        OnPropertyChanged(nameof(TimelineSelection));
        OnPropertyChanged(nameof(HistoricalDecisionContext));
    }

    private WorkspaceLayoutSnapshot CreateAutomaticLayoutSnapshot() => CreateLayoutSnapshot(isNamedLayout: false, name: null);

    private WorkspaceLayoutSnapshot CreateLayoutSnapshot(bool isNamedLayout, string? name) => new(
        SchemaVersion: 7,
        Workspace,
        Guid.NewGuid(),
        DateTimeOffset.UtcNow,
        isNamedLayout,
        name,
        SelectedSymbol,
        SelectedInterval,
        Registry.ToLayouts(),
        string.Empty,
        _dockLayoutXml,
        _windowBounds,
        IsActivityOpen,
        _windowState);

    private void ApplyLayoutSnapshot(WorkspaceLayoutSnapshot snapshot)
    {
        Workspace = snapshot.Workspace;
        SelectedSymbol = snapshot.SelectedSymbol;
        SelectedInterval = IntervalOptions.Contains(snapshot.SelectedInterval, StringComparer.Ordinal) ? snapshot.SelectedInterval : "5m";
        SetRegistry(new PaneRegistry());
        Registry.Restore(snapshot.Panes);
        WorkspaceFactory.EnsureStandardPanes(Registry, Workspace, SelectedSymbol, SelectedInterval);
        MigrateLegacyContextualPanes(snapshot.SchemaVersion);
        EnsureShadowReviewPane();
        _dockLayoutXml = snapshot.DockLayoutXml;
        _windowBounds = snapshot.WindowBounds;
        _windowState = snapshot.WindowState;
        IsActivityOpen = snapshot.ActivityExpanded;
        IsDiagnosticsOpen = Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Diagnostics)?.IsVisible == true;
        PrimaryChart = null;
        RaisePresentationProperties();
    }

    private static string PaneSyncLabel(PaneState? pane)
    {
        if (pane is null)
        {
            return "Independent";
        }

        if (pane.IsPinned)
        {
            return $"Pinned to {pane.Symbol}";
        }

        return pane.LinkGroup == LinkGroup.A
            ? "Follows Hunter"
            : "Independent";
    }

    private void MigrateLegacyContextualPanes(int schemaVersion)
    {
        if (schemaVersion >= 7 || Workspace != WorkspaceKind.Live)
        {
            return;
        }

        var missingPanes = new List<(PaneKind Kind, string Title)>();
        if (schemaVersion < 6)
        {
            missingPanes.Add((PaneKind.DailyWorkflow, "Daily Workflow"));
            missingPanes.Add((PaneKind.CandidateStory, "Candidate Story"));
        }
        if (schemaVersion < 7)
        {
            missingPanes.Add((PaneKind.ResearchMaturity, "Research Maturity"));
        }
        if (schemaVersion < 4)
        {
            missingPanes.AddRange(
            [
                (PaneKind.Automation, "Automation"),
                (PaneKind.Orders, "Orders"),
                (PaneKind.Positions, "Positions"),
            ]);
        }

        foreach (var (kind, title) in missingPanes)
        {
            if (Registry.Panes.Any(pane => pane.Kind == kind))
            {
                continue;
            }

            var linkGroup = kind == PaneKind.CandidateStory ? LinkGroup.A : LinkGroup.Unlinked;
            Registry.Create(kind, title, linkGroup, DockRegion.Bottom, SelectedSymbol, SelectedInterval).IsVisible = false;
        }
    }

    private void EnsureShadowReviewPane()
    {
        if (Workspace != WorkspaceKind.Review || Registry.Panes.Any(pane => pane.Kind == PaneKind.ShadowReview))
        {
            return;
        }

        Registry.Create(
            PaneKind.ShadowReview,
            "Test Trade Review",
            LinkGroup.A,
            DockRegion.Bottom,
            SelectedSymbol,
            SelectedInterval);
    }

    private async Task RefreshResearchMaturityAsync(CancellationToken cancellationToken)
    {
        if (_researchMaturityWorkspaceClient is null)
        {
            ResearchMaturity = null;
            RaiseResearchMaturityProperties();
            return;
        }

        try
        {
            ResearchMaturity = await _researchMaturityWorkspaceClient.GetSnapshotAsync(
                cancellationToken);
        }
        catch (Exception exception) when (
            exception is IOException
                or InvalidDataException
                or InvalidOperationException
                or JsonException)
        {
            var now = DateTimeOffset.UtcNow;
            ResearchMaturity = new ResearchMaturitySnapshot(
                1,
                ResearchMaturityEvidenceState.Unavailable,
                now,
                null,
                null,
                null,
                "Unavailable persisted research evidence",
                $"UNAVAILABLE | Research maturity could not be loaded: {exception.Message} "
                    + "No evidence or strategy conclusion was inferred.",
                "UNAVAILABLE",
                "UNAVAILABLE",
                "UNAVAILABLE",
                "UNAVAILABLE",
                "LOCKED",
                false,
                new ResearchMaturityAlertCounts(0, 0, 0, 0, null),
                0,
                new ResearchMaturityEvidenceGate(
                    0,
                    0,
                    "UNAVAILABLE",
                    "No action available",
                    "LOCKED",
                    "The persisted research-maturity boundary did not return usable evidence."),
                [],
                0,
                [],
                0,
                new ResearchEvidenceCensus(
                    new ResearchMaturityAlertCounts(0, 0, 0, 0, null),
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    [],
                    0),
                [exception.Message],
                ["Research evidence only; strategy changes remain prohibited."],
                true,
                true);
        }

        RaiseResearchMaturityProperties();
    }

    private void RaiseResearchMaturityProperties()
    {
        OnPropertyChanged(nameof(ResearchMaturityStateLabel));
        OnPropertyChanged(nameof(ResearchMaturityAsOfLabel));
        OnPropertyChanged(nameof(ResearchMaturityProgressLabel));
        OnPropertyChanged(nameof(ResearchMaturityRateLabel));
        OnPropertyChanged(nameof(ResearchCensusRateLabel));
        OnPropertyChanged(nameof(ResearchMaturityWarningsLabel));
        OnPropertyChanged(nameof(ResearchMaturitySafetyLabel));
    }

    private async Task RefreshWorkspaceDataAsync(CancellationToken cancellationToken)
    {
        await RefreshSavedWatchlistAsync(cancellationToken);

        if (_simulationWorkspaceClient is not null)
        {
            await RefreshSimulationWorkspaceDataAsync(cancellationToken);
            return;
        }

        if (_readOnlyWorkspaceClient is not null)
        {
            await RefreshReadOnlyWorkspaceDataAsync(cancellationToken);
            return;
        }

        IsReadOnlySnapshotMode = false;
        IsPythonSimulationWorkspaceMode = false;
        AlertEvidence = null;
        Candidates.Clear();
        foreach (var candidate in await _engineClient.GetCandidatesAsync(cancellationToken))
        {
            Candidates.Add(candidate);
        }

        Activity.Clear();
        foreach (var activity in await _engineClient.GetActivityAsync(cancellationToken))
        {
            Activity.Add(activity);
        }

        OnPropertyChanged(nameof(ActivityLabel));

        Health = await _engineClient.GetSystemHealthAsync(cancellationToken);
        ReplaySession = await _engineClient.GetReplaySessionAsync(cancellationToken);
        var candidateToSelect = Candidates.FirstOrDefault(candidate => candidate.Symbol == SelectedSymbol) ?? Candidates.FirstOrDefault();
        if (candidateToSelect is not null)
        {
            await SelectCandidateAsync(candidateToSelect, cancellationToken);
        }
    }

    private async Task RefreshDailyWorkflowDataAsync(CancellationToken cancellationToken)
    {
        if (_dailyWorkflowWorkspaceClient is null)
        {
            return;
        }
        try
        {
            DailyWorkflow = await _dailyWorkflowWorkspaceClient.GetSnapshotAsync(cancellationToken);
        }
        catch (Exception exception) when (
            exception is IOException or InvalidDataException or InvalidOperationException or JsonException)
        {
            var now = DateTimeOffset.UtcNow;
            DailyWorkflow = new DailyWorkflowSnapshot(
                1,
                DailyWorkflowEvidenceState.Unavailable,
                now,
                null,
                "Daily Workflow source unavailable",
                "Capture identity unavailable",
                "CAPTURE_MISSING",
                "Capture Missing",
                $"UNAVAILABLE | The Daily Workflow boundary failed closed: {exception.Message}",
                0,
                "unavailable",
                new DailyWorkflowReviewCounts(0, 0, 0, 0, 0, 0),
                new DailyWorkflowPlanCounts(0, 0, 0, 0, 0, 0, 0, 0),
                new DailyWorkflowOutcomeCounts(0, 0, 0),
                [],
                new DailyWorkflowNextAction(
                    "Next Required Action: restore persisted workflow evidence",
                    "The read-only host did not return a valid Daily Workflow snapshot.",
                    DailyWorkflowStepLevel.Blocked),
                [],
                ["The Daily Workflow snapshot is unavailable; no fallback or recalculation was created."],
                true);
        }
    }

    private async Task RefreshCandlesAsync(CancellationToken cancellationToken)
    {
        if (UsesPythonWorkspaceBoundary)
        {
            Candles.Clear();
            return;
        }

        Candles.Clear();
        foreach (var candle in await _engineClient.GetCandlesAsync(SelectedSymbol, SelectedInterval, cancellationToken))
        {
            Candles.Add(candle);
        }
    }

    private async Task RefreshChartPaneDataAsync(CancellationToken cancellationToken = default)
    {
        await _chartRefreshLock.WaitAsync(cancellationToken);
        try
        {
            await RefreshChartPaneDataCoreAsync(cancellationToken);
        }
        finally
        {
            _chartRefreshLock.Release();
        }
    }

    private async Task RefreshChartPaneDataCoreAsync(CancellationToken cancellationToken)
    {
        if (UsesPythonWorkspaceBoundary && _chartWorkspaceClient is null)
        {
            PrimaryChart = null;
            SecondaryCharts.Clear();
            OnPropertyChanged(nameof(ChartSourceLabel));
            return;
        }

        var primaryPane = PrimaryChartPane;
        if (primaryPane is null)
        {
            PrimaryChart = null;
            SecondaryCharts.Clear();
            return;
        }

        var primarySnapshot = await LoadChartSnapshotAsync(primaryPane.Symbol, primaryPane.Interval, cancellationToken);
        if (PrimaryChart is null || PrimaryChart.Pane.InstanceId != primaryPane.InstanceId)
        {
            PrimaryChart = new ChartPaneViewModel(primaryPane, primarySnapshot);
        }
        else
        {
            PrimaryChart.ApplySnapshot(primarySnapshot);
        }

        var secondaryPanes = Registry.Panes
            .Where(pane => pane.Kind == PaneKind.Chart && pane.InstanceId != primaryPane.InstanceId)
            .ToArray();
        var obsoleteCharts = SecondaryCharts.Where(chart => secondaryPanes.All(pane => pane.InstanceId != chart.Pane.InstanceId)).ToArray();
        foreach (var chart in obsoleteCharts)
        {
            SecondaryCharts.Remove(chart);
        }

        foreach (var pane in secondaryPanes)
        {
            var snapshot = await LoadChartSnapshotAsync(pane.Symbol, pane.Interval, cancellationToken);
            var chart = SecondaryCharts.FirstOrDefault(item => item.Pane.InstanceId == pane.InstanceId);
            if (chart is null)
            {
                SecondaryCharts.Add(new ChartPaneViewModel(pane, snapshot));
            }
            else
            {
                chart.ApplySnapshot(snapshot);
            }
        }
        OnPropertyChanged(nameof(ChartSourceLabel));
    }

    public async Task RefreshChartDisplayAsync(CancellationToken cancellationToken = default)
    {
        if (!await _chartRefreshLock.WaitAsync(0, cancellationToken))
        {
            return;
        }

        try
        {
            await RefreshChartPaneDataCoreAsync(cancellationToken);
        }
        finally
        {
            _chartRefreshLock.Release();
        }
    }

    private async Task<ChartSnapshot> LoadChartSnapshotAsync(
        string symbol,
        string interval,
        CancellationToken cancellationToken)
    {
        if (!UsesPythonWorkspaceBoundary)
        {
            var candles = await _engineClient.GetCandlesAsync(symbol, interval, cancellationToken);
            var observedAt = candles.Count > 0 ? candles[^1].Timestamp : DateTimeOffset.UtcNow;
            return new ChartSnapshot(
                1,
                symbol,
                interval,
                candles.Count > 0 ? ChartDataState.Available : ChartDataState.Unavailable,
                DateTimeOffset.UtcNow,
                observedAt,
                candles.Count > 0
                    ? "Local deterministic simulation candles."
                    : "No local deterministic simulation candles are available.",
                new DataLineage("Local simulation", observedAt, "Deterministic local shell data."),
                candles);
        }

        try
        {
            return await _chartWorkspaceClient!.GetSnapshotAsync(symbol, interval, cancellationToken);
        }
        catch (Exception exception) when (
            !cancellationToken.IsCancellationRequested
            && exception is IOException
                or InvalidDataException
                or InvalidOperationException
                or JsonException
                or System.Net.Sockets.SocketException
                or OperationCanceledException)
        {
            var now = DateTimeOffset.UtcNow;
            return new ChartSnapshot(
                1,
                symbol,
                interval,
                ChartDataState.Unavailable,
                now,
                now,
                $"UNAVAILABLE | Stored chart evidence could not be loaded: {exception.Message} No simulated fallback was created.",
                new DataLineage("Unavailable chart source", now, "The Python chart boundary did not return usable stored OHLC evidence."),
                []);
        }
    }

    private void RaisePresentationProperties()
    {
        RaiseCommandCenterProperties();
        OnPropertyChanged(nameof(Registry));
        OnPropertyChanged(nameof(Environment));
        OnPropertyChanged(nameof(EnvironmentLabel));
        OnPropertyChanged(nameof(EnvironmentDetail));
        OnPropertyChanged(nameof(ActivityLabel));
        OnPropertyChanged(nameof(WorkspaceTitle));
        OnPropertyChanged(nameof(WorkspaceNarrative));
        OnPropertyChanged(nameof(PrimaryChartPane));
        OnPropertyChanged(nameof(PrimaryChartLinkLabel));
        OnPropertyChanged(nameof(PrimaryTradePlanPane));
        OnPropertyChanged(nameof(PrimaryTradePlanLinkLabel));
        OnPropertyChanged(nameof(ShadowReviewPane));
        OnPropertyChanged(nameof(PositionsPane));
        OnPropertyChanged(nameof(CanRunSimulation));
        OnPropertyChanged(nameof(CanRunPrimaryAction));
        OnPropertyChanged(nameof(TradePlanSymbolLabel));
        OnPropertyChanged(nameof(TradePlanRiskStatusLabel));
        OnPropertyChanged(nameof(PlanningStatus));
        OnPropertyChanged(nameof(PrimaryActionLabel));
        OnPropertyChanged(nameof(ChartSourceLabel));
        OnPropertyChanged(nameof(ActivitySourceLabel));
        OnPropertyChanged(nameof(ResearchSummary));
        OnPropertyChanged(nameof(CandidateEvidenceSymbolLabel));
        OnPropertyChanged(nameof(CandidateCatalystHeadline));
        OnPropertyChanged(nameof(CandidateCatalystSourceLabel));
        OnPropertyChanged(nameof(CandidateCatalystObservedAtLabel));
        OnPropertyChanged(nameof(CandidateReadinessLabel));
        OnPropertyChanged(nameof(CandidateQualityLabel));
        OnPropertyChanged(nameof(CandidateLiquidityLabel));
        OnPropertyChanged(nameof(CandidateLineageSourceLabel));
        OnPropertyChanged(nameof(CandidateLineageAsOfLabel));
        OnPropertyChanged(nameof(CandidateLineageSummary));
        OnPropertyChanged(nameof(CandidateOpportunityNotes));
        OnPropertyChanged(nameof(CandidateOpportunityNotesLabel));
        OnPropertyChanged(nameof(TechnicalResearchOverview));
        OnPropertyChanged(nameof(TechnicalResearchEventRows));
        OnPropertyChanged(nameof(TechnicalResearchStudyRows));
        OnPropertyChanged(nameof(HasTechnicalResearchEvents));
        OnPropertyChanged(nameof(HasTechnicalResearchStudies));
        OnPropertyChanged(nameof(TechnicalResearchEventsEmptyLabel));
        OnPropertyChanged(nameof(TechnicalResearchStudiesEmptyLabel));
        OnPropertyChanged(nameof(ReplaySummary));
        OnPropertyChanged(nameof(ReplayContext));
        OnPropertyChanged(nameof(AlertEvidenceOverview));
        OnPropertyChanged(nameof(AlertRows));
        OnPropertyChanged(nameof(OutcomeRows));
        OnPropertyChanged(nameof(HasAlertRows));
        OnPropertyChanged(nameof(HasOutcomeRows));
        OnPropertyChanged(nameof(AlertRowsEmptyLabel));
        OnPropertyChanged(nameof(OutcomeRowsEmptyLabel));
        OnPropertyChanged(nameof(SavedWatchlistStateLabel));
        OnPropertyChanged(nameof(SavedWatchlistSourceLabel));
        OnPropertyChanged(nameof(SavedWatchlistCountLabel));
        OnPropertyChanged(nameof(SavedWatchlistAsOfLabel));
        OnPropertyChanged(nameof(SavedWatchlistSummary));
        OnPropertyChanged(nameof(SavedWatchlistWarnings));
        OnPropertyChanged(nameof(SavedWatchlistEmptyState));
        OnPropertyChanged(nameof(DailyWorkflow));
        OnPropertyChanged(nameof(CandidateStoryOverview));
        OnPropertyChanged(nameof(CandidateStoryRows));
        OnPropertyChanged(nameof(HasCandidateStoryPoints));
        OnPropertyChanged(nameof(CandidateStoryEmptyLabel));
    }

    private async Task RefreshSavedWatchlistAsync(CancellationToken cancellationToken)
    {
        if (_savedWatchlistWorkspaceClient is null)
        {
            return;
        }

        try
        {
            SavedWatchlist = await _savedWatchlistWorkspaceClient.GetSnapshotAsync(cancellationToken);
            SavedWatchlistItems.Clear();
            foreach (var item in SavedWatchlist.Items)
            {
                SavedWatchlistItems.Add(SavedWatchlistItemViewModel.From(item));
            }
        }
        catch (Exception exception) when (exception is IOException or InvalidDataException or InvalidOperationException or JsonException)
        {
            var now = DateTimeOffset.UtcNow;
            SavedWatchlist = new SavedWatchlistSnapshot(
                1,
                SavedWatchlistState.Unavailable,
                now,
                null,
                null,
                $"UNAVAILABLE | Saved-watchlist evidence could not be loaded: {exception.Message} No current candidate state was inferred.",
                "Unavailable saved-watchlist source",
                0,
                0,
                0,
                ["The Python saved-watchlist boundary did not return usable persisted evidence."],
                []);
            SavedWatchlistItems.Clear();
        }

        OnPropertyChanged(nameof(SavedWatchlistStateLabel));
        OnPropertyChanged(nameof(SavedWatchlistSourceLabel));
        OnPropertyChanged(nameof(SavedWatchlistCountLabel));
        OnPropertyChanged(nameof(SavedWatchlistAsOfLabel));
        OnPropertyChanged(nameof(SavedWatchlistSummary));
        OnPropertyChanged(nameof(SavedWatchlistWarnings));
        OnPropertyChanged(nameof(SavedWatchlistEmptyState));
    }

    private static string TextOrUnavailable(string? value, string unavailable) =>
        string.IsNullOrWhiteSpace(value) ? unavailable : value.Trim();

    private CandidateSnapshot? CandidateEvidence => TradePlan is null
        ? SelectedCandidate
        : Candidates.FirstOrDefault(candidate =>
            string.Equals(candidate.Symbol, TradePlan.Symbol, StringComparison.OrdinalIgnoreCase));

    private async Task RefreshSimulationWorkspaceDataAsync(CancellationToken cancellationToken)
    {
        IsReadOnlySnapshotMode = false;
        IsPythonSimulationWorkspaceMode = true;
        try
        {
            var snapshot = await _simulationWorkspaceClient!.GetSnapshotAsync(cancellationToken);
            _simulationWorkspaceSnapshot = snapshot;
            Candidates.Clear();
            foreach (var candidate in snapshot.Workspace.Candidates)
            {
                Candidates.Add(candidate);
            }

            Activity.Clear();
            foreach (var activity in snapshot.Workspace.Activity)
            {
                Activity.Add(activity);
            }

            Health = snapshot.Workspace.Health;
            AlertEvidence = snapshot.Workspace.AlertEvidence;
            ReplaySession = snapshot.Workspace.Replay;
            Candles.Clear();
            PrimaryChart = null;
            SecondaryCharts.Clear();
            var candidateToSelect = Candidates.FirstOrDefault(candidate => candidate.Symbol == SelectedSymbol) ?? Candidates.FirstOrDefault();
            if (candidateToSelect is not null)
            {
                SelectedCandidate = candidateToSelect;
                SelectedSymbol = candidateToSelect.Symbol;
                _linkGroups.PublishSymbol(LinkGroup.A, candidateToSelect.Symbol, SelectedInterval);
                ApplySimulationTradePlan(candidateToSelect.Symbol);
                await Task.WhenAll(
                    RefreshTechnicalResearchAsync(candidateToSelect.Symbol, cancellationToken),
                    RefreshCandidateStoryAsync(candidateToSelect.Symbol, cancellationToken));
            }
            else
            {
                TradePlan = null;
                TechnicalResearch = UnavailableTechnicalResearch(
                    SelectedSymbol,
                    "No selected candidate is available for technical research evidence.");
                CandidateStory = UnavailableCandidateStory(
                    SelectedSymbol,
                    "No selected candidate is available for Candidate Story evidence.");
            }

            StatusMessage = snapshot.Summary;
            OnPropertyChanged(nameof(ActivityLabel));
            RaisePresentationProperties();
        }
        catch (Exception exception) when (exception is IOException or InvalidDataException or InvalidOperationException or JsonException)
        {
            _simulationWorkspaceSnapshot = null;
            Candidates.Clear();
            Activity.Clear();
            var now = DateTimeOffset.UtcNow;
            var detail = $"Python simulation workspace unavailable: {exception.Message} Mock fallback is disabled.";
            Activity.Add(new ActivityEvent(now, "Engine", detail, string.Empty, HealthState.Unavailable));
            Health = new SystemHealthSnapshot(
                [new HealthComponentSnapshot("Python simulation workspace", HealthState.Unavailable, detail, now)],
                now);
            AlertEvidence = UnavailableAlertEvidence(now, detail);
            ReplaySession = new ReplaySnapshot("UNAVAILABLE", now, string.Empty, "source capture", "Replay context is unavailable because the Python simulation workspace could not be loaded.");
            TechnicalResearch = UnavailableTechnicalResearch(SelectedSymbol, detail);
            CandidateStory = UnavailableCandidateStory(SelectedSymbol, detail);
            TradePlan = null;
            Candles.Clear();
            PrimaryChart = null;
            SecondaryCharts.Clear();
            StatusMessage = detail;
            OnPropertyChanged(nameof(ActivityLabel));
            RaisePresentationProperties();
        }
    }

    private void ApplySimulationTradePlan(string symbol)
    {
        if (PrimaryTradePlanPane?.IsPinned == true)
        {
            return;
        }

        TradePlan = _simulationWorkspaceSnapshot?.TradePlans
            .FirstOrDefault(plan => string.Equals(plan.Symbol, symbol, StringComparison.OrdinalIgnoreCase));
    }

    private void ApplyShadowReviewTradePlan(ShadowTradeReviewSnapshot trade)
    {
        var entry = trade.Plan.ProposedEntry ?? 0m;
        var stop = trade.Plan.Stop ?? 0m;
        var target = trade.Plan.Targets.FirstOrDefault();
        var riskPerShare = entry > stop && stop > 0m ? entry - stop : 0m;
        var rewardToRisk = riskPerShare > 0m && target > entry
            ? (target - entry) / riskPerShare
            : 0m;
        var checks = new[]
        {
            new ReadinessCheck(
                "Evidence frozen",
                trade.EvidenceLock.EvidenceFrozen,
                trade.EvidenceLock.EvidenceFrozenLabel),
            new ReadinessCheck(
                "Plan frozen",
                trade.EvidenceLock.PlanFrozen,
                trade.EvidenceLock.PlanFrozenLabel),
            new ReadinessCheck(
                "Post-decision correction",
                !trade.EvidenceLock.PostDecisionCorrectionOccurred,
                trade.EvidenceLock.CorrectionLabel),
            new ReadinessCheck(
                "Evidence audit",
                string.Equals(trade.EvidenceLock.AuditStatus, "PASS", StringComparison.Ordinal),
                trade.EvidenceLock.ReasonDisplay),
        };
        var riskSummary = trade.Plan.RiskReasons.Count == 0
            ? "Frozen Risk Governor detail was unavailable."
            : string.Join(" | ", trade.Plan.RiskReasons);
        TradePlan = new TradePlanSnapshot(
            trade.Symbol,
            entry,
            stop,
            target,
            riskPerShare,
            0,
            rewardToRisk,
            trade.EvidenceEligible ? ReadinessState.ReadyForSimulation : ReadinessState.Blocked,
            checks,
            "Review only",
            new DataLineage(
                $"Frozen Shadow evidence {trade.ShadowTradeId}",
                trade.Identity.EvidenceSnapshotTimestamp,
                "This plan is the immutable decision-time Shadow snapshot, not the latest planning workspace."),
            [
                new TradeLevel("Entry", entry, "Frozen Shadow Trade proposed entry."),
                new TradeLevel("Stop", stop, "Frozen Shadow Trade stop."),
                .. trade.Plan.Targets.Select((value, index) =>
                    new TradeLevel($"Target {index + 1}", value, "Frozen Shadow Trade target.")),
            ],
            new RiskDecision(
                false,
                trade.Plan.RiskDecision,
                $"{riskSummary} Test Trade Review is read-only.",
                trade.Plan.RiskReasons));
    }

    private async Task RefreshShadowReviewAsync(CancellationToken cancellationToken)
    {
        if (_shadowReviewClient is null)
        {
            return;
        }

        try
        {
            _shadowReviewSnapshot = await _shadowReviewClient.GetSnapshotAsync(cancellationToken);
            var selectedTradeId = SelectedShadowTrade?.ShadowTradeId;
            ShadowSample = _shadowReviewSnapshot.Sample;
            ShadowMetrics = _shadowReviewSnapshot.Metrics;
            ShadowReviewStatus = _shadowReviewSnapshot.Summary;
            UpdateShadowFilterOptions(_shadowReviewSnapshot.Trades);
            ApplyShadowFilters();
            ActiveShadowTrade = _shadowReviewSnapshot.Trades.FirstOrDefault(
                trade => IsCurrentOfficialShadowTrade(trade)
                    && trade.ActiveMark.DisplayState is
                    "WORKING" or "AHEAD" or "BEHIND" or "FLAT"
                    or "STALE" or "HALTED" or "EXIT_PENDING");
            RefreshOpenPositions();
            if (Workspace == WorkspaceKind.Review)
            {
                SelectedShadowTrade = (
                    selectedTradeId is not null
                        ? ShadowTrades.FirstOrDefault(
                            trade => trade.ShadowTradeId == selectedTradeId)
                        : null
                ) ?? ShadowTrades.FirstOrDefault();
            }
            if (Workspace == WorkspaceKind.Review
                && SelectedShadowTrade is null
                && ShadowTrades.FirstOrDefault() is { } first)
            {
                SelectedShadowTrade = first;
            }
        }
        catch (Exception exception) when (exception is IOException or InvalidDataException or InvalidOperationException or JsonException)
        {
            _shadowReviewSnapshot = null;
            ShadowTrades.Clear();
            ShadowOfficialTrades.Clear();
            ShadowUnfilledBlockedTrades.Clear();
            SelectedShadowTrade = null;
            ActiveShadowTrade = null;
            OpenPositions.Clear();
            ShadowSample = new ShadowSampleStatus(
                30, 0, 0, 0, 0, 0, 0, 0, false,
                "Evidence collection is unavailable. No sample records were counted.",
                new ShadowSampleDefinition(
                    "engineering-preflight-v1",
                    new string('0', 64),
                    "prospective-fakebroker-live-mark-v2",
                    1,
                    false),
                "BLOCKED",
                false,
                ["Shadow evidence snapshot is unavailable."]);
            ShadowMetrics = new ShadowAggregateMetrics(
                "UNAVAILABLE", null, null, null, null, null, null, null, null, null, null,
                "Aggregate metrics are unavailable because the Shadow evidence snapshot failed closed.");
            ShadowReviewStatus = $"Shadow review unavailable: {exception.Message} No fallback evidence was created.";
        }
    }

    public async Task RefreshShadowReviewDisplayAsync(
        CancellationToken cancellationToken = default)
    {
        if (Workspace != WorkspaceKind.Review
            && PositionsPane?.IsVisible != true)
        {
            return;
        }

        if (_shadowReviewClient is null
            || !await _shadowRefreshLock.WaitAsync(0, cancellationToken))
        {
            return;
        }
        try
        {
            await RefreshShadowReviewAsync(cancellationToken);
        }
        finally
        {
            _shadowRefreshLock.Release();
        }
    }

    private void RefreshOpenPositions()
    {
        OpenPositions.Clear();
        if (_shadowReviewSnapshot is null)
        {
            return;
        }

        foreach (var position in _shadowReviewSnapshot.Trades
                     .Select(OpenPositionView.From)
                     .OfType<OpenPositionView>()
                     .OrderByDescending(position => position.UnrealizedPnl ?? decimal.MinValue)
                     .ThenBy(position => position.Symbol, StringComparer.Ordinal))
        {
            OpenPositions.Add(position);
        }

        RaiseOpenPositionProperties();
    }

    private void RaiseOpenPositionProperties()
    {
        OnPropertyChanged(nameof(HasOpenPositions));
        OnPropertyChanged(nameof(PositionsButtonLabel));
        OnPropertyChanged(nameof(PositionsButtonToolTip));
        OnPropertyChanged(nameof(OpenPositionCountDisplay));
        OnPropertyChanged(nameof(OpenPositionPnlDisplay));
        OnPropertyChanged(nameof(OpenPositionMarketValueDisplay));
        OnPropertyChanged(nameof(OpenPositionAttentionCount));
        OnPropertyChanged(nameof(OpenPositionQuoteHealthDisplay));
        OnPropertyChanged(nameof(PositionsModeLabel));
        OnPropertyChanged(nameof(PositionsSummary));
        OnPropertyChanged(nameof(PositionsSourceDetail));
    }

    private void UpdateShadowFilterOptions(IReadOnlyList<ShadowTradeReviewSnapshot> trades)
    {
        ShadowDateSessionOptions = Options(trades.Select(trade => trade.DateSessionLabel));
        ShadowSetupOptions = Options(trades.Select(trade => trade.Setup));
        ShadowCatalystOptions = Options(trades.Select(trade => trade.Catalyst));
        ShadowRegimeOptions = Options(trades.Select(trade => trade.MarketRegime));
        ShadowOutcomeOptions = Options(trades.Select(trade => trade.OutcomeLabel));
    }

    private static IReadOnlyList<string> Options(IEnumerable<string> values) =>
        new[] { "All" }
            .Concat(values.Where(value => !string.IsNullOrWhiteSpace(value)).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal))
            .ToArray();

    private void ApplyShadowFilters()
    {
        if (_shadowReviewSnapshot is null)
        {
            ShadowTrades.Clear();
            ShadowOfficialTrades.Clear();
            ShadowUnfilledBlockedTrades.Clear();
            return;
        }

        var filtered = _shadowReviewSnapshot.Trades.Where(trade =>
            Matches(ShadowDateSessionFilter, trade.DateSessionLabel)
            && Matches(ShadowSetupFilter, trade.Setup)
            && Matches(ShadowCatalystFilter, trade.Catalyst)
            && Matches(ShadowRegimeFilter, trade.MarketRegime)
            && Matches(ShadowOutcomeFilter, trade.OutcomeLabel)
            && Matches(ShadowEligibilityFilter, trade.EligibilityLabel));
        ShadowTrades.Clear();
        foreach (var trade in filtered)
        {
            ShadowTrades.Add(trade);
        }
        ShadowOfficialTrades.Clear();
        foreach (var trade in filtered.Where(trade =>
                     IsCurrentOfficialShadowTrade(trade)
                     && trade.ActiveMark.DisplayState is
                         "AHEAD" or "BEHIND" or "FLAT" or "STALE"
                         or "HALTED" or "EXIT_PENDING" or "WINNER"
                         or "LOSER" or "FLAT_EXIT"))
        {
            ShadowOfficialTrades.Add(trade);
        }
        ShadowUnfilledBlockedTrades.Clear();
        foreach (var trade in filtered.Where(trade =>
                     IsCurrentOfficialShadowTrade(trade)
                     && trade.ActiveMark.DisplayState is
                         "WORKING" or "UNFILLED" or "CANCELLED"
                         or "INVALIDATED"))
        {
            ShadowUnfilledBlockedTrades.Add(trade);
        }
    }

    private bool IsCurrentOfficialShadowTrade(
        ShadowTradeReviewSnapshot trade) =>
        trade.SampleDefinition.OfficialSampleAuthorized
        && string.Equals(
            trade.SampleDefinition.SampleVersion,
            ShadowSample.Definition.SampleVersion,
            StringComparison.Ordinal);

    private static bool Matches(string filter, string value) =>
        string.Equals(filter, "All", StringComparison.Ordinal)
        || string.Equals(filter, value, StringComparison.Ordinal);

    partial void OnShadowDateSessionFilterChanged(string value) => ApplyShadowFilters();
    partial void OnShadowSetupFilterChanged(string value) => ApplyShadowFilters();
    partial void OnShadowCatalystFilterChanged(string value) => ApplyShadowFilters();
    partial void OnShadowRegimeFilterChanged(string value) => ApplyShadowFilters();
    partial void OnShadowOutcomeFilterChanged(string value) => ApplyShadowFilters();
    partial void OnShadowEligibilityFilterChanged(string value) => ApplyShadowFilters();

    private async Task RefreshReadOnlyWorkspaceDataAsync(CancellationToken cancellationToken)
    {
        IsReadOnlySnapshotMode = true;
        IsPythonSimulationWorkspaceMode = false;
        try
        {
            var snapshot = await _readOnlyWorkspaceClient!.GetSnapshotAsync(cancellationToken);
            Candidates.Clear();
            foreach (var candidate in snapshot.Candidates)
            {
                Candidates.Add(candidate);
            }

            Activity.Clear();
            foreach (var activity in snapshot.Activity)
            {
                Activity.Add(activity);
            }

            Health = snapshot.Health;
            AlertEvidence = snapshot.AlertEvidence;
            ReplaySession = snapshot.Replay;
            StatusMessage = snapshot.Summary;
            OnPropertyChanged(nameof(ActivityLabel));
            var candidateToSelect = Candidates.FirstOrDefault(candidate => candidate.Symbol == SelectedSymbol) ?? Candidates.FirstOrDefault();
            if (candidateToSelect is not null)
            {
                await SelectCandidateAsync(candidateToSelect, cancellationToken);
            }
            else
            {
                TradePlan = null;
                Candles.Clear();
                PrimaryChart = null;
                SecondaryCharts.Clear();
                TechnicalResearch = UnavailableTechnicalResearch(
                    SelectedSymbol,
                    "No selected candidate is available for technical research evidence.");
                CandidateStory = UnavailableCandidateStory(
                    SelectedSymbol,
                    "No selected candidate is available for Candidate Story evidence.");
                RaisePresentationProperties();
            }
        }
        catch (Exception exception) when (exception is IOException or InvalidDataException or InvalidOperationException or JsonException)
        {
            Candidates.Clear();
            Activity.Clear();
            var now = DateTimeOffset.UtcNow;
            var detail = $"Python read-only snapshot unavailable: {exception.Message} Mock fallback is disabled.";
            Activity.Add(new ActivityEvent(now, "Engine", detail, string.Empty, HealthState.Unavailable));
            Health = new SystemHealthSnapshot(
                [new HealthComponentSnapshot("Python read-only workspace", HealthState.Unavailable, detail, now)],
                now);
            AlertEvidence = UnavailableAlertEvidence(now, detail);
            ReplaySession = new ReplaySnapshot("UNAVAILABLE", now, string.Empty, "source capture", "Replay context is unavailable because the Python snapshot could not be loaded.");
            TechnicalResearch = UnavailableTechnicalResearch(SelectedSymbol, detail);
            CandidateStory = UnavailableCandidateStory(SelectedSymbol, detail);
            TradePlan = null;
            Candles.Clear();
            PrimaryChart = null;
            SecondaryCharts.Clear();
            StatusMessage = detail;
            OnPropertyChanged(nameof(ActivityLabel));
            RaisePresentationProperties();
        }
    }

    partial void OnAlertEvidenceChanged(AlertEvidenceSnapshot? value)
    {
        OnPropertyChanged(nameof(AlertEvidenceOverview));
        OnPropertyChanged(nameof(AlertRows));
        OnPropertyChanged(nameof(OutcomeRows));
        OnPropertyChanged(nameof(HasAlertRows));
        OnPropertyChanged(nameof(HasOutcomeRows));
        OnPropertyChanged(nameof(AlertRowsEmptyLabel));
        OnPropertyChanged(nameof(OutcomeRowsEmptyLabel));
    }

    private static AlertEvidenceSnapshot UnavailableAlertEvidence(DateTimeOffset observedAt, string summary) => new(
        AlertEvidenceState.Unavailable,
        observedAt,
        summary,
        0,
        0,
        0,
        0,
        [],
        []);

    partial void OnTechnicalResearchChanged(TechnicalResearchSnapshot? value)
    {
        OnPropertyChanged(nameof(TechnicalResearchOverview));
        OnPropertyChanged(nameof(TechnicalResearchEventRows));
        OnPropertyChanged(nameof(TechnicalResearchStudyRows));
        OnPropertyChanged(nameof(HasTechnicalResearchEvents));
        OnPropertyChanged(nameof(HasTechnicalResearchStudies));
        OnPropertyChanged(nameof(TechnicalResearchEventsEmptyLabel));
        OnPropertyChanged(nameof(TechnicalResearchStudiesEmptyLabel));
        RefreshWhatChangedRows();
    }

    private async Task RefreshTechnicalResearchAsync(
        string symbol,
        CancellationToken cancellationToken)
    {
        var requestedSymbol = symbol.Trim().ToUpperInvariant();
        if (_technicalResearchWorkspaceClient is null)
        {
            TechnicalResearch = UnavailableTechnicalResearch(
                requestedSymbol,
                "The technical research boundary is not configured in this workspace.");
            return;
        }

        try
        {
            var snapshot = await _technicalResearchWorkspaceClient.GetSnapshotAsync(
                requestedSymbol,
                cancellationToken);
            if (string.Equals(SelectedSymbol, requestedSymbol, StringComparison.OrdinalIgnoreCase))
            {
                TechnicalResearch = snapshot;
            }
        }
        catch (Exception exception) when (
            exception is IOException or InvalidDataException or InvalidOperationException or JsonException)
        {
            if (string.Equals(SelectedSymbol, requestedSymbol, StringComparison.OrdinalIgnoreCase))
            {
                TechnicalResearch = UnavailableTechnicalResearch(
                    requestedSymbol,
                    $"Stored technical research evidence could not be loaded: {exception.Message}");
            }
        }
    }

    private async Task RefreshCandidateStoryAsync(
        string symbol,
        CancellationToken cancellationToken)
    {
        var requestedSymbol = symbol.Trim().ToUpperInvariant();
        var requestVersion = Interlocked.Increment(ref _candidateStoryRequestVersion);
        if (string.Equals(SelectedSymbol, requestedSymbol, StringComparison.OrdinalIgnoreCase))
        {
            CandidateStory = UnavailableCandidateStory(
                requestedSymbol,
                "Loading persisted Candidate Story evidence.");
        }
        if (_candidateStoryWorkspaceClient is null)
        {
            if (requestVersion == Volatile.Read(ref _candidateStoryRequestVersion)
                && string.Equals(SelectedSymbol, requestedSymbol, StringComparison.OrdinalIgnoreCase))
            {
                CandidateStory = UnavailableCandidateStory(
                    requestedSymbol,
                    "The Candidate Story boundary is not configured in this workspace.");
            }
            return;
        }

        try
        {
            var snapshot = await _candidateStoryWorkspaceClient.GetSnapshotAsync(
                requestedSymbol,
                cancellationToken);
            if (requestVersion == Volatile.Read(ref _candidateStoryRequestVersion)
                && string.Equals(SelectedSymbol, requestedSymbol, StringComparison.OrdinalIgnoreCase))
            {
                CandidateStory = snapshot;
            }
        }
        catch (Exception exception) when (
            exception is ArgumentException
                or IOException
                or InvalidDataException
                or InvalidOperationException
                or JsonException)
        {
            if (requestVersion == Volatile.Read(ref _candidateStoryRequestVersion)
                && string.Equals(SelectedSymbol, requestedSymbol, StringComparison.OrdinalIgnoreCase))
            {
                CandidateStory = UnavailableCandidateStory(
                    requestedSymbol,
                    $"Persisted Candidate Story evidence could not be loaded: {exception.Message}");
            }
        }
    }

    private static TechnicalResearchSnapshot UnavailableTechnicalResearch(string symbol, string summary) => new(
        1,
        string.IsNullOrWhiteSpace(symbol) ? "UNAVAILABLE" : symbol.Trim().ToUpperInvariant(),
        TechnicalResearchState.Unavailable,
        DateTimeOffset.UtcNow,
        null,
        summary,
        "Technical research source unavailable",
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        [],
        [],
        []);

    private static CandidateStorySnapshot UnavailableCandidateStory(string symbol, string summary) => new(
        1,
        string.IsNullOrWhiteSpace(symbol) ? "UNAVAILABLE" : symbol.Trim().ToUpperInvariant(),
        CandidateStoryEvidenceState.Unavailable,
        DateTimeOffset.UtcNow,
        null,
        "Candidate Story source unavailable",
        $"UNAVAILABLE | {summary}",
        string.Empty,
        string.Empty,
        string.Empty,
        "Insufficient data",
        "Trusted persisted capture evidence is unavailable.",
        "No trusted captures found",
        "No trusted captures found",
        "n/a",
        null,
        null,
        null,
        null,
        null,
        null,
        0,
        0,
        0,
        [],
        [summary],
        true);
}
