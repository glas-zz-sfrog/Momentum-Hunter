using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class TechnicalResearchViewTests
{
    [Fact]
    public void OverviewPreservesStateCountsSourceTimeAndWarnings()
    {
        var view = TechnicalResearchOverviewView.From(Snapshot("NVDA", TechnicalResearchState.Stale));

        Assert.Equal(TechnicalResearchState.Stale, view.State);
        Assert.Equal("STALE", view.StateLabel);
        Assert.Equal("NVDA", view.SymbolLabel);
        Assert.Equal("Source as of 2026-07-23 14:30:00 UTC", view.AsOfLabel);
        Assert.Contains("2 symbol events", view.CountSummary, StringComparison.Ordinal);
        Assert.Contains("1 studied outcomes", view.CountSummary, StringComparison.Ordinal);
        Assert.Equal("Stored events + studies", view.SourceLabel);
        Assert.Equal("Stored report warning.", view.WarningSummary);
    }

    [Fact]
    public void EventRowFormatsStoredMetricsAndHonestFallbacks()
    {
        var complete = TechnicalResearchEventRowView.From(Snapshot("NVDA").Events[0]);
        var missing = TechnicalResearchEventRowView.From(new TechnicalResearchEventSnapshot(
            string.Empty,
            null,
            string.Empty,
            string.Empty,
            string.Empty,
            string.Empty,
            string.Empty,
            null,
            null,
            null,
            null,
            null,
            string.Empty));

        Assert.Equal("2026-07-23", complete.TimestampLabel);
        Assert.Equal("Donchian 20 Day Breakout", complete.TypeLabel);
        Assert.Equal("DAILY", complete.TimeframeLabel);
        Assert.Contains("Trigger $125.50", complete.MetricsLabel, StringComparison.Ordinal);
        Assert.Contains("Distance +1.25%", complete.MetricsLabel, StringComparison.Ordinal);
        Assert.Contains("RVOL 2.25x", complete.MetricsLabel, StringComparison.Ordinal);
        Assert.Contains("Volume YES", complete.MetricsLabel, StringComparison.Ordinal);
        Assert.Contains("Relative strength NO", complete.MetricsLabel, StringComparison.Ordinal);
        Assert.Equal("Event time unavailable", missing.TimestampLabel);
        Assert.Equal("Event Type Unavailable", missing.TypeLabel);
        Assert.Equal("ID unavailable", missing.EventIdLabel);
        Assert.Contains("unavailable", missing.MetricsLabel, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void StudyRowPreservesReturnsExcursionsAndFailureFlags()
    {
        var view = TechnicalResearchStudyRowView.From(Snapshot("NVDA").Studies[0]);

        Assert.Contains("1d +1.00%", view.ReturnsLabel, StringComparison.Ordinal);
        Assert.Contains("5d +4.50%", view.ReturnsLabel, StringComparison.Ordinal);
        Assert.Contains("10d -1.00%", view.ReturnsLabel, StringComparison.Ordinal);
        Assert.Contains("MFE +6.00%", view.ExcursionLabel, StringComparison.Ordinal);
        Assert.Contains("MAE -2.00%", view.ExcursionLabel, StringComparison.Ordinal);
        Assert.Contains("Held NO", view.FlagsLabel, StringComparison.Ordinal);
        Assert.Contains("Failed YES", view.FlagsLabel, StringComparison.Ordinal);
        Assert.Contains("Extended NO", view.FlagsLabel, StringComparison.Ordinal);
    }

    [Fact]
    public async Task CandidateSelectionRefreshesResearchForTheSelectedSymbol()
    {
        var client = new RecordingResearchClient();
        var viewModel = new ShellViewModel(new MockEngineClient(), client);

        await viewModel.InitializeAsync();
        var target = viewModel.Candidates.Single(candidate => candidate.Symbol == "PLTR");
        await viewModel.SelectCandidateAsync(target);

        Assert.Equal("PLTR", viewModel.TechnicalResearchOverview.SymbolLabel);
        Assert.Equal(["NVDA", "PLTR"], client.Symbols);
        Assert.Single(viewModel.TechnicalResearchEventRows);
        Assert.True(viewModel.HasTechnicalResearchEvents);
        Assert.True(viewModel.HasTechnicalResearchStudies);
    }

    [Fact]
    public async Task ResearchFailureFailsClosedWithoutFallbackRows()
    {
        var viewModel = new ShellViewModel(new MockEngineClient(), new FailingResearchClient());

        await viewModel.InitializeAsync();

        Assert.Equal(TechnicalResearchState.Unavailable, viewModel.TechnicalResearchOverview.State);
        Assert.Empty(viewModel.TechnicalResearchEventRows);
        Assert.Empty(viewModel.TechnicalResearchStudyRows);
        Assert.Contains("could not be loaded", viewModel.TechnicalResearchOverview.Summary, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("unavailable", viewModel.TechnicalResearchEventsEmptyLabel, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task OlderResearchResponseCannotOverwriteTheNewestCandidateSelection()
    {
        var client = new OutOfOrderResearchClient();
        var viewModel = new ShellViewModel(new MockEngineClient(), client);
        await viewModel.InitializeAsync();
        var first = viewModel.Candidates.Single(candidate => candidate.Symbol == "PLTR");
        var newest = viewModel.Candidates.Single(candidate => candidate.Symbol == "CRWD");

        var firstSelection = viewModel.SelectCandidateAsync(first);
        await client.WaitUntilRequestedAsync("PLTR");
        var newestSelection = viewModel.SelectCandidateAsync(newest);
        await client.WaitUntilRequestedAsync("CRWD");
        client.Complete("CRWD");
        await newestSelection;
        client.Complete("PLTR");
        await firstSelection;

        Assert.Equal("CRWD", viewModel.SelectedSymbol);
        Assert.Equal("CRWD", viewModel.TechnicalResearchOverview.SymbolLabel);
    }

    private static TechnicalResearchSnapshot Snapshot(
        string symbol,
        TechnicalResearchState state = TechnicalResearchState.Available) => new(
        1,
        symbol,
        state,
        DateTimeOffset.Parse("2026-07-23T15:00:00Z"),
        DateTimeOffset.Parse("2026-07-23T14:30:00Z"),
        "Stored technical research only.",
        "Stored events + studies",
        23860,
        23857,
        2,
        1,
        1,
        1,
        0,
        ["Stored report warning."],
        [
            new TechnicalResearchEventSnapshot(
                "event-1",
                DateTimeOffset.Parse("2026-07-23T00:00:00Z"),
                "donchian_20_day_breakout",
                "daily",
                "Breakout present",
                "HIGH",
                "Sufficient",
                125.50m,
                1.25m,
                2.25m,
                true,
                false,
                "Stored event note.")
        ],
        [
            new TechnicalResearchStudySnapshot(
                "event-1",
                DateTimeOffset.Parse("2026-07-23T00:00:00Z"),
                "donchian_20_day_breakout",
                "daily",
                "Breakout failed",
                "Sufficient",
                null,
                null,
                null,
                1.00m,
                4.50m,
                -1.00m,
                6.00m,
                -2.00m,
                false,
                true,
                false,
                true,
                "No study notes were stored.")
        ]);

    private sealed class RecordingResearchClient : ITechnicalResearchWorkspaceClient
    {
        public List<string> Symbols { get; } = [];

        public Task<TechnicalResearchSnapshot> GetSnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default)
        {
            Symbols.Add(symbol);
            return Task.FromResult(Snapshot(symbol));
        }
    }

    private sealed class FailingResearchClient : ITechnicalResearchWorkspaceClient
    {
        public Task<TechnicalResearchSnapshot> GetSnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default) =>
            Task.FromException<TechnicalResearchSnapshot>(new InvalidDataException("research host unavailable"));
    }

    private sealed class OutOfOrderResearchClient : ITechnicalResearchWorkspaceClient
    {
        private readonly Dictionary<string, TaskCompletionSource<TechnicalResearchSnapshot>> _responses =
            new(StringComparer.Ordinal);

        public Task<TechnicalResearchSnapshot> GetSnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default)
        {
            if (string.Equals(symbol, "NVDA", StringComparison.Ordinal))
            {
                return Task.FromResult(Snapshot(symbol));
            }

            var response = new TaskCompletionSource<TechnicalResearchSnapshot>(
                TaskCreationOptions.RunContinuationsAsynchronously);
            _responses.Add(symbol, response);
            return response.Task;
        }

        public async Task WaitUntilRequestedAsync(string symbol)
        {
            while (!_responses.ContainsKey(symbol))
            {
                await Task.Yield();
            }
        }

        public void Complete(string symbol) =>
            _responses[symbol].SetResult(Snapshot(symbol));
    }
}
