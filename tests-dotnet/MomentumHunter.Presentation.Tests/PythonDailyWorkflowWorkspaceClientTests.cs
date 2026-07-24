using System.Text.Json;
using System.Text.Json.Nodes;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonDailyWorkflowWorkspaceClientTests
{
    [Fact]
    public void MapperPreservesCanonicalWorkflowEvidence()
    {
        using var document = JsonDocument.Parse(ValidPayload());

        var snapshot = PythonDailyWorkflowSnapshotMapper.Map(document.RootElement);

        Assert.Equal(DailyWorkflowEvidenceState.Stale, snapshot.State);
        Assert.Equal(54, snapshot.WorkflowScore);
        Assert.Equal(14, snapshot.Review.Total);
        Assert.Equal(14, snapshot.Review.Unreviewed);
        Assert.Equal("HISTORICAL_READ_ONLY", snapshot.OperatorContextState);
        Assert.Equal(DailyWorkflowStepLevel.Blocked, snapshot.NextAction.Level);
        Assert.Equal(
            ["capture", "review", "plans", "report", "readiness"],
            snapshot.Steps.Select(step => step.Id));
        Assert.Equal(DailyWorkflowLight.Red, snapshot.Steps[0].Light);
        Assert.True(snapshot.ReadOnly);
    }

    [Fact]
    public void MapperRejectsInconsistentReviewAndPlanCounts()
    {
        using var reviewMismatch = JsonDocument.Parse(ValidPayload().Replace("\"reviewed\": 0", "\"reviewed\": 1"));
        using var planMismatch = JsonDocument.Parse(ValidPayload().Replace("\"complete\": 0", "\"complete\": 1"));

        Assert.Throws<InvalidDataException>(() => PythonDailyWorkflowSnapshotMapper.Map(reviewMismatch.RootElement));
        Assert.Throws<InvalidDataException>(() => PythonDailyWorkflowSnapshotMapper.Map(planMismatch.RootElement));
    }

    [Fact]
    public void MapperRejectsUnknownStateMissingStepsAndWritablePayload()
    {
        using var unknown = JsonDocument.Parse(ValidPayload().Replace("\"state\": \"STALE\"", "\"state\": \"CURRENT\""));
        var missingStepPayload = JsonNode.Parse(ValidPayload())!;
        missingStepPayload["steps"]!.AsArray().RemoveAt(4);
        using var missingStep = JsonDocument.Parse(missingStepPayload.ToJsonString());
        using var writable = JsonDocument.Parse(ValidPayload().Replace("\"readOnly\": true", "\"readOnly\": false"));

        Assert.Throws<InvalidDataException>(() => PythonDailyWorkflowSnapshotMapper.Map(unknown.RootElement));
        Assert.Throws<InvalidDataException>(() => PythonDailyWorkflowSnapshotMapper.Map(missingStep.RootElement));
        Assert.Throws<InvalidDataException>(() => PythonDailyWorkflowSnapshotMapper.Map(writable.RootElement));
    }

    [Fact]
    public void MapperAllowsExplicitUnavailableStateOnlyWithoutCandidatesOrSteps()
    {
        using var document = JsonDocument.Parse(UnavailablePayload());

        var snapshot = PythonDailyWorkflowSnapshotMapper.Map(document.RootElement);

        Assert.Equal(DailyWorkflowEvidenceState.Unavailable, snapshot.State);
        Assert.Empty(snapshot.Steps);
        Assert.Equal(0, snapshot.Review.Total);
        Assert.Null(snapshot.SourceAsOf);
    }

    private static string ValidPayload() => $$"""
        {
          "schemaVersion": 1,
          "state": "STALE",
          "observedAt": "2026-07-23T15:00:00Z",
          "sourceAsOf": "2026-06-17T13:53:27Z",
          "sourceLabel": "event-trade-plan-briefing-2026-06-17-morning.json",
          "sourceContext": "2026-06-17 / morning / finviz / Institutional Momentum",
          "operatorContextState": "HISTORICAL_READ_ONLY",
          "operatorContextLabel": "Historical Snapshot - Read Only",
          "summary": "STALE | Read-only Daily Workflow projection.",
          "workflowScore": 54,
          "captureStatus": "warning - last scheduled capture failed",
          "review": {
            "total": 14,
            "reviewed": 0,
            "unreviewed": 14,
            "interested": 0,
            "rejected": 0,
            "watchlist": 0
          },
          "plans": {
            "watchlist": 0,
            "complete": 0,
            "incomplete": 0,
            "missingTrigger": 0,
            "missingStop": 0,
            "missingInvalidation": 0,
            "missingMaxLoss": 0,
            "withoutPlan": 0
          },
          "outcomes": {
            "completedNextDay": 949,
            "completedFiveDay": 912,
            "pending": 38
          },
          "readiness": [
            {"name": "Outcome Explorer", "status": "READY"},
            {"name": "Opportunity Research", "status": "READY"}
          ],
          "nextAction": {
            "title": "Next Required Action: restore a reviewable current workflow",
            "detail": "This persisted workflow is historical.",
            "level": "blocked"
          },
          "steps": [
            {{Step("capture", "Capture Health", "blocked", "Blocked", "red")}},
            {{Step("review", "Morning Review", "waiting", "Waiting", "gray")}},
            {{Step("plans", "Watchlist Plans", "waiting", "Waiting", "gray")}},
            {{Step("report", "Watchlist Report", "waiting", "Waiting", "gray")}},
            {{Step("readiness", "Readiness Gate", "complete", "Available check", "green")}}
          ],
          "warnings": ["REVIEWS INCOMPLETE", "CAPTURE FAILURE DETECTED"],
          "readOnly": true
        }
        """;

    private static string UnavailablePayload() => """
        {
          "schemaVersion": 1,
          "state": "UNAVAILABLE",
          "observedAt": "2026-07-23T15:00:00Z",
          "sourceAsOf": null,
          "sourceLabel": "Daily Workflow source unavailable",
          "sourceContext": "Capture identity unavailable",
          "operatorContextState": "CAPTURE_MISSING",
          "operatorContextLabel": "Capture Missing",
          "summary": "UNAVAILABLE | No source.",
          "workflowScore": 0,
          "captureStatus": "unavailable",
          "review": {"total": 0, "reviewed": 0, "unreviewed": 0, "interested": 0, "rejected": 0, "watchlist": 0},
          "plans": {"watchlist": 0, "complete": 0, "incomplete": 0, "missingTrigger": 0, "missingStop": 0, "missingInvalidation": 0, "missingMaxLoss": 0, "withoutPlan": 0},
          "outcomes": {"completedNextDay": 0, "completedFiveDay": 0, "pending": 0},
          "readiness": [],
          "nextAction": {"title": "Restore evidence", "detail": "No source.", "level": "blocked"},
          "steps": [],
          "warnings": ["No source."],
          "readOnly": true
        }
        """;

    private static string Step(string id, string name, string level, string status, string light) => $$"""
        {
          "id": "{{id}}",
          "name": "{{name}}",
          "level": "{{level}}",
          "status": "{{status}}",
          "light": "{{light}}",
          "dependency": "Persisted upstream evidence.",
          "blocker": "None.",
          "detail": "Read-only workflow detail."
        }
        """;
}
