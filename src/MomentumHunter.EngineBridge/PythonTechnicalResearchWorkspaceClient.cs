using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

public sealed class PythonTechnicalResearchWorkspaceClient : ITechnicalResearchWorkspaceClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonTechnicalResearchWorkspaceClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<TechnicalResearchSnapshot> GetSnapshotAsync(
        string symbol,
        CancellationToken cancellationToken = default)
    {
        var requestedSymbol = symbol.Trim().ToUpperInvariant();
        if (requestedSymbol.Length == 0)
        {
            throw new ArgumentException("A symbol is required for technical research evidence.", nameof(symbol));
        }

        var snapshot = PythonTechnicalResearchSnapshotMapper.Map(
            await _connection.GetTechnicalResearchSnapshotAsync(requestedSymbol, cancellationToken));
        if (!string.Equals(snapshot.Symbol, requestedSymbol, StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Python technical research identity mismatch: requested {requestedSymbol}, received {snapshot.Symbol}.");
        }

        return snapshot;
    }
}

public static class PythonTechnicalResearchSnapshotMapper
{
    public static TechnicalResearchSnapshot Map(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("The Python technical research snapshot must be a JSON object.");
        }

        var schemaVersion = Integer(root, "schemaVersion") ?? 0;
        if (schemaVersion != 1)
        {
            throw new InvalidDataException(
                $"Unsupported Python technical research snapshot schema version: {schemaVersion}.");
        }

        var observedAt = RequiredTimestamp(root, "observedAt");
        var counts = new[]
        {
            RequiredNonnegativeInteger(root, "globalEventCount"),
            RequiredNonnegativeInteger(root, "globalStudyCount"),
            RequiredNonnegativeInteger(root, "symbolEventCount"),
            RequiredNonnegativeInteger(root, "symbolStudyCount"),
            RequiredNonnegativeInteger(root, "presentEventCount"),
            RequiredNonnegativeInteger(root, "failedStudyCount"),
            RequiredNonnegativeInteger(root, "insufficientDataCount"),
        };
        var events = RequiredArray(root, "events").Select(Event).ToArray();
        var studies = RequiredArray(root, "studies").Select(Study).ToArray();
        var state = State(RequiredString(root, "state"));
        if (state is TechnicalResearchState.Empty or TechnicalResearchState.Unavailable
            && (events.Length > 0 || studies.Length > 0))
        {
            throw new InvalidDataException(
                "Empty or unavailable technical research snapshots cannot contain detail rows.");
        }

        return new TechnicalResearchSnapshot(
            schemaVersion,
            RequiredString(root, "symbol").ToUpperInvariant(),
            state,
            observedAt,
            NullableTimestamp(root, "asOf"),
            String(root, "summary") ?? "Technical research summary unavailable.",
            String(root, "sourceLabel") ?? "Technical research source unavailable.",
            counts[0],
            counts[1],
            counts[2],
            counts[3],
            counts[4],
            counts[5],
            counts[6],
            RequiredArray(root, "warnings").Select(RequiredArrayString).ToArray(),
            events,
            studies);
    }

    private static TechnicalResearchEventSnapshot Event(JsonElement item)
    {
        EnsureObject(item, "technical research event");
        return new TechnicalResearchEventSnapshot(
            String(item, "eventId") ?? string.Empty,
            NullableTimestamp(item, "eventTimestamp"),
            String(item, "eventType") ?? string.Empty,
            String(item, "timeframe") ?? string.Empty,
            String(item, "status") ?? "Insufficient data",
            String(item, "qualityFlag") ?? "UNAVAILABLE",
            String(item, "dataSufficiency") ?? "Insufficient data",
            Decimal(item, "triggerPrice"),
            Decimal(item, "distanceAboveTriggerPct"),
            Decimal(item, "relativeVolume"),
            NullableBoolean(item, "volumeConfirmed"),
            NullableBoolean(item, "relativeStrengthConfirmed"),
            String(item, "notes") ?? "No event notes were stored.");
    }

    private static TechnicalResearchStudySnapshot Study(JsonElement item)
    {
        EnsureObject(item, "technical research study");
        return new TechnicalResearchStudySnapshot(
            String(item, "eventId") ?? string.Empty,
            NullableTimestamp(item, "eventTimestamp"),
            String(item, "eventType") ?? string.Empty,
            String(item, "timeframe") ?? string.Empty,
            String(item, "status") ?? "Insufficient data",
            String(item, "dataSufficiency") ?? "Insufficient data",
            Decimal(item, "return5mPct"),
            Decimal(item, "return15mPct"),
            Decimal(item, "return60mPct"),
            Decimal(item, "return1dPct"),
            Decimal(item, "return5dPct"),
            Decimal(item, "return10dPct"),
            Decimal(item, "maxFavorableExcursionPct"),
            Decimal(item, "maxAdverseExcursionPct"),
            NullableBoolean(item, "heldAboveBreakoutLevel"),
            NullableBoolean(item, "failedBackBelowBreakoutLevel"),
            NullableBoolean(item, "becameExtended"),
            NullableBoolean(item, "volumeConfirmed"),
            String(item, "notes") ?? "No study notes were stored.");
    }

    private static TechnicalResearchState State(string state) => state.Trim().ToUpperInvariant() switch
    {
        "AVAILABLE" => TechnicalResearchState.Available,
        "STALE" => TechnicalResearchState.Stale,
        "PARTIAL" => TechnicalResearchState.Partial,
        "EMPTY" => TechnicalResearchState.Empty,
        _ => TechnicalResearchState.Unavailable,
    };

    private static void EnsureObject(JsonElement item, string label)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException($"A {label} row must be a JSON object.");
        }
    }

    private static IEnumerable<JsonElement> RequiredArray(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException(
                $"The Python technical research snapshot is missing array '{name}'.");
        }
        return value.EnumerateArray().ToArray();
    }

    private static string RequiredArrayString(JsonElement item) =>
        item.ValueKind == JsonValueKind.String
            ? item.GetString() ?? string.Empty
            : throw new InvalidDataException("Technical research warnings must be strings.");

    private static string RequiredString(JsonElement item, string name) =>
        String(item, name) is { Length: > 0 } value
            ? value
            : throw new InvalidDataException(
                $"The Python technical research snapshot is missing '{name}'.");

    private static string? String(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int RequiredNonnegativeInteger(JsonElement item, string name)
    {
        var value = Integer(item, name);
        if (value is null || value < 0)
        {
            throw new InvalidDataException(
                $"The Python technical research snapshot has invalid count '{name}'.");
        }
        return value.Value;
    }

    private static int? Integer(JsonElement item, string name) =>
        Property(item, name, out var value)
        && value.ValueKind == JsonValueKind.Number
        && value.TryGetInt32(out var number)
            ? number
            : null;

    private static decimal? Decimal(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind == JsonValueKind.Null)
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

    private static bool? NullableBoolean(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            return null;
        }
        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => null,
        };
    }

    private static DateTimeOffset RequiredTimestamp(JsonElement item, string name) =>
        NullableTimestamp(item, name)
        ?? throw new InvalidDataException(
            $"The Python technical research snapshot has invalid timestamp '{name}'.");

    private static DateTimeOffset? NullableTimestamp(JsonElement item, string name)
    {
        if (!Property(item, name, out var value)
            || value.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined)
        {
            return null;
        }
        return value.ValueKind == JsonValueKind.String
            && DateTimeOffset.TryParse(
                value.GetString(),
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
                out var timestamp)
            ? timestamp
            : null;
    }

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        if (item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out value))
        {
            return true;
        }
        value = default;
        return false;
    }
}
