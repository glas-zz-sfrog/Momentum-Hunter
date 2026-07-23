using System.Text.Json;
using System.Text.Json.Nodes;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonResearchMaturityWorkspaceClientTests
{
    [Fact]
    public void MapperPreservesSeparateMaturityAndCensusEvidence()
    {
        var snapshot = Map(ValidPayload());

        Assert.Equal(ResearchMaturityEvidenceState.Stale, snapshot.State);
        Assert.Equal(100m, snapshot.MaturityAlerts.CompletionRatePercent);
        Assert.Equal(50m, snapshot.Census.Alerts.CompletionRatePercent);
        Assert.Equal(1, snapshot.MaturityAlerts.Completed);
        Assert.Equal(2, snapshot.Census.Alerts.Total);
        Assert.Equal(41, snapshot.Census.Captures);
        Assert.Equal(675, snapshot.Census.CandidateRows);
        Assert.Equal(710, snapshot.Census.MinuteBars);
        Assert.Equal(4, snapshot.Gates.Count);
        Assert.Equal(12, snapshot.Census.TableCount);
        Assert.False(snapshot.StrategyChangeRecommendationsAllowed);
        Assert.All(snapshot.Gates, gate => Assert.False(gate.StrategyChangeAllowed));
        Assert.True(snapshot.ResearchOnly);
        Assert.True(snapshot.ReadOnly);
    }

    [Fact]
    public void MapperRejectsStrategyUnlockAtTopLevelOrGate()
    {
        var topLevel = ValidPayload();
        topLevel["strategyChangeRecommendationsAllowed"] = true;
        var gate = ValidPayload();
        gate["gates"]![1]!["strategyChangeAllowed"] = true;

        Assert.Throws<InvalidDataException>(() => Map(topLevel));
        Assert.Throws<InvalidDataException>(() => Map(gate));
    }

    [Fact]
    public void MapperRejectsUnlockedOptimizationOrWritableBoundary()
    {
        var optimization = ValidPayload();
        optimization["strategyOptimizationStatus"] = "REVIEW";
        var writable = ValidPayload();
        writable["readOnly"] = false;
        var production = ValidPayload();
        production["researchOnly"] = false;

        Assert.Throws<InvalidDataException>(() => Map(optimization));
        Assert.Throws<InvalidDataException>(() => Map(writable));
        Assert.Throws<InvalidDataException>(() => Map(production));
    }

    [Fact]
    public void MapperRejectsUnknownStateSchemaOrInvalidTimestamp()
    {
        var state = ValidPayload();
        state["state"] = "MAYBE";
        var schema = ValidPayload();
        schema["schemaVersion"] = 2;
        var timestamp = ValidPayload();
        timestamp["observedAt"] = "not-a-time";

        Assert.Throws<InvalidDataException>(() => Map(state));
        Assert.Throws<InvalidDataException>(() => Map(schema));
        Assert.Throws<InvalidDataException>(() => Map(timestamp));
    }

    [Fact]
    public void MapperRejectsAlertGateAndDisplayCountMismatches()
    {
        var alerts = ValidPayload();
        alerts["maturityTotalAlerts"] = 9;
        var gate = ValidPayload();
        gate["gates"]![1]!["completedNeeded"] = 23;
        var displayed = ValidPayload();
        displayed["displayedGateCount"] = 3;

        Assert.Throws<InvalidDataException>(() => Map(alerts));
        Assert.Throws<InvalidDataException>(() => Map(gate));
        Assert.Throws<InvalidDataException>(() => Map(displayed));
    }

    [Fact]
    public void MapperRejectsDuplicateRowsAndOutOfRangePercentage()
    {
        var duplicate = ValidPayload();
        duplicate["gates"]!.AsArray().Add(duplicate["gates"]![0]!.DeepClone());
        duplicate["gateCount"] = 5;
        duplicate["displayedGateCount"] = 5;
        var percentage = ValidPayload();
        percentage["censusCompletionRatePct"] = 101;

        Assert.Throws<InvalidDataException>(() => Map(duplicate));
        Assert.Throws<InvalidDataException>(() => Map(percentage));
    }

    [Fact]
    public async Task ClientUsesDedicatedResearchMaturityHostCommand()
    {
        var connection = new RecordingResearchMaturityConnection();
        var client = new PythonResearchMaturityWorkspaceClient(connection);

        var snapshot = await client.GetSnapshotAsync();

        Assert.True(connection.Called);
        Assert.Equal(ResearchMaturityEvidenceState.Stale, snapshot.State);
        Assert.Equal("LOCKED", snapshot.StrategyOptimizationStatus);
    }

    private static ResearchMaturitySnapshot Map(JsonNode payload)
    {
        using var document = JsonDocument.Parse(payload.ToJsonString());
        return PythonResearchMaturitySnapshotMapper.Map(document.RootElement);
    }

    private static JsonNode ValidPayload() =>
        JsonNode.Parse(
            """
            {
              "schemaVersion": 1,
              "state": "STALE",
              "observedAt": "2026-07-23T12:00:00Z",
              "sourceAsOf": "2026-06-27T06:35:44Z",
              "maturityGeneratedAt": "2026-06-27T06:35:44Z",
              "censusGeneratedAt": "2026-06-27T06:38:33Z",
              "sourceLabel": "evidence-analytics-maturity-latest.json + evidence-census-latest.json",
              "summary": "STALE | Persisted research maturity remains locked.",
              "maturityOverallStatus": "WARN",
              "censusOverallStatus": "WARN",
              "sampleConfidence": "COLLECTING_ONLY",
              "measurableEdgeStatus": "INSUFFICIENT_SAMPLE",
              "strategyOptimizationStatus": "LOCKED",
              "strategyChangeRecommendationsAllowed": false,
              "maturityTotalAlerts": 2,
              "maturityCompletedAlerts": 1,
              "maturityPendingAlerts": 0,
              "maturityUnscorableAlerts": 1,
              "maturityCompletionRatePct": 100.0,
              "evidenceNeededToNextGate": 24,
              "evidenceGate": {
                "completedAlerts": 1,
                "requiredAlerts": 25,
                "evidenceStatus": "COLLECTING",
                "allowedAction": "Collect evidence only",
                "strategyOptimizationStatus": "LOCKED",
                "reason": "1 completed alert; minimum 25 required."
              },
              "gates": [
                {
                  "name": "Collect Evidence",
                  "status": "UNLOCKED",
                  "currentCompletedAlerts": 1,
                  "requiredCompletedAlerts": 0,
                  "completedNeeded": 0,
                  "allowedAction": "Collect evidence only",
                  "strategyChangeAllowed": false
                },
                {
                  "name": "Identify Patterns",
                  "status": "LOCKED",
                  "currentCompletedAlerts": 1,
                  "requiredCompletedAlerts": 25,
                  "completedNeeded": 24,
                  "allowedAction": "Identify patterns",
                  "strategyChangeAllowed": false
                },
                {
                  "name": "Recommend Investigations",
                  "status": "LOCKED",
                  "currentCompletedAlerts": 1,
                  "requiredCompletedAlerts": 50,
                  "completedNeeded": 49,
                  "allowedAction": "Recommend investigations",
                  "strategyChangeAllowed": false
                },
                {
                  "name": "Strategy Modification Review",
                  "status": "LOCKED",
                  "currentCompletedAlerts": 1,
                  "requiredCompletedAlerts": 100,
                  "completedNeeded": 99,
                  "allowedAction": "Review possible strategy modifications",
                  "strategyChangeAllowed": false
                }
              ],
              "gateCount": 4,
              "displayedGateCount": 4,
              "questions": [
                {
                  "question": "Are Alerts Predictive",
                  "answer": "NOT_YET"
                },
                {
                  "question": "Does System Have Edge",
                  "answer": "NOT_YET"
                }
              ],
              "questionCount": 2,
              "displayedQuestionCount": 2,
              "censusTotalAlerts": 2,
              "censusCompletedAlerts": 1,
              "censusPendingAlerts": 0,
              "censusUnscorableAlerts": 1,
              "censusCompletionRatePct": 50.0,
              "captures": 41,
              "candidateRows": 675,
              "studyEligibleCaptures": 36,
              "quarantinedCaptures": 0,
              "minuteBars": 710,
              "minuteBarSymbols": 1,
              "evidenceRuns": 14,
              "evidenceMetrics": 380,
              "candidateReviews": 17,
              "watchlistItems": 8,
              "entryPlans": 27,
              "completeEntryPlans": 0,
              "incompleteEntryPlans": 27,
              "tableCounts": [
                { "name": "provider_quality_checks", "count": 3 },
                { "name": "opportunity_alerts", "count": 2 }
              ],
              "tableCount": 12,
              "displayedTableCount": 2,
              "warnings": [
                "INSUFFICIENT_COMPLETED_ALERTS_FOR_PATTERN_REVIEW",
                "Persisted source is older than the 24-hour display threshold."
              ],
              "safetyNotes": [
                "Research evidence only.",
                "Strategy changes remain locked."
              ],
              "researchOnly": true,
              "readOnly": true
            }
            """)!;

    private sealed class RecordingResearchMaturityConnection : IPythonEngineHostConnection
    {
        public bool Called { get; private set; }

        public Task<JsonElement> GetResearchMaturitySnapshotAsync(
            CancellationToken cancellationToken = default)
        {
            Called = true;
            using var document = JsonDocument.Parse(ValidPayload().ToJsonString());
            return Task.FromResult(document.RootElement.Clone());
        }

        public Task<PythonEngineHostSnapshot> EnsureConnectedAsync(
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PythonEngineHostSnapshot> GetSnapshotAsync(
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PythonEngineHostCommandResult> SendCommandAsync(
            string command,
            string commandId,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }
}
