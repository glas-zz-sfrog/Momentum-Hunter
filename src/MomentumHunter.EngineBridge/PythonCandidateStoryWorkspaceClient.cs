using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

public sealed class PythonCandidateStoryWorkspaceClient : ICandidateStoryWorkspaceClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonCandidateStoryWorkspaceClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<CandidateStorySnapshot> GetSnapshotAsync(
        string symbol,
        CancellationToken cancellationToken = default)
    {
        var requestedSymbol = CandidateStorySnapshotMapper.NormalizeSymbol(symbol);
        var snapshot = CandidateStorySnapshotMapper.Map(
            await _connection.GetCandidateStorySnapshotAsync(requestedSymbol, cancellationToken));
        if (!string.Equals(snapshot.Symbol, requestedSymbol, StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Candidate Story response symbol '{snapshot.Symbol}' does not match '{requestedSymbol}'.");
        }
        return snapshot;
    }
}

public static partial class CandidateStorySnapshotMapper
{
    private static readonly HashSet<string> AllowedStatuses = new(StringComparer.Ordinal)
    {
        "Insufficient data",
        "Building",
        "Holding",
        "Fading",
        "Peaked",
        "Stale",
    };

    public static CandidateStorySnapshot Map(JsonElement root)
    {
        RequireObject(root, "The Python Candidate Story snapshot must be a JSON object.");
        var schemaVersion = RequiredInteger(root, "schemaVersion");
        if (schemaVersion != 1)
        {
            throw new InvalidDataException($"Unsupported Python Candidate Story schema version: {schemaVersion}.");
        }

        var symbol = NormalizeSymbol(RequiredString(root, "symbol"));
        var state = State(RequiredString(root, "state"));
        var status = RequiredString(root, "status");
        if (!AllowedStatuses.Contains(status))
        {
            throw new InvalidDataException($"Unknown Candidate Story status: {status}.");
        }

        var trustedCaptureCount = NonNegativeInteger(root, "trustedCaptureCount");
        var totalPointCount = NonNegativeInteger(root, "totalPointCount");
        var displayedPointCount = NonNegativeInteger(root, "displayedPointCount");
        var points = RequiredArray(root, "points").Select(Point).ToArray();
        var warnings = RequiredArray(root, "warnings")
            .Select((item, index) => RequiredArrayString(item, $"warnings[{index}]"))
            .ToArray();
        var readOnly = RequiredBoolean(root, "readOnly");
        if (!readOnly)
        {
            throw new InvalidDataException("The Candidate Story boundary must remain read-only.");
        }

        ValidateCollections(state, trustedCaptureCount, totalPointCount, displayedPointCount, points);
        return new CandidateStorySnapshot(
            schemaVersion,
            symbol,
            state,
            RequiredTimestamp(root, "observedAt"),
            OptionalTimestamp(root, "sourceAsOf"),
            RequiredString(root, "sourceLabel"),
            RequiredString(root, "summary"),
            OptionalString(root, "company"),
            OptionalString(root, "sector"),
            OptionalString(root, "industry"),
            status,
            RequiredString(root, "statusDetail"),
            RequiredString(root, "firstSeenLabel"),
            RequiredString(root, "latestSeenLabel"),
            RequiredString(root, "peakScoreLabel"),
            OptionalDecimal(root, "firstPrice"),
            OptionalDecimal(root, "latestPrice"),
            OptionalDecimal(root, "moveSinceFirstPct"),
            OptionalDecimal(root, "firstScore"),
            OptionalDecimal(root, "latestScore"),
            OptionalDecimal(root, "peakScore"),
            trustedCaptureCount,
            totalPointCount,
            displayedPointCount,
            points,
            warnings,
            readOnly);
    }

    public static string NormalizeSymbol(string symbol)
    {
        var normalized = symbol?.Trim().ToUpperInvariant() ?? string.Empty;
        return SymbolPattern().IsMatch(normalized)
            ? normalized
            : throw new ArgumentException("Candidate Story requires a valid ticker symbol.", nameof(symbol));
    }

    private static CandidateStoryPointSnapshot Point(JsonElement item)
    {
        RequireObject(item, "Each Candidate Story point must be an object.");
        var trusted = RequiredBoolean(item, "trusted");
        if (!trusted)
        {
            throw new InvalidDataException("Candidate Story points must contain trusted captures only.");
        }
        var captureFactSource = RequiredString(item, "captureFactSource");
        if (!string.Equals(captureFactSource, "raw capture", StringComparison.Ordinal))
        {
            throw new InvalidDataException("Candidate Story capture facts must retain raw-capture provenance.");
        }
        return new CandidateStoryPointSnapshot(
            PositiveInteger(item, "sequence"),
            RequiredString(item, "identityKey"),
            RequiredString(item, "captureId"),
            OptionalTimestamp(item, "capturedAt"),
            RequiredString(item, "capturedAtLabel"),
            RequiredString(item, "captureLabel"),
            RequiredString(item, "session"),
            RequiredString(item, "sessionMarker"),
            RequiredString(item, "provider"),
            RequiredString(item, "scanner"),
            OptionalString(item, "mode"),
            RequiredString(item, "calendarLabel"),
            RequiredString(item, "trustLabel"),
            OptionalDecimal(item, "price"),
            OptionalDecimal(item, "score"),
            OptionalLong(item, "volume"),
            OptionalDecimal(item, "relativeVolume"),
            OptionalDecimal(item, "priceChangePreviousPct"),
            OptionalDecimal(item, "priceChangeFirstPct"),
            OptionalDecimal(item, "scoreChangePrevious"),
            RequiredString(item, "captureNote"),
            RequiredString(item, "laterAnnotation"),
            captureFactSource,
            RequiredString(item, "laterAnnotationSource"),
            RequiredArray(item, "warnings")
                .Select((warning, index) => RequiredArrayString(warning, $"point.warnings[{index}]"))
                .ToArray(),
            trusted);
    }

