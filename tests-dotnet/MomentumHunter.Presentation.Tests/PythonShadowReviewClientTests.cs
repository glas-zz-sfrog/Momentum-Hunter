using System.Text.Json;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonShadowReviewClientTests
{
    [Fact]
    public void MapperAcceptsNontransmittingFrozenEvidenceAndKeepsSmallSampleMetricsWithheld()
    {
        using var document = JsonDocument.Parse(Payload());

        var snapshot = PythonShadowReviewSnapshotMapper.Map(document.RootElement);

        Assert.False(snapshot.Transmitting);
        var trade = Assert.Single(snapshot.Trades);
        Assert.Equal("shadow-1", trade.ShadowTradeId);
        Assert.True(trade.EvidenceLock.EvidenceFrozen);
        Assert.True(trade.EvidenceLock.PlanFrozen);
        Assert.False(trade.EvidenceLock.PostDecisionCorrectionOccurred);
        Assert.True(trade.EvidenceEligible);
        Assert.True(trade.CountsTowardSample);
        Assert.Equal(1, snapshot.Sample.EligibleCompleted);
        Assert.False(snapshot.Sample.GateSatisfied);
        Assert.Equal("IN_PROGRESS", snapshot.Sample.ReadinessStatus);
        Assert.False(snapshot.Sample.CanStartOfficialSample);
        Assert.Equal("synthetic-official-v1", snapshot.Sample.Definition.SampleVersion);
        Assert.Equal("prospective-fakebroker-live-mark-v2", trade.SampleDefinition.FillModelVersion);
        Assert.Equal("Withheld", snapshot.Metrics.WinRateDisplay);
        Assert.Contains("entry slippage", trade.Execution.Quality.Summary, StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("""{"mode":"LIVE","transmitting":false}""")]
    [InlineData("""{"mode":"PAPER SHADOW / NONTRANSMITTING","transmitting":true}""")]
    [InlineData("""{"mode":"PAPER SHADOW / NONTRANSMITTING"}""")]
    public void MapperRejectsAnyPayloadThatIsNotExplicitlyNontransmitting(string payload)
    {
        using var document = JsonDocument.Parse(payload);

        Assert.Throws<InvalidDataException>(() => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsEvidenceEligibilityWhenThePlanLockFailed()
    {
        var payload = Payload().Replace(
            "\"planFrozen\": true",
            "\"planFrozen\": false",
            StringComparison.Ordinal);
        using var document = JsonDocument.Parse(payload);

        Assert.Throws<InvalidDataException>(() => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsProfitabilityMetricsBeforeThirtyEligibleCompletedRecords()
    {
        var payload = Payload().Replace(
            "\"winRatePercent\": null",
            "\"winRatePercent\": 100.0",
            StringComparison.Ordinal);
        using var document = JsonDocument.Parse(payload);

        Assert.Throws<InvalidDataException>(() => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsEligibleTradeWithoutOfficialSampleAuthorization()
    {
        var payload = Payload().Replace(
            "\"officialSampleAuthorized\": true",
            "\"officialSampleAuthorized\": false",
            StringComparison.Ordinal);
        using var document = JsonDocument.Parse(payload);

        Assert.Throws<InvalidDataException>(() => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsInconsistentPassingStartGate()
    {
        var payload = Payload()
            .Replace("\"readinessStatus\": \"IN_PROGRESS\"", "\"readinessStatus\": \"PASS\"", StringComparison.Ordinal)
            .Replace("\"canStartOfficialSample\": false", "\"canStartOfficialSample\": true", StringComparison.Ordinal);
        using var document = JsonDocument.Parse(payload);

        Assert.Throws<InvalidDataException>(() => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsOpenTradeLabeledAsFinal()
    {
        var payload = Payload().Replace(
            "\"lifecycleState\": \"completed\"",
            "\"lifecycleState\": \"open\"",
            StringComparison.Ordinal);
        using var document = JsonDocument.Parse(payload);

        Assert.Throws<InvalidDataException>(() => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsStaleMarkThatExposesLivePnl()
    {
        var payload = Payload()
            .Replace("\"displayState\": \"WINNER\"", "\"displayState\": \"STALE\"", StringComparison.Ordinal)
            .Replace("\"unrealizedPnl\": null", "\"unrealizedPnl\": 12.34", StringComparison.Ordinal);
        using var document = JsonDocument.Parse(payload);

        Assert.Throws<InvalidDataException>(() => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsOffsetlessProviderTimestamp()
    {
        var payload = Payload().Replace(
            "2026-07-23T10:30:00-05:00",
            "2026-07-23T10:30:00",
            StringComparison.Ordinal);
        using var document = JsonDocument.Parse(payload);

        Assert.Throws<InvalidDataException>(
            () => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperCarriesPythonMarkValuesWithoutRecalculation()
    {
        var payload = Payload()
            .Replace("\"displayState\": \"WINNER\"", "\"displayState\": \"AHEAD\"", StringComparison.Ordinal)
            .Replace("\"lifecycleState\": \"completed\"", "\"lifecycleState\": \"open\"", StringComparison.Ordinal)
            .Replace("\"countsTowardSample\": true", "\"countsTowardSample\": false", StringComparison.Ordinal)
            .Replace("\"eligibleCompleted\": 1", "\"eligibleCompleted\": 0", StringComparison.Ordinal)
            .Replace("\"unrealizedPnl\": null", "\"unrealizedPnl\": 12.34", StringComparison.Ordinal)
            .Replace("\"unrealizedR\": null", "\"unrealizedR\": 0.42", StringComparison.Ordinal);
        using var document = JsonDocument.Parse(payload);

        var trade = Assert.Single(PythonShadowReviewSnapshotMapper.Map(document.RootElement).Trades);

        Assert.Equal("AHEAD", trade.ActiveMark.DisplayState);
        Assert.Equal(104.00m, trade.ActiveMark.CurrentExecutableMark);
        Assert.Equal(12.34m, trade.ActiveMark.UnrealizedPnl);
        Assert.Equal(0.42m, trade.ActiveMark.UnrealizedR);
        Assert.Equal("synthetic-test-provider", trade.ActiveMark.QuoteProvider);
    }

    [Fact]
    public void ReviewClientContractExposesOnlySnapshotRead()
    {
        var methods = typeof(MomentumHunter.Application.IShadowReviewClient).GetMethods();

        var method = Assert.Single(methods);
        Assert.Equal("GetSnapshotAsync", method.Name);
    }

    private static string Payload() => """
    {
      "schemaVersion": 2,
      "mode": "PAPER SHADOW / NONTRANSMITTING",
      "engineVersion": "shadow_trading_v1",
      "transmitting": false,
      "summary": "Prospective Shadow Trading uses supplied evidence and FakeBroker execution only.",
      "reviewTrades": [
        {
          "shadowTradeId": "shadow-1",
          "symbol": "NVDA",
          "setup": "Breakout",
          "catalyst": "Earnings continuation",
          "marketRegime": "risk_on",
          "session": "REGULAR",
          "decisionTimestamp": "2026-07-23T10:00:00-05:00",
          "evidenceSnapshotTimestamp": "2026-07-23T09:59:00-05:00",
          "tradePlanId": "plan-1",
          "riskDecisionId": "risk-1",
          "riskDecision": "Simulation-only",
          "riskReasons": ["FakeBroker simulation only."],
          "proposedEntry": 100.00,
          "simulatedFill": 100.06,
          "spreadPercent": 0.12,
          "slippageBps": 5.0,
          "stop": 98.00,
          "targets": [104.00, 106.00],
          "exit": 104.00,
          "exitReason": "target_1",
          "idealPnl": 8.00,
          "executablePnl": 7.88,
          "rMultiple": 1.91,
          "mfeDollars": 8.20,
          "maeDollars": -1.10,
          "durationSeconds": 1800,
          "outcome": "WIN",
          "lifecycleState": "completed",
          "direction": "LONG",
          "quantity": 2,
          "displayState": "WINNER",
          "activeMark": {
            "schemaVersion": 1,
            "displayState": "WINNER",
            "direction": "LONG",
            "quantity": 2,
            "simulatedFill": 100.06,
            "currentExecutableMark": 104.00,
            "bid": 104.00,
            "ask": 104.02,
            "unrealizedPnl": null,
            "unrealizedR": null,
            "mfeDollars": 8.20,
            "maeDollars": -1.10,
            "stop": 98.00,
            "targets": [104.00, 106.00],
            "distanceToStop": null,
            "distanceToNextTarget": null,
            "quoteProvider": "synthetic-test-provider",
            "providerQuoteTimestamp": "2026-07-23T10:30:00-05:00",
            "localReceiptTimestamp": "2026-07-23T10:30:00.020-05:00",
            "quoteAgeSeconds": 0.02,
            "holdingDurationSeconds": 1800,
            "lifecycleState": "completed",
            "condition": "LIVE",
            "reason": "Synthetic completed fixture.",
            "finalExecutablePnl": 7.88,
            "finalR": 1.91,
            "exitReason": "target_1"
          },
          "dataQualityState": "COMPLETE",
          "sampleMetadata": {
            "sampleVersion": "synthetic-official-v1",
            "strategyConfigurationFingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "fillModelVersion": "prospective-fakebroker-live-mark-v2",
            "evidenceSchemaVersion": 1,
            "officialSampleAuthorized": true
          },
          "lastReason": "Shadow position closed by target_1.",
          "evidenceLock": {
            "evidenceFrozen": true,
            "planFrozen": true,
            "decisionTimestamp": "2026-07-23T10:00:00-05:00",
            "postDecisionCorrectionOccurred": false,
            "auditStatus": "PASS",
            "reasons": []
          },
          "evidenceEligible": true,
          "countsTowardSample": true,
          "executionQuality": {
            "summary": "FakeBroker applied 5.00 basis points of entry slippage.",
            "factors": [
              "Observed spread at fill was 0.12%.",
              "FakeBroker applied 5.00 basis points of entry slippage."
            ],
            "technicalCodes": [
              {
                "timestamp": "2026-07-23T10:00:05-05:00",
                "eventType": "fake_order_filled",
                "action": "fake_order_filled",
                "result": "filled",
                "reason": "Synthetic fill."
              }
            ]
          }
        }
      ],
      "sample": {
        "minimumRequired": 30,
        "eligibleCompleted": 1,
        "completed": 1,
        "active": 0,
        "unfilled": 0,
        "riskRejected": 0,
        "dataQualityInvalidated": 0,
        "excluded": 0,
        "gateSatisfied": false,
        "sampleVersion": "synthetic-official-v1",
        "strategyConfigurationFingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "fillModelVersion": "prospective-fakebroker-live-mark-v2",
        "evidenceSchemaVersion": 1,
        "officialSampleAuthorized": true,
        "readinessStatus": "IN_PROGRESS",
        "canStartOfficialSample": false,
        "readinessFindings": ["Sample version already contains 1 persisted trade record(s)."],
        "status": "Evidence collection in progress. Results are not yet sufficient for strategy conclusions."
      },
      "reviewMetrics": {
        "sampleStatus": "INSUFFICIENT_SAMPLE",
        "winRatePercent": null,
        "averageWin": null,
        "averageLoss": null,
        "expectancy": null,
        "averageR": null,
        "maximumDrawdown": null,
        "profitFactor": null,
        "idealPnl": null,
        "executablePnl": null,
        "idealVsExecutableGap": null,
        "conclusion": "Evidence collection in progress. Results are not yet sufficient for strategy conclusions."
      }
    }
    """;
}
