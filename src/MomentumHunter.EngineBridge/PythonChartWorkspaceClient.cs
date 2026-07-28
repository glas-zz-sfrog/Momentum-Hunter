using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

public sealed class PythonChartWorkspaceClient : IChartWorkspaceClient
{
    public const string StagedSchwabSourceLabel = "Schwab Trader API price history (inactive staging)";

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
        EnsureIdentity(snapshot, requestedSymbol, requestedInterval);
        if (snapshot.PreviewOnly || !snapshot.ActiveChartSource)
        {
            throw new InvalidDataException(
                "The active chart boundary returned preview-only or inactive chart evidence.");
        }

        return snapshot;
    }

    public async Task<ChartSnapshot> GetStagedPreviewAsync(
        string symbol,
        string interval,
        CancellationToken cancellationToken = default)
    {
        var requestedSymbol = symbol.Trim().ToUpperInvariant();
        var requestedInterval = interval.Trim();
        var snapshot = PythonChartSnapshotMapper.MapStagedPreview(
            await _connection.GetStagedSchwabChartPreviewAsync(
                requestedSymbol,
                requestedInterval,
                cancellationToken));
        EnsureIdentity(snapshot, requestedSymbol, requestedInterval);
        return snapshot;
    }

    private static void EnsureIdentity(
        ChartSnapshot snapshot,
        string requestedSymbol,
        string requestedInterval)
    {
        if (string.Equals(snapshot.Symbol, requestedSymbol, StringComparison.Ordinal)
            && string.Equals(snapshot.Interval, requestedInterval, StringComparison.Ordinal))
        {
            return;
        }

        throw new InvalidDataException(
            $"Python chart snapshot identity mismatch: requested {requestedSymbol} {requestedInterval}, "
            + $"received {snapshot.Symbol} {snapshot.Interval}.");
    }
}

public static class PythonChartSnapshotMapper
{
    public static ChartSnapshot Map(JsonElement root) => Map(root, requireStagedPreview: false);

    public static ChartSnapshot MapStagedPreview(JsonElement root) =>
        Map(root, requireStagedPreview: true);

    private static ChartSnapshot Map(JsonElement root, bool requireStagedPreview)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("The Python chart snapshot must be a JSON object.");
        }

        var schemaVersion = Integer(root, "schemaVersion") ?? 0;
        if (schemaVersion != 1)
        {
            throw new InvalidDataException($"Unsupported Python chart snapshot schema version: {schemaVersion}.");
        }

        var observedAt = Timestamp(root, "observedAt", DateTimeOffset.UtcNow);
        var asOf = Timestamp(root, "asOf", observedAt);
        var lineage = Object(root, "lineage");
        var previewOnly = Boolean(root, "previewOnly") ?? false;
        var activeChartSource = Boolean(root, "activeChartSource") ?? true;
        if (requireStagedPreview
            && (!previewOnly
                || activeChartSource
                || Boolean(root, "transmitting") is not false
                || !string.Equals(String(root, "orderTransmission"), "UNAVAILABLE", StringComparison.Ordinal)
                || !string.Equals(
                    String(lineage, "sourceLabel"),
                    PythonChartWorkspaceClient.StagedSchwabSourceLabel,
                    StringComparison.Ordinal)))
        {
            throw new InvalidDataException(
                "The Python staged chart preview is missing its inactive, nontransmitting safety envelope.");
        }
        var candles = Array(root, "candles").Select(Candle).ToArray();
        if (candles.Any(candle => candle.Open <= 0m
            || candle.High < Math.Max(candle.Open, Math.Max(candle.Close, candle.Low))
            || candle.Low > Math.Min(candle.Open, Math.Min(candle.Close, candle.High))
            || candle.Volume < 0))
        {
            throw new InvalidDataException("The Python chart snapshot contains invalid OHLCV geometry.");
        }

        return new ChartSnapshot(
            schemaVersion,
            RequiredString(root, "symbol"),
            RequiredString(root, "interval"),
            State(String(root, "state")),
            observedAt,
            asOf,
            String(root, "summary") ?? "Chart evidence summary unavailable.",
            new DataLineage(
                String(lineage, "sourceLabel") ?? "Unavailable chart source",
                Timestamp(lineage, "asOf", asOf),
                String(lineage, "summary") ?? "Chart source lineage unavailable."),
            candles,
            previewOnly,
            activeChartSource);
    }

    private static CandleSnapshot Candle(JsonElement item)
    {
        var timestamp = Timestamp(item, "timestamp", DateTimeOffset.MinValue);
        var open = Decimal(item, "open");
        var high = Decimal(item, "high");
        var low = Decimal(item, "low");
        var close = Decimal(item, "close");
        var volume = Long(item, "volume");
        if (timestamp == DateTimeOffset.MinValue
            || open is null
            || high is null
            || low is null
            || close is null
            || volume is null)
        {
            throw new InvalidDataException("A Python chart candle is missing required OHLCV fields.");
        }

        return new CandleSnapshot(timestamp, open.Value, high.Value, low.Value, close.Value, volume.Value);
    }

    private static ChartDataState State(string? state) => state?.Trim().ToUpperInvariant() switch
    {
        "AVAILABLE" => ChartDataState.Available,
        "STALE" => ChartDataState.Stale,
        "INSUFFICIENT_DATA" => ChartDataState.InsufficientData,
        _ => ChartDataState.Unavailable,
    };

    private static JsonElement Object(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value
            : default;

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

    private static bool? Boolean(JsonElement item, string name)
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
        return value.ValueKind == JsonValueKind.String
            && long.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
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

    private static DateTimeOffset Timestamp(JsonElement item, string name, DateTimeOffset fallback) =>
        DateTimeOffset.TryParse(
            String(item, name),
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal,
            out var value)
            ? value
            : fallback;

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object
            && item.TryGetProperty(name, out value)
            && value.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined;
    }
}
