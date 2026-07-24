using MomentumHunter.Application;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class MonitoringStatusTests
{
    [Fact]
    public void StartingStateIsExplicitBeforeTheFirstStatusUpdate()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());

        Assert.Equal("STARTING", viewModel.MonitoringStatus.StateLabel);
        Assert.Equal("0 monitored symbols", viewModel.MonitoringStatus.MonitoredSymbolsLabel);
        Assert.Equal("0 completed cycles", viewModel.MonitoringStatus.CompletedCyclesLabel);
        Assert.Equal("No completed scan recorded", viewModel.MonitoringStatus.LastCompletedLabel);
    }

    [Fact]
    public void HealthyStatusShowsCountsAndUtcCompletionTime()
    {
        var status = new BackgroundCollectionStatus(
            BackgroundCollectionState.Healthy,
            DateTimeOffset.Parse("2026-07-23T09:15:00-05:00"),
            22,
            61,
            "Monitoring normally.");

        var view = MonitoringStatusView.From(status);

        Assert.Equal("HEALTHY", view.StateLabel);
        Assert.Equal("22 monitored symbols", view.MonitoredSymbolsLabel);
        Assert.Equal("61 completed cycles", view.CompletedCyclesLabel);
        Assert.Equal("2026-07-23 14:15:00 UTC", view.LastCompletedLabel);
        Assert.Contains("22 symbols", view.Summary, StringComparison.Ordinal);
        Assert.Equal("Monitoring normally.", view.SourceDetail);
    }

    [Fact]
    public void DegradedStatusPreservesProviderDetail()
    {
        var view = MonitoringStatusView.From(new BackgroundCollectionStatus(
            BackgroundCollectionState.Degraded,
            DateTimeOffset.Parse("2026-07-23T14:00:00Z"),
            7,
            3,
            "Minute-bar source is delayed."));

        Assert.Equal("DEGRADED", view.StateLabel);
        Assert.Contains("limited data", view.Summary, StringComparison.OrdinalIgnoreCase);
        Assert.Equal("Minute-bar source is delayed.", view.SourceDetail);
    }

    [Theory]
    [InlineData(BackgroundCollectionState.Paused, "PAUSED")]
    [InlineData(BackgroundCollectionState.Blocked, "BLOCKED")]
    [InlineData(BackgroundCollectionState.Stopping, "STOPPING")]
    public void NonHealthyStatesRemainDistinct(
        BackgroundCollectionState state,
        string expectedLabel)
    {
        var view = MonitoringStatusView.From(new BackgroundCollectionStatus(
            state,
            null,
            1,
            1,
            $"{state} source detail."));

        Assert.Equal(expectedLabel, view.StateLabel);
        Assert.Equal("1 monitored symbol", view.MonitoredSymbolsLabel);
        Assert.Equal("1 completed cycle", view.CompletedCyclesLabel);
        Assert.Equal("No completed scan recorded", view.LastCompletedLabel);
    }

    [Fact]
    public void ShellPublishesMonitoringStatusWithoutChangingLifecycleCommands()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        var changed = new List<string?>();
        viewModel.PropertyChanged += (_, args) => changed.Add(args.PropertyName);
        var status = new BackgroundCollectionStatus(
            BackgroundCollectionState.Paused,
            null,
            5,
            2,
            "Operator paused monitoring.");

        viewModel.UpdateBackgroundStatus(status);

        Assert.Contains(nameof(ShellViewModel.MonitoringStatus), changed);
        Assert.Equal("PAUSED", viewModel.MonitoringStatus.StateLabel);
        Assert.Equal("Monitoring: Paused", viewModel.BackgroundStatusLabel);
        Assert.True(viewModel.IsMonitoringPaused);
        Assert.Equal("Resume Monitoring", viewModel.MonitoringToggleLabel);
    }
}
