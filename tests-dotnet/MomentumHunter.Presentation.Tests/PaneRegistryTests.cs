using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class PaneRegistryTests
{
    [Fact]
    public void CreateAssignsStableDistinctInstanceIdentifiers()
    {
        var registry = new PaneRegistry();

        var first = registry.Create(PaneKind.Chart, "Chart");
        var second = registry.Create(PaneKind.Chart, "Chart");

        Assert.NotEqual(Guid.Empty, first.InstanceId);
        Assert.NotEqual(first.InstanceId, second.InstanceId);
        Assert.Equal(2, registry.Panes.Count);
    }

    [Fact]
    public void SoftClosePreservesPaneAndReopenRestoresIt()
    {
        var registry = new PaneRegistry();
        var pane = registry.Create(PaneKind.TradePlan, "Trade Plan");

        Assert.True(registry.SoftClose(pane.InstanceId));
        Assert.False(pane.IsVisible);
        Assert.Same(pane, registry.Find(pane.InstanceId));

        Assert.True(registry.Reopen(pane.InstanceId));
        Assert.True(pane.IsVisible);
    }

    [Fact]
    public void RemovePermanentlyDeletesPane()
    {
        var registry = new PaneRegistry();
        var pane = registry.Create(PaneKind.Activity, "Activity");

        Assert.True(registry.Remove(pane.InstanceId));

        Assert.Null(registry.Find(pane.InstanceId));
        Assert.Empty(registry.Panes);
    }

    [Fact]
    public void LinkGroupUpdatesOnlyUnpinnedPeersInTheSameGroup()
    {
        var registry = new PaneRegistry();
        var source = registry.Create(PaneKind.Hunter, "Hunter", LinkGroup.A, symbol: "NVDA");
        var chart = registry.Create(PaneKind.Chart, "Chart", LinkGroup.A, symbol: "NVDA");
        var plan = registry.Create(PaneKind.TradePlan, "Trade Plan", LinkGroup.A, symbol: "NVDA");
        var pinned = registry.Create(PaneKind.Chart, "Pinned", LinkGroup.A, symbol: "MSFT");
        pinned.IsPinned = true;
        var unlinked = registry.Create(PaneKind.Chart, "Independent", LinkGroup.Unlinked, symbol: "AMD");
        var coordinator = new LinkGroupCoordinator(registry);

        coordinator.PublishSymbol(source.LinkGroup, "PLTR", "15m");

        Assert.Equal("PLTR", chart.Symbol);
        Assert.Equal("15m", plan.Interval);
        Assert.Equal("MSFT", pinned.Symbol);
        Assert.Equal("AMD", unlinked.Symbol);
    }

    [Theory]
    [InlineData(WorkspaceKind.Live, "Hunter", PaneKind.Activity, false)]
    [InlineData(WorkspaceKind.Replay, "Replay Timeline", PaneKind.ReplayEvents, false)]
    [InlineData(WorkspaceKind.Review, "Outcome Explorer", PaneKind.ReviewOutcomes, false)]
    public void WorkspaceFactoryCreatesExpectedDefaultPanes(WorkspaceKind workspace, string hunterTitle, PaneKind lowerPaneKind, bool lowerPaneVisible)
    {
        var registry = WorkspaceFactory.Create(workspace);

        var expectedPaneCount = workspace == WorkspaceKind.Live ? 10 : 5;
        Assert.Equal(expectedPaneCount, registry.Panes.Count);
        Assert.Equal(hunterTitle, registry.Panes.Single(pane => pane.Kind == PaneKind.Hunter).Title);
        Assert.Equal(lowerPaneVisible, registry.Panes.Single(pane => pane.Kind == lowerPaneKind).IsVisible);
        Assert.False(registry.Panes.Single(pane => pane.Kind == PaneKind.Diagnostics).IsVisible);
    }

    [Fact]
    public void LiveWorkspaceKeepsResearchAndWatchlistAvailableAsHiddenPanes()
    {
        var registry = WorkspaceFactory.Create(WorkspaceKind.Live);

        Assert.False(registry.Panes.Single(pane => pane.Kind == PaneKind.Research).IsVisible);
        Assert.False(registry.Panes.Single(pane => pane.Kind == PaneKind.Watchlist).IsVisible);
    }

    [Fact]
    public void LiveWorkspaceKeepsAutomationOrdersAndPositionsAsHiddenInformationalPanes()
    {
        var registry = WorkspaceFactory.Create(WorkspaceKind.Live);

        foreach (var kind in new[] { PaneKind.Automation, PaneKind.Orders, PaneKind.Positions })
        {
            var pane = registry.Panes.Single(candidate => candidate.Kind == kind);
            Assert.False(pane.IsVisible);
            Assert.Equal(LinkGroup.Unlinked, pane.LinkGroup);
            Assert.Equal(DockRegion.Bottom, pane.DockRegion);
        }
    }

    [Fact]
    public async Task AutosaveDebouncesRapidLayoutChanges()
    {
        var store = new InMemoryLayoutStore();
        var coordinator = new LayoutAutosaveCoordinator(
            store,
            () => CreateSnapshot("NVDA"),
            TimeSpan.FromMilliseconds(25));

        coordinator.RequestSave();
        coordinator.RequestSave();
        await Task.Delay(125);

        Assert.Single(store.Saved);
    }

    [Fact]
    public async Task ShellRestoresLastKnownLayoutAndCanSaveNamedLayout()
    {
        var store = new InMemoryLayoutStore(CreateSnapshot("PLTR") with { Checksum = "layout-ignored-by-memory-store" });
        var viewModel = new ShellViewModel(new MockEngineClient(), store);

        await viewModel.InitializeAsync();
        await viewModel.SaveNamedLayoutAsync("Operator Layout");
        await viewModel.SelectCandidateAsync(viewModel.Candidates.Single(candidate => candidate.Symbol == "NVDA"));
        await viewModel.RestoreNamedLayoutAsync("Operator Layout");

        Assert.Equal("PLTR", viewModel.SelectedSymbol);
        Assert.Contains(store.Saved, snapshot => snapshot.IsNamedLayout && snapshot.Name == "Operator Layout");
    }

    [Fact]
    public async Task ShellRestoresPersistedSecondaryChartContext()
    {
        var chartBId = Guid.NewGuid();
        var snapshot = CreateSnapshot("NVDA") with
        {
            Panes =
            [
                new PaneLayout(Guid.NewGuid(), PaneKind.Chart, "Chart", LinkGroup.A, "NVDA", "5m", false, true, DockRegion.Center, 0, null, null),
                new PaneLayout(chartBId, PaneKind.Chart, "Chart", LinkGroup.B, "MSTR", "15m", false, true, DockRegion.Center, 1, null, null),
            ],
        };
        var viewModel = new ShellViewModel(new MockEngineClient(), new InMemoryLayoutStore(snapshot));

        await viewModel.InitializeAsync();

        var chartB = Assert.Single(viewModel.SecondaryCharts);
        Assert.Equal(chartBId, chartB.Pane.InstanceId);
        Assert.Equal(LinkGroup.B, chartB.Pane.LinkGroup);
        Assert.Equal("MSTR", chartB.Pane.Symbol);
        Assert.Equal("15m", chartB.Pane.Interval);
    }

    [Fact]
    public async Task ShellRestoresMostRecentWorkspaceInsteadOfAlwaysStartingLive()
    {
        var live = CreateSnapshot("NVDA") with { CreatedAt = DateTimeOffset.Parse("2026-07-13T12:00:00Z") };
        var replay = CreateSnapshot("PLTR") with
        {
            Workspace = WorkspaceKind.Replay,
            CreatedAt = DateTimeOffset.Parse("2026-07-13T15:00:00Z"),
        };
        var viewModel = new ShellViewModel(new MockEngineClient(), new InMemoryLayoutStore(live, replay));

        await viewModel.InitializeAsync();

        Assert.Equal(WorkspaceKind.Replay, viewModel.Workspace);
        Assert.Equal("PLTR", viewModel.SelectedSymbol);
    }

    [Fact]
    public async Task ShellMigratesLegacyLiveLayoutWithNewContextualPanesOnce()
    {
        var legacyLiveLayout = CreateSnapshot("NVDA") with { SchemaVersion = 3 };
        var viewModel = new ShellViewModel(new MockEngineClient(), new InMemoryLayoutStore(legacyLiveLayout));

        await viewModel.InitializeAsync();

        foreach (var kind in new[] { PaneKind.Automation, PaneKind.Orders, PaneKind.Positions })
        {
            Assert.False(viewModel.Registry.Panes.Single(pane => pane.Kind == kind).IsVisible);
        }
    }

    [Fact]
    public async Task ShellDoesNotRecreateContextualPanesRemovedFromCurrentLayout()
    {
        var currentLayoutWithoutContextualPanes = CreateSnapshot("NVDA") with { SchemaVersion = 4 };
        var viewModel = new ShellViewModel(new MockEngineClient(), new InMemoryLayoutStore(currentLayoutWithoutContextualPanes));

        await viewModel.InitializeAsync();

        Assert.DoesNotContain(viewModel.Registry.Panes, pane => pane.Kind == PaneKind.Automation);
        Assert.DoesNotContain(viewModel.Registry.Panes, pane => pane.Kind == PaneKind.Orders);
        Assert.DoesNotContain(viewModel.Registry.Panes, pane => pane.Kind == PaneKind.Positions);
    }

    [Fact]
    public void PaneRegistryRaisesChangedForPanePropertyAndPermanentRemoval()
    {
        var registry = new PaneRegistry();
        var notifications = 0;
        registry.Changed += (_, _) => notifications++;
        var pane = registry.Create(PaneKind.Chart, "Chart");

        pane.IsPinned = true;
        registry.Remove(pane.InstanceId);

        Assert.True(notifications >= 3);
    }

    [Fact]
    public void SoftClosePersistsPaneIdentityWhilePermanentRemoveDoesNot()
    {
        var registry = new PaneRegistry();
        var softClosed = registry.Create(PaneKind.Chart, "Chart B", LinkGroup.B, symbol: "MSTR", interval: "Daily");
        softClosed.IsPinned = true;
        softClosed.SoftClosedDockLayoutXml = "<LayoutRoot><LayoutDocument ContentId=\"chart-b\" /></LayoutRoot>";
        Assert.True(registry.SoftClose(softClosed.InstanceId));

        var restored = new PaneRegistry();
        restored.Restore(registry.ToLayouts());
        var retained = Assert.Single(restored.Panes);
        Assert.Equal(softClosed.InstanceId, retained.InstanceId);
        Assert.Equal("MSTR", retained.Symbol);
        Assert.Equal("Daily", retained.Interval);
        Assert.True(retained.IsPinned);
        Assert.False(retained.IsVisible);
        Assert.Equal(softClosed.SoftClosedDockLayoutXml, retained.SoftClosedDockLayoutXml);

        Assert.True(registry.Remove(softClosed.InstanceId));
        Assert.Empty(registry.ToLayouts());
    }

    [Fact]
    public async Task DiagnosticsPaneStartsHiddenAndCanBeToggledWithoutASeparateRoute()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();

        viewModel.ToggleDiagnosticsCommand.Execute(null);

        Assert.True(viewModel.IsDiagnosticsOpen);
        Assert.True(viewModel.Registry.Panes.Single(pane => pane.Kind == PaneKind.Diagnostics).IsVisible);
    }

    private static WorkspaceLayoutSnapshot CreateSnapshot(string symbol) => new(
        1,
        WorkspaceKind.Live,
        Guid.NewGuid(),
        DateTimeOffset.UtcNow,
        false,
        null,
        symbol,
        "5m",
        [new PaneLayout(Guid.NewGuid(), PaneKind.Chart, "Chart", LinkGroup.A, symbol, "5m", false, true, DockRegion.Center, 0, null, null)],
        string.Empty);

    private sealed class InMemoryLayoutStore : IWorkspaceLayoutStore
    {
        private readonly List<WorkspaceLayoutSnapshot> _existing;

        public InMemoryLayoutStore(params WorkspaceLayoutSnapshot[] existing)
        {
            _existing = existing.ToList();
        }

        public List<WorkspaceLayoutSnapshot> Saved { get; } = [];

        public Task SaveAsync(WorkspaceLayoutSnapshot snapshot, CancellationToken cancellationToken = default)
        {
            Saved.Add(snapshot);
            return Task.CompletedTask;
        }

        public Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(WorkspaceKind workspace, CancellationToken cancellationToken = default) =>
            Task.FromResult(_existing.FirstOrDefault(snapshot => snapshot.Workspace == workspace));

        public Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(_existing.OrderByDescending(snapshot => snapshot.CreatedAt).FirstOrDefault());

        public Task<IReadOnlyList<WorkspaceLayoutSnapshot>> ListAsync(WorkspaceKind workspace, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<WorkspaceLayoutSnapshot>>(_existing.Where(snapshot => snapshot.Workspace == workspace).ToArray());

        public Task<WorkspaceLayoutSnapshot?> LoadNamedAsync(WorkspaceKind workspace, string name, CancellationToken cancellationToken = default) =>
            Task.FromResult(_existing.Concat(Saved).FirstOrDefault(snapshot => snapshot.Workspace == workspace && snapshot.IsNamedLayout && snapshot.Name == name));
    }
}
