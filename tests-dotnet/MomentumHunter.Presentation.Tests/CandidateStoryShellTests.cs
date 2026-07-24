using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class CandidateStoryShellTests
{
    [Fact]
    public async Task CandidateSelectionLoadsReadOnlyStoryAndKeepsAnnotationsSeparate()
    {
        var client = new StaticCandidateStoryClient();
        var viewModel = new ShellViewModel(new MockEngineClient(), client);
        var candidate = Candidate("CRWV");

        await viewModel.SelectCandidateAsync(candidate);

        Assert.Equal("CRWV", viewModel.CandidateStory!.Symbol);
        Assert.Equal("Fading", viewModel.CandidateStoryOverview.Status);
        Assert.Equal("PARTIAL", viewModel.CandidateStoryOverview.State);
        var row = Assert.Single(viewModel.CandidateStoryRows);
        Assert.Equal("First seen, Latest capture", row.CaptureNote);
        Assert.Equal("Post-capture outcome: complete", row.LaterAnnotation);
        Assert.Contains("finviz", row.SourceContext, StringComparison.Ordinal);
        Assert.True(viewModel.CandidateStory.ReadOnly);
    }

    [Fact]
    public async Task OlderCandidateStoryResponseCannotOverwriteNewerSelection()
    {
        var client = new DelayedCandidateStoryClient();
        var viewModel = new ShellViewModel(new MockEngineClient(), client);

        var firstSelection = viewModel.SelectCandidateAsync(Candidate("CRWV"));
        var secondSelection = viewModel.SelectCandidateAsync(Candidate("EQX"));
        client.Complete("EQX");
        await secondSelection;
        client.Complete("CRWV");
        await firstSelection;

        Assert.Equal("EQX", viewModel.SelectedSymbol);
        Assert.Equal("EQX", viewModel.CandidateStory!.Symbol);
    }

    [Fact]
    public async Task CandidateStoryFailureFailsClosedWithoutBlockingOtherSelectionState()
    {
        var viewModel = new ShellViewModel(new MockEngineClient(), new FailingCandidateStoryClient());

        await viewModel.SelectCandidateAsync(Candidate("CRWV"));

        Assert.Equal("CRWV", viewModel.SelectedSymbol);
        Assert.Equal(CandidateStoryEvidenceState.Unavailable, viewModel.CandidateStory!.State);
        Assert.Empty(viewModel.CandidateStory.Points);
        Assert.True(viewModel.CandidateStory.ReadOnly);
        Assert.Contains("failed closed", viewModel.CandidateStory.Summary, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task InvalidCandidateStoryRequestFailsClosedInsideTheShell()
    {
        var viewModel = new ShellViewModel(
            new MockEngineClient(),
            new InvalidRequestCandidateStoryClient());

        await viewModel.SelectCandidateAsync(Candidate("../CRWV"));

        Assert.Equal(CandidateStoryEvidenceState.Unavailable, viewModel.CandidateStory!.State);
        Assert.Empty(viewModel.CandidateStory.Points);
        Assert.True(viewModel.CandidateStory.ReadOnly);
        Assert.Contains("valid ticker", viewModel.CandidateStory.Summary, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task LegacyLiveLayoutGainsHiddenLinkedCandidateStoryPane()
    {
        var legacyPanes = WorkspaceFactory.Create(WorkspaceKind.Live)
            .ToLayouts()
            .Where(pane => pane.Kind != PaneKind.CandidateStory)
            .ToArray();
        var legacy = new WorkspaceLayoutSnapshot(
            4,
            WorkspaceKind.Live,
            Guid.NewGuid(),
            DateTimeOffset.UtcNow,
            false,
            null,
            "NVDA",
            "5m",
            legacyPanes,
            string.Empty);
        var viewModel = new ShellViewModel(
            new MockEngineClient(),
            new StaticLayoutStore(legacy),
            new StaticCandidateStoryClient());

        await viewModel.InitializeAsync();

        var pane = Assert.Single(viewModel.Registry.Panes.Where(item => item.Kind == PaneKind.CandidateStory));
        Assert.False(pane.IsVisible);
        Assert.Equal(LinkGroup.A, pane.LinkGroup);
        Assert.Equal(DockRegion.Bottom, pane.DockRegion);
    }

    [Fact]
    public void CandidateStoryFormattingIsExplicitForMissingData()
    {
        var empty = Snapshot("CRWV", CandidateStoryEvidenceState.Empty, []);

        var overview = CandidateStoryOverviewView.From(empty);

        Assert.Equal("n/a", overview.Move);
        Assert.Equal("n/a -> n/a", overview.ScorePath);
        Assert.Equal("0 trusted captures", overview.CaptureCount);
    }

    [Fact]
    public void CandidateStoryPaneIsDedicatedReadOnlyAndContainsNoActionButtons()
    {
        var root = FindRepositoryRoot();
        var xaml = File.ReadAllText(
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml"));
        var paneStart = xaml.IndexOf("x:Name=\"CandidateStoryAnchor\"", StringComparison.Ordinal);
        var paneEnd = xaml.IndexOf("</avalon:LayoutAnchorablePane>", paneStart, StringComparison.Ordinal);

        Assert.True(paneStart >= 0);
        Assert.True(paneEnd > paneStart);
        var pane = xaml[paneStart..paneEnd];
        Assert.Contains("DockHeight=\"520\"", xaml[..paneEnd], StringComparison.Ordinal);
        Assert.Contains("<DataGrid", pane, StringComparison.Ordinal);
        Assert.Contains("READ ONLY", pane, StringComparison.Ordinal);
        Assert.DoesNotContain("<Button", pane, StringComparison.Ordinal);
    }

    private static CandidateSnapshot Candidate(string symbol) => new(
        symbol,
        $"{symbol} Company",
        100m,
        1m,
        1_000_000,
        2m,
        "Stored candidate",
        ReadinessState.NeedsEvidence,
        "Persisted",
        DateTimeOffset.UtcNow);

    private static CandidateStorySnapshot Snapshot(
        string symbol,
        CandidateStoryEvidenceState state,
        IReadOnlyList<CandidateStoryPointSnapshot>? points = null)
    {
        points ??=
        [
            new CandidateStoryPointSnapshot(
                1,
                $"{symbol}-story-1",
                "2026-06-17|morning|finviz|Base Momentum",
                DateTimeOffset.Parse("2026-06-17T07:00:00-05:00"),
                "2026-06-17 07:00 AM CT",
                "Jun 17",
                "morning",
                "AM",
                "finviz",
                "Base Momentum",
                "PAPER",
                "Market session",
                "Trusted active capture",
                100m,
                80m,
                35_000_000,
                2.2m,
                null,
                0m,
                null,
                "First seen, Latest capture",
                "Post-capture outcome: complete",
                "raw capture",
                "later review/outcome annotation",
                [],
                true),
        ];
        var hasPoints = points.Count > 0;
        return new CandidateStorySnapshot(
            1,
            symbol,
            state,
            DateTimeOffset.UtcNow,
            hasPoints ? DateTimeOffset.Parse("2026-06-17T07:00:00-05:00") : null,
            "Persisted trusted raw captures",
            state == CandidateStoryEvidenceState.Unavailable
                ? "UNAVAILABLE | Candidate Story failed closed."
                : $"{state.ToString().ToUpperInvariant()} | Read-only Candidate Story.",
            hasPoints ? $"{symbol} Company" : string.Empty,
            hasPoints ? "Technology" : string.Empty,
            hasPoints ? "Software" : string.Empty,
            hasPoints ? "Fading" : "Insufficient data",
            hasPoints ? "Score cooled and price fell below first seen." : "No trusted captures found.",
            hasPoints ? "Jun 17, 2026 7:00 AM CT" : "No trusted captures found",
            hasPoints ? "Jun 17, 2026 7:00 AM CT" : "No trusted captures found",
            hasPoints ? "Jun 17, 2026 7:00 AM CT" : "n/a",
            hasPoints ? 100m : null,
            hasPoints ? 100m : null,
            hasPoints ? 0m : null,
            hasPoints ? 80m : null,
            hasPoints ? 80m : null,
            hasPoints ? 80m : null,
            points.Count,
            points.Count,
            points.Count,
            points,
            hasPoints ? ["Stored evidence is partial."] : ["No trusted captures found."],
            true);
    }

    private sealed class StaticCandidateStoryClient : ICandidateStoryWorkspaceClient
    {
        public Task<CandidateStorySnapshot> GetSnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(Snapshot(symbol, CandidateStoryEvidenceState.Partial));
    }

    private sealed class FailingCandidateStoryClient : ICandidateStoryWorkspaceClient
    {
        public Task<CandidateStorySnapshot> GetSnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default) =>
            throw new InvalidDataException("Candidate Story boundary failed closed.");
    }

    private sealed class InvalidRequestCandidateStoryClient : ICandidateStoryWorkspaceClient
    {
        public Task<CandidateStorySnapshot> GetSnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default) =>
            throw new ArgumentException("Candidate Story requires a valid ticker symbol.", nameof(symbol));
    }

    private sealed class DelayedCandidateStoryClient : ICandidateStoryWorkspaceClient
    {
        private readonly Dictionary<string, TaskCompletionSource<CandidateStorySnapshot>> _requests =
            new(StringComparer.Ordinal);

        public Task<CandidateStorySnapshot> GetSnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default)
        {
            var source = new TaskCompletionSource<CandidateStorySnapshot>(
                TaskCreationOptions.RunContinuationsAsynchronously);
            _requests[symbol] = source;
            return source.Task;
        }

        public void Complete(string symbol) =>
            _requests[symbol].SetResult(Snapshot(symbol, CandidateStoryEvidenceState.Partial));
    }

    private sealed class StaticLayoutStore : IWorkspaceLayoutStore
    {
        private readonly WorkspaceLayoutSnapshot _snapshot;

        public StaticLayoutStore(WorkspaceLayoutSnapshot snapshot)
        {
            _snapshot = snapshot;
        }

        public Task SaveAsync(WorkspaceLayoutSnapshot snapshot, CancellationToken cancellationToken = default) =>
            Task.CompletedTask;

        public Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(
            WorkspaceKind workspace,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(_snapshot.Workspace == workspace ? _snapshot : null);

        public Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(_snapshot);

        public Task<IReadOnlyList<WorkspaceLayoutSnapshot>> ListAsync(
            WorkspaceKind workspace,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<WorkspaceLayoutSnapshot>>([_snapshot]);

        public Task<WorkspaceLayoutSnapshot?> LoadNamedAsync(
            WorkspaceKind workspace,
            string name,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<WorkspaceLayoutSnapshot?>(null);
    }

    private static string FindRepositoryRoot()
    {
        var current = new DirectoryInfo(AppContext.BaseDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, "MomentumHunter.Workstation.sln")))
            {
                return current.FullName;
            }
            current = current.Parent;
        }
        throw new DirectoryNotFoundException("Could not locate the Momentum Hunter repository root.");
    }
}
