using System.Text.Json;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Integration.Tests;

public sealed class PythonReadOnlyWorkspaceSnapshotMapperTests
{
    [Fact]
    public void MapsPersistedEvidenceWithoutInventingPlanningAvailability()
    {
        using var document = JsonDocument.Parse("""
            {
              "schemaVersion": 2,
              "observedAt": "2026-07-17T15:00:00Z",
              "summary": "Read-only Python evidence snapshot.",
              "planningAvailable": false,
              "candidates": [
                {
                  "symbol": "NVDA",
                  "company": "NVIDIA Corporation",
                  "lastPrice": 176.42,
                  "changePercent": 3.18,
                  "volume": 84700112,
                  "relativeVolume": 2.4,
                  "catalyst": "Stored catalyst",
                  "sourceReadinessLabel": "PLANNING_SCAFFOLD",
                  "qualityLabel": "Persisted report",
                  "observedAt": "2026-07-17T14:30:00Z",
                  "score": 97,
                  "liquidity": "RVOL 2.40x",
                  "catalystSummary": { "headline": "Stored catalyst", "sourceLabel": "Persisted trade-planning report", "observedAt": "2026-07-17T14:30:00Z" },
                  "dataLineage": { "sourceLabel": "Persisted trade-planning report", "asOf": "2026-07-17T14:30:00Z", "summary": "No recalculation occurred." }
                }
              ],
              "activity": [
                { "timestamp": "2026-07-17T14:30:00Z", "category": "Research", "message": "Persisted report loaded.", "symbol": "", "state": "Healthy" }
              ],
              "health": {
                "checkedAt": "2026-07-17T15:00:00Z",
                "components": [
                  { "name": "Trade planning report", "state": "Healthy", "summary": "Loaded", "checkedAt": "2026-07-17T14:30:00Z" }
                ]
              },
              "alertEvidence": {
                "state": "AVAILABLE",
                "asOf": "2026-07-17T14:40:00Z",
                "summary": "Stored alert states and outcomes.",
                "totalAlertCount": 3,
                "activeAlertCount": 1,
                "recordedOutcomeCount": 2,
                "unscorableOutcomeCount": 1,
                "activeAlerts": [
                  {
                    "alertId": "alert-active",
                    "timestamp": "2026-07-17T14:35:00Z",
                    "symbol": "NVDA",
                    "alertType": "BREAKOUT",
                    "state": "ACTIVE",
                    "summary": "Range breakout persisted."
                  }
                ],
                "outcomes": [
                  {
                    "alertId": "",
                    "symbol": "AMD",
                    "alertTimestamp": null,
                    "status": "UNSCORABLE_OUTCOME",
                    "classification": "UNSCORABLE_MISSING_ENTRY_PRICE",
                    "summary": "Stored status and classification."
                  }
                ]
              },
              "replay": {
                "replayId": "NOT_SELECTED",
                "asOf": "2026-07-17T14:25:00Z",
                "symbol": "",
                "interval": "source capture",
                "summary": "No candidate replay identity was synthesized."
              }
            }
            """);

        var snapshot = PythonReadOnlyWorkspaceSnapshotMapper.Map(document.RootElement);

        var candidate = Assert.Single(snapshot.Candidates);
        Assert.Equal("NVDA", candidate.Symbol);
        Assert.Equal(176.42m, candidate.LastPrice);
        Assert.Equal("PLANNING_SCAFFOLD", candidate.OperatorState);
        Assert.Equal(ReadinessState.NeedsEvidence, candidate.Readiness);
        Assert.Equal("Persisted trade-planning report", candidate.DataLineage!.SourceLabel);
        Assert.False(snapshot.PlanningAvailable);
        Assert.Equal("NOT_SELECTED", snapshot.Replay.ReplayId);
        Assert.Equal(AlertEvidenceState.Available, snapshot.AlertEvidence.State);
        Assert.Equal(3, snapshot.AlertEvidence.TotalAlertCount);
        Assert.Equal(1, snapshot.AlertEvidence.ActiveAlertCount);
        var alert = Assert.Single(snapshot.AlertEvidence.ActiveAlerts);
        Assert.Equal("alert-active", alert.AlertId);
        Assert.Equal("BREAKOUT", alert.AlertType);
        Assert.Equal(DateTimeOffset.Parse("2026-07-17T14:35:00Z"), alert.Timestamp);
        var outcome = Assert.Single(snapshot.AlertEvidence.Outcomes);
        Assert.Equal("UNSCORABLE_OUTCOME", outcome.Status);
        Assert.Equal("UNSCORABLE_MISSING_ENTRY_PRICE", outcome.Classification);
        Assert.Null(outcome.AlertTimestamp);
    }

