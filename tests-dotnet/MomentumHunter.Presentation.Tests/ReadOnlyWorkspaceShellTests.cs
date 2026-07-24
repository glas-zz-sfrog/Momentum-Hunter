using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class ReadOnlyWorkspaceShellTests
{
    [Fact]
    public async Task ReadOnlySnapshotPopulatesPersistedEvidenceAndDoesNotRequestAMockTradePlan()
    {
        var snapshot = Snapshot();
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), new StaticReadOnlyWorkspaceClient(snapshot));

        await viewModel.InitializeAsync();

        var candidate = Assert.Single(viewModel.Candidates);
        Assert.Equal("NVDA", candidate.Symbol);
        Assert.Equal("PLANNING_SCAFFOLD", candidate.OperatorState);
        Assert.True(viewModel.IsReadOnlySnapshotMode);
        Assert.Null(viewModel.TradePlan);
        Assert.Empty(viewModel.Candles);
        Assert.False(viewModel.CanRunSimulation);
        Assert.False(viewModel.CanRunPrimaryAction);
        Assert.Equal("READ-ONLY", viewModel.EnvironmentLabel);
        Assert.Contains("Planning and order actions are unavailable", viewModel.EnvironmentDetail, StringComparison.Ordinal);
        Assert.Contains("unavailable at this read-only boundary", viewModel.PlanningStatus, StringComparison.Ordinal);
        Assert.Contains("Stored chart evidence is independent", viewModel.PlanningStatus, StringComparison.Ordinal);
        Assert.Contains("not create a substitute plan", viewModel.PlanningStatus, StringComparison.Ordinal);
        Assert.Equal(AlertEvidenceState.Available, viewModel.AlertEvidenceOverview.State);
        Assert.Equal("NVDA", Assert.Single(viewModel.AlertRows).SymbolLabel);
        Assert.Equal("SUCCESSFUL", Assert.Single(viewModel.OutcomeRows).ClassificationLabel);
    }

    [Fact]
    public async Task UnavailableReadOnlySnapshotDoesNotFallBackToMockCandidates()
    {
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), new FailingReadOnlyWorkspaceClient());

        await viewModel.InitializeAsync();

        Assert.True(viewModel.IsReadOnlySnapshotMode);
        Assert.Empty(viewModel.Candidates);
        Assert.Null(viewModel.TradePlan);
        Assert.NotNull(viewModel.Health);
        Assert.Equal(HealthState.Unavailable, Assert.Single(viewModel.Health!.Components).State);
        Assert.Contains("Mock fallback is disabled", viewModel.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ReadOnlyPrimaryActionRemainsNonExecuting()
    {
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), new StaticReadOnlyWorkspaceClient(Snapshot()));
        await viewModel.InitializeAsync();

        await viewModel.RunPrimaryActionAsync();

        Assert.Null(viewModel.LastSimulationResult);
        Assert.Contains("read-only Python evidence snapshot", viewModel.StatusMessage, StringComparison.OrdinalIgnoreCase);
    }

    private static ReadOnlyWorkspaceSnapshot Snapshot()
    {
        var observedAt = DateTimeOffset.Parse("2026-07-17T15:00:00Z");
        var candidate = new CandidateSnapshot(
            "NVDA",
            "NVIDIA Corporation",
            176.42m,
            3.18m,
            84700112,
            2.4m,
            "Stored catalyst",
            ReadinessState.NeedsEvidence,
            "Persisted report",
            observedAt,
            97,
            "RVOL 2.40x",
            new CatalystSummary("Stored catalyst", "Persisted trade-planning report", observedAt),
            new DataLineage("Persisted trade-planning report", observedAt, "No recalculation occurred."),
            "PLANNING_SCAFFOLD");
        return new ReadOnlyWorkspaceSnapshot(
            2,
            observedAt,
            "Read-only Python evidence snapshot.",
            [candidate],
            [new ActivityEvent(observedAt, "Research", "Persisted report loaded.", "NVDA", HealthState.Healthy)],
            new SystemHealthSnapshot([new HealthComponentSnapshot("Trade planning report", HealthState.Healthy, "Loaded", observedAt)], observedAt),
            new AlertEvidenceSnapshot(
                AlertEvidenceState.Available,
                observedAt,
                "Stored alert evidence.",
                2,
                1,
                1,
                0,
                [new AlertEvent("alert-active", observedAt, "NVDA", "BREAKOUT", "ACTIVE", "Stored alert.")],
                [new OutcomeSnapshot("alert-complete", "CRWD", observedAt, "COMPLETED", "SUCCESSFUL", "Stored outcome.")]),
            new ReplaySnapshot("NOT_SELECTED", observedAt, string.Empty, "source capture", "No candidate replay identity was synthesized."),
            false);
    }

    private sealed class StaticReadOnlyWorkspaceClient : IReadOnlyWorkspaceClient
    {
        private readonly ReadOnlyWorkspaceSnapshot _snapshot;

        public StaticReadOnlyWorkspaceClient(ReadOnlyWorkspaceSnapshot snapshot)
        {
            _snapshot = snapshot;
        }

        public Task<ReadOnlyWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(_snapshot);
    }

    private sealed class FailingReadOnlyWorkspaceClient : IReadOnlyWorkspaceClient
    {
        public Task<ReadOnlyWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromException<ReadOnlyWorkspaceSnapshot>(new InvalidOperationException("host unavailable"));
    }

    private sealed class ThrowingEngineClient : IEngineClient
    {
        private static Task<T> Unexpected<T>() => Task.FromException<T>(new InvalidOperationException("Mock engine access is forbidden in read-only snapshot mode."));

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
