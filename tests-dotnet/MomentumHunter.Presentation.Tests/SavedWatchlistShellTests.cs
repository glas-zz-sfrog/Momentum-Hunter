using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class SavedWatchlistShellTests
{
    [Fact]
    public async Task SavedWatchlistLoadsIndependentlyAndPreservesHistoricalLabels()
    {
        var savedWatchlistClient = new StaticSavedWatchlistClient(Snapshot());
        var viewModel = new ShellViewModel(
            new MockEngineClient(),
            savedWatchlistClient);

        await viewModel.InitializeAsync();

        Assert.NotEmpty(viewModel.Candidates);
        Assert.Equal(SavedWatchlistState.Stale, viewModel.SavedWatchlist!.State);
        Assert.Equal("STALE", viewModel.SavedWatchlistStateLabel);
        Assert.Equal("watchlist-2026-06-18.json", viewModel.SavedWatchlistSourceLabel);
        Assert.Equal("1 displayed | 1 usable | 1 stored", viewModel.SavedWatchlistCountLabel);
        var row = Assert.Single(viewModel.SavedWatchlistItems);
        Assert.Equal("#2", row.RankLabel);
        Assert.Equal("CRWV", row.Symbol);
        Assert.Equal("Stored score 82", row.ScoreLabel);
        Assert.Equal("$118.50 | +0.8%", row.PriceChangeLabel);
        Assert.Equal("No operator notes stored", row.NotesLabel);
        Assert.Empty(viewModel.SavedWatchlistEmptyState);

        await viewModel.SelectCandidateAsync(viewModel.Candidates[1]);

        Assert.Equal("CRWV", Assert.Single(viewModel.SavedWatchlistItems).Symbol);
        Assert.Equal(1, savedWatchlistClient.RequestCount);
    }

    [Fact]
    public async Task FailedSavedWatchlistFailsClosedWithoutBlockingTheWorkspace()
    {
        var viewModel = new ShellViewModel(
            new MockEngineClient(),
            new FailingSavedWatchlistClient());

        await viewModel.InitializeAsync();

        Assert.NotEmpty(viewModel.Candidates);
        Assert.Equal(SavedWatchlistState.Unavailable, viewModel.SavedWatchlist!.State);
        Assert.Empty(viewModel.SavedWatchlistItems);
        Assert.Contains("No current candidate state was inferred", viewModel.SavedWatchlistSummary, StringComparison.Ordinal);
        Assert.Contains("unavailable", viewModel.SavedWatchlistEmptyState, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void PresentationUsesExplicitFallbacksForMissingStoredFields()
    {
        var row = SavedWatchlistItemViewModel.From(new SavedWatchlistItemSnapshot(
            4,
            "EQX",
            "",
            null,
            null,
            null,
            null,
            null,
            "",
            "",
            "",
            null,
            "",
            ""));

        Assert.Equal("Company unavailable", row.CompanyLabel);
        Assert.Equal("Stored score unavailable", row.ScoreLabel);
        Assert.Equal("Price unavailable | change unavailable", row.PriceChangeLabel);
        Assert.Equal("Volume unavailable | RVOL unavailable", row.VolumeLabel);
        Assert.Equal("Sector and industry unavailable", row.ClassificationLabel);
        Assert.Equal("Freshness unavailable", row.FreshnessLabel);
        Assert.Equal("Saved time unavailable", row.SavedAtLabel);
        Assert.Equal("No stored headline", row.HeadlineLabel);
        Assert.Equal("No operator notes stored", row.NotesLabel);
    }

    private static SavedWatchlistSnapshot Snapshot()
    {
        var savedAt = DateTimeOffset.Parse("2026-06-18T20:00:00Z");
        var item = new SavedWatchlistItemSnapshot(
            2,
            "CRWV",
            "CoreWeave",
            82,
            118.50m,
            0.8m,
            1_250_000,
            0.2m,
            "Technology",
            "Infrastructure",
            "STALE",
            savedAt,
            "Stored headline",
            "");
        return new SavedWatchlistSnapshot(
            1,
            SavedWatchlistState.Stale,
            DateTimeOffset.Parse("2026-07-23T15:00:00Z"),
            savedAt,
            "2026-06-18",
            "STALE | Historical source order is preserved.",
            "watchlist-2026-06-18.json",
            1,
            1,
            1,
            ["The latest saved watchlist is older than 36 hours."],
            [item]);
    }

    private sealed class StaticSavedWatchlistClient : ISavedWatchlistWorkspaceClient
    {
        private readonly SavedWatchlistSnapshot _snapshot;

        public StaticSavedWatchlistClient(SavedWatchlistSnapshot snapshot)
        {
            _snapshot = snapshot;
        }

        public int RequestCount { get; private set; }

        public Task<SavedWatchlistSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(RecordRead());

        private SavedWatchlistSnapshot RecordRead()
        {
            RequestCount++;
            return _snapshot;
        }
    }

    private sealed class FailingSavedWatchlistClient : ISavedWatchlistWorkspaceClient
    {
        public Task<SavedWatchlistSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromException<SavedWatchlistSnapshot>(new InvalidDataException("malformed source"));
    }
}