    private static void ValidateCollections(
        CandidateStoryEvidenceState state,
        int trustedCaptureCount,
        int totalPointCount,
        int displayedPointCount,
        IReadOnlyList<CandidateStoryPointSnapshot> points)
    {
        if (trustedCaptureCount != totalPointCount)
        {
            throw new InvalidDataException("Candidate Story trusted capture and total point counts must match.");
        }
        if (displayedPointCount != points.Count || displayedPointCount > totalPointCount)
        {
            throw new InvalidDataException("Candidate Story displayed point counts are inconsistent.");
        }
        if (!points.Select(point => point.Sequence).SequenceEqual(Enumerable.Range(1, points.Count)))
        {
            throw new InvalidDataException("Candidate Story point sequence must be contiguous and ordered.");
        }
        if (points.Select(point => point.IdentityKey).Distinct(StringComparer.Ordinal).Count() != points.Count)
        {
            throw new InvalidDataException("Candidate Story point identities must be unique.");
        }
        var captured = points.Where(point => point.CapturedAt.HasValue).Select(point => point.CapturedAt!.Value).ToArray();
        if (!captured.SequenceEqual(captured.OrderBy(value => value)))
        {
            throw new InvalidDataException("Candidate Story points must be chronological.");
        }

        if (state is CandidateStoryEvidenceState.Empty or CandidateStoryEvidenceState.Unavailable)
        {
            if (totalPointCount != 0 || points.Count != 0)
            {
                throw new InvalidDataException("An empty or unavailable Candidate Story cannot contain points.");
            }
            return;
        }
        if (totalPointCount == 0 || points.Count == 0)
        {
            throw new InvalidDataException("An available or partial Candidate Story must contain trusted points.");
        }
    }

    private static CandidateStoryEvidenceState State(string value) => value.ToUpperInvariant() switch
    {
        "AVAILABLE" => CandidateStoryEvidenceState.Available,
        "PARTIAL" => CandidateStoryEvidenceState.Partial,
        "EMPTY" => CandidateStoryEvidenceState.Empty,
        "UNAVAILABLE" => CandidateStoryEvidenceState.Unavailable,
        _ => throw new InvalidDataException($"Unknown Candidate Story evidence state: {value}."),
    };

    private static int PositiveInteger(JsonElement item, string name)
    {
        var value = RequiredInteger(item, name);
        return value > 0
            ? value
            : throw new InvalidDataException($"Candidate Story '{name}' must be positive.");
    }

    private static int NonNegativeInteger(JsonElement item, string name)
    {
        var value = RequiredInteger(item, name);
        return value >= 0
            ? value
            : throw new InvalidDataException($"Candidate Story '{name}' cannot be negative.");
    }

    private static int RequiredInteger(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number
            : throw new InvalidDataException($"The Candidate Story snapshot is missing integer '{name}'.");

    private static long? OptionalLong(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)
            ? number
            : throw new InvalidDataException($"The Candidate Story snapshot has invalid integer '{name}'.");
    }

    private static decimal? OptionalDecimal(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        return value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var number)
            ? number
            : throw new InvalidDataException($"The Candidate Story snapshot has invalid number '{name}'.");
    }

    private static bool RequiredBoolean(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? value.GetBoolean()
            : throw new InvalidDataException($"The Candidate Story snapshot is missing boolean '{name}'.");

    private static string RequiredString(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.String
            && value.GetString()?.Trim() is { Length: > 0 } text
            ? text
            : throw new InvalidDataException($"The Candidate Story snapshot is missing '{name}'.");

    private static string OptionalString(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()?.Trim() ?? string.Empty
            : throw new InvalidDataException($"The Candidate Story snapshot is missing string '{name}'.");

    private static string RequiredArrayString(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.String && item.GetString()?.Trim() is { Length: > 0 } text
            ? text
            : throw new InvalidDataException($"The Candidate Story snapshot contains invalid '{name}'.");

    private static DateTimeOffset RequiredTimestamp(JsonElement item, string name) =>
        DateTimeOffset.TryParse(
            RequiredString(item, name),
            CultureInfo.InvariantCulture,
            DateTimeStyles.RoundtripKind,
            out var value)
            ? value
            : throw new InvalidDataException($"The Candidate Story snapshot has invalid timestamp '{name}'.");

    private static DateTimeOffset? OptionalTimestamp(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        if (value.ValueKind != JsonValueKind.String
            || !DateTimeOffset.TryParse(
                value.GetString(),
                CultureInfo.InvariantCulture,
                DateTimeStyles.RoundtripKind,
                out var timestamp))
        {
            throw new InvalidDataException($"The Candidate Story snapshot has invalid timestamp '{name}'.");
        }
        return timestamp;
    }

    private static JsonElement RequiredObject(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value
            : throw new InvalidDataException($"The Candidate Story snapshot is missing object '{name}'.");

    private static IReadOnlyList<JsonElement> RequiredArray(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.Array
            ? value.EnumerateArray().ToArray()
            : throw new InvalidDataException($"The Candidate Story snapshot is missing array '{name}'.");

    private static void RequireObject(JsonElement item, string message)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException(message);
        }
    }

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object
            && item.TryGetProperty(name, out value)
            && value.ValueKind is not JsonValueKind.Undefined;
    }

    [GeneratedRegex("^[A-Z][A-Z0-9.-]{0,14}$", RegexOptions.CultureInvariant)]
    private static partial Regex SymbolPattern();
}
