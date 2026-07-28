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
    private const int MaxStagedPreviewCandles = 180;
    private const int MaxStagedPreviewTextLength = 2048;
    private static readonly HashSet<string> StagedPreviewFields =
    [
        "schemaVersion",
        "symbol",
        "interval",
        "state",
        "observedAt",
        "asOf",
        "summary",
        "previewOnly",
        "activeChartSource",
        "transmitting",
        "orderTransmission",
        "lineage",
        "candles",
    ];
    private static readonly HashSet<string> StagedPreviewLineageFields =
    [
        "sourceLabel",
        "asOf",
        "summary",
    ];
    private static readonly HashSet<string> StagedPreviewCandleFields =
    [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ];

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

        var observedAt = requireStagedPreview
            ? RequiredTimestamp(root, "observedAt")
            : Timestamp(root, "observedAt", DateTimeOffset.UtcNow);
        var asOf = requireStagedPreview
            ? RequiredTimestamp(root, "asOf")
            : Timestamp(root, "asOf", observedAt);
        var lineage = Object(root, "lineage");
        var previewOnly = Boolean(root, "previewOnly") ?? false;
        var activeChartSource = Boolean(root, "activeChartSource") ?? true;
        var candleElements = Array(root, "candles").ToArray();
        var candles = candleElements.Select(Candle).ToArray();
        if (candles.Any(candle => candle.Open <= 0m
            || candle.High < Math.Max(candle.Open, Math.Max(candle.Close, candle.Low))
            || candle.Low > Math.Min(candle.Open, Math.Min(candle.Close, candle.High))
            || candle.Volume < 0))
        {
            throw new InvalidDataException("The Python chart snapshot contains invalid OHLCV geometry.");
        }
        if (requireStagedPreview)
        {
            ValidateStagedPreviewEnvelope(
                root,
                lineage,
                candleElements,
                candles,
                observedAt,
                asOf,
                previewOnly,
                activeChartSource);
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
                requireStagedPreview
                    ? RequiredTimestamp(lineage, "asOf")
                    : Timestamp(lineage, "asOf", asOf),
                String(lineage, "summary") ?? "Chart source lineage unavailable."),
            candles,
            previewOnly,
            activeChartSource);
    }

    private static void ValidateStagedPreviewEnvelope(
        JsonElement root,
        JsonElement lineage,
        IReadOnlyList<JsonElement> candleElements,
        IReadOnlyList<CandleSnapshot> candles,
        DateTimeOffset observedAt,
        DateTimeOffset asOf,
        bool previewOnly,
        bool activeChartSource)
    {
        var state = RequiredString(root, "state");
        var summary = RequiredString(root, "summary");
        var lineageSummary = RequiredString(lineage, "summary");
        if (!HasExactFields(root, StagedPreviewFields)
            || !HasExactFields(lineage, StagedPreviewLineageFields)
            || candleElements.Any(item => !HasExactFields(item, StagedPreviewCandleFields))
            || candleElements.Any(item => !HasStrictStagedCandleTypes(item))
            || !previewOnly
            || activeChartSource
            || Boolean(root, "transmitting") is not false
            || !string.Equals(String(root, "orderTransmission"), "UNAVAILABLE", StringComparison.Ordinal)
            || !string.Equals(
                String(lineage, "sourceLabel"),
                PythonChartWorkspaceClient.StagedSchwabSourceLabel,
                StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                "The Python staged chart preview is missing its exact inactive, nontransmitting safety envelope.");
        }

        var allowedStates = new HashSet<string>(StringComparer.Ordinal)
        {
            "AVAILABLE",
            "STALE",
            "INSUFFICIENT_DATA",
            "UNAVAILABLE",
        };
        if (!allowedStates.Contains(state)
            || !BoundedText(summary)
            || !summary.StartsWith(
                $"STAGED PREVIEW ONLY | {state.Replace('_', ' ')} |",
                StringComparison.Ordinal)
            || !BoundedText(lineageSummary)
            || RequiredTimestamp(lineage, "asOf") != asOf
            || asOf > observedAt.AddSeconds(5)
            || candles.Count > MaxStagedPreviewCandles)
        {
            throw new InvalidDataException(
                "The Python staged chart preview has invalid state, time, text, or candle bounds.");
        }

        for (var index = 1; index < candles.Count; index++)
        {
            if (candles[index].Timestamp <= candles[index - 1].Timestamp)
            {
                throw new InvalidDataException(
                    "The Python staged chart preview candles must be unique and strictly ordered.");
            }
        }
        if (candles.Count > 0 && candles[^1].Timestamp != asOf)
        {
            throw new InvalidDataException(
                "The Python staged chart preview as-of time must match its latest candle.");
        }

        var countMatchesState = state switch
        {
            "UNAVAILABLE" => candles.Count == 0,
            "INSUFFICIENT_DATA" => candles.Count == 1,
            "AVAILABLE" or "STALE" => candles.Count >= 2,
            _ => false,
        };
        if (!countMatchesState)
        {
            throw new InvalidDataException(
                "The Python staged chart preview state does not match its candle count.");
        }
    }

    private static bool HasExactFields(JsonElement item, IReadOnlySet<string> expected)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            return false;
        }
        var properties = item.EnumerateObject().ToArray();
        return properties.Length == expected.Count
            && properties
                .Select(property => property.Name)
                .ToHashSet(StringComparer.Ordinal)
                .SetEquals(expected);
    }

    private static bool HasStrictStagedCandleTypes(JsonElement item) =>
        RequiredNumber(item, "open")
        && RequiredNumber(item, "high")
        && RequiredNumber(item, "low")
        && RequiredNumber(item, "close")
        && Property(item, "volume", out var volume)
        && volume.ValueKind == JsonValueKind.Number
        && volume.TryGetInt64(out _)
        && HasExplicitOffset(String(item, "timestamp"));

    private static bool RequiredNumber(JsonElement item, string name) =>
        Property(item, name, out var value)
        && value.ValueKind == JsonValueKind.Number
        && value.TryGetDecimal(out _);

    private static bool BoundedText(string value) =>
        !string.IsNullOrWhiteSpace(value)
        && value.Length <= MaxStagedPreviewTextLength;

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

    private static DateTimeOffset RequiredTimestamp(JsonElement item, string name)
    {
        var text = RequiredString(item, name);
        if (!HasExplicitOffset(text)
            || !DateTimeOffset.TryParse(
                text,
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var value))
        {
            throw new InvalidDataException(
                $"The Python staged chart preview has an invalid '{name}' timestamp.");
        }
        return value.ToUniversalTime();
    }

    private static bool HasExplicitOffset(string? value) =>
        value is not null
        && (value.EndsWith('Z')
            || (value.Length >= 6
                && value[^3] == ':'
                && value[^6] is '+' or '-'));

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object
            && item.TryGetProperty(name, out value)
            && value.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined;
    }
}
