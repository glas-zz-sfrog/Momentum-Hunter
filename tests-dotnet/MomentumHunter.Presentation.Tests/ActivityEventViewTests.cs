using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class ActivityEventViewTests
{
    [Fact]
    public void ActivityProjectionPreservesFieldsAndConvertsTimeToUtc()
    {
        var view = ActivityEventView.From(new ActivityEvent(
            DateTimeOffset.Parse("2026-07-23T09:15:00-05:00"),
            " Readiness ",
            " Catalyst source needs review. ",
            " nvda ",
            HealthState.Degraded));

        Assert.Equal("2026-07-23 14:15:00 UTC", view.TimestampLabel);
        Assert.Equal("Readiness", view.CategoryLabel);
        Assert.Equal("Catalyst source needs review.", view.Message);
        Assert.Equal("nvda", view.ScopeLabel);
        Assert.Equal(HealthState.Degraded, view.State);
        Assert.Equal("DEGRADED", view.StateLabel);
    }

    [Fact]
    public void BlankSourceFieldsUseExplicitFallbacks()
    {
        var view = ActivityEventView.From(new ActivityEvent(
            DateTimeOffset.Parse("2026-07-23T14:00:00Z"),
            " ",
            " ",
            " ",
            HealthState.Unavailable));

        Assert.Equal("Event", view.CategoryLabel);
        Assert.Equal("No event detail was supplied.", view.Message);
        Assert.Equal("Workspace", view.ScopeLabel);
        Assert.Equal("UNAVAILABLE", view.StateLabel);
    }

    [Fact]
    public async Task ShellPreservesSourceActivityOrder()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());

        await viewModel.InitializeAsync();

        Assert.Equal(3, viewModel.ActivityRows.Count);
        Assert.Equal(
            ["Research", "Readiness", "Simulation"],
            viewModel.ActivityRows.Select(row => row.CategoryLabel));
        Assert.Equal(
            [HealthState.Healthy, HealthState.Degraded, HealthState.Healthy],
            viewModel.ActivityRows.Select(row => row.State));
        Assert.Equal("3 source events", viewModel.ActivityCountLabel);
    }

    [Fact]
    public async Task BackgroundInsertRefreshesRowsAndKeepsExistingEvents()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        var priorMessages = viewModel.ActivityRows.Select(row => row.Message).ToArray();
        var changed = new List<string?>();
        viewModel.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        viewModel.RecordBackgroundActivity(new BackgroundCollectionActivity(
            DateTimeOffset.Parse("2026-07-23T14:30:00Z"),
            "Collection blocked for source review.",
            BackgroundCollectionState.Blocked));

        Assert.Equal(4, viewModel.ActivityRows.Count);
        Assert.Equal("Collection blocked for source review.", viewModel.ActivityRows[0].Message);
        Assert.Equal("UNAVAILABLE", viewModel.ActivityRows[0].StateLabel);
        Assert.Equal("Workspace", viewModel.ActivityRows[0].ScopeLabel);
        Assert.Equal(priorMessages, viewModel.ActivityRows.Skip(1).Select(row => row.Message));
        Assert.Contains(nameof(ShellViewModel.ActivityRows), changed);
        Assert.Contains(nameof(ShellViewModel.ActivityCountLabel), changed);
    }

    [Fact]
    public async Task SimulationInsertAppearsWithoutChangingPriorSourceRows()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        await viewModel.InitializeAsync();
        var before = viewModel.ActivityRows.Count;

        await viewModel.RunPrimaryActionAsync();

        Assert.Equal(before + 1, viewModel.ActivityRows.Count);
        Assert.Equal("Simulation", viewModel.ActivityRows[0].CategoryLabel);
        Assert.Equal(HealthState.Healthy, viewModel.ActivityRows[0].State);
    }
}
