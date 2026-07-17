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

        var observedAt = Timestamp(root, "observedAt", DateTimeOffset.UtcNow);
        var candidates = Array(root, "candidates").Select(item => Candidate(item, observedAt)).ToArray();
        var activity = Array(root, "activity").Select(item => Activity(item, observedAt)).ToArray();
        var health = Health(Object(root, "health"), observedAt);
        var replay = Replay(Object(root, "replay"), observedAt);
        return new ReadOnlyWorkspaceSnapshot(
            Integer(root, "schemaVersion") ?? 0,
            observedAt,
            String(root, "summary") ?? "Python read-only workspace snapshot.",
            candidates,
            activity,
            health,
            replay,
            Boolean(root, "planningAvailable"));
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
            readinessLabel);
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
