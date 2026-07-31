using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class CommandPaletteTests
{
    [Fact]
    public async Task EmptyPaletteShowsAdvertisedActionsAndCurrentCandidates()
    {
        var viewModel = await InitializedViewModel();

        viewModel.OpenCommandPalette();

        Assert.True(viewModel.IsCommandPaletteOpen);
        Assert.True(viewModel.HasCommandPaletteResults);
        Assert.Contains(viewModel.CommandPaletteResults, item => item.Action == CommandPaletteAction.AddChart);
        Assert.Contains(viewModel.CommandPaletteResults, item => item.Action == CommandPaletteAction.OpenPositions);
        Assert.Contains(viewModel.CommandPaletteResults, item => item.Action == CommandPaletteAction.ToggleActivity);
        Assert.Contains(viewModel.CommandPaletteResults, item => item.Action == CommandPaletteAction.ViewDiagnostics);
        Assert.Contains(viewModel.CommandPaletteResults, item => item.Symbol == "NVDA");
        Assert.Same(viewModel.CommandPaletteResults[0], viewModel.SelectedCommandPaletteItem);
        Assert.Contains(
            $"{viewModel.Candidates.Count} current Hunter symbols",
            viewModel.CommandPaletteScopeLabel,
            StringComparison.Ordinal);
    }

    [Fact]
    public async Task CandidateFilteringIsCaseInsensitiveAndRanksExactSymbolFirst()
    {
        var viewModel = await InitializedViewModel();

        viewModel.OpenCommandPalette("pltr");

        var first = Assert.IsType<CommandPaletteItem>(viewModel.SelectedCommandPaletteItem);
        Assert.Equal(CommandPaletteAction.OpenCandidate, first.Action);
        Assert.Equal("PLTR", first.Symbol);
        Assert.Contains("Palantir", first.Title, StringComparison.Ordinal);
    }

    [Fact]
    public async Task PartialCompanyQueryFiltersWithoutBecomingAnExactQuickOpen()
    {
        var viewModel = await InitializedViewModel();

        viewModel.OpenCommandPalette("lant");

        var first = Assert.IsType<CommandPaletteItem>(viewModel.SelectedCommandPaletteItem);
        Assert.Equal("PLTR", first.Symbol);
        Assert.Null(viewModel.FindExactCommandPaletteItem("lant"));
    }

    [Fact]
    public async Task ExactSymbolQuickOpenUsesExistingCandidateSelectionWorkflow()
    {
        var viewModel = await InitializedViewModel();
        var item = Assert.IsType<CommandPaletteItem>(viewModel.FindExactCommandPaletteItem("amd"));
        viewModel.OpenCommandPalette("amd");

        var result = await viewModel.ExecuteCommandPaletteItemAsync(item);

        Assert.True(result.Executed);
        Assert.Equal(CommandPaletteAction.OpenCandidate, result.Action);
        Assert.Equal("AMD", viewModel.SelectedSymbol);
        Assert.Equal("AMD", viewModel.SelectedCandidate?.Symbol);
        Assert.False(viewModel.IsCommandPaletteOpen);
        Assert.Equal(string.Empty, viewModel.CommandQuery);
        Assert.Contains("Opened candidate AMD", viewModel.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public async Task AddChartCommandUsesExistingLinkedChartWorkflow()
    {
        var viewModel = await InitializedViewModel();
        var item = Assert.IsType<CommandPaletteItem>(viewModel.FindExactCommandPaletteItem("new chart"));

        var result = await viewModel.ExecuteCommandPaletteItemAsync(item);

        Assert.True(result.Executed);
        Assert.Equal(CommandPaletteAction.AddChart, result.Action);
        Assert.NotNull(result.AddedPane);
        Assert.Equal(viewModel.SelectedSymbol, result.AddedPane.Symbol);
        Assert.Contains(viewModel.SecondaryCharts, chart => chart.Pane.InstanceId == result.AddedPane.InstanceId);
    }

    [Fact]
    public async Task ActivityAndDiagnosticsCommandsUpdateExistingPaneState()
    {
        var viewModel = await InitializedViewModel();
        var activity = Assert.IsType<CommandPaletteItem>(viewModel.FindExactCommandPaletteItem("activity"));
        var diagnostics = Assert.IsType<CommandPaletteItem>(viewModel.FindExactCommandPaletteItem("diagnostics"));

        var activityResult = await viewModel.ExecuteCommandPaletteItemAsync(activity);
        var diagnosticsResult = await viewModel.ExecuteCommandPaletteItemAsync(diagnostics);

        Assert.True(activityResult.Executed);
        Assert.True(viewModel.IsActivityOpen);
        Assert.True(diagnosticsResult.Executed);
        Assert.True(viewModel.IsDiagnosticsOpen);
        Assert.True(viewModel.Registry.Panes.Single(pane => pane.Kind == Contracts.PaneKind.Diagnostics).IsVisible);
    }

    [Fact]
    public async Task NoMatchAndStaleCandidateFailVisiblyWithoutClosingPalette()
    {
        var viewModel = await InitializedViewModel();
        viewModel.OpenCommandPalette("zzzz");

        var noMatch = await viewModel.ExecuteCommandPaletteItemAsync();

        Assert.False(noMatch.Executed);
        Assert.True(viewModel.IsCommandPaletteOpen);
        Assert.False(viewModel.HasCommandPaletteResults);
        Assert.Contains("'zzzz' is not in the current Hunter list", viewModel.StatusMessage, StringComparison.Ordinal);
        var examples = string.Join(", ", viewModel.Candidates.Take(3).Select(candidate => candidate.Symbol));
        Assert.Contains(examples, viewModel.CommandPaletteEmptyText, StringComparison.Ordinal);

        var stale = Assert.IsType<CommandPaletteItem>(viewModel.FindExactCommandPaletteItem("NVDA"));
        viewModel.Candidates.Clear();
        var staleResult = await viewModel.ExecuteCommandPaletteItemAsync(stale);

        Assert.False(staleResult.Executed);
        Assert.True(viewModel.IsCommandPaletteOpen);
        Assert.Contains("no longer available", viewModel.StatusMessage, StringComparison.Ordinal);
    }

    [Fact]
    public void CatalogRejectsInvalidLimit()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => CommandPaletteCatalog.Filter([], string.Empty, 0));
    }

    [Fact]
    public void WorkstationHostsPaletteInsideMainWindowAcrossActivationChanges()
    {
        var root = FindRepositoryRoot();
        var xaml = File.ReadAllText(
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml"));
        var codeBehind = File.ReadAllText(
            Path.Combine(root, "src", "MomentumHunter.Desktop.Wpf", "MainWindow.xaml.cs"));

        Assert.Contains("x:Name=\"CommandPaletteOverlay\"", xaml, StringComparison.Ordinal);
        Assert.Contains("Grid.RowSpan=\"3\"", xaml, StringComparison.Ordinal);
        Assert.Contains("Binding IsCommandPaletteOpen", xaml, StringComparison.Ordinal);
        Assert.Contains("Activated=\"Window_Activated\"", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("x:Name=\"CommandPalettePopup\"", xaml, StringComparison.Ordinal);
        Assert.Contains("private void Window_Activated", codeBehind, StringComparison.Ordinal);
        Assert.Contains("FocusCommandPaletteSearch();", codeBehind, StringComparison.Ordinal);
    }

    private static async Task<ShellViewModel> InitializedViewModel()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        return viewModel;
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
