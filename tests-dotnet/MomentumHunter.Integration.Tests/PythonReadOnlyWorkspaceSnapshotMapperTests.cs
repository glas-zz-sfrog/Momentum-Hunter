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
              "schemaVersion": 1,
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
    }

    [Fact]
    public void RejectsANonObjectPayload()
    {
        using var document = JsonDocument.Parse("[]");

        Assert.Throws<InvalidDataException>(() => PythonReadOnlyWorkspaceSnapshotMapper.Map(document.RootElement));
    }
}
