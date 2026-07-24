using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class ReplayContextTests
{
    [Fact]
    public void MissingSnapshotIsExplicitlyUnavailable()
    {
        var context = ReplayContextView.From(null);

        Assert.Equal("UNAVAILABLE", context.StatusLabel);
        Assert.Equal("Replay identity unavailable", context.ReplayIdLabel);
        Assert.Equal("Symbol not selected", context.SymbolLabel);
        Assert.Equal("Interval unavailable", context.IntervalLabel);
        Assert.Equal("Replay time unavailable", context.AsOfLabel);
    }

    [Fact]
    public void NotSelectedSnapshotPreservesSourceStateWithoutInventingIdentity()
    {
        var at = DateTimeOffset.Parse("2026-07-23T09:15:00-05:00");
        var context = ReplayContextView.From(new ReplaySnapshot(
            "NOT_SELECTED",
            at,
            string.Empty,
            "source capture",
            "No candidate replay identity was synthesized."));

        Assert.Equal("NOT SELECTED", context.StatusLabel);
        Assert.Equal("NOT_SELECTED", context.ReplayIdLabel);
        Assert.Equal("Symbol not selected", context.SymbolLabel);
        Assert.Equal("source capture", context.IntervalLabel);
        Assert.Equal("2026-07-23 14:15:00 UTC", context.AsOfLabel);
        Assert.Equal("No candidate replay identity was synthesized.", context.Summary);
    }

    [Fact]
    public void AvailableSnapshotExposesExactReadOnlyIdentity()
    {
        var context = ReplayContextView.From(new ReplaySnapshot(
            "capture-20260722-153000-NVDA",
            DateTimeOffset.Parse("2026-07-22T15:30:00Z"),
            "NVDA",
            "5m",
            "Stored replay context loaded."));

        Assert.Equal("AVAILABLE", context.StatusLabel);
        Assert.Equal("capture-20260722-153000-NVDA", context.ReplayIdLabel);
        Assert.Equal("NVDA", context.SymbolLabel);
        Assert.Equal("5m", context.IntervalLabel);
        Assert.Equal("2026-07-22 15:30:00 UTC", context.AsOfLabel);
        Assert.Equal("Stored replay context loaded.", context.Summary);
    }

    [Fact]
    public void UnavailableAndBlankFieldsRemainHonest()
    {
        var context = ReplayContextView.From(new ReplaySnapshot(
            " unavailable ",
            DateTimeOffset.Parse("2026-07-23T14:00:00Z"),
            " ",
            " ",
            " "));

        Assert.Equal("UNAVAILABLE", context.StatusLabel);
        Assert.Equal("unavailable", context.ReplayIdLabel);
        Assert.Equal("Symbol not selected", context.SymbolLabel);
        Assert.Equal("Interval unavailable", context.IntervalLabel);
        Assert.Equal("No replay summary was supplied.", context.Summary);
    }

    [Fact]
    public async Task ShellPublishesReplayContextWhenReplaySnapshotChanges()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        var changed = new List<string?>();
        viewModel.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        await viewModel.InitializeAsync();

        Assert.Contains(nameof(ShellViewModel.ReplayContext), changed);
        Assert.Equal("AVAILABLE", viewModel.ReplayContext.StatusLabel);
        Assert.False(string.IsNullOrWhiteSpace(viewModel.ReplayContext.ReplayIdLabel));
        Assert.False(string.IsNullOrWhiteSpace(viewModel.ReplayContext.Summary));
    }
}
