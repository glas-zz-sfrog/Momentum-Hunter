using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class ResearchMaturityShellTests
{
    [Fact]
    public async Task ShellLoadsHiddenUnlinkedResearchMaturityIndependentlyOfCandidateSelection()
    {
        var client = new StaticResearchMaturityClient(Snapshot());
        var viewModel = new ShellViewModel(new MockEngineClient(), client);

        await viewModel.InitializeAsync();

        var pane = Assert.Single(
            viewModel.Registry.Panes.Where(item => item.Kind == PaneKind.ResearchMaturity));
        Assert.False(pane.IsVisible);
        Assert.Equal(LinkGroup.Unlinked, pane.LinkGroup);
        Assert.Equal(ResearchMaturityEvidenceState.Stale, viewModel.ResearchMaturity?.State);
        Assert.Equal("STALE", viewModel.ResearchMaturityStateLabel);
        Assert.Contains("100.0%", viewModel.ResearchMaturityRateLabel, StringComparison.Ordinal);
        Assert.Contains("50.0%", viewModel.ResearchCensusRateLabel, StringComparison.Ordinal);
        Assert.Contains("1 completed / 25 required", viewModel.ResearchMaturityProgressLabel, StringComparison.Ordinal);
        Assert.Equal(1, client.CallCount);

        var originalPaneSymbol = pane.Symbol;
        var nextCandidate = viewModel.Candidates.First(candidate => candidate.Symbol != viewModel.SelectedSymbol);
        await viewModel.SelectCandidateAsync(nextCandidate);

        Assert.Equal(originalPaneSymbol, pane.Symbol);
        Assert.Equal(1, client.CallCount);
        Assert.Equal(41, viewModel.ResearchMaturity?.Census.Captures);
    }

    [Fact]
    public async Task ShellConvertsResearchBoundaryFailureToLockedUnavailableState()
    {
        var viewModel = new ShellViewModel(
            new MockEngineClient(),
            new FailingResearchMaturityClient());

        await viewModel.InitializeAsync();

        Assert.Equal(
            ResearchMaturityEvidenceState.Unavailable,
            viewModel.ResearchMaturity?.State);
        Assert.Equal("LOCKED", viewModel.ResearchMaturity?.StrategyOptimizationStatus);
        Assert.False(viewModel.ResearchMaturity?.StrategyChangeRecommendationsAllowed);
        Assert.True(viewModel.ResearchMaturity?.ResearchOnly);
        Assert.True(viewModel.ResearchMaturity?.ReadOnly);
        Assert.Contains(
            "No evidence or strategy conclusion was inferred",
            viewModel.ResearchMaturity?.Summary,
            StringComparison.Ordinal);
    }

    private static ResearchMaturitySnapshot Snapshot() => new(
        1,
        ResearchMaturityEvidenceState.Stale,
        DateTimeOffset.Parse("2026-07-23T12:00:00Z"),
        DateTimeOffset.Parse("2026-06-27T06:35:44Z"),
        DateTimeOffset.Parse("2026-06-27T06:35:44Z"),
        DateTimeOffset.Parse("2026-06-27T06:38:33Z"),
        "evidence-analytics-maturity-latest.json + evidence-census-latest.json",
        "STALE | Persisted research maturity remains locked.",
        "WARN",
        "WARN",
        "COLLECTING_ONLY",
        "INSUFFICIENT_SAMPLE",
        "LOCKED",
        false,
        new ResearchMaturityAlertCounts(2, 1, 0, 1, 100m),
        24,
        new ResearchMaturityEvidenceGate(
            1,
            25,
            "COLLECTING",
            "Collect evidence only",
            "LOCKED",
            "1 completed alert; minimum 25 required."),
        [
            new ResearchMaturityGate(
                "Collect Evidence",
                "UNLOCKED",
                1,
                0,
                0,
                "Collect evidence only",
                false),
            new ResearchMaturityGate(
                "Identify Patterns",
                "LOCKED",
                1,
                25,
                24,
                "Identify patterns",
                false),
        ],
        2,
        [
            new ResearchMaturityQuestion("Are Alerts Predictive", "NOT_YET"),
        ],
        1,
        new ResearchEvidenceCensus(
            new ResearchMaturityAlertCounts(2, 1, 0, 1, 50m),
            41,
            675,
            36,
            0,
            710,
            1,
            14,
            380,
            17,
            8,
            27,
            0,
            27,
            [new ResearchMaturityTableCount("captures", 41)],
            1),
        ["LOW_COMPLETED_ALERT_SAMPLE"],
        ["Research evidence only; strategy changes remain locked."],
        true,
        true);

    private sealed class StaticResearchMaturityClient : IResearchMaturityWorkspaceClient
    {
        private readonly ResearchMaturitySnapshot _snapshot;

        public StaticResearchMaturityClient(ResearchMaturitySnapshot snapshot)
        {
            _snapshot = snapshot;
        }

        public int CallCount { get; private set; }

        public Task<ResearchMaturitySnapshot> GetSnapshotAsync(
            CancellationToken cancellationToken = default)
        {
            CallCount++;
            return Task.FromResult(_snapshot);
        }
    }

    private sealed class FailingResearchMaturityClient : IResearchMaturityWorkspaceClient
    {
        public Task<ResearchMaturitySnapshot> GetSnapshotAsync(
            CancellationToken cancellationToken = default) =>
            throw new InvalidDataException("persisted maturity payload was invalid");
    }
}
