using System.Runtime.CompilerServices;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class ShadowReviewShellTests
{
    [Fact]
    public async Task ReviewSelectionUpdatesLinkedChartPlanWhyAndActivity()
    {
        var shadowClient = new StaticShadowReviewClient(ShadowSnapshot());
        var chartClient = new RecordingChartClient();
        var viewModel = CreateViewModel(shadowClient, chartClient);
        await viewModel.InitializeAsync();
        await viewModel.ChangeWorkspaceAsync(WorkspaceKind.Review);
        var selected = viewModel.ShadowTrades.Single(trade => trade.Symbol == "EQX");

        await viewModel.SelectShadowTradeAsync(selected);

        Assert.Equal("EQX", viewModel.SelectedSymbol);
        Assert.Equal("EQX", viewModel.PrimaryChartPane!.Symbol);
        Assert.Equal("EQX", viewModel.TradePlan!.Symbol);
        Assert.Equal(50m, viewModel.TradePlan.Entry);
        Assert.Contains("Frozen Shadow evidence", viewModel.TradePlan.DataLineage.SourceLabel, StringComparison.Ordinal);
        Assert.Equal(1, viewModel.TradePlanTabIndex);
        Assert.False(viewModel.CanRunPrimaryAction);
        Assert.Equal("REVIEW ONLY", viewModel.EnvironmentLabel);
        Assert.Contains("No broker or order actions", viewModel.EnvironmentDetail, StringComparison.Ordinal);
        Assert.Contains(viewModel.Activity, item => item.Category == "Test Trade Review" && item.Symbol == "EQX");
        Assert.Contains(("EQX", "5m"), chartClient.Requests);
        Assert.Equal(2, shadowClient.SnapshotReads);
        Assert.True(viewModel.Registry.Panes.Single(pane => pane.Kind == PaneKind.ShadowReview).IsVisible);
    }

    [Fact]
    public async Task ReviewSelectionRespectsPinnedChartAndTradePlan()
    {
        var viewModel = CreateViewModel(new StaticShadowReviewClient(ShadowSnapshot()), new RecordingChartClient());
        await viewModel.InitializeAsync();
        await viewModel.ChangeWorkspaceAsync(WorkspaceKind.Review);
        var first = viewModel.ShadowTrades.Single(trade => trade.Symbol == "NVDA");
        var second = viewModel.ShadowTrades.Single(trade => trade.Symbol == "EQX");
        await viewModel.SelectShadowTradeAsync(first);
        await viewModel.TogglePrimaryChartPinCommand.ExecuteAsync(null);
        await viewModel.TogglePrimaryTradePlanPinCommand.ExecuteAsync(null);

        await viewModel.SelectShadowTradeAsync(second);

        Assert.Equal("EQX", viewModel.SelectedSymbol);
        Assert.Equal("NVDA", viewModel.PrimaryChartPane!.Symbol);
        Assert.Equal("NVDA", viewModel.TradePlan!.Symbol);
        Assert.True(viewModel.PrimaryChartPane.IsPinned);
        Assert.True(viewModel.PrimaryTradePlanPane!.IsPinned);
    }

    [Fact]
    public async Task RestrainedFiltersUseCanonicalReviewFields()
    {
        var viewModel = CreateViewModel(new StaticShadowReviewClient(ShadowSnapshot()), new RecordingChartClient());
        await viewModel.InitializeAsync();

        viewModel.ShadowSetupFilter = "Breakout";
        viewModel.ShadowOutcomeFilter = "WINNER";
        viewModel.ShadowEligibilityFilter = "ELIGIBLE";

        var trade = Assert.Single(viewModel.ShadowTrades);
        Assert.Equal("NVDA", trade.Symbol);
        Assert.Equal("Prospective Shadow Trades: 1 / 30", viewModel.ShadowSample.ProgressLabel);
        Assert.Equal("OFFICIAL SAMPLE \u2022 IN PROGRESS", viewModel.ShadowSample.ReadinessLabel);
        Assert.Contains("synthetic-official-v1", viewModel.ShadowSample.DefinitionLabel, StringComparison.Ordinal);
        Assert.Equal("Withheld", viewModel.ShadowMetrics.ExpectancyDisplay);
    }

    [Fact]
    public async Task ActiveCardAndCompactListsUsePythonDisplayStates()
    {
        var viewModel = CreateViewModel(
            new StaticShadowReviewClient(ShadowSnapshot()),
            new RecordingChartClient());

        await viewModel.InitializeAsync();

        Assert.Equal("EQX", viewModel.ActiveShadowTrade?.Symbol);
        Assert.Equal("WORKING", viewModel.ActiveShadowTrade?.ActiveMark.DisplayState);
        Assert.Equal("NVDA", Assert.Single(viewModel.ShadowOfficialTrades).Symbol);
        Assert.Equal("EQX", Assert.Single(viewModel.ShadowUnfilledBlockedTrades).Symbol);
        Assert.Equal(50m, viewModel.ActiveShadowTrade?.ActiveMark.Ask);
        Assert.Null(viewModel.ActiveShadowTrade?.ActiveMark.UnrealizedPnl);
        Assert.Null(viewModel.ActiveShadowTrade?.ActiveMark.UnrealizedR);
    }

    [Fact]
    public async Task ActiveCardAndOfficialListsExcludePriorSampleRecords()
    {
        var snapshot = ShadowSnapshot();
        var currentWorking = snapshot.Trades.Single(trade => trade.Symbol == "EQX");
        var priorWorking = currentWorking with
        {
            Identity = currentWorking.Identity with
            {
                ShadowTradeId = "shadow-prior",
                Symbol = "OLD",
            },
            SampleDefinition = new ShadowSampleDefinition(
                "engineering-preflight-v1",
                new string('b', 64),
                "prospective-fakebroker-v1",
                1,
                false),
        };
        var mixedSnapshot = snapshot with
        {
            Trades = [priorWorking, .. snapshot.Trades],
        };
        var viewModel = CreateViewModel(
            new StaticShadowReviewClient(mixedSnapshot),
            new RecordingChartClient());

        await viewModel.InitializeAsync();

        Assert.Equal("EQX", viewModel.ActiveShadowTrade?.Symbol);
        Assert.DoesNotContain(
            viewModel.ShadowOfficialTrades,
            trade => trade.Symbol == "OLD");
        Assert.DoesNotContain(
            viewModel.ShadowUnfilledBlockedTrades,
            trade => trade.Symbol == "OLD");
    }

    [Fact]
    public void CompactReviewGridBindingsAreReadOnlyForImmutableSnapshots()
    {
        var root = FindRepositoryRoot();
        var xaml = File.ReadAllText(
            Path.Combine(
                root,
                "src",
                "MomentumHunter.Desktop.Wpf",
                "MainWindow.xaml"));

        Assert.Contains(
            "Text=\"{Binding Symbol, Mode=OneWay}\"",
            xaml,
            StringComparison.Ordinal);
        Assert.Contains(
            "Text=\"{Binding ActiveShadowTrade.Symbol, Mode=OneWay}\"",
            xaml,
            StringComparison.Ordinal);
        Assert.Contains(
            "Text=\"{Binding ActiveMark.DisplayState, Mode=OneWay}\"",
            xaml,
            StringComparison.Ordinal);
        Assert.Contains(
            "Text=\"{Binding ActiveMark.CurrentOrFinalRDisplay, Mode=OneWay}\"",
            xaml,
            StringComparison.Ordinal);
        Assert.Contains(
            "Text=\"{Binding ActiveMark.Reason, Mode=OneWay}\"",
            xaml,
            StringComparison.Ordinal);
        var reviewGridStart = xaml.IndexOf(
            "<TabItem Header=\"Official Trades\">",
            StringComparison.Ordinal);
        var reviewGridEnd = xaml.IndexOf(
            "<TabItem Header=\"Counterfactuals\">",
            reviewGridStart,
            StringComparison.Ordinal);
        var reviewGridXaml = xaml[reviewGridStart..reviewGridEnd];
        Assert.DoesNotContain(
            "DataGridTextColumn",
            reviewGridXaml,
            StringComparison.Ordinal);
        Assert.Contains(
            "DataGridTemplateColumn",
            reviewGridXaml,
            StringComparison.Ordinal);
        var shadowReviewStart = xaml.IndexOf(
            "<TextBlock Text=\"Test Trade Review\"",
            StringComparison.Ordinal);
        var shadowReviewEnd = xaml.IndexOf(
            "<avalon:LayoutAnchorable x:Name=\"ReviewOutcomesAnchor\"",
            shadowReviewStart,
            StringComparison.Ordinal);
        var shadowReviewXaml = xaml[shadowReviewStart..shadowReviewEnd];
        var inlineBindings = shadowReviewXaml
            .Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries)
            .Where(line => line.Contains("<Run Text=\"{Binding", StringComparison.Ordinal));
        Assert.All(
            inlineBindings,
            line => Assert.Contains("Mode=OneWay", line, StringComparison.Ordinal));
    }

    [Fact]
    public void ReviewPaneIsExpandedWhenShownOrRestored()
    {
        var root = FindRepositoryRoot();
        var codeBehind = File.ReadAllText(
            Path.Combine(
                root,
                "src",
                "MomentumHunter.Desktop.Wpf",
                "MainWindow.xaml.cs"));

        Assert.True(
            codeBehind.Split(
                "EnsureAnchorablePaneHeight(ShadowReviewContentId, 620);",
                StringSplitOptions.None).Length >= 3,
            "Test Trade Review should expand both when reopened and when workspace visibility is restored.");
    }

    [Fact]
    public void EmptyActivatedSampleUsesTruthfulActiveAwaitingTradeLabel()
    {
        var status = new ShadowSampleStatus(
            30, 0, 0, 0, 0, 0, 0, 0, false,
            "Evidence collection has not started.",
            SampleDefinition(),
            "PASS",
            true,
            []);

        Assert.Equal("OFFICIAL SAMPLE \u2022 ACTIVE - AWAITING TRADE 1", status.ReadinessLabel);
        Assert.Contains("immutable official-sample definition is active", status.ReadinessReasonDisplay, StringComparison.Ordinal);
    }

    private static ShellViewModel CreateViewModel(
        IShadowReviewClient shadowClient,
        IChartWorkspaceClient chartClient) =>
        new(
            new ThrowingEngineClient(),
            new EmptyLayoutStore(),
            new StaticSimulationWorkspaceClient(SimulationSnapshot()),
            chartClient,
            shadowClient);

    private static ShadowReviewSnapshot ShadowSnapshot()
    {
        var at = DateTimeOffset.Parse("2026-07-23T10:00:00-05:00");
        var nvda = Trade("shadow-nvda", "NVDA", "Breakout", "WIN", true, "completed", at);
        var eqx = Trade("shadow-eqx", "EQX", "Pullback", "ACTIVE", false, "pending_entry", at.AddMinutes(5));
        return new ShadowReviewSnapshot(
            2,
            "PAPER SHADOW / NONTRANSMITTING",
            "shadow_trading_v1",
            false,
            "Prospective Shadow Trading uses supplied evidence and FakeBroker execution only.",
            [nvda, eqx],
            new ShadowSampleStatus(
                30, 1, 1, 1, 1, 0, 1, 1, false,
                "Evidence collection in progress. Results are not yet sufficient for strategy conclusions.",
                SampleDefinition(),
                "IN_PROGRESS",
                false,
                ["Sample version already contains persisted trade records."]),
            new ShadowAggregateMetrics(
                "INSUFFICIENT_SAMPLE", null, null, null, null, null, null, null, null, null, null,
                "Evidence collection in progress. Results are not yet sufficient for strategy conclusions."));
    }

    private static ShadowTradeReviewSnapshot Trade(
        string id,
        string symbol,
        string setup,
        string outcome,
        bool eligible,
        string lifecycle,
        DateTimeOffset at)
    {
        var lockState = new ShadowEvidenceLock(
            eligible,
            eligible,
            at,
            false,
            eligible ? "PASS" : "FAIL",
            eligible ? [] : ["Data quality is PARTIAL; this record is excluded."]);
        return new ShadowTradeReviewSnapshot(
            new ShadowTradeIdentity(
                id, symbol, setup, "Stored catalyst", "risk_on", "REGULAR", at, at.AddMinutes(-1),
                $"plan-{symbol}", $"risk-{symbol}"),
            new ShadowPlanReview(
                eligible ? "Simulation-only" : "Needs review",
                ["FakeBroker simulation only."],
                symbol == "NVDA" ? 100m : 50m,
                symbol == "NVDA" ? 98m : 48m,
                symbol == "NVDA" ? [104m, 106m] : [53m, 55m]),
            new ShadowExecutionReview(
                eligible ? 100.05m : null,
                eligible ? 0.12m : null,
                eligible ? 5m : null,
                eligible ? 104m : null,
                eligible ? "target_1" : string.Empty,
                lifecycle,
                eligible ? "Shadow position closed by target_1." : "Waiting for a later quote.",
                new ShadowExecutionQuality(
                    eligible ? "FakeBroker applied entry slippage." : "No fill has occurred.",
                    eligible ? ["Observed spread was 0.12%."] : ["No fill has occurred."],
                    [])),
            new ShadowOutcomeReview(
                outcome,
                eligible ? 8m : null,
                eligible ? 7.90m : null,
                eligible ? 1.9m : null,
                eligible ? 8.2m : null,
                eligible ? -1.1m : null,
                eligible ? 1800 : null),
            new ShadowActiveMarkReview(
                eligible ? "WINNER" : "WORKING",
                "LONG",
                2,
                eligible ? 100.05m : null,
                eligible ? 104m : null,
                eligible ? 104m : 49.95m,
                eligible ? 104.02m : 50m,
                null,
                null,
                eligible ? 8.2m : null,
                eligible ? -1.1m : null,
                symbol == "NVDA" ? 98m : 48m,
                symbol == "NVDA" ? [104m, 106m] : [53m, 55m],
                null,
                null,
                "synthetic-ui-proof",
                at.AddMinutes(30),
                at.AddMinutes(30).AddMilliseconds(20),
                0.02m,
                eligible ? 1800 : null,
                lifecycle,
                "LIVE",
                eligible ? "Synthetic completed fixture." : "Waiting for a later quote.",
                eligible ? 7.9m : null,
                eligible ? 1.9m : null,
                eligible ? "target_1" : string.Empty),
            lockState,
            SampleDefinition(),
            eligible ? "COMPLETE" : "PARTIAL",
            eligible,
            eligible && lifecycle == "completed");
    }

    private static ShadowSampleDefinition SampleDefinition() => new(
        "synthetic-official-v1",
        new string('a', 64),
        "prospective-fakebroker-live-mark-v2",
        1,
        true);

    private static string FindRepositoryRoot(
        [CallerFilePath] string sourceFilePath = "")
    {
        foreach (var start in new[]
                 {
                     Path.GetDirectoryName(sourceFilePath) ?? string.Empty,
                     Directory.GetCurrentDirectory(),
                     AppContext.BaseDirectory,
                 })
        {
            if (string.IsNullOrWhiteSpace(start))
            {
                continue;
            }

            var directory = new DirectoryInfo(start);
            while (directory is not null)
            {
                if (File.Exists(Path.Combine(directory.FullName, "MomentumHunter.Workstation.sln")))
                {
                    return directory.FullName;
                }

                directory = directory.Parent;
            }
        }

        throw new DirectoryNotFoundException(
            "Could not locate the Momentum Hunter repository root.");
    }

    private static SimulationWorkspaceSnapshot SimulationSnapshot()
    {
        var at = DateTimeOffset.Parse("2026-07-23T15:00:00Z");
        var lineage = new DataLineage("Persisted report", at, "Read-only evidence.");
        var candidates = new[] { Candidate("NVDA", at, lineage), Candidate("EQX", at, lineage) };
        var workspace = new ReadOnlyWorkspaceSnapshot(
            1,
            at,
            "Persisted evidence.",
            candidates,
            [],
            new SystemHealthSnapshot([], at),
            new AlertEvidenceSnapshot(
                AlertEvidenceState.Empty,
                at,
                "No persisted alert evidence in this synthetic Shadow fixture.",
                0,
                0,
                0,
                0,
                [],
                []),
            new ReplaySnapshot("NOT_SELECTED", at, string.Empty, "source capture", "No replay."),
            true);
        return new SimulationWorkspaceSnapshot(
            1,
            at,
            "Python FakeBroker simulation workspace.",
            workspace,
            [Plan("NVDA", 100m, lineage), Plan("EQX", 50m, lineage)],
            true);
    }

    private static CandidateSnapshot Candidate(string symbol, DateTimeOffset at, DataLineage lineage) => new(
        symbol,
        symbol,
        100m,
        1m,
        1_000_000,
        2m,
        "Stored catalyst",
        ReadinessState.ReadyForSimulation,
        "Persisted report",
        at,
        90,
        "RVOL 2.00x",
        new CatalystSummary("Stored catalyst", "Persisted report", at),
        lineage,
        "EXECUTION_READY_TRADE");

    private static TradePlanSnapshot Plan(string symbol, decimal entry, DataLineage lineage)
    {
        var risk = new RiskDecision(true, "Simulation-only", "FakeBroker simulation only.", ["Simulation only."]);
        return new TradePlanSnapshot(
            symbol,
            entry,
            entry - 2m,
            entry + 4m,
            2m,
            2,
            2m,
            ReadinessState.ReadyForSimulation,
            [new ReadinessCheck("Stop defined", true, "Frozen stop.")],
            "Run FakeBroker simulation",
            lineage,
            [new TradeLevel("Entry", entry, "Frozen entry.")],
            risk);
    }

    private sealed class StaticShadowReviewClient : IShadowReviewClient
    {
        private readonly ShadowReviewSnapshot _snapshot;

        public StaticShadowReviewClient(ShadowReviewSnapshot snapshot)
        {
            _snapshot = snapshot;
        }

        public int SnapshotReads { get; private set; }

        public Task<ShadowReviewSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
        {
            SnapshotReads++;
            return Task.FromResult(_snapshot);
        }
    }

    private sealed class StaticSimulationWorkspaceClient : ISimulationWorkspaceClient
    {
        private readonly SimulationWorkspaceSnapshot _snapshot;

        public StaticSimulationWorkspaceClient(SimulationWorkspaceSnapshot snapshot)
        {
            _snapshot = snapshot;
        }

        public Task<SimulationWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(_snapshot);

        public Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default) =>
            throw new InvalidOperationException("Shadow review tests must not run simulation.");
    }

    private sealed class RecordingChartClient : IChartWorkspaceClient
    {
        public List<(string Symbol, string Interval)> Requests { get; } = [];

        public Task<ChartSnapshot> GetSnapshotAsync(
            string symbol,
            string interval,
            CancellationToken cancellationToken = default)
        {
            Requests.Add((symbol, interval));
            var at = DateTimeOffset.Parse("2026-07-23T15:00:00Z");
            return Task.FromResult(new ChartSnapshot(
                1,
                symbol,
                interval,
                ChartDataState.Available,
                at,
                at,
                "AVAILABLE | Stored chart evidence.",
                new DataLineage("Stored bars", at, "Read-only evidence."),
                [new CandleSnapshot(at, 100m, 101m, 99m, 100.5m, 1000)]));
        }
    }

    private sealed class EmptyLayoutStore : IWorkspaceLayoutStore
    {
        public Task SaveAsync(WorkspaceLayoutSnapshot snapshot, CancellationToken cancellationToken = default) =>
            Task.CompletedTask;

        public Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(WorkspaceKind workspace, CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(null);

        public Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(null);

        public Task<IReadOnlyList<WorkspaceLayoutSnapshot>> ListAsync(WorkspaceKind workspace, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<WorkspaceLayoutSnapshot>>([]);

        public Task<WorkspaceLayoutSnapshot?> LoadNamedAsync(WorkspaceKind workspace, string name, CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(null);
    }

    private sealed class ThrowingEngineClient : IEngineClient
    {
        private static Task<T> Unexpected<T>() =>
            Task.FromException<T>(new InvalidOperationException("Mock engine access is forbidden in Shadow review mode."));

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
