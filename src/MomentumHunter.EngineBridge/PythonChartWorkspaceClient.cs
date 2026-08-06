using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

public sealed class PythonChartWorkspaceClient : IChartWorkspaceClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonChartWorkspaceClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<ChartSnapshot> GetSnapshotAsync(
        string symbol,
        string interval,
        CancellationToken cancellationToken = default)
    {
        var requestedSymbol = symbol.Trim().ToUpperInvariant();
        var requestedInterval = interval.Trim();
        var snapshot = PythonChartSnapshotMapper.Map(
            await _connection.GetChartSnapshotAsync(requestedSymbol, requestedInterval, cancellationToken));
        if (!string.Equals(snapshot.Symbol, requestedSymbol, StringComparison.Ordinal)
            || !string.Equals(snapshot.Interval, requestedInterval, StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Python chart snapshot identity mismatch: requested {requestedSymbol} {requestedInterval}, "
                + $"received {snapshot.Symbol} {snapshot.Interval}.");
        }

        return snapshot;
    }
}

public static class PythonChartSnapshotMapper
{
    public static ChartSnapshot Map(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("The Python chart snapshot must be a JSON object.");
        }

        var schemaVersion = Integer(root, "schemaVersion") ?? 0;
        if (schemaVersion != 2)
        {
            throw new InvalidDataException($"Unsupported Python chart snapshot schema version: {schemaVersion}.");
        }

        var observedAt = Timestamp(root, "observedAt", DateTimeOffset.UtcNow);
        var asOf = Timestamp(root, "asOf", observedAt);
        var lineage = RequiredObject(root, "lineage");
        var lineageSource = RequiredString(lineage, "sourceLabel");
        var stateText = RequiredString(root, "state").Trim().ToUpperInvariant();
        var state = State(stateText);
        var quality = Quality(RequiredObject(root, "quality"));
        var candles = Array(root, "candles").Select(Candle).ToArray();
        if (candles.Any(candle => candle.Open <= 0m
            || candle.High < Math.Max(candle.Open, Math.Max(candle.Close, candle.Low))
            || candle.Low > Math.Min(candle.Open, Math.Min(candle.Close, candle.High))
            || candle.Volume < 0m
            || candle.PresentMinuteCount < 1
            || candle.ExpectedMinuteCount < candle.PresentMinuteCount
            || candle.IsInProgress != string.Equals(candle.State, "IN_PROGRESS", StringComparison.Ordinal)))
        {
            throw new InvalidDataException("The Python chart snapshot contains invalid OHLCV or lifecycle geometry.");
        }
        var inProgressCount = candles.Count(candle => candle.IsInProgress);
        var completedCount = candles.Length - inProgressCount;
        if (!string.Equals(quality.Status, stateText, StringComparison.Ordinal)
            || !string.Equals(quality.SourceLabel, lineageSource, StringComparison.Ordinal)
            || quality.CompletedCount != completedCount
            || quality.InProgressCount != inProgressCount
            || quality.GapCount != candles.Count(candle => candle.HasGapBefore)
            || quality.CorrectionCount != candles.Count(candle =>
                string.Equals(candle.State, "CORRECTED", StringComparison.Ordinal))
            || quality.UnreconciledCount != candles.Count(candle =>
                string.Equals(candle.State, "COMPLETED_UNRECONCILED", StringComparison.Ordinal))
            || (quality.LatestCompletedBarAt is null) != (completedCount == 0)
            || (quality.LatestInProgressBarAt is null) != (inProgressCount == 0))
        {
            throw new InvalidDataException("The Python chart quality metadata contradicts its candle payload.");
        }

