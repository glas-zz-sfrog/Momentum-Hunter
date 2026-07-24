using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class SimulationWorkspaceShellTests
{
    [Fact]
    public async Task PythonSimulationWorkspaceUsesPersistedPlanAndDoesNotCallMockEngine()
    {
        var client = new StaticSimulationWorkspaceClient(Snapshot(allowed: true));
        var chartClient = new RecordingChartWorkspaceClient(ChartDataState.Stale);
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client, chartClient);

        await viewModel.InitializeAsync();

        Assert.True(viewModel.IsPythonSimulationWorkspaceMode);
        Assert.False(viewModel.IsReadOnlySnapshotMode);
        Assert.NotNull(viewModel.TradePlan);
        Assert.NotNull(viewModel.PrimaryChart);
        Assert.Equal(2, viewModel.PrimaryChart!.Candles.Count);
        Assert.Equal(ChartDataState.Stale, viewModel.PrimaryChart.DataState);
        Assert.Equal(DateTimeOffset.Parse("2026-06-18T20:00:00Z"), viewModel.PrimaryChart.LatestBar!.Timestamp);
        Assert.Contains("O 119.10", viewModel.PrimaryChart.LatestBarSummary, StringComparison.Ordinal);
        Assert.Contains("V 1,500", viewModel.PrimaryChart.LatestBarSummary, StringComparison.Ordinal);
        Assert.True(viewModel.CanRunSimulation);
        Assert.Contains("Python FakeBroker Only", viewModel.EnvironmentLabel, StringComparison.Ordinal);
        Assert.Equal("NVDA", viewModel.TradePlanSymbolLabel);
        Assert.Equal("Simulation-only", viewModel.TradePlanRiskStatusLabel);
        Assert.Contains("read-only evidence", viewModel.PlanningStatus, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("STALE", viewModel.ChartSourceLabel, StringComparison.Ordinal);
        Assert.Equal([("NVDA", "5m")], chartClient.Requests);

        await viewModel.RunPrimaryActionAsync();

        Assert.Equal(["NVDA"], client.RunSymbols);
        Assert.NotNull(viewModel.LastSimulationResult);
        Assert.Equal(SimulationResultState.Completed, viewModel.LastSimulationResult!.State);
        Assert.Contains("simulated order", viewModel.StatusMessage, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task PythonChartRefreshUsesSelectedSymbolIntervalAndLinkedPaneContext()
    {
        var client = new StaticSimulationWorkspaceClient(Snapshot(allowed: true));
        var chartClient = new RecordingChartWorkspaceClient(ChartDataState.Available);
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client, chartClient);
        await viewModel.InitializeAsync();
        chartClient.Requests.Clear();

        await viewModel.ChangeIntervalAsync("Daily");
        var linkedPane = await viewModel.AddLinkedChartAsync();
        var selected = viewModel.Candidates[0] with { Symbol = "EQX", Company = "Equinox Gold" };
        await viewModel.SelectCandidateAsync(selected);

        Assert.Contains(("NVDA", "Daily"), chartClient.Requests);
        Assert.Equal("Daily", linkedPane.Interval);
        Assert.Contains(("EQX", "Daily"), chartClient.Requests);
        Assert.Equal("EQX", viewModel.PrimaryChart!.Pane.Symbol);
        Assert.Equal("Daily", viewModel.PrimaryChart.Pane.Interval);
        Assert.All(viewModel.SecondaryCharts, chart => Assert.Equal("NVDA", chart.Pane.Symbol));
        Assert.All(viewModel.SecondaryCharts, chart => Assert.Equal("Daily", chart.Pane.Interval));
        Assert.Contains(("NVDA", "Daily"), chartClient.Requests);
    }

    [Fact]
    public async Task PinnedPrimaryChartRetainsItsSymbolWhenCandidateSelectionChanges()
    {
        var client = new StaticSimulationWorkspaceClient(Snapshot(allowed: true));
        var chartClient = new RecordingChartWorkspaceClient(ChartDataState.Available);
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client, chartClient);
        await viewModel.InitializeAsync();
        chartClient.Requests.Clear();

        await viewModel.TogglePrimaryChartPinCommand.ExecuteAsync(null);
        await viewModel.ChangeIntervalAsync("Daily");
        var selected = viewModel.Candidates[0] with { Symbol = "EQX", Company = "Equinox Gold" };
        await viewModel.SelectCandidateAsync(selected);

        Assert.True(viewModel.PrimaryChart!.Pane.IsPinned);
        Assert.Equal("NVDA", viewModel.PrimaryChart.Pane.Symbol);
        Assert.Equal("5m", viewModel.PrimaryChart.Pane.Interval);
        Assert.Equal("Pinned", viewModel.PrimaryChartLinkLabel);
        Assert.Contains(("NVDA", "5m"), chartClient.Requests);
        Assert.All(chartClient.Requests, request => Assert.Equal(("NVDA", "5m"), request));
    }

    [Fact]
    public async Task MissingStoredChartDataIsExplicitAndNeverUsesMockCandles()
    {
        var client = new StaticSimulationWorkspaceClient(Snapshot(allowed: true));
        var chartClient = new RecordingChartWorkspaceClient(ChartDataState.Unavailable);
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client, chartClient);

        await viewModel.InitializeAsync();

        Assert.NotNull(viewModel.PrimaryChart);
        Assert.Empty(viewModel.PrimaryChart!.Candles);
        Assert.Equal("No stored candles available", viewModel.PrimaryChart.EmptyStateText);
        Assert.Equal("Latest bar unavailable", viewModel.PrimaryChart.LatestBarSummary);
        Assert.Contains("UNAVAILABLE", viewModel.ChartSourceLabel, StringComparison.Ordinal);
        Assert.Contains("No simulated fallback", viewModel.ChartSourceLabel, StringComparison.Ordinal);
    }

    [Fact]
    public async Task BlockedPythonPlanDoesNotCallSimulationOrMutateEvidence()
    {
        var client = new StaticSimulationWorkspaceClient(Snapshot(allowed: false));
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client);

        await viewModel.InitializeAsync();
        await viewModel.RunPrimaryActionAsync();

        Assert.Empty(client.RunSymbols);
        Assert.Null(viewModel.LastSimulationResult);
        Assert.Equal("Unavailable", viewModel.TradePlan!.StopDisplay);
        Assert.Contains("Risk Governor", viewModel.StatusMessage, StringComparison.Ordinal);
        Assert.Contains("no evidence was changed", viewModel.StatusMessage, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task MissingPersistedPlanUsesExplicitUnavailableLabelsAndCannotRunSimulation()
    {
        var client = new StaticSimulationWorkspaceClient(Snapshot(allowed: false, includePlan: false));
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client);

        await viewModel.InitializeAsync();
        await viewModel.RunPrimaryActionAsync();

        Assert.Null(viewModel.TradePlan);
        Assert.False(viewModel.CanRunSimulation);
        Assert.False(viewModel.CanRunPrimaryAction);
        Assert.Equal("NVDA", viewModel.TradePlanSymbolLabel);
        Assert.Equal("Plan unavailable", viewModel.TradePlanRiskStatusLabel);
        Assert.Contains("No persisted TradePlan is available for NVDA", viewModel.PlanningStatus, StringComparison.Ordinal);
        Assert.Contains("Simulation is unavailable", viewModel.PlanningStatus, StringComparison.Ordinal);
        Assert.Empty(client.RunSymbols);
    }

    private static SimulationWorkspaceSnapshot Snapshot(bool allowed, bool includePlan = true)
    {
        var observedAt = DateTimeOffset.Parse("2026-07-17T15:00:00Z");
        var lineage = new DataLineage("Persisted trade-planning report", observedAt, "No score or readiness recalculation occurred.");
        var candidate = new CandidateSnapshot(
            "NVDA",
            "NVIDIA Corporation",
            176.42m,
            3.18m,
            84700112,
            2.4m,
            "Stored catalyst",
            ReadinessState.ReadyForSimulation,
            "Persisted report",
            observedAt,
            97,
            "RVOL 2.40x",
            new CatalystSummary("Stored catalyst", "Persisted trade-planning report", observedAt),
            lineage,
            "EXECUTION_READY_TRADE");
        var risk = new RiskDecision(
            allowed,
            allowed ? "Simulation-only" : "Blocked",
            allowed ? "Risk Governor permits FakeBroker simulation only." : "A hard stop is required before simulation.",
            allowed ? ["Plan can be simulated only."] : ["A hard stop is required before simulation."]);
        var plan = new TradePlanSnapshot(
            "NVDA",
            176.42m,
            allowed ? 171.42m : 0m,
            186.42m,
            5m,
            2,
            2m,
            ReadinessState.ReadyForSimulation,
            [new ReadinessCheck("Stop defined", allowed, risk.Summary)],
            allowed ? "Run FakeBroker simulation" : "Risk review required",
            lineage,
            [new TradeLevel("Entry", 176.42m, "Persisted TradePlan entry.")],
            risk);
        var workspace = new ReadOnlyWorkspaceSnapshot(
            2,
            observedAt,
            "Persisted evidence loaded.",
            [candidate],
            [new ActivityEvent(observedAt, "Research", "Persisted report loaded.", "NVDA", HealthState.Healthy)],
            new SystemHealthSnapshot([new HealthComponentSnapshot("Trade planning report", HealthState.Healthy, "Loaded", observedAt)], observedAt),
            new AlertEvidenceSnapshot(
                AlertEvidenceState.Empty,
                observedAt,
                "The persisted alert store is readable but empty.",
                0,
                0,
                0,
                0,
                [],
                []),
            new ReplaySnapshot("NOT_SELECTED", observedAt, string.Empty, "source capture", "No replay identity was synthesized."),
            true);
        return new SimulationWorkspaceSnapshot(
            1,
            observedAt,
            "Python simulation workspace uses FakeBroker only.",
            workspace,
            includePlan ? [plan] : [],
            includePlan);
    }

    private sealed class StaticSimulationWorkspaceClient : ISimulationWorkspaceClient
    {
        private readonly SimulationWorkspaceSnapshot _snapshot;

        public StaticSimulationWorkspaceClient(SimulationWorkspaceSnapshot snapshot)
        {
            _snapshot = snapshot;
        }

        public List<string> RunSymbols { get; } = [];

        public Task<SimulationWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(_snapshot);

        public Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default)
        {
            RunSymbols.Add(symbol);
            var plan = _snapshot.TradePlans.Single();
            return Task.FromResult(new SimulationResult(
                SimulationResultState.Completed,
                symbol,
                $"{symbol} simulated order filled through FakeBroker only.",
                plan.RiskDecision!,
                new ExecutionAuditSnapshot("audit-nvda", EnvironmentMode.Simulation, "PASS", "Simulation audit passed.", DateTimeOffset.UtcNow)));
        }
    }

    private sealed class RecordingChartWorkspaceClient : IChartWorkspaceClient
    {
        private readonly ChartDataState _state;

        public RecordingChartWorkspaceClient(ChartDataState state)
        {
            _state = state;
        }

        public List<(string Symbol, string Interval)> Requests { get; } = [];

        public Task<ChartSnapshot> GetSnapshotAsync(
            string symbol,
            string interval,
            CancellationToken cancellationToken = default)
        {
            Requests.Add((symbol, interval));
            var at = DateTimeOffset.Parse("2026-06-18T20:00:00Z");
            var candles = _state == ChartDataState.Unavailable
                ? Array.Empty<CandleSnapshot>()
                : [
                    new CandleSnapshot(at.AddMinutes(-5), 118.90m, 119.20m, 118.70m, 119.10m, 0),
                    new CandleSnapshot(at, 119.10m, 119.40m, 118.80m, 119.00m, 1500),
                ];
            var label = _state.ToString().ToUpperInvariant();
            return Task.FromResult(new ChartSnapshot(
                1,
                symbol,
                interval,
                _state,
                DateTimeOffset.Parse("2026-07-23T05:03:00Z"),
                at,
                _state == ChartDataState.Unavailable
                    ? "UNAVAILABLE | No stored bars are available. No simulated fallback was created."
                    : $"{label} | {candles.Length} stored {interval} candle(s) | no provider fetch",
                new DataLineage("stored-bars.json", at, "Read-only local evidence."),
                candles));
        }
    }

    private sealed class ThrowingEngineClient : IEngineClient
    {
        private static Task<T> Unexpected<T>() => Task.FromException<T>(new InvalidOperationException("Mock engine access is forbidden in Python simulation workspace mode."));

        public Task<IReadOnlyList<CandidateSnapshot>> GetCandidatesAsync(CancellationToken cancellationToken = default) => Unexpected<IReadOnlyList<CandidateSnapshot>>();

        public Task<IReadOnlyList<CandleSnapshot>> GetCandlesAsync(string symbol, string interval, CancellationToken cancellationToken = default) => Unexpected<IReadOnlyList<CandleSnapshot>>();

        public Task<TradePlanSnapshot> GetTradePlanAsync(string symbol, CancellationToken cancellationToken = default) => Unexpected<TradePlanSnapshot>();

        public Task<IReadOnlyList<ActivityEvent>> GetActivityAsync(CancellationToken cancellationToken = default) => Unexpected<IReadOnlyList<ActivityEvent>>();

        public Task<SystemHealthSnapshot> GetSystemHealthAsync(CancellationToken cancellationToken = default) => Unexpected<SystemHealthSnapshot>();

        public Task<ReplaySnapshot> GetReplaySessionAsync(CancellationToken cancellationToken = default) => Unexpected<ReplaySnapshot>();

        public Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default) => Unexpected<SimulationResult>();

        public Task<TradePlanSnapshot> ResolveMissingDataAsync(string symbol, CancellationToken cancellationToken = default) => Unexpected<TradePlanSnapshot>();
    }
}
