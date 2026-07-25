using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

/// <summary>
/// Read-only mapping of canonical Python/FakeBroker Shadow Trading evidence.
/// </summary>
public sealed class PythonShadowReviewClient : IShadowReviewClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonShadowReviewClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<ShadowReviewSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
        PythonShadowReviewSnapshotMapper.Map(await _connection.GetShadowTradingSnapshotAsync(cancellationToken));
}

public static class PythonShadowReviewSnapshotMapper
{
    private const string ShadowMode = "PAPER SHADOW / NONTRANSMITTING";

    public static ShadowReviewSnapshot Map(JsonElement root)
    {
        RequireReadOnlyShadowMode(root);
        var trades = Array(root, "reviewTrades").Select(Trade).ToArray();
        var sample = Sample(Object(root, "sample"));
        var metrics = Metrics(Object(root, "reviewMetrics"));
        if (sample.EligibleCompleted != trades.Count(trade => trade.CountsTowardSample))
        {
            throw new InvalidDataException("Shadow sample count does not match the eligible completed trade records.");
        }
        if (sample.GateSatisfied != (sample.EligibleCompleted >= sample.MinimumRequired))
        {
            throw new InvalidDataException("Shadow sample gate is inconsistent with its minimum sample size.");
        }
        if (!sample.GateSatisfied && HasUngatedMetric(metrics))
        {
            throw new InvalidDataException("Shadow profitability metrics were exposed before the minimum sample gate.");
        }
        if (trades.Any(trade => trade.CountsTowardSample && trade.SampleDefinition != sample.Definition))
        {
            throw new InvalidDataException("A counted Shadow trade does not match the active sample definition.");
        }
        if (sample.CanStartOfficialSample
            && (!sample.Definition.OfficialSampleAuthorized
                || !string.Equals(sample.ReadinessStatus, "PASS", StringComparison.Ordinal)
                || sample.ReadinessFindings.Count != 0))
        {
            throw new InvalidDataException("The Shadow sample start gate is internally inconsistent.");
        }
        if (!sample.CanStartOfficialSample
            && string.Equals(sample.ReadinessStatus, "PASS", StringComparison.Ordinal))
        {
            throw new InvalidDataException("An active empty Shadow sample must expose its prospective start state consistently.");
        }

        return new ShadowReviewSnapshot(
            RequiredInteger(root, "schemaVersion"),
            RequiredString(root, "mode"),
            RequiredString(root, "engineVersion"),
            false,
            String(root, "summary") ?? "Prospective Shadow Trading review.",
            trades,
            sample,
            metrics);
    }

