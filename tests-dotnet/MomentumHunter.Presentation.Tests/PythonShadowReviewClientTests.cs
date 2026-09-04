using System.Text.Json;
using System.Text.Json.Nodes;
using MomentumHunter.Contracts;
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
        Assert.Equal(LifecyclePositionLinkageStatus.LegacyUnbound, trade.LinkageStatus);
        Assert.Null(trade.OpportunityId);
        Assert.Null(trade.SetupId);
        Assert.Null(trade.PositionId);
        Assert.Null(trade.OpenedAt);
    }

    [Fact]
    public void MapperMapsExactAuthoritativeIdentityAndPreservesOpenedAtOffset()
    {
        const string openedAt = "2026-07-23T10:00:05.123456-05:00";
        using var document = JsonDocument.Parse(IdentityPayload(
            "PROVEN",
            opportunityId: "opportunity-1",
            setupId: "setup-1",
            tradePlanId: "plan-1",
            positionId: "position-1",
            openedAt: openedAt));

        var trade = Assert.Single(PythonShadowReviewSnapshotMapper.Map(document.RootElement).Trades);

        Assert.Equal("opportunity-1", trade.Identity.OpportunityId);
        Assert.Equal("setup-1", trade.Identity.SetupId);
        Assert.Equal("plan-1", trade.Identity.TradePlanId);
        Assert.Equal("position-1", trade.Identity.PositionId);
        Assert.Equal(LifecyclePositionLinkageStatus.Proven, trade.Identity.LinkageStatus);
        Assert.Equal(DateTimeOffset.Parse(openedAt), trade.Identity.OpenedAt);
        Assert.Equal(TimeSpan.FromHours(-5), trade.Identity.OpenedAt?.Offset);
        Assert.Equal(trade.Identity.OpportunityId, trade.OpportunityId);
        Assert.Equal(trade.Identity.SetupId, trade.SetupId);
        Assert.Equal(trade.Identity.TradePlanId, trade.TradePlanId);
        Assert.Equal(trade.Identity.PositionId, trade.PositionId);
        Assert.Equal(trade.Identity.OpenedAt, trade.OpenedAt);
        Assert.Equal(trade.Identity.LinkageStatus, trade.LinkageStatus);
    }

    [Theory]
    [InlineData("PROVEN", LifecyclePositionLinkageStatus.Proven)]
    [InlineData("UNKNOWN", LifecyclePositionLinkageStatus.Unknown)]
    [InlineData("UNAVAILABLE", LifecyclePositionLinkageStatus.Unavailable)]
    [InlineData("LEGACY_UNBOUND", LifecyclePositionLinkageStatus.LegacyUnbound)]
    public void MapperKeepsAllPythonLinkageStatesDistinct(
        string state,
        LifecyclePositionLinkageStatus expected)
    {
        var payload = state switch
        {
            "PROVEN" => IdentityPayload(
                state,
                opportunityId: "opportunity-1",
                setupId: "setup-1",
                tradePlanId: "plan-1",
                positionId: "position-1",
                openedAt: "2026-07-23T10:00:05-05:00"),
            "UNAVAILABLE" => IdentityPayload(
                state,
                opportunityId: "opportunity-1",
                setupId: "setup-1",
                tradePlanId: "plan-1"),
            "UNKNOWN" => IdentityPayload(
                state,
                opportunityId: "opportunity-1",
                setupId: null,
                tradePlanId: "plan-1",
                positionId: "position-with-incomplete-provenance"),
            _ => IdentityPayload(
                state,
                opportunityId: null,
                setupId: null,
                tradePlanId: "plan-1"),
        };
        using var document = JsonDocument.Parse(payload);

        var trade = Assert.Single(PythonShadowReviewSnapshotMapper.Map(document.RootElement).Trades);

        Assert.Equal(expected, trade.LinkageStatus);
    }

    [Theory]
    [InlineData("opportunityId")]
    [InlineData("setupId")]
    [InlineData("tradePlanId")]
    [InlineData("positionId")]
    [InlineData("openedAt")]
    public void MapperRejectsIncompleteProvenChain(string missingField)
    {
        var root = IdentityPayloadNode(
            "PROVEN",
            opportunityId: "opportunity-1",
            setupId: "setup-1",
            tradePlanId: "plan-1",
            positionId: "position-1",
            openedAt: "2026-07-23T10:00:05-05:00");
        TradeNode(root)[missingField] = null;
        using var document = JsonDocument.Parse(root.ToJsonString());

        Assert.Throws<InvalidDataException>(
            () => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Theory]
    [InlineData("NOT_AVAILABLE")]
    [InlineData("proven")]
    [InlineData("UNRECOGNIZED")]
    [InlineData("")]
    public void MapperRejectsMalformedAuthoritativeLinkageState(string state)
    {
        using var document = JsonDocument.Parse(IdentityPayload(
            state,
            opportunityId: null,
            setupId: null,
            tradePlanId: "plan-1"));

        Assert.Throws<InvalidDataException>(
            () => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsHistoricalSentinelAsNewPositionIdentity()
    {
        using var document = JsonDocument.Parse(IdentityPayload(
            "UNKNOWN",
            opportunityId: "opportunity-1",
            setupId: "setup-1",
            tradePlanId: "plan-1",
            positionId: "NOT_AVAILABLE"));

        Assert.Throws<InvalidDataException>(
            () => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperDowngradesHistoricalIdentityLinkageAndSentinelsToLegacyUnbound()
    {
        var root = PayloadNode();
        var tradeNode = TradeNode(root);
        tradeNode["identityLinkage"] = "PROVEN";
        tradeNode["opportunityId"] = "UNKNOWN";
        tradeNode["setupId"] = "UNKNOWN";
        tradeNode["positionId"] = "NOT_AVAILABLE";
        tradeNode["openedAt"] = "";
        using var document = JsonDocument.Parse(root.ToJsonString());

        var trade = Assert.Single(PythonShadowReviewSnapshotMapper.Map(document.RootElement).Trades);

        Assert.Equal(LifecyclePositionLinkageStatus.LegacyUnbound, trade.LinkageStatus);
        Assert.Null(trade.OpportunityId);
        Assert.Null(trade.SetupId);
        Assert.Null(trade.PositionId);
        Assert.Null(trade.OpenedAt);
        Assert.Null(typeof(ShadowTradeIdentity).GetProperty("IdentityLinkage"));
    }

    [Fact]
    public void MapperRejectsMixedHistoricalAndAuthoritativeLinkageFields()
    {
        var root = IdentityPayloadNode(
            "UNKNOWN",
            opportunityId: null,
            setupId: null,
            tradePlanId: "plan-1");
        TradeNode(root)["identityLinkage"] = "UNKNOWN";
        using var document = JsonDocument.Parse(root.ToJsonString());

        Assert.Throws<InvalidDataException>(
            () => PythonShadowReviewSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperPreservesUnavailableOpenedAtWithoutSubstitutingAnotherTimestamp()
    {
        using var document = JsonDocument.Parse(IdentityPayload(
            "UNAVAILABLE",
            opportunityId: "opportunity-1",
            setupId: "setup-1",
            tradePlanId: "plan-1"));

        var trade = Assert.Single(PythonShadowReviewSnapshotMapper.Map(document.RootElement).Trades);

        Assert.Equal(LifecyclePositionLinkageStatus.Unavailable, trade.LinkageStatus);
        Assert.Null(trade.PositionId);
        Assert.Null(trade.OpenedAt);
        Assert.NotEqual(trade.DecisionTimestamp, trade.OpenedAt);
        Assert.NotEqual(trade.Identity.EvidenceSnapshotTimestamp, trade.OpenedAt);
    }

    [Fact]
    public void MapperKeepsRepeatedSymbolsDistinctBySuppliedIdentityOnly()
    {
        var root = IdentityPayloadNode(
            "PROVEN",
            opportunityId: "opportunity-1",
            setupId: "setup-1",
            tradePlanId: "plan-1",
            positionId: "position-1",
            openedAt: "2026-07-23T10:00:05-05:00");
        var trades = root["reviewTrades"]!.AsArray();
        var second = JsonNode.Parse(trades[0]!.ToJsonString())!.AsObject();
        second["shadowTradeId"] = "shadow-2";
        second["opportunityId"] = "opportunity-2";
        second["setupId"] = "setup-2";
        second["tradePlanId"] = "plan-2";
        second["positionId"] = "position-2";
        second["openedAt"] = "2026-07-23T10:01:05-05:00";
        second["evidenceEligible"] = false;
        second["countsTowardSample"] = false;
        trades.Add(second);
        using var document = JsonDocument.Parse(root.ToJsonString());

        var mapped = PythonShadowReviewSnapshotMapper.Map(document.RootElement).Trades;

        Assert.Equal(2, mapped.Count);
        Assert.All(mapped, trade => Assert.Equal("NVDA", trade.Symbol));
        Assert.Equal(["opportunity-1", "opportunity-2"], mapped.Select(trade => trade.OpportunityId));
        Assert.Equal(["setup-1", "setup-2"], mapped.Select(trade => trade.SetupId));
        Assert.Equal(["plan-1", "plan-2"], mapped.Select(trade => trade.TradePlanId));
        Assert.Equal(["position-1", "position-2"], mapped.Select(trade => trade.PositionId));
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

    private static string IdentityPayload(
        string linkageStatus,
        string? opportunityId,
        string? setupId,
        string tradePlanId,
        string? positionId = null,
        string? openedAt = null) =>
        IdentityPayloadNode(
            linkageStatus,
            opportunityId,
            setupId,
            tradePlanId,
            positionId,
            openedAt).ToJsonString();

    private static JsonObject IdentityPayloadNode(
        string linkageStatus,
        string? opportunityId,
        string? setupId,
        string tradePlanId,
        string? positionId = null,
        string? openedAt = null)
    {
        var root = PayloadNode();
        var trade = TradeNode(root);
        trade["linkageStatus"] = linkageStatus;
        trade["opportunityId"] = opportunityId;
        trade["setupId"] = setupId;
        trade["tradePlanId"] = tradePlanId;
        trade["positionId"] = positionId;
        trade["openedAt"] = openedAt;
        return root;
    }

    private static JsonObject PayloadNode() => JsonNode.Parse(Payload())!.AsObject();

    private static JsonObject TradeNode(JsonObject root) =>
        root["reviewTrades"]!.AsArray()[0]!.AsObject();

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