    [Fact]
    public void PreservesMissingNumericEvidenceAsNullInsteadOfZero()
    {
        using var document = JsonDocument.Parse("""
            {
              "schemaVersion": 1,
              "observedAt": "2026-07-17T15:00:00Z",
              "planningAvailable": false,
              "candidates": [
                {
                  "symbol": "NVDA",
                  "company": "NVIDIA Corporation",
                  "catalyst": "Stored catalyst",
                  "sourceReadinessLabel": "UNAVAILABLE",
                  "qualityLabel": "last price unavailable",
                  "observedAt": "2026-07-17T14:30:00Z"
                }
              ],
              "activity": [],
              "health": { "checkedAt": "2026-07-17T15:00:00Z", "components": [] },
              "replay": { "replayId": "UNAVAILABLE", "asOf": "2026-07-17T15:00:00Z", "symbol": "", "interval": "source capture", "summary": "Unavailable" }
            }
            """);

        var snapshot = PythonReadOnlyWorkspaceSnapshotMapper.Map(document.RootElement);

        var candidate = Assert.Single(snapshot.Candidates);
        Assert.Null(candidate.LastPrice);
        Assert.Null(candidate.RelativeVolume);
        Assert.Equal("UNAVAILABLE", candidate.OperatorState);
        Assert.Equal(ReadinessState.StaleData, candidate.Readiness);
        Assert.Equal(AlertEvidenceState.Unavailable, snapshot.AlertEvidence.State);
        Assert.Contains("schema v1", snapshot.AlertEvidence.Summary, StringComparison.Ordinal);
    }

    [Fact]
    public void RejectsANonObjectPayload()
    {
        using var document = JsonDocument.Parse("[]");

        Assert.Throws<InvalidDataException>(() => PythonReadOnlyWorkspaceSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void RejectsAnUnsupportedSchemaVersion()
    {
        using var document = JsonDocument.Parse("""{ "schemaVersion": 3 }""");

        Assert.Throws<InvalidDataException>(() => PythonReadOnlyWorkspaceSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void ClampsMalformedNegativeEvidenceCountsWithoutCreatingRows()
    {
        using var document = JsonDocument.Parse("""
            {
              "schemaVersion": 2,
              "observedAt": "2026-07-17T15:00:00Z",
              "candidates": [],
              "activity": [],
              "health": { "checkedAt": "2026-07-17T15:00:00Z", "components": [] },
              "alertEvidence": {
                "state": "EMPTY",
                "asOf": "2026-07-17T15:00:00Z",
                "totalAlertCount": -1,
                "activeAlertCount": -2,
                "recordedOutcomeCount": -3,
                "unscorableOutcomeCount": -4,
                "activeAlerts": [],
                "outcomes": []
              },
              "replay": { "replayId": "NOT_SELECTED", "asOf": "2026-07-17T15:00:00Z" }
            }
            """);

        var snapshot = PythonReadOnlyWorkspaceSnapshotMapper.Map(document.RootElement);

        Assert.Equal(0, snapshot.AlertEvidence.TotalAlertCount);
        Assert.Equal(0, snapshot.AlertEvidence.ActiveAlertCount);
        Assert.Equal(0, snapshot.AlertEvidence.RecordedOutcomeCount);
        Assert.Equal(0, snapshot.AlertEvidence.UnscorableOutcomeCount);
        Assert.Empty(snapshot.AlertEvidence.ActiveAlerts);
        Assert.Empty(snapshot.AlertEvidence.Outcomes);
    }
}
