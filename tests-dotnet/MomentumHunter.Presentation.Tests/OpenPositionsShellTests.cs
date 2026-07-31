using System.Runtime.CompilerServices;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class OpenPositionsShellTests
{
    [Fact]
    public void PositionViewCalculatesBrokerageStyleValuesFromExecutableMark()
    {
        var row = Assert.IsType<OpenPositionView>(
            OpenPositionView.From(Trade("open-1", "NVDA", "AHEAD", 4, 100m, 103m, 12m, 1.5m)));

        Assert.Equal("LONG", row.Side);
        Assert.Equal("$100.0000", row.AverageFillDisplay);
        Assert.Equal("$103.0000", row.ExecutableMarkDisplay);
        Assert.Equal("$412.00", row.MarketValueDisplay);
        Assert.Equal("$12.00", row.UnrealizedPnlDisplay);
        Assert.Equal("3.00%", row.UnrealizedPercentDisplay);
        Assert.Equal("1.50 R", row.UnrealizedRDisplay);
        Assert.Equal("$105.0000", row.NextTargetDisplay);
        Assert.Equal("POSITIVE", row.PnlState);
    }

    [Theory]
    [InlineData("WORKING", 0, false)]
    [InlineData("WINNER", 4, true)]
    [InlineData("LOSER", 4, true)]
    public void PositionViewExcludesOrdersAndClosedTrades(string state, int quantity, bool hasFill)
    {
        var trade = Trade(
            $"excluded-{state}",
            "EQX",
            state,
            quantity,
            hasFill ? 50m : null,
            hasFill ? 51m : null,
            hasFill ? 4m : null,
            hasFill ? 0.5m : null);

        Assert.Null(OpenPositionView.From(trade));
    }

    [Fact]
    public async Task ShellAggregatesOpenPositionsAndCommandReopensThePane()
    {
        var shadowClient = new StaticShadowReviewClient(Snapshot());
        var viewModel = new ShellViewModel(
            new MockEngineClient(),
            new EmptyLayoutStore(),
            new StaticSimulationWorkspaceClient(),
            new EmptyChartWorkspaceClient(),
            shadowClient);

        await viewModel.InitializeAsync();

        var open = Assert.Single(viewModel.OpenPositions);
        Assert.Equal("NVDA", open.Symbol);
        Assert.Equal("Positions 1", viewModel.PositionsButtonLabel);
        Assert.Equal("$12.00", viewModel.OpenPositionPnlDisplay);
        Assert.Equal("$412.00", viewModel.OpenPositionMarketValueDisplay);
        Assert.Equal("Current", viewModel.OpenPositionQuoteHealthDisplay);
        Assert.False(viewModel.PositionsPane!.IsVisible);

        var command = Assert.IsType<CommandPaletteItem>(
            viewModel.FindExactCommandPaletteItem("positions"));
        var result = await viewModel.ExecuteCommandPaletteItemAsync(command);

        Assert.True(result.Executed);
        Assert.Equal(CommandPaletteAction.OpenPositions, result.Action);
        Assert.True(viewModel.PositionsPane.IsVisible);
        Assert.Equal(2, shadowClient.SnapshotReads);
        Assert.Contains("Opened Positions with 1", viewModel.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task StalePositionRaisesAttentionWithoutInventingAccountPositions()
    {
        var stale = Trade("stale-1", "AMD", "STALE", 2, 80m, 79m, -2m, -0.4m);
        var snapshot = Snapshot() with { Trades = [stale] };
        var viewModel = new ShellViewModel(
            new MockEngineClient(),
            new EmptyLayoutStore(),
            new StaticSimulationWorkspaceClient(),
            new EmptyChartWorkspaceClient(),
            new StaticShadowReviewClient(snapshot));

        await viewModel.InitializeAsync();

        Assert.Equal(1, viewModel.OpenPositionAttentionCount);
        Assert.Equal("1 need attention", viewModel.OpenPositionQuoteHealthDisplay);
        Assert.Contains("Schwab account positions are not connected", viewModel.PositionsSourceDetail, StringComparison.Ordinal);
        Assert.Equal("NEGATIVE", Assert.Single(viewModel.OpenPositions).PnlState);
    }

    [Fact]
    public void StalePositionWithoutExecutableMarkRemainsVisibleAndUnavailable()
    {
        var stale = Trade("stale-no-mark", "AMD", "STALE", 2, 80m, null, null, null);

        var row = Assert.IsType<OpenPositionView>(OpenPositionView.From(stale));

        Assert.Equal("Unavailable", row.ExecutableMarkDisplay);
        Assert.Equal("Unavailable", row.MarketValueDisplay);
        Assert.Equal("Unavailable", row.UnrealizedPnlDisplay);
        Assert.Equal("STALE", row.State);
    }

    [Fact]
    public void ShortPositionUsesTheNearestLowerTarget()
    {
        var shortPosition = Trade(
            "short-1",
            "TSLA",
            "AHEAD",
            3,
            250m,
            242m,
            24m,
            1.2m,
            "SHORT",
            [245m, 235m]);

        var row = Assert.IsType<OpenPositionView>(OpenPositionView.From(shortPosition));

        Assert.Equal("SHORT", row.Side);
        Assert.Equal("$235.0000", row.NextTargetDisplay);
        Assert.Equal("$726.00", row.MarketValueDisplay);
    }

    [Fact]
    public void WpfPositionsSurfaceIsReadOnlyDenseAndFirstClass()
    {
        var root = FindRepositoryRoot();
        var xaml = File.ReadAllText(
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml"));
        var codeBehind = File.ReadAllText(
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml.cs"));
        var start = xaml.IndexOf(
            "<avalon:LayoutAnchorable x:Name=\"PositionsAnchor\"",
            StringComparison.Ordinal);
        var end = xaml.IndexOf(
            "<avalon:LayoutAnchorable x:Name=\"ReplayEventsAnchor\"",
            start,
            StringComparison.Ordinal);
        var positionsXaml = xaml[start..end];

        Assert.Contains("Content=\"{Binding PositionsButtonLabel}\"", xaml, StringComparison.Ordinal);
        Assert.Contains("Click=\"PositionsButton_Click\"", xaml, StringComparison.Ordinal);
        Assert.Contains("x:Name=\"OpenPositionsGrid\"", positionsXaml, StringComparison.Ordinal);
        Assert.Contains("Header=\"Unrealized\"", positionsXaml, StringComparison.Ordinal);
        Assert.Contains("Header=\"Quote Age\"", positionsXaml, StringComparison.Ordinal);
        Assert.Contains("Text=\"{Binding PositionsModeLabel}\"", positionsXaml, StringComparison.Ordinal);
        Assert.Contains("Text=\"{Binding PositionsSourceDetail}\"", positionsXaml, StringComparison.Ordinal);
        Assert.DoesNotContain("Buy", positionsXaml, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Sell", positionsXaml, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Cancel", positionsXaml, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("EnsureAnchorablePaneHeight(PositionsContentId, 360);", codeBehind, StringComparison.Ordinal);
    }

    private static ShadowReviewSnapshot Snapshot()
    {
        var definition = Definition();
        return new ShadowReviewSnapshot(
            2,
            "PAPER SHADOW / NONTRANSMITTING",
            "shadow_trading_v1",
            false,
            "Read-only FakeBroker Shadow evidence.",
            [
                Trade("open-1", "NVDA", "AHEAD", 4, 100m, 103m, 12m, 1.5m),
                Trade("working-1", "EQX", "WORKING", 0, null, null, null, null),
                Trade("closed-1", "MSFT", "WINNER", 2, 200m, 210m, 20m, 2m),
            ],
            new ShadowSampleStatus(
                30, 0, 1, 1, 1, 0, 0, 2, false,
                "Evidence collection in progress.",
                definition,
                "IN_PROGRESS",
                false,
                ["Sample contains persisted test records."]),
            new ShadowAggregateMetrics(
                "INSUFFICIENT_SAMPLE",
                null, null, null, null, null, null, null, null, null, null,
                "Metrics withheld."));
    }

    private static ShadowTradeReviewSnapshot Trade(
        string id,
        string symbol,
        string state,
        int quantity,
        decimal? fill,
        decimal? mark,
        decimal? pnl,
        decimal? r,
        string direction = "LONG",
        IReadOnlyList<decimal>? targets = null)
    {
        var at = DateTimeOffset.Parse("2026-07-30T14:00:00-05:00");
        var isClosed = state is "WINNER" or "LOSER";
        var isWorking = state == "WORKING";
        targets ??= [105m, 110m];
        return new ShadowTradeReviewSnapshot(
            new ShadowTradeIdentity(
                id, symbol, "Breakout", "Stored catalyst", "risk_on", "REGULAR",
                at, at.AddMinutes(-1), $"plan-{symbol}", $"risk-{symbol}"),
            new ShadowPlanReview("Simulation-only", ["FakeBroker only."], fill, 97m, targets),
            new ShadowExecutionReview(
                fill,
                0.1m,
                2m,
                isClosed ? mark : null,
                isClosed ? "target_1" : string.Empty,
                isClosed ? "completed" : isWorking ? "pending_entry" : "open",
                "Synthetic position fixture.",
                new ShadowExecutionQuality("Synthetic fixture.", [], [])),
            new ShadowOutcomeReview(
                isClosed ? state : "ACTIVE",
                isClosed ? pnl : null,
                isClosed ? pnl : null,
                isClosed ? r : null,
                null,
                null,
                null),
            new ShadowActiveMarkReview(
                state,
                direction,
                quantity,
                fill,
                mark,
                mark is null ? null : mark - 0.02m,
                mark is null ? null : mark + 0.02m,
                pnl,
                r,
                pnl is null ? null : pnl + 1m,
                pnl is null ? null : Math.Min(pnl.Value, -1m),
                97m,
                targets,
                null,
                null,
                "Schwab market data",
                at,
                at.AddMilliseconds(25),
                state == "STALE" ? 12m : 0.5m,
                fill is null ? null : 300,
                isClosed ? "completed" : isWorking ? "pending_entry" : "open",
                state == "STALE" ? "STALE" : "LIVE",
                "Synthetic position fixture.",
                isClosed ? pnl : null,
                isClosed ? r : null,
                isClosed ? "target_1" : string.Empty),
            new ShadowEvidenceLock(true, true, at, false, "PASS", []),
            Definition(),
            "COMPLETE",
            true,
            isClosed);
    }

    private static ShadowSampleDefinition Definition() => new(
        "synthetic-official-v1",
        new string('a', 64),
        "prospective-fakebroker-live-mark-v2",
        1,
        true);

    private static string FindRepositoryRoot([CallerFilePath] string sourceFilePath = "")
    {
        var directory = new DirectoryInfo(Path.GetDirectoryName(sourceFilePath)!);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "MomentumHunter.Workstation.sln")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the Momentum Hunter repository root.");
    }

    private sealed class StaticShadowReviewClient(ShadowReviewSnapshot snapshot) : IShadowReviewClient
    {
        public int SnapshotReads { get; private set; }

        public Task<ShadowReviewSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
        {
            SnapshotReads++;
            return Task.FromResult(snapshot);
        }
    }

    private sealed class StaticSimulationWorkspaceClient : ISimulationWorkspaceClient
    {
        public Task<SimulationWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
        {
            var at = DateTimeOffset.Parse("2026-07-30T14:00:00-05:00");
            var workspace = new ReadOnlyWorkspaceSnapshot(
                2,
                at,
                "No current candidates in this position-shell fixture.",
                [],
                [],
                new SystemHealthSnapshot([], at),
                new AlertEvidenceSnapshot(
                    AlertEvidenceState.Empty, at, "No alerts.", 0, 0, 0, 0, [], []),
                new ReplaySnapshot("NOT_SELECTED", at, string.Empty, "fixture", "No replay."),
                true);
            return Task.FromResult(new SimulationWorkspaceSnapshot(
                1, at, "FakeBroker fixture.", workspace, [], false));
        }

        public Task<SimulationResult> RunSimulationAsync(
            string symbol,
            CancellationToken cancellationToken = default) =>
            throw new InvalidOperationException("The read-only position monitor cannot run simulation.");
    }

    private sealed class EmptyChartWorkspaceClient : IChartWorkspaceClient
    {
        public Task<ChartSnapshot> GetSnapshotAsync(
            string symbol,
            string interval,
            CancellationToken cancellationToken = default)
        {
            var at = DateTimeOffset.Parse("2026-07-30T14:00:00-05:00");
            return Task.FromResult(new ChartSnapshot(
                1,
                symbol,
                interval,
                ChartDataState.Unavailable,
                at,
                at,
                "No chart in position-shell fixture.",
                new DataLineage("Fixture", at, "No chart."),
                []));
        }
    }

    private sealed class EmptyLayoutStore : IWorkspaceLayoutStore
    {
        public Task SaveAsync(WorkspaceLayoutSnapshot snapshot, CancellationToken cancellationToken = default) =>
            Task.CompletedTask;
        public Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(
            WorkspaceKind workspace,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(null);
        public Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(
            CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(null);
        public Task<IReadOnlyList<WorkspaceLayoutSnapshot>> ListAsync(
            WorkspaceKind workspace,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<WorkspaceLayoutSnapshot>>([]);
        public Task<WorkspaceLayoutSnapshot?> LoadNamedAsync(
            WorkspaceKind workspace,
            string name,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(null);
    }
}
