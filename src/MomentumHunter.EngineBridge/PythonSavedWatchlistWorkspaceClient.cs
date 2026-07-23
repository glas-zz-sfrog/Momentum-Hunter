using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

public sealed class PythonSavedWatchlistWorkspaceClient : ISavedWatchlistWorkspaceClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonSavedWatchlistWorkspaceClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<SavedWatchlistSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
        PythonSavedWatchlistSnapshotMapper.Map(
            await _connection.GetSavedWatchlistSnapshotAsync(cancellationToken));
}

public static class PythonSavedWatchlistSnapshotMapper
{
    public static SavedWatchlistSnapshot Map(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("The Python saved-watchlist snapshot must be a JSON object.");
        }

        var schemaVersion = RequiredInteger(root, "schemaVersion");
        if (schemaVersion != 1)
        {
            throw new InvalidDataException($"Unsupported Python saved-watchlist schema version: {schemaVersion}.");
        }

        var state = State(RequiredString(root, "state"));
        var watchlistDate = OptionalString(root, "watchlistDate");
        if (watchlistDate is not null
            && !DateOnly.TryParseExact(
                watchlistDate,
                "yyyy-MM-dd",
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out _))
        {
            throw new InvalidDataException("The Python saved-watchlist snapshot has an invalid watchlist date.");
        }
        var totalItemCount = NonNegativeInteger(root, "totalItemCount");
        var usableItemCount = NonNegativeInteger(root, "usableItemCount");
        var displayedItemCount = NonNegativeInteger(root, "displayedItemCount");
        var warnings = RequiredArray(root, "warnings").Select(RequiredTextValue).ToArray();
        var items = RequiredArray(root, "items").Select(Item).ToArray();

        if (totalItemCount < usableItemCount
            || usableItemCount < displayedItemCount
            || displayedItemCount != items.Length)
        {
            throw new InvalidDataException("The Python saved-watchlist snapshot contains inconsistent item counts.");
        }
        if (items.Select(item => item.SourceRank).Distinct().Count() != items.Length)
        {
            throw new InvalidDataException("The Python saved-watchlist snapshot contains duplicate source ranks.");
        }
        if (!items.Select(item => item.SourceRank).SequenceEqual(items.Select(item => item.SourceRank).Order())
            || items.Any(item => item.SourceRank > totalItemCount))
        {
            throw new InvalidDataException("The Python saved-watchlist snapshot does not preserve valid source-rank order.");
        }
        if (state is SavedWatchlistState.Empty or SavedWatchlistState.Unavailable && items.Length != 0)
        {
            throw new InvalidDataException("An empty or unavailable saved-watchlist snapshot cannot contain display rows.");
        }
        if (state is SavedWatchlistState.Available or SavedWatchlistState.Stale or SavedWatchlistState.Partial
            && usableItemCount == 0)
        {
            throw new InvalidDataException("An available, stale, or partial saved-watchlist snapshot must contain usable rows.");
        }
        if (state == SavedWatchlistState.Empty && totalItemCount != 0)
        {
            throw new InvalidDataException("An empty saved-watchlist snapshot cannot report stored rows.");
        }

        return new SavedWatchlistSnapshot(
            schemaVersion,
            state,
            RequiredTimestamp(root, "observedAt"),
            OptionalTimestamp(root, "asOf"),
            watchlistDate,
            RequiredString(root, "summary"),
            RequiredString(root, "sourceLabel"),
            totalItemCount,
            usableItemCount,
            displayedItemCount,
            warnings,
            items);
    }

    private static SavedWatchlistItemSnapshot Item(JsonElement item)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("A Python saved-watchlist item must be a JSON object.");
        }

        var sourceRank = RequiredInteger(item, "sourceRank");
        if (sourceRank <= 0)
        {
            throw new InvalidDataException("A Python saved-watchlist item has an invalid source rank.");
        }

        var volume = OptionalLong(item, "volume");
        if (volume is < 0)
        {
            throw new InvalidDataException("A Python saved-watchlist item has negative volume.");
        }
        var score = OptionalInteger(item, "score");
        var price = OptionalDecimal(item, "price");
        var relativeVolume = OptionalDecimal(item, "relativeVolume");
        if (score is < 0 || price is < 0m || relativeVolume is < 0m)
        {
            throw new InvalidDataException("A Python saved-watchlist item contains a negative nonnegative field.");
        }

        return new SavedWatchlistItemSnapshot(
            sourceRank,
            RequiredString(item, "symbol").Trim().ToUpperInvariant(),
            OptionalString(item, "company") ?? string.Empty,
            score,
            price,
            OptionalDecimal(item, "percentChange"),
            volume,
            relativeVolume,
            OptionalString(item, "sector") ?? string.Empty,
            OptionalString(item, "industry") ?? string.Empty,
            OptionalString(item, "freshness") ?? string.Empty,
            OptionalTimestamp(item, "savedAt"),
            OptionalString(item, "freshestHeadline") ?? string.Empty,
            OptionalString(item, "userNotes") ?? string.Empty);
    }

    private static SavedWatchlistState State(string value) => value.Trim().ToUpperInvariant() switch
    {
        "AVAILABLE" => SavedWatchlistState.Available,
        "STALE" => SavedWatchlistState.Stale,
        "PARTIAL" => SavedWatchlistState.Partial,
        "EMPTY" => SavedWatchlistState.Empty,
        "UNAVAILABLE" => SavedWatchlistState.Unavailable,
        _ => throw new InvalidDataException($"Unsupported Python saved-watchlist state: {value}."),
    };

    private static JsonElement[] RequiredArray(JsonElement item, string name)
    {
        if (!Property(item, name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException($"The Python saved-watchlist snapshot is missing array '{name}'.");
        }

        return value.EnumerateArray().ToArray();
    }

    private static string RequiredTextValue(JsonElement item) =>
        item.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(item.GetString())
            ? item.GetString()!
            : throw new InvalidDataException("A Python saved-watchlist warning must be non-empty text.");

    private static string RequiredString(JsonElement item, string name) =>
        OptionalString(item, name) is { } value && !string.IsNullOrWhiteSpace(value)
            ? value.Trim()
            : throw new InvalidDataException($"The Python saved-watchlist snapshot is missing '{name}'.");

    private static string? OptionalString(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int NonNegativeInteger(JsonElement item, string name)
    {
        var value = RequiredInteger(item, name);
        return value >= 0
            ? value
            : throw new InvalidDataException($"The Python saved-watchlist snapshot has a negative '{name}'.");
    }

    private static int RequiredInteger(JsonElement item, string name) =>
        OptionalInteger(item, name)
        ?? throw new InvalidDataException($"The Python saved-watchlist snapshot is missing integer '{name}'.");

    private static int? OptionalInteger(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            return null;
        }
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number
            : null;
    }

    private static long? OptionalLong(JsonElement item, string name)
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

    private static decimal? OptionalDecimal(JsonElement item, string name)
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

    private static DateTimeOffset RequiredTimestamp(JsonElement item, string name) =>
        OptionalTimestamp(item, name)
        ?? throw new InvalidDataException($"The Python saved-watchlist snapshot is missing timestamp '{name}'.");

    private static DateTimeOffset? OptionalTimestamp(JsonElement item, string name) =>
        DateTimeOffset.TryParse(
            OptionalString(item, name),
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal,
            out var value)
            ? value
            : null;

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object
            && item.TryGetProperty(name, out value)
            && value.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined;
    }
}
