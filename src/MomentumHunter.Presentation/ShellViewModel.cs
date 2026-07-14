using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
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
    private readonly IWorkspaceLayoutStore? _layoutStore;
    private readonly LayoutAutosaveCoordinator? _layoutAutosave;
    private LinkGroupCoordinator _linkGroups = null!;
    private string? _dockLayoutXml;
    private RectGeometry? _windowBounds;
    private WindowDisplayState _windowState;

    public ShellViewModel(IEngineClient engineClient)
        : this(engineClient, layoutStore: null, isInternalConstruction: true)
    {
    }

    public ShellViewModel(IEngineClient engineClient, IWorkspaceLayoutStore layoutStore)
        : this(engineClient, layoutStore, isInternalConstruction: true)
    {
    }

    private ShellViewModel(IEngineClient engineClient, IWorkspaceLayoutStore? layoutStore, bool isInternalConstruction)
    {
        _engineClient = engineClient;
        _layoutStore = layoutStore;
        SetRegistry(WorkspaceFactory.Create(WorkspaceKind.Live));
        if (_layoutStore is not null)
        {
            _layoutAutosave = new LayoutAutosaveCoordinator(_layoutStore, CreateAutomaticLayoutSnapshot);
        }

        Candidates = [];
        Activity = [];
        Candles = [];
        WorkspaceOptions = Enum.GetValues<WorkspaceKind>();
        IntervalOptions = ["1m", "5m", "15m", "Daily"];
    }

    public PaneRegistry Registry { get; private set; } = null!;

    public ObservableCollection<CandidateSnapshot> Candidates { get; }

    public ObservableCollection<ActivityEvent> Activity { get; }

    public ObservableCollection<CandleSnapshot> Candles { get; }

    public ObservableCollection<ChartPaneViewModel> SecondaryCharts { get; } = [];

    public IReadOnlyList<WorkspaceKind> WorkspaceOptions { get; }

    public IReadOnlyList<string> IntervalOptions { get; }

    [ObservableProperty]
    private WorkspaceKind _workspace = WorkspaceKind.Live;

    [ObservableProperty]
    private CandidateSnapshot? _selectedCandidate;

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
    private SimulationResult? _lastSimulationResult;

    [ObservableProperty]
    private ChartPaneViewModel? _primaryChart;

    [ObservableProperty]
    private bool _isHealthOpen;

    [ObservableProperty]
    private bool _isActivityOpen;

    [ObservableProperty]
    private bool _isDiagnosticsOpen;

    [ObservableProperty]
    private bool _isCommandPaletteOpen;

    [ObservableProperty]
    private string _statusMessage = "Mock engine | Local deterministic data | No provider calls";

    public EnvironmentMode Environment => Workspace switch
    {
        WorkspaceKind.Live => EnvironmentMode.Simulation,
        WorkspaceKind.Replay => EnvironmentMode.Replay,
        _ => EnvironmentMode.Review,
    };

    public string WorkspaceTitle => Workspace switch
    {
        WorkspaceKind.Live => "Live Hunter",
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

    public string PrimaryChartLinkLabel => PrimaryChartPane?.IsPinned == true
        ? "Pinned"
        : $"Link {PrimaryChartPane?.LinkGroup ?? LinkGroup.Unlinked}";

    public string PrimaryTradePlanLinkLabel => PrimaryTradePlanPane?.IsPinned == true
        ? "Pinned"
        : $"Link {PrimaryTradePlanPane?.LinkGroup ?? LinkGroup.Unlinked}";

    public string EnvironmentLabel => Environment switch
    {
        EnvironmentMode.Simulation => "SIMULATION \u2022 FakeBroker",
        EnvironmentMode.Replay => "REPLAY \u2022 Read Only",
        _ => "REVIEW \u2022 Read Only",
    };

    public string ActivityLabel => Activity.Count == 0 ? "Activity" : $"Activity {Activity.Count}";

    public bool CanRunSimulation => TradePlan?.RiskDecision?.Allowed == true && Environment == EnvironmentMode.Simulation;

    public RectGeometry? RestoredWindowBounds => _windowBounds;

    public string? RestoredDockLayoutXml => _dockLayoutXml;

    public WindowDisplayState RestoredWindowState => _windowState;

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

        await RefreshWorkspaceDataAsync(cancellationToken);
        await RefreshChartPaneDataAsync(cancellationToken);
    }

    public async Task SelectCandidateAsync(CandidateSnapshot candidate, CancellationToken cancellationToken = default)
    {
        SelectedCandidate = candidate;
        SelectedSymbol = candidate.Symbol;
        var plan = await _engineClient.GetTradePlanAsync(candidate.Symbol, cancellationToken);
        await RefreshCandlesAsync(cancellationToken);
        _linkGroups.PublishSymbol(LinkGroup.A, candidate.Symbol, SelectedInterval);
        if (PrimaryTradePlanPane?.IsPinned != true)
        {
            TradePlan = plan;
        }

        await RefreshChartPaneDataAsync(cancellationToken);
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
        await RefreshCandlesAsync(cancellationToken);
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
    private void ToggleCommandPalette() => IsCommandPaletteOpen = !IsCommandPaletteOpen;

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
        if (!PrimaryTradePlanPane.IsPinned)
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

    public async Task RunPrimaryActionAsync(CancellationToken cancellationToken = default)
    {
        if (TradePlan is null)
        {
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

    private WorkspaceLayoutSnapshot CreateAutomaticLayoutSnapshot() => CreateLayoutSnapshot(isNamedLayout: false, name: null);

    private WorkspaceLayoutSnapshot CreateLayoutSnapshot(bool isNamedLayout, string? name) => new(
        SchemaVersion: 4,
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
        MigrateLegacyContextualPanes(snapshot.SchemaVersion);
        _dockLayoutXml = snapshot.DockLayoutXml;
        _windowBounds = snapshot.WindowBounds;
        _windowState = snapshot.WindowState;
        IsActivityOpen = snapshot.ActivityExpanded;
        IsDiagnosticsOpen = Registry.Panes.FirstOrDefault(pane => pane.Kind == PaneKind.Diagnostics)?.IsVisible == true;
        PrimaryChart = null;
        RaisePresentationProperties();
    }

    private void MigrateLegacyContextualPanes(int schemaVersion)
    {
        if (schemaVersion >= 4 || Workspace != WorkspaceKind.Live)
        {
            return;
        }

        foreach (var (kind, title) in new[]
        {
            (PaneKind.Automation, "Automation"),
            (PaneKind.Orders, "Orders"),
            (PaneKind.Positions, "Positions"),
        })
        {
            if (Registry.Panes.Any(pane => pane.Kind == kind))
            {
                continue;
            }

            Registry.Create(kind, title, LinkGroup.Unlinked, DockRegion.Bottom, SelectedSymbol, SelectedInterval).IsVisible = false;
        }
    }

    private async Task RefreshWorkspaceDataAsync(CancellationToken cancellationToken)
    {
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

    private async Task RefreshCandlesAsync(CancellationToken cancellationToken)
    {
        Candles.Clear();
        foreach (var candle in await _engineClient.GetCandlesAsync(SelectedSymbol, SelectedInterval, cancellationToken))
        {
            Candles.Add(candle);
        }
    }

    private async Task RefreshChartPaneDataAsync(CancellationToken cancellationToken = default)
    {
        var primaryPane = PrimaryChartPane;
        if (primaryPane is null)
        {
            PrimaryChart = null;
            SecondaryCharts.Clear();
            return;
        }

        var primaryCandles = await _engineClient.GetCandlesAsync(primaryPane.Symbol, primaryPane.Interval, cancellationToken);
        if (PrimaryChart is null || PrimaryChart.Pane.InstanceId != primaryPane.InstanceId)
        {
            PrimaryChart = new ChartPaneViewModel(primaryPane, primaryCandles);
        }
        else
        {
            PrimaryChart.ReplaceCandles(primaryCandles);
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
            var candles = await _engineClient.GetCandlesAsync(pane.Symbol, pane.Interval, cancellationToken);
            var chart = SecondaryCharts.FirstOrDefault(item => item.Pane.InstanceId == pane.InstanceId);
            if (chart is null)
            {
                SecondaryCharts.Add(new ChartPaneViewModel(pane, candles));
            }
            else
            {
                chart.ReplaceCandles(candles);
            }
        }
    }

    private void RaisePresentationProperties()
    {
        OnPropertyChanged(nameof(Registry));
        OnPropertyChanged(nameof(Environment));
        OnPropertyChanged(nameof(EnvironmentLabel));
        OnPropertyChanged(nameof(ActivityLabel));
        OnPropertyChanged(nameof(WorkspaceTitle));
        OnPropertyChanged(nameof(WorkspaceNarrative));
        OnPropertyChanged(nameof(PrimaryChartPane));
        OnPropertyChanged(nameof(PrimaryChartLinkLabel));
        OnPropertyChanged(nameof(PrimaryTradePlanPane));
        OnPropertyChanged(nameof(PrimaryTradePlanLinkLabel));
        OnPropertyChanged(nameof(CanRunSimulation));
    }
}
