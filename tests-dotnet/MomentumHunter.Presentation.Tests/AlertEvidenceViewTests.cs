using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class AlertEvidenceViewTests
{
    [Fact]
    public void OverviewPreservesSourceStateCountsSummaryAndUtcTime()
    {
        var evidence = Snapshot(AlertEvidenceState.Available);

        var view = AlertEvidenceOverviewView.From(evidence);

        Assert.Equal(AlertEvidenceState.Available, view.State);
        Assert.Equal("AVAILABLE", view.StateLabel);
        Assert.Equal("Source as of 2026-07-23 14:30:00 UTC", view.AsOfLabel);
        Assert.Equal("Stored alert states and classifications.", view.Summary);
        Assert.Equal("3 total | 1 active or pending | 2 outcomes | 1 unscorable", view.CountSummary);
    }

    [Fact]
    public void MissingSnapshotIsExplicitlyUnavailable()
    {
        var view = AlertEvidenceOverviewView.From(null);

        Assert.Equal(AlertEvidenceState.Unavailable, view.State);
        Assert.Equal("UNAVAILABLE", view.StateLabel);
        Assert.Equal("As-of time unavailable", view.AsOfLabel);
        Assert.Contains("No alert evidence snapshot", view.Summary, StringComparison.Ordinal);
    }

    [Fact]
    public void AlertRowUsesHonestFallbacksAndUtcConversion()
    {
        var complete = AlertEventRowView.From(new AlertEvent(
            " alert-1 ",
            DateTimeOffset.Parse("2026-07-23T09:15:00-05:00"),
            " nvda ",
            " breakout ",
            " active ",
            " Stored reason. "));
        var missing = AlertEventRowView.From(new AlertEvent(string.Empty, null, string.Empty, string.Empty, string.Empty, string.Empty));

        Assert.Equal("2026-07-23 14:15:00 UTC", complete.TimestampLabel);
        Assert.Equal("nvda", complete.SymbolLabel);
        Assert.Equal("breakout", complete.TypeLabel);
        Assert.Equal("ACTIVE", complete.StateLabel);
        Assert.Equal("alert-1", complete.AlertIdLabel);
        Assert.Equal("Stored reason.", complete.Summary);
        Assert.Equal("Time unavailable", missing.TimestampLabel);
        Assert.Equal("Symbol unavailable", missing.SymbolLabel);
        Assert.Equal("ID unavailable", missing.AlertIdLabel);
    }

    [Fact]
    public void OutcomeRowPreservesStoredStatusAndClassification()
    {
        var view = OutcomeRowView.From(new OutcomeSnapshot(
            "outcome-1",
            "CRWD",
            DateTimeOffset.Parse("2026-07-23T14:00:00Z"),
            "completed",
            "successful",
            "Stored 60m +4.25%."));

        Assert.Equal("COMPLETED", view.StatusLabel);
        Assert.Equal("SUCCESSFUL", view.ClassificationLabel);
        Assert.Equal("Stored 60m +4.25%.", view.Summary);
    }

    [Fact]
    public async Task ShellFailureClearsRowsAndReportsUnavailableEvidence()
    {
        var viewModel = new ShellViewModel(new MockEngineClient(), new FailingReadOnlyWorkspaceClient());

        await viewModel.InitializeAsync();

        Assert.Equal(AlertEvidenceState.Unavailable, viewModel.AlertEvidenceOverview.State);
        Assert.Empty(viewModel.AlertRows);
        Assert.Empty(viewModel.OutcomeRows);
        Assert.False(viewModel.HasAlertRows);
        Assert.False(viewModel.HasOutcomeRows);
        Assert.Contains("unavailable", viewModel.AlertRowsEmptyLabel, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("unavailable", viewModel.OutcomeRowsEmptyLabel, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void DuplicateAndMissingIdsRemainSeparateRows()
    {
        var evidence = Snapshot(AlertEvidenceState.Available) with
        {
            ActiveAlerts =
            [
                new AlertEvent("same", null, "NVDA", "BREAKOUT", "ACTIVE", "First"),
                new AlertEvent("same", null, "CRWD", "MOMENTUM", "ACTIVE", "Second"),
                new AlertEvent(string.Empty, null, "AMD", "VOLUME", "ACTIVE", "Third"),
            ],
        };

        var rows = evidence.ActiveAlerts.Select(AlertEventRowView.From).ToArray();

        Assert.Equal(3, rows.Length);
        Assert.Equal(["NVDA", "CRWD", "AMD"], rows.Select(row => row.SymbolLabel));
        Assert.Equal("ID unavailable", rows[2].AlertIdLabel);
    }

    private static AlertEvidenceSnapshot Snapshot(AlertEvidenceState state) => new(
        state,
        DateTimeOffset.Parse("2026-07-23T09:30:00-05:00"),
        "Stored alert states and classifications.",
        3,
        1,
        2,
        1,
        [new AlertEvent("alert-active", DateTimeOffset.Parse("2026-07-23T14:25:00Z"), "NVDA", "BREAKOUT", "ACTIVE", "Stored alert.")],
        [new OutcomeSnapshot("alert-complete", "CRWD", DateTimeOffset.Parse("2026-07-23T14:20:00Z"), "COMPLETED", "SUCCESSFUL", "Stored outcome.")]);

    private sealed class FailingReadOnlyWorkspaceClient : MomentumHunter.Application.IReadOnlyWorkspaceClient
    {
        public Task<ReadOnlyWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromException<ReadOnlyWorkspaceSnapshot>(new InvalidOperationException("host unavailable"));
    }
}