    private static ShadowTradeReviewSnapshot Trade(JsonElement item)
    {
        var evidenceLockItem = Object(item, "evidenceLock");
        var evidenceLock = new ShadowEvidenceLock(
            Boolean(evidenceLockItem, "evidenceFrozen"),
            Boolean(evidenceLockItem, "planFrozen"),
            RequiredTimestamp(evidenceLockItem, "decisionTimestamp"),
            Boolean(evidenceLockItem, "postDecisionCorrectionOccurred"),
            RequiredString(evidenceLockItem, "auditStatus"),
            StringArray(evidenceLockItem, "reasons"));
        var eligible = Boolean(item, "evidenceEligible");
        var countsTowardSample = Boolean(item, "countsTowardSample");
        var sampleDefinition = SampleDefinition(Object(item, "sampleMetadata"));
        if (eligible && (!evidenceLock.EvidenceFrozen
                         || !evidenceLock.PlanFrozen
                         || evidenceLock.PostDecisionCorrectionOccurred
                         || !string.Equals(evidenceLock.AuditStatus, "PASS", StringComparison.Ordinal)
                         || !sampleDefinition.OfficialSampleAuthorized))
        {
            throw new InvalidDataException("A Shadow trade cannot be evidence-eligible when an evidence lock, audit, or sample authorization failed.");
        }

        var lifecycleState = RequiredString(item, "lifecycleState");
        var outcomeLabel = RequiredString(item, "outcome");
        if (countsTowardSample && (!eligible
                                  || !string.Equals(lifecycleState, "completed", StringComparison.Ordinal)
                                  || outcomeLabel is not ("WIN" or "LOSS" or "FLAT")))
        {
            throw new InvalidDataException("Only eligible completed Shadow outcomes may count toward the evidence sample.");
        }

        var qualityItem = Object(item, "executionQuality");
        var quality = new ShadowExecutionQuality(
            RequiredString(qualityItem, "summary"),
            StringArray(qualityItem, "factors"),
            Array(qualityItem, "technicalCodes")
                .Select(code => new ShadowTechnicalEvent(
                    RequiredTimestamp(code, "timestamp"),
                    RequiredString(code, "eventType"),
                    RequiredString(code, "action"),
                    RequiredString(code, "result"),
                    String(code, "reason") ?? string.Empty))
                .ToArray());
        var decisionTimestamp = RequiredTimestamp(item, "decisionTimestamp");
        if (decisionTimestamp != evidenceLock.DecisionTimestamp)
        {
            throw new InvalidDataException("Shadow decision timestamp does not match the frozen evidence lock.");
        }

        return new ShadowTradeReviewSnapshot(
            new ShadowTradeIdentity(
                RequiredString(item, "shadowTradeId"),
                RequiredString(item, "symbol"),
                String(item, "setup") ?? "Unknown",
                String(item, "catalyst") ?? "Unknown",
                String(item, "marketRegime") ?? "Unknown",
                String(item, "session") ?? "Unknown",
                decisionTimestamp,
                RequiredTimestamp(item, "evidenceSnapshotTimestamp"),
                RequiredString(item, "tradePlanId"),
                RequiredString(item, "riskDecisionId")),
            new ShadowPlanReview(
                RequiredString(item, "riskDecision"),
                StringArray(item, "riskReasons"),
                Decimal(item, "proposedEntry"),
                Decimal(item, "stop"),
                NumberArray(item, "targets")),
            new ShadowExecutionReview(
                Decimal(item, "simulatedFill"),
                Decimal(item, "spreadPercent"),
                Decimal(item, "slippageBps"),
                Decimal(item, "exit"),
                String(item, "exitReason") ?? string.Empty,
                lifecycleState,
                String(item, "lastReason") ?? string.Empty,
                quality),
            new ShadowOutcomeReview(
                outcomeLabel,
                Decimal(item, "idealPnl"),
                Decimal(item, "executablePnl"),
                Decimal(item, "rMultiple"),
                Decimal(item, "mfeDollars"),
                Decimal(item, "maeDollars"),
                Integer(item, "durationSeconds")),
            evidenceLock,
            sampleDefinition,
            RequiredString(item, "dataQualityState"),
            eligible,
            countsTowardSample);
    }

    private static ShadowSampleStatus Sample(JsonElement item)
    {
        var definition = new ShadowSampleDefinition(
            RequiredString(item, "sampleVersion"),
            RequiredString(item, "strategyConfigurationFingerprint"),
            RequiredString(item, "fillModelVersion"),
            RequiredInteger(item, "evidenceSchemaVersion"),
            Boolean(item, "officialSampleAuthorized"));
        ValidateSampleDefinition(definition);
        var readinessStatus = RequiredString(item, "readinessStatus");
        if (readinessStatus is not ("PASS" or "BLOCKED" or "IN_PROGRESS"))
        {
            throw new InvalidDataException("Shadow sample readiness status is unsupported.");
        }
        return new ShadowSampleStatus(
            RequiredInteger(item, "minimumRequired"),
            RequiredInteger(item, "eligibleCompleted"),
            RequiredInteger(item, "completed"),
            RequiredInteger(item, "active"),
            RequiredInteger(item, "unfilled"),
            RequiredInteger(item, "riskRejected"),
            RequiredInteger(item, "dataQualityInvalidated"),
            RequiredInteger(item, "excluded"),
            Boolean(item, "gateSatisfied"),
            RequiredString(item, "status"),
            definition,
            readinessStatus,
            Boolean(item, "canStartOfficialSample"),
            StringArray(item, "readinessFindings"));
    }

    private static ShadowSampleDefinition SampleDefinition(JsonElement item)
    {
        var definition = new ShadowSampleDefinition(
            RequiredString(item, "sampleVersion"),
            RequiredString(item, "strategyConfigurationFingerprint"),
            RequiredString(item, "fillModelVersion"),
            RequiredInteger(item, "evidenceSchemaVersion"),
            Boolean(item, "officialSampleAuthorized"));
        ValidateSampleDefinition(definition);
        return definition;
    }