        return new ChartSnapshot(
            schemaVersion,
            RequiredString(root, "symbol"),
            RequiredString(root, "interval"),
            state,
            observedAt,
            asOf,
            String(root, "summary") ?? "Chart evidence summary unavailable.",
            new DataLineage(
                lineageSource,
                Timestamp(lineage, "asOf", asOf),
                String(lineage, "summary") ?? "Chart source lineage unavailable."),
            candles,
            quality);
    }

    private static CandleSnapshot Candle(JsonElement item)
    {
        var timestamp = Timestamp(item, "timestamp", DateTimeOffset.MinValue);
        var open = Decimal(item, "open");
        var high = Decimal(item, "high");
        var low = Decimal(item, "low");
        var close = Decimal(item, "close");
        var volume = Decimal(item, "volume");
        if (timestamp == DateTimeOffset.MinValue
            || open is null
            || high is null
            || low is null
            || close is null
            || volume is null)
        {
            throw new InvalidDataException("A Python chart candle is missing required OHLCV fields.");
        }

        var state = RequiredString(item, "state").Trim().ToUpperInvariant();
        var source = RequiredString(item, "source");
        var providerTimestamp = NullableTimestamp(item, "providerTimestamp")
            ?? throw new InvalidDataException("A Python chart candle is missing its provider timestamp.");
        var presentMinuteCount = Integer(item, "presentMinuteCount")
            ?? throw new InvalidDataException("A Python chart candle is missing its present-minute count.");
        var expectedMinuteCount = Integer(item, "expectedMinuteCount")
            ?? throw new InvalidDataException("A Python chart candle is missing its expected-minute count.");

        return new CandleSnapshot(
            timestamp,
            open.Value,
            high.Value,
            low.Value,
            close.Value,
            volume.Value,
            state,
            source,
            providerTimestamp,
            NullableTimestamp(item, "receivedAt"),
            RequiredBoolean(item, "isCanonical"),
            RequiredBoolean(item, "isInProgress"),
            RequiredBoolean(item, "hasGapBefore"),
            StringArray(item, "discrepancyFields"),
            presentMinuteCount,
            expectedMinuteCount);
    }

    private static ChartQualitySnapshot Quality(JsonElement item) => new(
        RequiredString(item, "provider"),
        RequiredString(item, "sourceLabel"),
        RequiredString(item, "status").Trim().ToUpperInvariant(),
        StringArray(item, "sessionDates"),
        NullableTimestamp(item, "latestCompletedBarAt"),
        NullableTimestamp(item, "latestInProgressBarAt"),
        NullableTimestamp(item, "latestProviderTimestamp"),
        NullableTimestamp(item, "latestReceiptAt"),
        Decimal(item, "ageSeconds"),
        RequiredBoolean(item, "stale"),
        RequiredInteger(item, "gapCount"),
        RequiredInteger(item, "correctionCount"),
        RequiredInteger(item, "unreconciledCount"),
        RequiredInteger(item, "inProgressCount"),
        RequiredInteger(item, "completedCount"),
        StringArray(item, "findings"));

    private static ChartDataState State(string state) => state switch
    {
        "AVAILABLE" => ChartDataState.Available,
        "PARTIAL" => ChartDataState.Partial,
        "STALE" => ChartDataState.Stale,
        "INSUFFICIENT_DATA" => ChartDataState.InsufficientData,
        "UNAVAILABLE" => ChartDataState.Unavailable,
        _ => throw new InvalidDataException($"Unsupported Python chart state: {state}."),
    };

    private static JsonElement Object(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value
            : default;

    private static JsonElement RequiredObject(JsonElement item, string name)
    {
        var value = Object(item, name);
        return value.ValueKind == JsonValueKind.Object
            ? value
            : throw new InvalidDataException($"The Python chart snapshot is missing object '{name}'.");
    }

    private static IEnumerable<JsonElement> Array(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Array
            ? value.EnumerateArray().ToArray()
            : [];

    private static string RequiredString(JsonElement item, string name) =>
        String(item, name) is { Length: > 0 } value
            ? value
            : throw new InvalidDataException($"The Python chart snapshot is missing '{name}'.");

    private static string? String(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int? Integer(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            return null;
        }
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number
            : null;
    }

    private static int RequiredInteger(JsonElement item, string name) =>
        Integer(item, name)
        ?? throw new InvalidDataException($"The Python chart snapshot is missing integer '{name}'.");

    private static bool RequiredBoolean(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            throw new InvalidDataException($"The Python chart snapshot is missing boolean '{name}'.");
        }
        if (value.ValueKind is JsonValueKind.True or JsonValueKind.False)
        {
            return value.GetBoolean();
        }
        throw new InvalidDataException($"The Python chart snapshot field '{name}' was not boolean.");
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

    private static DateTimeOffset Timestamp(JsonElement item, string name, DateTimeOffset fallback) =>
        DateTimeOffset.TryParse(
            String(item, name),
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal,
            out var value)
            ? value
            : fallback;

    private static DateTimeOffset? NullableTimestamp(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind != JsonValueKind.String)
        {
            return null;
        }
        return DateTimeOffset.TryParse(
            value.GetString(),
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal,
            out var parsed)
            ? parsed
            : throw new InvalidDataException($"The Python chart snapshot timestamp '{name}' was invalid.");
    }

    private static IReadOnlyList<string> StringArray(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException($"The Python chart snapshot is missing string array '{name}'.");
        }
        var values = value.EnumerateArray()
            .Select(entry => entry.ValueKind == JsonValueKind.String ? entry.GetString() : null)
            .ToArray();
        if (values.Any(entry => string.IsNullOrWhiteSpace(entry)))
        {
            throw new InvalidDataException($"The Python chart snapshot array '{name}' contained an invalid value.");
        }
        return values.Select(entry => entry!).ToArray();
    }

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object
            && item.TryGetProperty(name, out value)
            && value.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined;
    }
}
