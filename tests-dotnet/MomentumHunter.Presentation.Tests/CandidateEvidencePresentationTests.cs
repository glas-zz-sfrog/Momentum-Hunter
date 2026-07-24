using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class CandidateEvidencePresentationTests
{
    [Fact]
    public async Task PersistedCandidateEvidenceTracksSelectionWithoutRecalculatingSourceFacts()
    {
        var observedAt = DateTimeOffset.Parse("2026-07-23T14:35:00Z");
        var first = Candidate(
            "NVDA",
            97,
            "EXECUTION_READY_TRADE",
            "Semiconductor leadership remained the stored catalyst.",
            "Source A",
            "RVOL 2.40x | spread 0.08%",
            "Fresh persisted report",
            "trade-planning-report-a.json",
            ["Prior high held.", "Participation expanded."]);
        var second = Candidate(
            "EQX",
            79,
            "PLANNING_SCAFFOLD",
            "Gold strength was the stored catalyst.",
            "Source B",
            "RVOL 0.50x | spread 0.22%",
            "Persisted report; relative volume incomplete",
            "trade-planning-report-b.json",
            ["Relative volume needs review."]);
        var viewModel = new ShellViewModel(
            new ThrowingEngineClient(),
            new StaticReadOnlyWorkspaceClient(Snapshot(observedAt, first, second)));

        await viewModel.InitializeAsync();

        Assert.Equal("NVDA", viewModel.CandidateEvidenceSymbolLabel);
        Assert.Equal(first.CatalystSummary!.Headline, viewModel.CandidateCatalystHeadline);
        Assert.Equal("Source A", viewModel.CandidateCatalystSourceLabel);
        Assert.Equal("EXECUTION_READY_TRADE", viewModel.CandidateReadinessLabel);
        Assert.Equal("RVOL 2.40x | spread 0.08%", viewModel.CandidateLiquidityLabel);
        Assert.Equal("Fresh persisted report", viewModel.CandidateQualityLabel);
        Assert.Equal("trade-planning-report-a.json", viewModel.CandidateLineageSourceLabel);
        Assert.Equal(["Prior high held.", "Participation expanded."], viewModel.CandidateOpportunityNotes);
        Assert.Equal("2 persisted opportunity notes", viewModel.CandidateOpportunityNotesLabel);

        await viewModel.SelectCandidateAsync(second);

        Assert.Same(second, viewModel.SelectedCandidate);
        Assert.Equal("EQX", viewModel.CandidateEvidenceSymbolLabel);
        Assert.Equal(second.CatalystSummary!.Headline, viewModel.CandidateCatalystHeadline);
        Assert.Equal("Source B", viewModel.CandidateCatalystSourceLabel);
        Assert.Equal("PLANNING_SCAFFOLD", viewModel.CandidateReadinessLabel);
        Assert.Equal("RVOL 0.50x | spread 0.22%", viewModel.CandidateLiquidityLabel);
        Assert.Equal("Persisted report; relative volume incomplete", viewModel.CandidateQualityLabel);
        Assert.Equal("trade-planning-report-b.json", viewModel.CandidateLineageSourceLabel);
        Assert.Equal(["Relative volume needs review."], viewModel.CandidateOpportunityNotes);
        Assert.Equal("1 persisted opportunity note", viewModel.CandidateOpportunityNotesLabel);
        Assert.Equal(79, second.Score);
        Assert.Equal(ReadinessState.NeedsEvidence, second.Readiness);
    }

    [Fact]
    public async Task PartialCandidateEvidenceUsesExplicitUnavailableStates()
    {
        var observedAt = DateTimeOffset.Parse("2026-07-23T14:35:00Z");
        var candidate = new CandidateSnapshot(
            "CRWD",
            "CrowdStrike Holdings",
            488.13m,
            null,
            null,
            null,
            string.Empty,
            ReadinessState.StaleData,
            string.Empty,
            observedAt,
            82,
            string.Empty,
            null,
            null,
            "STALE_DATA",
            []);
        var viewModel = new ShellViewModel(
            new ThrowingEngineClient(),
            new StaticReadOnlyWorkspaceClient(Snapshot(observedAt, candidate)));

        await viewModel.InitializeAsync();

        Assert.Equal("No stored catalyst summary is available.", viewModel.CandidateCatalystHeadline);
        Assert.Equal("Catalyst source unavailable", viewModel.CandidateCatalystSourceLabel);
        Assert.Equal("Catalyst timestamp unavailable", viewModel.CandidateCatalystObservedAtLabel);
        Assert.Equal("STALE_DATA", viewModel.CandidateReadinessLabel);
        Assert.Equal("Source quality unavailable", viewModel.CandidateQualityLabel);
        Assert.Equal("Liquidity data unavailable", viewModel.CandidateLiquidityLabel);
        Assert.Equal("Source lineage unavailable", viewModel.CandidateLineageSourceLabel);
        Assert.Equal("Lineage timestamp unavailable", viewModel.CandidateLineageAsOfLabel);
        Assert.Equal("No source lineage summary was supplied.", viewModel.CandidateLineageSummary);
        Assert.Empty(viewModel.CandidateOpportunityNotes);
        Assert.Equal("No stored opportunity notes are available.", viewModel.CandidateOpportunityNotesLabel);
    }

    [Fact]
    public async Task PinnedTradePlanKeepsEvidenceAttachedToThePinnedSymbol()
    {
        var engine = new MockEngineClient();
        var viewModel = new ShellViewModel(engine);
        await viewModel.InitializeAsync();
        var originalSymbol = viewModel.TradePlan!.Symbol;
        var originalCatalyst = viewModel.CandidateCatalystHeadline;
        var replacement = viewModel.Candidates.First(candidate => candidate.Symbol != originalSymbol);

        await viewModel.TogglePrimaryTradePlanPinCommand.ExecuteAsync(null);
        await viewModel.SelectCandidateAsync(replacement);

        Assert.Equal(replacement.Symbol, viewModel.SelectedSymbol);
        Assert.Equal(originalSymbol, viewModel.TradePlanSymbolLabel);
        Assert.Equal(originalSymbol, viewModel.CandidateEvidenceSymbolLabel);
        Assert.Equal(originalCatalyst, viewModel.CandidateCatalystHeadline);
    }

    private static CandidateSnapshot Candidate(
        string symbol,
        int score,
        string readiness,
        string catalyst,
        string catalystSource,
        string liquidity,
        string quality,
        string lineageSource,
        IReadOnlyList<string> notes)
    {
        var observedAt = DateTimeOffset.Parse("2026-07-23T14:35:00Z");
        return new CandidateSnapshot(
            symbol,
            $"{symbol} Company",
            100m,
            1m,
            1_000_000,
            2m,
            catalyst,
            readiness.StartsWith("EXECUTION_READY", StringComparison.Ordinal)
                ? ReadinessState.ReadyForSimulation
                : ReadinessState.NeedsEvidence,
            quality,
            observedAt,
            score,
            liquidity,
            new CatalystSummary(catalyst, catalystSource, observedAt),
            new DataLineage(lineageSource, observedAt, "Read-only persisted evidence; no recalculation occurred."),
            readiness,
            notes);
    }

    private static ReadOnlyWorkspaceSnapshot Snapshot(
        DateTimeOffset observedAt,
        params CandidateSnapshot[] candidates) =>
        new(
            2,
            observedAt,
            "Read-only Python evidence snapshot.",
            candidates,
            [],
            new SystemHealthSnapshot([], observedAt),
            new AlertEvidenceSnapshot(
                AlertEvidenceState.Empty,
                observedAt,
                "No stored alert evidence was supplied for this candidate-evidence fixture.",
                0,
                0,
                0,
                0,
                [],
                []),
            new ReplaySnapshot("NOT_SELECTED", observedAt, string.Empty, "source capture", "No replay identity was synthesized."),
            false);

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

    private sealed class ThrowingEngineClient : IEngineClient
    {
        private static Task<T> Unexpected<T>() =>
            Task.FromException<T>(new InvalidOperationException("Candidate evidence must remain on the read-only Python boundary."));

        public Task<IReadOnlyList<CandidateSnapshot>> GetCandidatesAsync(CancellationToken cancellationToken = default) =>
            Unexpected<IReadOnlyList<CandidateSnapshot>>();

        public Task<IReadOnlyList<CandleSnapshot>> GetCandlesAsync(
            string symbol,
            string interval,
            CancellationToken cancellationToken = default) =>
            Unexpected<IReadOnlyList<CandleSnapshot>>();

        public Task<TradePlanSnapshot> GetTradePlanAsync(string symbol, CancellationToken cancellationToken = default) =>
            Unexpected<TradePlanSnapshot>();

        public Task<IReadOnlyList<ActivityEvent>> GetActivityAsync(CancellationToken cancellationToken = default) =>
            Unexpected<IReadOnlyList<ActivityEvent>>();

        public Task<SystemHealthSnapshot> GetSystemHealthAsync(CancellationToken cancellationToken = default) =>
            Unexpected<SystemHealthSnapshot>();

        public Task<ReplaySnapshot> GetReplaySessionAsync(CancellationToken cancellationToken = default) =>
            Unexpected<ReplaySnapshot>();

        public Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default) =>
            Unexpected<SimulationResult>();

        public Task<TradePlanSnapshot> ResolveMissingDataAsync(string symbol, CancellationToken cancellationToken = default) =>
            Unexpected<TradePlanSnapshot>();
    }
}
