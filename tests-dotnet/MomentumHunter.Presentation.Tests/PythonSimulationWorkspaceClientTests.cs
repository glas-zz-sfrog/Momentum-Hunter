using System.Text.Json;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonSimulationWorkspaceClientTests
{
    [Fact]
    public void MapperAcceptsOnlyTheFakeBrokerSimulationContractAndMapsRiskEvidence()
    {
        using var document = JsonDocument.Parse(SimulationPayload());

        var snapshot = PythonSimulationWorkspaceSnapshotMapper.Map(document.RootElement);

        Assert.True(snapshot.PlanningAvailable);
        var plan = Assert.Single(snapshot.TradePlans);
        Assert.Equal("NVDA", plan.Symbol);
        Assert.Equal(176.42m, plan.Entry);
        Assert.True(plan.RiskDecision!.Allowed);
        Assert.Equal("Simulation-only", plan.RiskDecision.State);
        Assert.Contains(plan.Checks, check => check.Name == "Stop defined" && check.Passed);
    }

    [Fact]
    public void MapperRejectsAnyModeOtherThanFakeBrokerSimulation()
    {
        using var document = JsonDocument.Parse("""{"mode":"PAPER","workspace":{},"plans":[]}""");

        Assert.Throws<InvalidDataException>(() => PythonSimulationWorkspaceSnapshotMapper.Map(document.RootElement));
    }

    private static string SimulationPayload() => """
    {
      "schemaVersion": 1,
      "mode": "SIMULATION_ONLY_FAKE_BROKER",
      "observedAt": "2026-07-17T15:00:00Z",
      "summary": "Python simulation workspace uses FakeBroker only.",
      "planningAvailable": true,
      "workspace": {
        "schemaVersion": 1,
        "observedAt": "2026-07-17T15:00:00Z",
        "summary": "Persisted evidence loaded.",
        "planningAvailable": false,
        "candidates": [
          {
            "symbol": "NVDA",
            "company": "NVIDIA Corporation",
            "lastPrice": 176.42,
            "catalyst": "Stored catalyst",
            "sourceReadinessLabel": "EXECUTION_READY_TRADE",
            "qualityLabel": "Persisted report",
            "observedAt": "2026-07-17T15:00:00Z",
            "score": 97,
            "liquidity": "RVOL 2.40x",
            "catalystSummary": { "headline": "Stored catalyst", "sourceLabel": "Persisted report", "observedAt": "2026-07-17T15:00:00Z" },
            "dataLineage": { "sourceLabel": "Persisted report", "asOf": "2026-07-17T15:00:00Z", "summary": "No recalculation occurred." }
          }
        ],
        "activity": [],
        "health": { "checkedAt": "2026-07-17T15:00:00Z", "components": [] },
        "replay": { "replayId": "NOT_SELECTED", "asOf": "2026-07-17T15:00:00Z", "symbol": "", "interval": "source capture", "summary": "No replay identity was synthesized." }
      },
      "plans": [
        {
          "symbol": "NVDA",
          "tradePlanId": "tp-NVDA",
          "entry": 176.42,
          "stop": 171.42,
          "target": 186.42,
          "riskPerShare": 5.0,
          "simulatedQuantity": 2,
          "rewardToRisk": 2.0,
          "sourceReadinessLabel": "EXECUTION_READY_TRADE",
          "primaryAction": "Run FakeBroker simulation",
          "warnings": [],
          "risk": {
            "resultId": "risk-NVDA",
            "timestamp": "2026-07-17T15:00:00Z",
            "status": "Simulation-only",
            "allowsSimulation": true,
            "reasons": ["Plan can be simulated only."],
            "gates": [ { "name": "Stop defined", "state": "Pass", "reason": "Stop is present for simulation review." } ]
          }
        }
      ]
    }
    """;
}
