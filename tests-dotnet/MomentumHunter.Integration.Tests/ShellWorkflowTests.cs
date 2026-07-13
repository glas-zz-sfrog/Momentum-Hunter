using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Integration.Tests;

public sealed class ShellWorkflowTests
{
    [Fact]
    public async Task SelectingCandidateUpdatesLinkedChartAndTradePlanState()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        var candidate = viewModel.Candidates.Single(item => item.Symbol == "PLTR");

        await viewModel.SelectCandidateAsync(candidate);

        Assert.Equal("PLTR", viewModel.SelectedSymbol);
        Assert.Equal("PLTR", viewModel.TradePlan!.Symbol);
        Assert.NotEmpty(viewModel.Candles);
        Assert.All(viewModel.Registry.Panes.Where(pane => pane.LinkGroup == LinkGroup.A), pane => Assert.Equal("PLTR", pane.Symbol));
    }

    [Fact]
    public async Task IntervalChangeRefreshesCandlesAndPropagatesAcrossLinkGroup()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();

        await viewModel.ChangeIntervalAsync("15m");

        Assert.Equal("15m", viewModel.SelectedInterval);
        Assert.All(viewModel.Registry.Panes.Where(pane => pane.LinkGroup == LinkGroup.A), pane => Assert.Equal("15m", pane.Interval));
        Assert.Equal(60, viewModel.Candles.Count);
    }

    [Fact]
    public async Task AdditionalChartKeepsItsOwnCandleContextWhenLinkASelectionChanges()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        var chartB = viewModel.AddLinkedChart();
        var chartBContext = Assert.Single(viewModel.SecondaryCharts);
        var originalCandles = chartBContext.Candles.ToArray();

        await viewModel.SelectCandidateAsync(viewModel.Candidates.Single(candidate => candidate.Symbol == "PLTR"));

        Assert.Equal(LinkGroup.B, chartB.LinkGroup);
        Assert.Equal("NVDA", chartB.Symbol);
        Assert.Equal(originalCandles, chartBContext.Candles);
        Assert.Equal("PLTR", viewModel.PrimaryChart!.Pane.Symbol);
    }

    [Fact]
    public async Task PinnedPrimaryChartRetainsItsSymbolAndCandlesWhenSelectionChanges()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        var originalCandles = viewModel.PrimaryChart!.Candles.ToArray();

        await viewModel.TogglePrimaryChartPinCommand.ExecuteAsync(null);
        await viewModel.SelectCandidateAsync(viewModel.Candidates.Single(candidate => candidate.Symbol == "PLTR"));

        Assert.True(viewModel.PrimaryChart.Pane.IsPinned);
        Assert.Equal("NVDA", viewModel.PrimaryChart.Pane.Symbol);
        Assert.Equal(originalCandles, viewModel.PrimaryChart.Candles);
        Assert.Equal("PLTR", viewModel.SelectedSymbol);
    }

    [Fact]
    public async Task PinnedTradePlanRetainsItsPlanWhenSelectionChanges()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();

        await viewModel.TogglePrimaryTradePlanPinCommand.ExecuteAsync(null);
        await viewModel.SelectCandidateAsync(viewModel.Candidates.Single(candidate => candidate.Symbol == "MSTR"));

        Assert.True(viewModel.PrimaryTradePlanPane!.IsPinned);
        Assert.Equal("NVDA", viewModel.TradePlan!.Symbol);
        Assert.Equal("MSTR", viewModel.SelectedSymbol);
    }

    [Fact]
    public async Task SwitchingWorkspaceDoesNotCarryDynamicChartInstancesForward()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        var chartB = viewModel.AddLinkedChart();

        viewModel.ChangeWorkspace(WorkspaceKind.Review);

        Assert.Null(viewModel.Registry.Find(chartB.InstanceId));
        Assert.Empty(viewModel.SecondaryCharts);
        Assert.Single(viewModel.Registry.Panes.Where(pane => pane.Kind == PaneKind.Chart));
    }

    [Theory]
    [InlineData(WorkspaceKind.Live, "SIMULATION \u2022 FakeBroker")]
    [InlineData(WorkspaceKind.Replay, "REPLAY \u2022 Read Only")]
    [InlineData(WorkspaceKind.Review, "REVIEW \u2022 Read Only")]
    public async Task EnvironmentIdentityReflectsTheActiveWorkspace(WorkspaceKind workspace, string expectedLabel)
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();

        viewModel.ChangeWorkspace(workspace);

        Assert.Equal(expectedLabel, viewModel.EnvironmentLabel);
    }

    [Fact]
    public async Task DailyIntervalIsAvailableAndUsesTheSameReadOnlyEngineBoundary()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();

        await viewModel.ChangeIntervalAsync("Daily");

        Assert.Equal("Daily", viewModel.SelectedInterval);
        Assert.Equal(60, viewModel.Candles.Count);
        Assert.All(viewModel.Registry.Panes.Where(pane => pane.LinkGroup == LinkGroup.A), pane => Assert.Equal("Daily", pane.Interval));
    }

    [Fact]
    public async Task WorkspacesCarryDistinctOperatorIntentWithoutChangingEngineBoundary()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();

        viewModel.ChangeWorkspace(WorkspaceKind.Replay);

        Assert.Equal(EnvironmentMode.Replay, viewModel.Environment);
        Assert.Equal("Replay Timeline", viewModel.Registry.Panes.Single(pane => pane.Kind == PaneKind.Hunter).Title);
        Assert.Contains("historical", viewModel.WorkspaceNarrative, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task ActivityHandleShowsTheCurrentUnreadCountWithoutExpandingThePane()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();

        Assert.Equal("Activity 3", viewModel.ActivityLabel);
        Assert.False(viewModel.IsActivityOpen);
    }

    [Fact]
    public async Task MockEngineIsSimulationOnlyAndExposesNoOrderSubmissionContract()
    {
        var engine = new MockEngineClient();
        var plan = await engine.GetTradePlanAsync("NVDA");
        var publicMethodNames = typeof(MockEngineClient).GetMethods().Select(method => method.Name).ToArray();

        Assert.Equal(ReadinessState.ReadyForSimulation, plan.Readiness);
        Assert.DoesNotContain(publicMethodNames, name => name.Contains("Submit", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(publicMethodNames, name => name.Contains("Order", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(publicMethodNames, name => name.Contains("Broker", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(publicMethodNames, name => name.Contains("Network", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(publicMethodNames, name => name == nameof(MockEngineClient.GetReplaySessionAsync));
        Assert.Contains(publicMethodNames, name => name == nameof(MockEngineClient.RunSimulationAsync));
        Assert.Contains(publicMethodNames, name => name == nameof(MockEngineClient.ResolveMissingDataAsync));
    }

    [Fact]
    public async Task SimulationRequiresRiskGateAndRecordsAnAuditOnlyForEligiblePlan()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        await viewModel.SelectCandidateAsync(viewModel.Candidates.Single(candidate => candidate.Symbol == "NVDA"));

        await viewModel.RunPrimaryActionAsync();

        Assert.NotNull(viewModel.LastSimulationResult);
        Assert.Equal(SimulationResultState.Completed, viewModel.LastSimulationResult!.State);
        Assert.Equal(EnvironmentMode.Simulation, viewModel.LastSimulationResult.Audit.Mode);
        Assert.True(viewModel.LastSimulationResult.RiskDecision.Allowed);
    }

    [Fact]
    public async Task IncompleteEvidenceUsesRepairPathInsteadOfSimulation()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        await viewModel.SelectCandidateAsync(viewModel.Candidates.Single(candidate => candidate.Symbol == "MSTR"));

        await viewModel.RunPrimaryActionAsync();

        Assert.Null(viewModel.LastSimulationResult);
        Assert.False(viewModel.TradePlan!.RiskDecision!.Allowed);
        Assert.Contains("does not mutate evidence", viewModel.StatusMessage, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void SoftClosedLinkedPaneReceivesTheLatestContextBeforeItIsReopened()
    {
        var registry = new PaneRegistry();
        var hunter = registry.Create(PaneKind.Hunter, "Hunter", LinkGroup.A, symbol: "NVDA");
        var chart = registry.Create(PaneKind.Chart, "Chart", LinkGroup.A, symbol: "NVDA");
        Assert.True(registry.SoftClose(chart.InstanceId));
        var coordinator = new LinkGroupCoordinator(registry);

        coordinator.PublishSymbol(hunter.LinkGroup, "AMD", "Daily");

        Assert.False(chart.IsVisible);
        Assert.Equal("AMD", chart.Symbol);
        Assert.Equal("Daily", chart.Interval);
    }
}
