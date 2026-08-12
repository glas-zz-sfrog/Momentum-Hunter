using System.Text.Json;

namespace MomentumHunter.EngineBridge;

internal static class PythonEngineHostWireContract
{
    private static readonly string[] EndpointProperties =
    [
        "schemaVersion",
        "protocolVersion",
        "hostInstanceId",
        "processId",
        "startedAtUtc",
        "address",
        "port",
        "accessToken",
        "runtimeBuildHash",
        "selectorArmSchemaVersion",
    ];

    private static readonly string[] ResponseProperties =
    [
        "protocolVersion",
        "requestId",
        "accepted",
        "error",
        "result",
    ];

    private static readonly string[] RequiredResultProperties =
    [
        "code",
        "summary",
        "snapshot",
    ];

    private static readonly string[] ErrorProperties = ["code", "summary"];

    private static readonly string[] SnapshotProperties =
    [
        "schemaVersion",
        "identity",
        "health",
        "collection",
        "activePositionMarking",
        "capabilities",
    ];

    private static readonly string[] IdentityProperties =
    [
        "protocolVersion",
        "hostInstanceId",
        "processId",
        "startedAtUtc",
        "transport",
        "runtimeBuildHash",
        "selectorArmSchemaVersion",
    ];

    private static readonly string[] HealthProperties =
    [
        "state",
        "observedAtUtc",
        "detail",
    ];

    private static readonly string[] CollectionProperties =
    [
        "state",
        "isPaused",
        "cycleInProgress",
        "cycleCount",
        "monitoredSymbolCount",
        "lastCompletedCycleAtUtc",
        "nextScheduledCycleAtUtc",
        "detail",
    ];

    private static readonly string[] ActivePositionMarkingProperties =
    [
        "state",
        "cadenceSeconds",
        "cycleCount",
        "providerRequestCount",
        "lastCompletedAtUtc",
        "detail",
        "transport",
        "orderTransmission",
    ];

    internal static void ValidateEndpoint(JsonElement root)
    {
        RequireExactObject(root, "endpoint", EndpointProperties);
    }

    internal static void ValidateResponse(JsonElement root)
    {
        RequireExactObject(root, "response", ResponseProperties);
        if (root.GetProperty("error") is { ValueKind: JsonValueKind.Object } error)
        {
            RequireExactObject(error, "response.error", ErrorProperties);
        }
        else if (root.GetProperty("error").ValueKind != JsonValueKind.Null)
        {
            throw new JsonException(
                "Python Engine Host response.error must be null or an object.");
        }
        var result = RequiredObject(root, "result", "response");
        RequireObjectWithOptionalProperties(
            result,
            "response.result",
            RequiredResultProperties,
            ["payload"]);
        var snapshot = RequiredObject(result, "snapshot", "response.result");
        RequireExactObject(snapshot, "response.result.snapshot", SnapshotProperties);
        RequireExactObject(
            RequiredObject(snapshot, "identity", "response.result.snapshot"),
            "response.result.snapshot.identity",
            IdentityProperties);
        RequireExactObject(
            RequiredObject(snapshot, "health", "response.result.snapshot"),
            "response.result.snapshot.health",
            HealthProperties);
        RequireExactObject(
            RequiredObject(snapshot, "collection", "response.result.snapshot"),
            "response.result.snapshot.collection",
            CollectionProperties);
        RequireExactObject(
            RequiredObject(snapshot, "activePositionMarking", "response.result.snapshot"),
            "response.result.snapshot.activePositionMarking",
            ActivePositionMarkingProperties);
        if (!snapshot.TryGetProperty("capabilities", out var capabilities)
            || capabilities.ValueKind != JsonValueKind.Array)
        {
            throw new JsonException(
                "Python Engine Host response.result.snapshot.capabilities must be an array.");
        }
    }

    private static JsonElement RequiredObject(
        JsonElement parent,
        string property,
        string context)
    {
        if (!parent.TryGetProperty(property, out var value)
            || value.ValueKind != JsonValueKind.Object)
        {
            throw new JsonException(
                $"Python Engine Host {context} is missing object '{property}'.");
        }
        return value;
    }

    private static void RequireExactObject(
        JsonElement value,
        string context,
        IReadOnlyCollection<string> expectedProperties)
    {
        if (value.ValueKind != JsonValueKind.Object)
        {
            throw new JsonException($"Python Engine Host {context} must be an object.");
        }

        var observed = value.EnumerateObject()
            .Select(property => property.Name)
            .ToArray();
        var missing = expectedProperties.Except(observed, StringComparer.Ordinal).ToArray();
        var unexpected = observed.Except(expectedProperties, StringComparer.Ordinal).ToArray();
        if (missing.Length == 0 && unexpected.Length == 0)
        {
            return;
        }

        throw new JsonException(
            $"Python Engine Host {context} contract drift detected; "
            + $"missing=[{string.Join(',', missing)}], "
            + $"unexpected=[{string.Join(',', unexpected)}].");
    }

    private static void RequireObjectWithOptionalProperties(
        JsonElement value,
        string context,
        IReadOnlyCollection<string> requiredProperties,
        IReadOnlyCollection<string> optionalProperties)
    {
        if (value.ValueKind != JsonValueKind.Object)
        {
            throw new JsonException($"Python Engine Host {context} must be an object.");
        }

        var observed = value.EnumerateObject()
            .Select(property => property.Name)
            .ToArray();
        var allowed = requiredProperties.Concat(optionalProperties).ToArray();
        var missing = requiredProperties.Except(observed, StringComparer.Ordinal).ToArray();
        var unexpected = observed.Except(allowed, StringComparer.Ordinal).ToArray();
        if (missing.Length == 0 && unexpected.Length == 0)
        {
            return;
        }

        throw new JsonException(
            $"Python Engine Host {context} contract drift detected; "
            + $"missing=[{string.Join(',', missing)}], "
            + $"unexpected=[{string.Join(',', unexpected)}].");
    }
}