    private static void ValidateSampleDefinition(ShadowSampleDefinition definition)
    {
        if (string.IsNullOrWhiteSpace(definition.SampleVersion)
            || definition.SampleVersion.Length > 64
            || !(definition.SampleVersion[0] is >= 'a' and <= 'z'
                 || definition.SampleVersion[0] is >= '0' and <= '9')
            || definition.SampleVersion.Any(character =>
                !(character is >= 'a' and <= 'z'
                  || character is >= '0' and <= '9'
                  || character is '.' or '_' or '-'))
            || definition.StrategyConfigurationFingerprint.Length != 64
            || definition.StrategyConfigurationFingerprint.Any(character =>
                !Uri.IsHexDigit(character) || char.IsUpper(character))
            || string.IsNullOrWhiteSpace(definition.FillModelVersion)
            || definition.EvidenceSchemaVersion <= 0)
        {
            throw new InvalidDataException("Shadow sample definition is malformed.");
        }
    }

    private static ShadowAggregateMetrics Metrics(JsonElement item) => new(
        RequiredString(item, "sampleStatus"),
        Decimal(item, "winRatePercent"),
        Decimal(item, "averageWin"),
        Decimal(item, "averageLoss"),
        Decimal(item, "expectancy"),
        Decimal(item, "averageR"),
        Decimal(item, "maximumDrawdown"),
        Decimal(item, "profitFactor"),
        Decimal(item, "idealPnl"),
        Decimal(item, "executablePnl"),
        Decimal(item, "idealVsExecutableGap"),
        RequiredString(item, "conclusion"));

    private static bool HasUngatedMetric(ShadowAggregateMetrics metrics) =>
        metrics.WinRatePercent is not null
        || metrics.AverageWin is not null
        || metrics.AverageLoss is not null
        || metrics.Expectancy is not null
        || metrics.AverageR is not null
        || metrics.MaximumDrawdown is not null
        || metrics.ProfitFactor is not null
        || metrics.IdealPnl is not null
        || metrics.ExecutablePnl is not null
        || metrics.IdealVsExecutableGap is not null;

    private static void RequireReadOnlyShadowMode(JsonElement root)
    {
        if (!string.Equals(String(root, "mode"), ShadowMode, StringComparison.Ordinal))
        {
            throw new InvalidDataException("The Python host payload is not the nontransmitting Shadow Trading contract.");
        }
        if (!Property(root, "transmitting", out var transmitting) || transmitting.ValueKind != JsonValueKind.False)
        {
            throw new InvalidDataException("The Shadow Trading review contract must explicitly declare transmitting false.");
        }
    }

    private static JsonElement Object(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value
            : throw new InvalidDataException($"Shadow review field '{name}' must be an object.");

    private static IEnumerable<JsonElement> Array(JsonElement item, string name)
    {
        if (item.ValueKind == JsonValueKind.Object
            && item.TryGetProperty(name, out var value)
            && value.ValueKind == JsonValueKind.Array)
        {
            return value.EnumerateArray().ToArray();
        }
        throw new InvalidDataException($"Shadow review field '{name}' must be an array.");
    }

    private static IReadOnlyList<string> StringArray(JsonElement item, string name) =>
        Array(item, name)
            .Where(value => value.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(value.GetString()))
            .Select(value => value.GetString()!)
            .ToArray();

    private static IReadOnlyList<decimal> NumberArray(JsonElement item, string name) =>
        Array(item, name)
            .Select(value => value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var number)
                ? number
                : throw new InvalidDataException($"Shadow review field '{name}' contains a non-numeric value."))
            .ToArray();

    private static string RequiredString(JsonElement item, string name) =>
        String(item, name) is { } value && !string.IsNullOrWhiteSpace(value)
            ? value
            : throw new InvalidDataException($"Shadow review field '{name}' is required.");

    private static string? String(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.Object
        && item.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int RequiredInteger(JsonElement item, string name) =>
        Integer(item, name) ?? throw new InvalidDataException($"Shadow review field '{name}' must be an integer.");

    private static int? Integer(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            return null;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String
               && int.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
            ? number
            : null;
    }

    private static decimal? Decimal(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            return null;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String
               && decimal.TryParse(value.GetString(), NumberStyles.Number, CultureInfo.InvariantCulture, out number)
            ? number
            : null;
    }

    private static bool Boolean(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.True;

    private static DateTimeOffset RequiredTimestamp(JsonElement item, string name) =>
        DateTimeOffset.TryParse(String(item, name), CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var value)
            ? value
            : throw new InvalidDataException($"Shadow review field '{name}' must be a timestamp.");

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object
               && item.TryGetProperty(name, out value)
               && value.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined;
    }
}
