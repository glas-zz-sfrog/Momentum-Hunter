using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class HealthDiagnosticsTests
{
    [Fact]
    public void MissingSnapshotIsExplicitlyUnavailable()
    {
        var diagnostics = HealthDiagnosticsView.From(null);

        Assert.Equal("UNAVAILABLE", diagnostics.StatusLabel);
        Assert.Equal("No system health snapshot is available.", diagnostics.Summary);
        Assert.Equal("Snapshot time unavailable", diagnostics.CheckedAtLabel);
        Assert.Empty(diagnostics.Components);
    }

    [Fact]
    public void HealthySnapshotPreservesSourceOrderAndConvertsTimesToUtc()
    {
        var snapshot = new SystemHealthSnapshot(
            [
                new HealthComponentSnapshot(
                    "Trade planning report",
                    HealthState.Healthy,
                    "Persisted report loaded.",
                    DateTimeOffset.Parse("2026-07-23T09:05:00-05:00")),
                new HealthComponentSnapshot(
                    "Active monitor",
                    HealthState.Healthy,
                    "One cycle completed.",
                    DateTimeOffset.Parse("2026-07-23T09:06:00-05:00")),
            ],
            DateTimeOffset.Parse("2026-07-23T09:07:00-05:00"));

        var diagnostics = HealthDiagnosticsView.From(snapshot);

        Assert.Equal("HEALTHY", diagnostics.StatusLabel);
        Assert.Equal("2 components | 2 healthy | 0 degraded | 0 unavailable", diagnostics.Summary);
        Assert.Equal("Snapshot checked 2026-07-23 14:07:00 UTC", diagnostics.CheckedAtLabel);
        Assert.Equal(["Trade planning report", "Active monitor"], diagnostics.Components.Select(component => component.Name));
        Assert.Equal("Checked 2026-07-23 14:05:00 UTC", diagnostics.Components[0].CheckedAtLabel);
    }

    [Fact]
    public void MixedSnapshotKeepsExactComponentStatesAndUsesDegradedOverallState()
    {
        var at = DateTimeOffset.Parse("2026-07-23T14:00:00Z");
        var snapshot = new SystemHealthSnapshot(
            [
                new HealthComponentSnapshot("Report", HealthState.Healthy, "Loaded.", at),
                new HealthComponentSnapshot("Monitor", HealthState.Degraded, "Last cycle warned.", at),
                new HealthComponentSnapshot("Alerts", HealthState.Unavailable, "Store missing.", at),
            ],
            at);

        var diagnostics = HealthDiagnosticsView.From(snapshot);

        Assert.Equal("DEGRADED", diagnostics.StatusLabel);
        Assert.Equal("3 components | 1 healthy | 1 degraded | 1 unavailable", diagnostics.Summary);
        Assert.Equal(
            [HealthState.Healthy, HealthState.Degraded, HealthState.Unavailable],
            diagnostics.Components.Select(component => component.State));
        Assert.Equal(["HEALTHY", "DEGRADED", "UNAVAILABLE"], diagnostics.Components.Select(component => component.StateLabel));
    }

    [Fact]
    public void EmptyAndPartialSnapshotsRemainHonest()
    {
        var at = DateTimeOffset.Parse("2026-07-23T14:00:00Z");
        var empty = HealthDiagnosticsView.From(new SystemHealthSnapshot([], at));
        var partial = HealthDiagnosticsView.From(new SystemHealthSnapshot(
            [new HealthComponentSnapshot(" ", HealthState.Unavailable, " ", at)],
            at));

        Assert.Equal("UNAVAILABLE", empty.StatusLabel);
        Assert.Contains("no component diagnostics", empty.Summary, StringComparison.OrdinalIgnoreCase);
        Assert.Equal("PARTIAL", partial.StatusLabel);
        Assert.Equal("Unnamed health component", partial.Components[0].Name);
        Assert.Equal("No diagnostic summary was supplied.", partial.Components[0].Summary);
    }

    [Fact]
    public async Task ShellPublishesDiagnosticsWheneverHealthSnapshotChanges()
    {
        var viewModel = new ShellViewModel(new MockEngineClient());
        var changed = new List<string?>();
        viewModel.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        await viewModel.InitializeAsync();

        Assert.Contains(nameof(ShellViewModel.Diagnostics), changed);
        Assert.Equal("DEGRADED", viewModel.Diagnostics.StatusLabel);
        Assert.Equal(3, viewModel.Diagnostics.Components.Count);
        Assert.Contains(viewModel.Diagnostics.Components, component => component.Name == "Broker connectivity" && component.State == HealthState.Unavailable);
    }
}
