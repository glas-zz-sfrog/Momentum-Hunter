using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class DailyWorkflowShellTests
{
    [Fact]
    public async Task InitializationLoadsWorkflowIndependentlyAndFormatsOperatorEvidence()
    {
        var client = new RecordingDailyWorkflowClient(Snapshot());
        var viewModel = new ShellViewModel(new MockEngineClient(), client);

        await viewModel.InitializeAsync();

        Assert.Equal(1, client.Calls);
        Assert.Equal(DailyWorkflowEvidenceState.Stale, viewModel.DailyWorkflow!.State);
        Assert.Equal("STALE", viewModel.DailyWorkflowStateLabel);
        Assert.Contains("Workflow discipline 54%", viewModel.DailyWorkflowScoreLabel);
        Assert.Contains("Reviews 0/14", viewModel.DailyWorkflowReviewLabel);
        Assert.Contains("CAPTURE FAILURE DETECTED", viewModel.DailyWorkflowWarningsLabel);
        Assert.Contains("2026-06-17", viewModel.DailyWorkflowAsOfLabel);
    }

    [Fact]
    public async Task CandidateChangesDoNotReloadOrMutateTheDailyWorkflowSnapshot()
    {
        var snapshot = Snapshot();
        var client = new RecordingDailyWorkflowClient(snapshot);
        var viewModel = new ShellViewModel(new MockEngineClient(), client);
        await viewModel.InitializeAsync();

        await viewModel.SelectCandidateAsync(viewModel.Candidates.Last());

        Assert.Equal(1, client.Calls);
        Assert.Same(snapshot, viewModel.DailyWorkflow);
        Assert.Equal(14, viewModel.DailyWorkflow!.Review.Total);
    }

    [Fact]
    public async Task WorkflowFailureFailsClosedWithoutBlockingTheMainWorkspace()
    {
        var viewModel = new ShellViewModel(new MockEngineClient(), new FailingDailyWorkflowClient());

        await viewModel.InitializeAsync();

        Assert.NotEmpty(viewModel.Candidates);
        Assert.Equal(DailyWorkflowEvidenceState.Unavailable, viewModel.DailyWorkflow!.State);
        Assert.Empty(viewModel.DailyWorkflow.Steps);
        Assert.Contains("failed closed", viewModel.DailyWorkflow.Summary, StringComparison.OrdinalIgnoreCase);
        Assert.True(viewModel.DailyWorkflow.ReadOnly);
    }

    private static DailyWorkflowSnapshot Snapshot()
    {
        var observedAt = DateTimeOffset.Parse("2026-07-23T15:00:00Z");
        return new DailyWorkflowSnapshot(
            1,
            DailyWorkflowEvidenceState.Stale,
            observedAt,
            DateTimeOffset.Parse("2026-06-17T13:53:27Z"),
            "event-trade-plan-briefing-2026-06-17-morning.json",
            "2026-06-17 / morning / finviz / Institutional Momentum",
            "HISTORICAL_READ_ONLY",
            "Historical Snapshot - Read Only",
            "STALE | Read-only Daily Workflow projection.",
            54,
            "warning - last scheduled capture failed",
            new DailyWorkflowReviewCounts(14, 0, 14, 0, 0, 0),
            new DailyWorkflowPlanCounts(0, 0, 0, 0, 0, 0, 0, 0),
            new DailyWorkflowOutcomeCounts(949, 912, 38),
            [new DailyWorkflowReadinessGate("Outcome Explorer", "READY")],
            new DailyWorkflowNextAction(
                "Next Required Action: restore a reviewable current workflow",
                "This persisted workflow is historical.",
                DailyWorkflowStepLevel.Blocked),
            [
                Step("capture", "Capture Health", DailyWorkflowStepLevel.Blocked, DailyWorkflowLight.Red),
                Step("review", "Morning Review", DailyWorkflowStepLevel.Waiting, DailyWorkflowLight.Gray),
                Step("plans", "Watchlist Plans", DailyWorkflowStepLevel.Waiting, DailyWorkflowLight.Gray),
                Step("report", "Watchlist Report", DailyWorkflowStepLevel.Waiting, DailyWorkflowLight.Gray),
                Step("readiness", "Readiness Gate", DailyWorkflowStepLevel.Complete, DailyWorkflowLight.Green),
            ],
            ["REVIEWS INCOMPLETE", "CAPTURE FAILURE DETECTED"],
            true);
    }

    private static DailyWorkflowStepSnapshot Step(
        string id,
        string name,
        DailyWorkflowStepLevel level,
        DailyWorkflowLight light) =>
        new(id, name, level, level.ToString(), light, "Persisted evidence.", "None.", "Read-only detail.");

    private sealed class RecordingDailyWorkflowClient : IDailyWorkflowWorkspaceClient
    {
        private readonly DailyWorkflowSnapshot _snapshot;

        public RecordingDailyWorkflowClient(DailyWorkflowSnapshot snapshot)
        {
            _snapshot = snapshot;
        }

        public int Calls { get; private set; }

        public Task<DailyWorkflowSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
        {
            Calls++;
            return Task.FromResult(_snapshot);
        }
    }

    private sealed class FailingDailyWorkflowClient : IDailyWorkflowWorkspaceClient
    {
        public Task<DailyWorkflowSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            Task.FromException<DailyWorkflowSnapshot>(new InvalidDataException("invalid workflow payload"));
    }
}
