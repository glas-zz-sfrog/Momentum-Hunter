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
        using var document = JsonDocument.Parse("""{ "schemaVersion": 4 }""");

        Assert.Throws<InvalidDataException>(() => PythonReadOnlyWorkspaceSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapsCommandCenterV3WithoutChangingMachineIdentitiesOrStoredChartFacts()
    {
        using var document = JsonDocument.Parse("""
            {
              "schemaVersion": 3,
              "observedAt": "2026-08-17T15:10:00Z",
              "summary": "Bounded command center.",
              "planningAvailable": false,
              "candidates": [],
              "activity": [],
              "health": { "checkedAt": "2026-08-17T15:10:00Z", "components": [] },
              "alertEvidence": { "state": "UNAVAILABLE", "asOf": "2026-08-17T15:10:00Z", "activeAlerts": [], "outcomes": [] },
              "replay": { "replayId": "NOT_SELECTED", "asOf": "2026-08-17T15:10:00Z" },
              "commandCenter": {
                "observedAt": "2026-08-17T15:10:00Z",
                "sessionDate": "2026-08-17",
                "projectionState": "PARTIAL",
                "sourceCoverage": { "radar": "AVAILABLE", "accepted": "AVAILABLE", "rejected": "AVAILABLE", "rankedCandidates": "AVAILABLE", "miniCharts": "PARTIAL" },
                "limitations": ["One symbol has no stored history."],
                "populationContractVersion": "command-center-populations-v1",
                "sourceIdentities": { "hotUniverse": "hot-source", "candidateLifecycle": "ledger-source" },
                "radarMembers": [{
                  "radarPresentationIdentity": "hot-member-NVDA-2026-08-17-g1",
                  "membershipGeneration": 1,
                  "derivedLifecycleOpportunityId": "opportunity-hash",
                  "symbol": "NVDA",
                  "sessionDate": "2026-08-17",
                  "firstSurfacedAt": "2026-08-17T14:35:00Z",
                  "lastObservedAt": "2026-08-17T15:09:00Z",
                  "currentState": "TRACKED",
                  "currentTier": "HOT",
                  "sourceSnapshotIdentity": "snapshot-1",
                  "dataLineage": "Validated Hot Universe."
                }],
                "acceptedDispositions": [{
                  "dispositionPresentationIdentity": "2026-08-17|opportunity-hash|setup-1|ACCEPTED",
                  "dispositionEventId": "event-first-eligible",
                  "kind": "ACCEPTED",
                  "opportunityId": "opportunity-hash",
                  "setupId": "setup-1",
                  "setupFamily": "CONTINUATION_BREAKOUT",
                  "setupSequence": 1,
                  "symbol": "NVDA",
                  "sessionDate": "2026-08-17",
                  "previousState": "BREAKOUT_CONFIRMED",
                  "reachedState": "EXECUTION_ELIGIBLE",
                  "occurredAt": "2026-08-17T14:45:00Z",
                  "reason": "First exact qualifying event.",
                  "sourceIdentity": "canonical-bars",
                  "evidenceFingerprint": "fingerprint",
                  "dataLineage": "Exact lifecycle event."
                }],
                "rejectedDispositions": [],
                "rankedCandidates": [{
                  "stableCandidateIdentity": "ranked-source-row-1",
                  "symbol": "NVDA",
                  "company": "NVIDIA",
                  "sourceRank": 1,
                  "score": 92,
                  "relativeVolume": 3.8,
                  "lastPrice": 949.21,
                  "changePercent": 3.72,
                  "catalystSummary": "Stored catalyst",
                  "radarMemberIdentity": "hot-member-NVDA-2026-08-17-g1",
                  "acceptedDispositionIds": ["2026-08-17|opportunity-hash|setup-1|ACCEPTED"],
                  "rejectedDispositionIds": [],
                  "rawMachineState": "TRACKED",
                  "displayFirstSurfacedAt": "2026-08-17T14:35:00Z",
                  "displayStateChangedAt": "2026-08-17T14:45:00Z",
                  "dataLineage": "Source-ranked row.",
                  "sourceIdentity": "report-source",
                  "miniChartSymbolKey": "NVDA",
                  "hypotheticalEntry": 944.50,
                  "hypotheticalStop": 936.00,
                  "hypotheticalTarget": 960.00
                }, {
                  "stableCandidateIdentity": "ranked-source-row-2",
                  "symbol": "BAD",
                  "company": "Malformed Score",
                  "sourceRank": 2,
                  "score": "not-a-score",
                  "acceptedDispositionIds": [],
                  "rejectedDispositionIds": [],
                  "miniChartSymbolKey": "BAD"
                }, {
                  "stableCandidateIdentity": "ranked-source-row-3",
                  "symbol": "MISS",
                  "company": "Missing Score",
                  "sourceRank": 3,
                  "acceptedDispositionIds": [],
                  "rejectedDispositionIds": [],
                  "miniChartSymbolKey": "MISS"
                }],
                "lifecycleEvents": [{
                  "eventIdentity": "hot-transition-1",
                  "sourceKind": "HOT_UNIVERSE",
                  "sourceSequence": 7,
                  "symbol": "NVDA",
                  "occurredAt": "2026-08-17T14:35:00Z",
                  "previousState": "",
                  "nextState": "TRACKED",
                  "reason": "DISCOVERED",
                  "opportunityId": "",
                  "radarMemberIdentity": "hot-member-NVDA-2026-08-17-g1",
                  "derivedLifecycleOpportunityId": "opportunity-hash",
                  "setupId": ""
                }],
                "miniChartsBySymbol": {
                  "NVDA": {
                    "state": "AVAILABLE",
                    "symbol": "NVDA",
                    "interval": "15m",
                    "requestedSessionCount": 2,
                    "sourceSessionDates": ["2026-08-14", "2026-08-17"],
                    "points": [
                      { "timestamp": "2026-08-14T15:00:00Z", "close": 940.00 },
                      { "timestamp": "2026-08-17T15:00:00Z", "close": 949.21 }
                    ],
                    "sourceLabel": "Stored canonical candles",
                    "asOf": "2026-08-17T15:10:00Z",
                    "gapCount": 0,
                    "correctionCount": 0,
                    "findings": [],
                    "limitation": ""
                  }
                },
                "reportObservedAt": "2026-08-17T15:05:00Z",
                "radarMapGeometryState": "NOT_YET_AUTHORIZED"
              }
            }
            """);

        var snapshot = PythonReadOnlyWorkspaceSnapshotMapper.Map(document.RootElement);

        var commandCenter = Assert.IsType<CommandCenterSnapshot>(snapshot.CommandCenter);
        Assert.Equal(CommandCenterEvidenceState.Partial, commandCenter.ProjectionState);
        Assert.Equal("hot-member-NVDA-2026-08-17-g1", Assert.Single(commandCenter.RadarMembers).RadarPresentationIdentity);
        Assert.Equal("opportunity-hash", Assert.Single(commandCenter.RadarMembers).DerivedLifecycleOpportunityId);
        Assert.Equal("event-first-eligible", Assert.Single(commandCenter.AcceptedDispositions).DispositionEventId);
        Assert.Equal(1, commandCenter.RankedCandidates.Single(item => item.Symbol == "NVDA").SourceRank);
        Assert.Null(commandCenter.RankedCandidates.Single(item => item.Symbol == "BAD").Score);
        Assert.Null(commandCenter.RankedCandidates.Single(item => item.Symbol == "MISS").Score);
        var hotTransition = Assert.Single(commandCenter.LifecycleEvents);
        Assert.Equal(7, hotTransition.SourceSequence);
        Assert.Empty(hotTransition.OpportunityId);
        Assert.Equal("hot-member-NVDA-2026-08-17-g1", hotTransition.RadarMemberIdentity);
        Assert.Equal("opportunity-hash", hotTransition.DerivedLifecycleOpportunityId);
        Assert.NotEqual(hotTransition.RadarMemberIdentity, hotTransition.DerivedLifecycleOpportunityId);
        var chart = commandCenter.MiniChartsBySymbol["NVDA"];
        Assert.Equal(new[] { "2026-08-14", "2026-08-17" }, chart.SourceSessionDates);
        Assert.Equal(949.21m, chart.Points[^1].Close);
        Assert.False(snapshot.PlanningAvailable);
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
