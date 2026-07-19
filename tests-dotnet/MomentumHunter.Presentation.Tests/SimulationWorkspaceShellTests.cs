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
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client);

        await viewModel.InitializeAsync();

        Assert.True(viewModel.IsPythonSimulationWorkspaceMode);
        Assert.False(viewModel.IsReadOnlySnapshotMode);
        Assert.NotNull(viewModel.TradePlan);
        Assert.Empty(viewModel.Candles);
        Assert.True(viewModel.CanRunSimulation);
        Assert.Contains("Python FakeBroker Only", viewModel.EnvironmentLabel, StringComparison.Ordinal);
        Assert.Equal("NVDA", viewModel.TradePlanSymbolLabel);
        Assert.Equal("Simulation-only", viewModel.TradePlanRiskStatusLabel);
        Assert.Contains("chart integration remains deferred", viewModel.PlanningStatus, StringComparison.OrdinalIgnoreCase);

        await viewModel.RunPrimaryActionAsync();

        Assert.Equal(["NVDA"], client.RunSymbols);
        Assert.NotNull(viewModel.LastSimulationResult);
        Assert.Equal(SimulationResultState.Completed, viewModel.LastSimulationResult!.State);
        Assert.Contains("simulated order", viewModel.StatusMessage, StringComparison.OrdinalIgnoreCase);
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
            1,
            observedAt,
            "Persisted evidence loaded.",
            [candidate],
            [new ActivityEvent(observedAt, "Research", "Persisted report loaded.", "NVDA", HealthState.Healthy)],
            new SystemHealthSnapshot([new HealthComponentSnapshot("Trade planning report", HealthState.Healthy, "Loaded", observedAt)], observedAt),
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
