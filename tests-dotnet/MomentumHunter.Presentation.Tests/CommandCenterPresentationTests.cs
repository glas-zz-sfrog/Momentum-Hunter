using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class CommandCenterPresentationTests
{
    private static readonly DateTimeOffset Now = DateTimeOffset.Parse("2026-08-17T16:00:00Z");

    [Fact]
    public void FreshnessIsDerivedOnlyFromTheFactualPresentationTimestamp()
    {
        var fresh = DisplayFreshnessView.From(Now.AddMinutes(-7), Now);
        var recent = DisplayFreshnessView.From(Now.AddMinutes(-45), Now);
        var seen = DisplayFreshnessView.From(Now.AddHours(-4), Now);

        Assert.Equal(DisplayFreshnessState.New, fresh.DisplayFreshnessState);
        Assert.Equal("NEW 7m", fresh.DisplayFreshnessLabel);
        Assert.Equal(DisplayFreshnessState.Recent, recent.DisplayFreshnessState);
        Assert.Equal(DisplayFreshnessState.Seen, seen.DisplayFreshnessState);
        Assert.Equal(TimeSpan.FromMinutes(7), fresh.DisplayAttentionAge);
    }

    [Fact]
    public void SourceRankAndScoreIgnoreChartShapeAndDisplayFreshnessClock()
    {
        var first = CommandCenter(
            [Ranked("source-row-b", "BBB", 2, 99), Ranked("source-row-a", "AAA", 1, 12)],
            Chart("AAA", 10m, 11m));
        var second = CommandCenter(
            [Ranked("source-row-b", "BBB", 2, 99), Ranked("source-row-a", "AAA", 1, 12)],
            Chart("AAA", 25m, 9m));

        var initial = CommandCenterProjection.Ranked(first, Now);
        var later = CommandCenterProjection.Ranked(second, Now.AddHours(3));

        Assert.Equal(new[] { "AAA", "BBB" }, initial.Select(item => item.Symbol));
        Assert.Equal(new[] { 1, 2 }, initial.Select(item => item.SourceRank));
        Assert.Equal(initial.Select(item => item.SourceRank), later.Select(item => item.SourceRank));
        Assert.Equal(initial.Select(item => item.Score), later.Select(item => item.Score));
        Assert.NotEqual(initial[0].DisplayFreshness.DisplayFreshnessState, later[0].DisplayFreshness.DisplayFreshnessState);
    }

    [Fact]
    public void AcceptedAndRejectedRetainEquivalentExactEventChartContext()
    {
        var accepted = Disposition("ACCEPTED", "event-first-eligible", "EXECUTION_ELIGIBLE", Now.AddMinutes(-20));
        var rejected = Disposition("REJECTED", "event-first-missed", "ENTRY_MISSED", Now.AddMinutes(-10));
        var snapshot = CommandCenter([Ranked("source-row-a", "AAA", 1, 92)], Chart("AAA", 10m, 11m)) with
        {
            AcceptedDispositions = [accepted],
            RejectedDispositions = [rejected],
        };

        var acceptedView = Assert.Single(CommandCenterProjection.Dispositions(snapshot.AcceptedDispositions, snapshot, Now));
        var rejectedView = Assert.Single(CommandCenterProjection.Dispositions(snapshot.RejectedDispositions, snapshot, Now));

        Assert.Equal("event-first-eligible", acceptedView.DispositionEventId);
        Assert.Equal(accepted.OccurredAt, acceptedView.DisplayMiniChart.TransitionTimestamp);
        Assert.Equal("event-first-missed", rejectedView.DispositionEventId);
        Assert.Equal(rejected.OccurredAt, rejectedView.DisplayMiniChart.TransitionTimestamp);
        Assert.Equal(acceptedView.DisplayMiniChart.Points, rejectedView.DisplayMiniChart.Points);
    }

    [Fact]
    public async Task GuardedBatchRefreshPreservesSelectionAndUsesOneHostCallPerRefresh()
    {
        var initial = CommandCenter(
            [Ranked("stable-a", "AAA", 1, 92), Ranked("stable-b", "BBB", 2, 87)],
            Chart("AAA", 10m, 11m));
        var refreshed = CommandCenter(
            [Ranked("stable-new", "NEW", 1, 95), Ranked("stable-b", "BBB", 2, 87), Ranked("stable-a", "AAA", 3, 92)],
            Chart("AAA", 10m, 11m));
        var client = new SequenceReadOnlyClient(Workspace(initial), Workspace(refreshed));
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client);
        await viewModel.InitializeAsync();
        viewModel.SelectedCommandCenterCandidate = viewModel.CommandCenterRankedCandidates.Single(item => item.StableCandidateIdentity == "stable-b");

        await viewModel.RefreshCommandCenterDisplayAsync();

        Assert.Equal(2, client.CallCount);
        Assert.Equal("stable-b", viewModel.SelectedCommandCenterCandidate?.StableCandidateIdentity);
        Assert.Equal(new[] { "stable-new", "stable-b", "stable-a" }, viewModel.CommandCenterRankedCandidates.Select(item => item.StableCandidateIdentity));
    }

    [Fact]
    public async Task HostPollingCannotMasqueradeAsOrDisplaceLifecycleChronology()
    {
        var projection = CommandCenter(
            [Ranked("source-row-a", "AAA", 1, 92)],
            Chart("AAA", 10m, 11m)) with
        {
            LifecycleEvents = [LifecycleEvent("lifecycle-first", "AAA")],
        };
        var client = new SequenceReadOnlyClient(Workspace(projection), Workspace(projection));
        var viewModel = new ShellViewModel(new ThrowingEngineClient(), client);
        await viewModel.InitializeAsync();

        for (var index = 0; index < 25; index++)
        {
            viewModel.RecordBackgroundActivity(new BackgroundCollectionActivity(
                Now.AddSeconds(index),
                "Refreshed Python Engine Host status.",
                BackgroundCollectionState.Healthy));
        }

        await viewModel.RefreshCommandCenterDisplayAsync();

        var lifecycle = Assert.Single(viewModel.CommandCenterRecentEvents);
        Assert.Equal("lifecycle-first", lifecycle.EventIdentity);
        Assert.Equal("AAA", lifecycle.Symbol);
        Assert.DoesNotContain(
            viewModel.Activity,
            item => item.Message.Contains("Python Engine Host", StringComparison.Ordinal)
                && !string.IsNullOrWhiteSpace(item.Symbol));
    }

    [Fact]
    public void MissingSourceScoreRendersAsUnavailableRatherThanZero()
    {
        var projection = CommandCenter(
            [Ranked("source-row-a", "AAA", 1, null)],
            Chart("AAA", 10m, 11m));

        var row = Assert.Single(CommandCenterProjection.Ranked(projection, Now));

        Assert.Null(row.Score);
        Assert.Equal("—", row.ScoreLabel);
    }

    [Fact]
    public void LifecycleChronologyUsesSequenceOnlyWithinSameSourceKind()
    {
        var occurredAt = Now.AddMinutes(-2);
        var events = new[]
        {
            LifecycleEvent("newest", "AAA", 1, "HOT_UNIVERSE", occurredAt.AddMinutes(1), "", ""),
            LifecycleEvent("hot-low", "AAA", 1, "HOT_UNIVERSE", occurredAt, "ZZZ", "AAA"),
            LifecycleEvent("candidate-low", "AAA", 2, "CANDIDATE_LIFECYCLE", occurredAt, "AAA", "ZZZ"),
            LifecycleEvent("candidate-tie-b", "AAA", 5, "CANDIDATE_LIFECYCLE", occurredAt, "B", "A"),
            LifecycleEvent("hot-high", "AAA", 7, "HOT_UNIVERSE", occurredAt, "STATE_2", "STATE_1"),
            LifecycleEvent("candidate-tie-a", "AAA", 5, "CANDIDATE_LIFECYCLE", occurredAt, "A", "B"),
            LifecycleEvent("candidate-high", "AAA", 9, "CANDIDATE_LIFECYCLE", occurredAt, "STATE_1", "STATE_2"),
            LifecycleEvent("candidate-no-sequence", "AAA", null, "CANDIDATE_LIFECYCLE", occurredAt),
        };
        var expected = new[]
        {
            "newest",
            "candidate-high",
            "candidate-tie-a",
            "candidate-tie-b",
            "candidate-low",
            "candidate-no-sequence",
            "hot-high",
            "hot-low",
        };

        Assert.Equal(expected, CommandCenterProjection.LifecycleEvents(events, 18).Select(item => item.EventIdentity));

        var reshuffled = events
            .Reverse()
            .Select((item, index) => item with
            {
                PreviousState = $"IGNORED_{index}",
                NextState = "ALSO_IGNORED",
            })
            .ToArray();
        Assert.Equal(expected, CommandCenterProjection.LifecycleEvents(reshuffled, 18).Select(item => item.EventIdentity));

        var unrelatedSources = new[]
        {
            LifecycleEvent("candidate", "AAA", 1, "CANDIDATE_LIFECYCLE", occurredAt),
            LifecycleEvent("hot", "AAA", 999, "HOT_UNIVERSE", occurredAt),
        };
        var swappedUnrelatedSequences = new[]
        {
            unrelatedSources[0] with { SourceSequence = 999 },
            unrelatedSources[1] with { SourceSequence = 1 },
        };
        Assert.Equal(
            new[] { "candidate", "hot" },
            CommandCenterProjection.LifecycleEvents(unrelatedSources, 18).Select(item => item.EventIdentity));
        Assert.Equal(
            new[] { "candidate", "hot" },
            CommandCenterProjection.LifecycleEvents(swappedUnrelatedSequences, 18).Select(item => item.EventIdentity));
    }

    [Fact]
    public void CommandCenterBoundaryDoesNotReferenceCandidateFreshnessScore()
    {
        var root = FindRepositoryRoot();
        var paths = new[]
        {
            Path.Combine(root, "momentum_hunter", "workstation_read_models.py"),
            Path.Combine(root, "src", "MomentumHunter.Contracts", "WorkstationContracts.cs"),
            Path.Combine(root, "src", "MomentumHunter.Presentation", "CommandCenterModels.cs"),
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "Controls", "CommandCenterView.xaml"),
        };

        foreach (var path in paths)
        {
            Assert.DoesNotContain("freshness_score", File.ReadAllText(path), StringComparison.OrdinalIgnoreCase);
        }
    }

    [Fact]
    public void HostHealthAndProjectionAvailabilityRemainDistinctSignals()
    {
        var viewModel = new ShellViewModel(new ThrowingEngineClient())
        {
            Health = new SystemHealthSnapshot(
                [new HealthComponentSnapshot("Read-only host", HealthState.Healthy, "Connected.", Now)],
                Now),
            CommandCenter = CommandCenter(
                [Ranked("source-row-a", "AAA", 1, 92)],
                Chart("AAA", 10m, 11m)) with
            {
                ProjectionState = CommandCenterEvidenceState.Unavailable,
            },
        };

        Assert.Equal("HOST HEALTHY", viewModel.CommandCenterHostHealthLabel);
        Assert.Equal("UNAVAILABLE", viewModel.CommandCenterDataHealthLabel);
    }

    private static CommandCenterSnapshot CommandCenter(
        IReadOnlyList<CommandCenterRankedCandidateSnapshot> ranked,
        CommandCenterMiniChartSeriesSnapshot chart) => new(
        Now,
        "2026-08-17",
        CommandCenterEvidenceState.Available,
        new CommandCenterSourceCoverage(
            CommandCenterEvidenceState.Available,
            CommandCenterEvidenceState.Available,
            CommandCenterEvidenceState.Available,
            CommandCenterEvidenceState.Available,
            CommandCenterEvidenceState.Available),
        [],
        "command-center-populations-v1",
        new Dictionary<string, string>(),
        [],
        [],
        [],
        ranked,
        [],
        new Dictionary<string, CommandCenterMiniChartSeriesSnapshot>(StringComparer.OrdinalIgnoreCase)
        {
            [chart.Symbol] = chart,
        },
        Now,
        "NOT_YET_AUTHORIZED");

    private static CommandCenterRankedCandidateSnapshot Ranked(
        string identity,
        string symbol,
        int rank,
        int? score) => new(
        identity,
        symbol,
        $"{symbol} Incorporated",
        rank,
        score,
        2.5m,
        21m,
        3m,
        "Stored catalyst",
        $"member-{symbol}",
        [],
        [],
        "TRACKED",
        Now.AddMinutes(-10),
        Now.AddMinutes(-7),
        "Source-ranked row.",
        "report-source",
        symbol,
        null,
        null,
        null);

    private static CommandCenterLifecycleEventSnapshot LifecycleEvent(
        string eventIdentity,
        string symbol,
        int? sourceSequence = 1,
        string sourceKind = "CANDIDATE_LIFECYCLE",
        DateTimeOffset? occurredAt = null,
        string previousState = "BREAKOUT_CONFIRMED",
        string nextState = "EXECUTION_ELIGIBLE") => new(
        eventIdentity,
        sourceKind,
        sourceSequence,
        symbol,
        occurredAt ?? Now.AddMinutes(-2),
        previousState,
        nextState,
        "Exact lifecycle event.",
        "opportunity-1",
        null,
        null,
        "setup-1");

    private static CommandCenterMiniChartSeriesSnapshot Chart(string symbol, decimal first, decimal last) => new(
        CommandCenterEvidenceState.Available,
        symbol,
        "15m",
        2,
        ["2026-08-14", "2026-08-17"],
        [
            new CommandCenterMiniChartPointSnapshot(Now.AddDays(-3), first),
            new CommandCenterMiniChartPointSnapshot(Now, last),
        ],
        "Stored canonical candles",
        Now,
        0,
        0,
        [],
        string.Empty);

    private static CommandCenterDispositionSnapshot Disposition(
        string kind,
        string eventId,
        string reachedState,
        DateTimeOffset occurredAt) => new(
        $"2026-08-17|opportunity|setup-1|{kind}",
        eventId,
        kind,
        "opportunity",
        "setup-1",
        "CONTINUATION_BREAKOUT",
        1,
        "AAA",
        "2026-08-17",
        "BREAKOUT_CONFIRMED",
        reachedState,
        occurredAt,
        eventId,
        "canonical-bars",
        "fingerprint",
        "Exact first event.");

    private static ReadOnlyWorkspaceSnapshot Workspace(CommandCenterSnapshot commandCenter) => new(
        3,
        Now,
        "Read-only Command Center snapshot.",
        [],
        [],
        new SystemHealthSnapshot([], Now),
        new AlertEvidenceSnapshot(AlertEvidenceState.Unavailable, Now, "Unavailable", 0, 0, 0, 0, [], []),
        new ReplaySnapshot("NOT_SELECTED", Now, string.Empty, "source capture", "Not selected"),
        false,
        commandCenter);

    private sealed class SequenceReadOnlyClient(params ReadOnlyWorkspaceSnapshot[] snapshots) : IReadOnlyWorkspaceClient
    {
        private int _index;
        public int CallCount { get; private set; }

        public Task<ReadOnlyWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
        {
            CallCount++;
            var snapshot = snapshots[Math.Min(_index, snapshots.Length - 1)];
            _index++;
            return Task.FromResult(snapshot);
        }
    }

    private sealed class ThrowingEngineClient : IEngineClient
    {
        private static Task<T> Unexpected<T>() => Task.FromException<T>(new InvalidOperationException("Legacy engine call is forbidden."));
        public Task<IReadOnlyList<CandidateSnapshot>> GetCandidatesAsync(CancellationToken cancellationToken = default) => Unexpected<IReadOnlyList<CandidateSnapshot>>();
        public Task<IReadOnlyList<CandleSnapshot>> GetCandlesAsync(string symbol, string interval, CancellationToken cancellationToken = default) => Unexpected<IReadOnlyList<CandleSnapshot>>();
        public Task<TradePlanSnapshot> GetTradePlanAsync(string symbol, CancellationToken cancellationToken = default) => Unexpected<TradePlanSnapshot>();
        public Task<IReadOnlyList<ActivityEvent>> GetActivityAsync(CancellationToken cancellationToken = default) => Unexpected<IReadOnlyList<ActivityEvent>>();
        public Task<SystemHealthSnapshot> GetSystemHealthAsync(CancellationToken cancellationToken = default) => Unexpected<SystemHealthSnapshot>();
        public Task<ReplaySnapshot> GetReplaySessionAsync(CancellationToken cancellationToken = default) => Unexpected<ReplaySnapshot>();
        public Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default) => Unexpected<SimulationResult>();
        public Task<TradePlanSnapshot> ResolveMissingDataAsync(string symbol, CancellationToken cancellationToken = default) => Unexpected<TradePlanSnapshot>();
    }

    private static string FindRepositoryRoot()
    {
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            if (File.Exists(Path.Combine(current.FullName, "AGENTS.md")))
            {
                return current.FullName;
            }
        }
        throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
