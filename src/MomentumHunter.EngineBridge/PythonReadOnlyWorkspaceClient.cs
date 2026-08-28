using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

/// <summary>
/// Maps only the Python host's persisted-evidence snapshot. It deliberately has no
/// TradePlan, simulation, provider, broker, Paper, or Live operation surface.
/// </summary>
public sealed class PythonReadOnlyWorkspaceClient : IReadOnlyWorkspaceClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonReadOnlyWorkspaceClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<ReadOnlyWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
    {
        var payload = await _connection.GetReadOnlyWorkspaceSnapshotAsync(cancellationToken);
        return PythonReadOnlyWorkspaceSnapshotMapper.Map(payload);
    }
}

public static class PythonReadOnlyWorkspaceSnapshotMapper
{
    public static ReadOnlyWorkspaceSnapshot Map(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("The Python read-only workspace snapshot must be a JSON object.");
        }

        var schemaVersion = Integer(root, "schemaVersion") ?? 0;
        if (schemaVersion is not (1 or 2 or 3))
        {
            throw new InvalidDataException($"Unsupported Python read-only workspace schema version: {schemaVersion}.");
        }

        var observedAt = Timestamp(root, "observedAt", DateTimeOffset.UtcNow);
        var candidates = Array(root, "candidates").Select(item => Candidate(item, observedAt)).ToArray();
        var activity = Array(root, "activity").Select(item => Activity(item, observedAt)).ToArray();
        var health = Health(Object(root, "health"), observedAt);
        var alertEvidence = schemaVersion >= 2
            ? AlertEvidence(Object(root, "alertEvidence"), observedAt)
            : UnavailableAlertEvidence(observedAt, "Alert evidence was not supplied by read-only workspace schema v1.");
        var replay = Replay(Object(root, "replay"), observedAt);
        var commandCenter = schemaVersion >= 3
            ? CommandCenter(Object(root, "commandCenter"), observedAt)
            : null;
        return new ReadOnlyWorkspaceSnapshot(
            schemaVersion,
            observedAt,
            String(root, "summary") ?? "Python read-only workspace snapshot.",
            candidates,
            activity,
            health,
            alertEvidence,
            replay,
            Boolean(root, "planningAvailable"),
            commandCenter);
    }

    private static CommandCenterSnapshot? CommandCenter(JsonElement item, DateTimeOffset fallback)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        var observedAt = Timestamp(item, "observedAt", fallback);
        var coverage = Object(item, "sourceCoverage");
        return new CommandCenterSnapshot(
            observedAt,
            String(item, "sessionDate") ?? string.Empty,
            CommandCenterState(String(item, "projectionState")),
            new CommandCenterSourceCoverage(
                CommandCenterState(String(coverage, "radar")),
                CommandCenterState(String(coverage, "accepted")),
                CommandCenterState(String(coverage, "rejected")),
                CommandCenterState(String(coverage, "rankedCandidates")),
                CommandCenterState(String(coverage, "miniCharts"))),
            StringArray(item, "limitations"),
            String(item, "populationContractVersion") ?? "UNAVAILABLE",
            StringDictionary(Object(item, "sourceIdentities")),
            Array(item, "radarMembers").Select(RadarMember).ToArray(),
            Array(item, "acceptedDispositions").Select(Disposition).ToArray(),
            Array(item, "rejectedDispositions").Select(Disposition).ToArray(),
            Array(item, "rankedCandidates").Select(RankedCandidate).OrderBy(row => row.SourceRank).ToArray(),
            Array(item, "lifecycleEvents").Select(LifecycleEvent).ToArray(),
            MiniChartDictionary(Object(item, "miniChartsBySymbol"), observedAt),
            Timestamp(item, "reportObservedAt", observedAt),
            String(item, "radarMapGeometryState") ?? "NOT_YET_AUTHORIZED");
    }

    private static CommandCenterRadarMemberSnapshot RadarMember(JsonElement item) => new(
        String(item, "radarPresentationIdentity") ?? string.Empty,
        Integer(item, "membershipGeneration") ?? 0,
        String(item, "derivedLifecycleOpportunityId") ?? string.Empty,
        String(item, "symbol") ?? string.Empty,
        String(item, "sessionDate") ?? string.Empty,
        NullableTimestamp(item, "firstSurfacedAt"),
        NullableTimestamp(item, "lastObservedAt"),
        String(item, "currentState") ?? "UNAVAILABLE",
        String(item, "currentTier") ?? "UNAVAILABLE",
        String(item, "sourceSnapshotIdentity") ?? string.Empty,
        String(item, "dataLineage") ?? "Source lineage unavailable.");

    private static CommandCenterDispositionSnapshot Disposition(JsonElement item) => new(
        String(item, "dispositionPresentationIdentity") ?? string.Empty,
        String(item, "dispositionEventId") ?? string.Empty,
        String(item, "kind") ?? "UNAVAILABLE",
        String(item, "opportunityId") ?? string.Empty,
        String(item, "setupId") ?? string.Empty,
        String(item, "setupFamily") ?? string.Empty,
        Integer(item, "setupSequence") ?? 0,
        String(item, "symbol") ?? string.Empty,
        String(item, "sessionDate") ?? string.Empty,
        String(item, "previousState") ?? string.Empty,
        String(item, "reachedState") ?? string.Empty,
        NullableTimestamp(item, "occurredAt"),
        String(item, "reason") ?? "Reason unavailable.",
        String(item, "sourceIdentity") ?? string.Empty,
        String(item, "evidenceFingerprint") ?? string.Empty,
        String(item, "dataLineage") ?? "Source lineage unavailable.");

    private static CommandCenterRankedCandidateSnapshot RankedCandidate(JsonElement item) => new(
        String(item, "stableCandidateIdentity") ?? string.Empty,
        String(item, "symbol") ?? string.Empty,
        String(item, "company") ?? "Company unavailable",
        Integer(item, "sourceRank") ?? 0,
        Integer(item, "score"),
        Decimal(item, "relativeVolume"),
        Decimal(item, "lastPrice"),
        Decimal(item, "changePercent"),
        String(item, "catalystSummary") ?? "Catalyst unavailable",
        String(item, "radarMemberIdentity"),
        StringArray(item, "acceptedDispositionIds"),
        StringArray(item, "rejectedDispositionIds"),
        String(item, "rawMachineState"),
        NullableTimestamp(item, "displayFirstSurfacedAt"),
        NullableTimestamp(item, "displayStateChangedAt"),
        String(item, "dataLineage") ?? "Source lineage unavailable.",
        String(item, "sourceIdentity") ?? string.Empty,
        String(item, "miniChartSymbolKey") ?? string.Empty,
        Decimal(item, "hypotheticalEntry"),
        Decimal(item, "hypotheticalStop"),
        Decimal(item, "hypotheticalTarget"));

    private static CommandCenterLifecycleEventSnapshot LifecycleEvent(JsonElement item) => new(
        String(item, "eventIdentity") ?? string.Empty,
        String(item, "sourceKind") ?? "UNAVAILABLE",
        String(item, "symbol") ?? string.Empty,
        NullableTimestamp(item, "occurredAt"),
        String(item, "previousState") ?? string.Empty,
        String(item, "nextState") ?? string.Empty,
        String(item, "reason") ?? "Reason unavailable.",
        String(item, "opportunityId") ?? string.Empty,
        String(item, "radarMemberIdentity"),
        String(item, "derivedLifecycleOpportunityId"),
        String(item, "setupId") ?? string.Empty);

    private static IReadOnlyDictionary<string, CommandCenterMiniChartSeriesSnapshot> MiniChartDictionary(
        JsonElement item,
        DateTimeOffset fallback)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            return new Dictionary<string, CommandCenterMiniChartSeriesSnapshot>();
        }

        return item.EnumerateObject().ToDictionary(
            property => property.Name,
            property => MiniChart(property.Value, fallback),
            StringComparer.OrdinalIgnoreCase);
    }

    private static CommandCenterMiniChartSeriesSnapshot MiniChart(JsonElement item, DateTimeOffset fallback) => new(
        CommandCenterState(String(item, "state")),
        String(item, "symbol") ?? string.Empty,
        String(item, "interval") ?? "15m",
        Integer(item, "requestedSessionCount") ?? 2,
        StringArray(item, "sourceSessionDates"),
        Array(item, "points")
            .Select(point => new CommandCenterMiniChartPointSnapshot(
                Timestamp(point, "timestamp", fallback),
                Decimal(point, "close") ?? 0m))
            .ToArray(),
        String(item, "sourceLabel") ?? "Stored history source unavailable",
        Timestamp(item, "asOf", fallback),
        Integer(item, "gapCount") ?? 0,
        Integer(item, "correctionCount") ?? 0,
        StringArray(item, "findings"),
        String(item, "limitation") ?? string.Empty);

    private static CommandCenterEvidenceState CommandCenterState(string? value) => value?.Trim().ToUpperInvariant() switch
    {
        "AVAILABLE" => CommandCenterEvidenceState.Available,
        "PARTIAL" => CommandCenterEvidenceState.Partial,
        _ => CommandCenterEvidenceState.Unavailable,
    };

    private static IReadOnlyList<string> StringArray(JsonElement item, string name) =>
        Array(item, name)
            .Where(value => value.ValueKind == JsonValueKind.String)
            .Select(value => value.GetString()?.Trim() ?? string.Empty)
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .ToArray();

    private static IReadOnlyDictionary<string, string> StringDictionary(JsonElement item)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            return new Dictionary<string, string>();
        }

        return item.EnumerateObject()
            .Where(property => property.Value.ValueKind == JsonValueKind.String)
            .ToDictionary(
                property => property.Name,
                property => property.Value.GetString()?.Trim() ?? string.Empty,
                StringComparer.Ordinal);
    }

    private static CandidateSnapshot Candidate(JsonElement item, DateTimeOffset fallback)
    {
        var catalyst = String(item, "catalyst") ?? "No stored catalyst summary";
        var observedAt = Timestamp(item, "observedAt", fallback);
        var readinessLabel = String(item, "sourceReadinessLabel") ?? "UNAVAILABLE";
        var catalystPayload = Object(item, "catalystSummary");
        var lineagePayload = Object(item, "dataLineage");
        return new CandidateSnapshot(
            String(item, "symbol") ?? string.Empty,
            String(item, "company") ?? "Company unavailable",
            Decimal(item, "lastPrice"),
            Decimal(item, "changePercent"),
            Long(item, "volume"),
            Decimal(item, "relativeVolume"),
            catalyst,
            Readiness(readinessLabel),
            String(item, "qualityLabel") ?? "Source quality unavailable",
            observedAt,
            Integer(item, "score") ?? 0,
            String(item, "liquidity") ?? "Liquidity data unavailable",
            new CatalystSummary(
                String(catalystPayload, "headline") ?? catalyst,
                String(catalystPayload, "sourceLabel") ?? "Persisted trade-planning report",
                Timestamp(catalystPayload, "observedAt", observedAt)),
            new DataLineage(
                String(lineagePayload, "sourceLabel") ?? "Unavailable source lineage",
                Timestamp(lineagePayload, "asOf", observedAt),
                String(lineagePayload, "summary") ?? "No source lineage was supplied."),
            readinessLabel,
            Array(item, "notes")
                .Where(note => note.ValueKind == JsonValueKind.String)
                .Select(note => note.GetString()?.Trim() ?? string.Empty)
                .Where(note => !string.IsNullOrWhiteSpace(note))
                .ToArray());
    }

    private static ActivityEvent Activity(JsonElement item, DateTimeOffset fallback) => new(
        Timestamp(item, "timestamp", fallback),
        String(item, "category") ?? "Evidence",
        String(item, "message") ?? "No activity detail supplied.",
        String(item, "symbol") ?? string.Empty,
        HealthStateValue(String(item, "state")));

    private static SystemHealthSnapshot Health(JsonElement item, DateTimeOffset fallback) => new(
        Array(item, "components").Select(component => new HealthComponentSnapshot(
            String(component, "name") ?? "Unnamed component",
            HealthStateValue(String(component, "state")),
            String(component, "summary") ?? "No health detail supplied.",
            Timestamp(component, "checkedAt", fallback))).ToArray(),
        Timestamp(item, "checkedAt", fallback));

    private static AlertEvidenceSnapshot AlertEvidence(JsonElement item, DateTimeOffset fallback)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            return UnavailableAlertEvidence(fallback, "Alert evidence was not supplied by the Python read-only workspace.");
        }

        return new AlertEvidenceSnapshot(
            AlertEvidenceStateValue(String(item, "state")),
            Timestamp(item, "asOf", fallback),
            String(item, "summary") ?? "No alert evidence summary was supplied.",
            Math.Max(0, Integer(item, "totalAlertCount") ?? 0),
            Math.Max(0, Integer(item, "activeAlertCount") ?? 0),
            Math.Max(0, Integer(item, "recordedOutcomeCount") ?? 0),
            Math.Max(0, Integer(item, "unscorableOutcomeCount") ?? 0),
            Array(item, "activeAlerts").Select(Alert).ToArray(),
            Array(item, "outcomes").Select(Outcome).ToArray());
    }

    private static AlertEvent Alert(JsonElement item) => new(
        String(item, "alertId") ?? string.Empty,
        NullableTimestamp(item, "timestamp"),
        String(item, "symbol") ?? string.Empty,
        String(item, "alertType") ?? string.Empty,
        String(item, "state") ?? "UNAVAILABLE",
        String(item, "summary") ?? "No alert summary was supplied.");

    private static OutcomeSnapshot Outcome(JsonElement item) => new(
        String(item, "alertId") ?? string.Empty,
        String(item, "symbol") ?? string.Empty,
        NullableTimestamp(item, "alertTimestamp"),
        String(item, "status") ?? "UNAVAILABLE",
        String(item, "classification") ?? "UNAVAILABLE",
        String(item, "summary") ?? "No outcome summary was supplied.");

    private static AlertEvidenceSnapshot UnavailableAlertEvidence(DateTimeOffset observedAt, string summary) => new(
        AlertEvidenceState.Unavailable,
        observedAt,
        summary,
        0,
        0,
        0,
        0,
        [],
        []);

    private static ReplaySnapshot Replay(JsonElement item, DateTimeOffset fallback) => new(
        String(item, "replayId") ?? "UNAVAILABLE",
        Timestamp(item, "asOf", fallback),
        String(item, "symbol") ?? string.Empty,
        String(item, "interval") ?? "source capture",
        String(item, "summary") ?? "Replay context is unavailable." );

    private static ReadinessState Readiness(string label)
    {
        var normalized = label.Trim().ToUpperInvariant();
        if (normalized.StartsWith("EXECUTION_READY", StringComparison.Ordinal))
        {
            return ReadinessState.ReadyForSimulation;
        }
        if (normalized.Contains("PLANNING", StringComparison.Ordinal) || normalized.Contains("EVIDENCE", StringComparison.Ordinal))
        {
            return ReadinessState.NeedsEvidence;
        }
        if (normalized.Contains("DO_NOT_TRADE", StringComparison.Ordinal) || normalized.Contains("BLOCKED", StringComparison.Ordinal))
        {
            return ReadinessState.Blocked;
        }
        return ReadinessState.StaleData;
    }

    private static HealthState HealthStateValue(string? state) => state?.Trim().ToUpperInvariant() switch
    {
        "HEALTHY" or "IDLE" or "RUNNING" or "PAUSED" => HealthState.Healthy,
        "DEGRADED" or "FAILED" or "BLOCKED" => HealthState.Degraded,
        _ => HealthState.Unavailable,
    };

    private static AlertEvidenceState AlertEvidenceStateValue(string? state) => state?.Trim().ToUpperInvariant() switch
    {
        "AVAILABLE" => AlertEvidenceState.Available,
        "EMPTY" => AlertEvidenceState.Empty,
        _ => AlertEvidenceState.Unavailable,
    };

    private static JsonElement Object(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value
            : default;

    private static IEnumerable<JsonElement> Array(JsonElement item, string name)
    {
        if (item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array)
        {
            return value.EnumerateArray().ToArray();
        }

        return [];
    }

    private static string? String(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static DateTimeOffset? NullableTimestamp(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        return DateTimeOffset.TryParse(
            value.GetString(),
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
            out var timestamp)
            ? timestamp
            : null;
    }

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
        return value.ValueKind == JsonValueKind.String && int.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
            ? number
            : null;
    }

    private static long? Long(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            return null;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String && long.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
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
        return value.ValueKind == JsonValueKind.String && decimal.TryParse(value.GetString(), NumberStyles.Number, CultureInfo.InvariantCulture, out number)
            ? number
            : null;
    }

    private static bool Boolean(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.True;

    private static DateTimeOffset Timestamp(JsonElement item, string name, DateTimeOffset fallback) =>
        DateTimeOffset.TryParse(String(item, name), CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var value)
            ? value
            : fallback;

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out value) && value.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined;
    }
}
