using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonSavedWatchlistWorkspaceClientTests
{
    [Fact]
    public void MapperPreservesStoredStaleRowsNullsCountsAndWarnings()
    {
        using var document = JsonDocument.Parse(StalePayload);

        var snapshot = PythonSavedWatchlistSnapshotMapper.Map(document.RootElement);

        Assert.Equal(SavedWatchlistState.Stale, snapshot.State);
        Assert.Equal("watchlist-2026-06-18.json", snapshot.SourceLabel);
        Assert.Equal("2026-06-18", snapshot.WatchlistDate);
        Assert.Equal(3, snapshot.TotalItemCount);
        Assert.Equal(2, snapshot.UsableItemCount);
        Assert.Equal(2, snapshot.DisplayedItemCount);
        Assert.Equal(["The latest saved watchlist is older than 36 hours."], snapshot.Warnings);
        Assert.Equal(["CRWV", "EQX"], snapshot.Items.Select(item => item.Symbol));
        Assert.Equal([1, 3], snapshot.Items.Select(item => item.SourceRank));
        Assert.Equal(82, snapshot.Items[0].Score);
        Assert.Null(snapshot.Items[1].Price);
        Assert.Null(snapshot.Items[1].RelativeVolume);
        Assert.Equal("Stored note", snapshot.Items[0].UserNotes);
    }

    [Theory]
    [InlineData("EMPTY")]
    [InlineData("UNAVAILABLE")]
    public void MapperPreservesExplicitNoRowStates(string state)
    {
        using var document = JsonDocument.Parse(
            $$"""
            {
              "schemaVersion": 1,
              "state": "{{state}}",
              "observedAt": "2026-07-23T15:00:00Z",
              "asOf": null,
              "watchlistDate": null,
              "summary": "{{state}} | No saved rows.",
              "sourceLabel": "No saved watchlist file",
              "totalItemCount": 0,
              "usableItemCount": 0,
              "displayedItemCount": 0,
              "warnings": [],
              "items": []
            }
            """);

        var snapshot = PythonSavedWatchlistSnapshotMapper.Map(document.RootElement);

        Assert.Empty(snapshot.Items);
        Assert.Equal(Enum.Parse<SavedWatchlistState>(state, ignoreCase: true), snapshot.State);
    }

    [Fact]
    public void MapperRejectsUnsupportedSchemaStateOrInvalidDate()
    {
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"schemaVersion\": 1", "\"schemaVersion\": 2")));
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"state\": \"STALE\"", "\"state\": \"CURRENT\"")));
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"watchlistDate\": \"2026-06-18\"", "\"watchlistDate\": \"06/18/2026\"")));
    }

    [Fact]
    public void MapperRejectsInconsistentCountsDuplicateRanksAndRowsInEmptyState()
    {
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"displayedItemCount\": 2", "\"displayedItemCount\": 1")));
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"sourceRank\": 3", "\"sourceRank\": 1")));
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"sourceRank\": 1", "\"sourceRank\": 4")));
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"state\": \"STALE\"", "\"state\": \"EMPTY\"")));
    }

    [Fact]
    public void MapperRejectsBlankSymbolNegativeVolumeAndMissingArrays()
    {
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"symbol\": \"CRWV\"", "\"symbol\": \"   \"")));
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"volume\": 1000", "\"volume\": -1")));
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"relativeVolume\": 0.2", "\"relativeVolume\": -0.2")));
        Assert.Throws<InvalidDataException>(() => Map(StalePayload.Replace("\"warnings\": [\"The latest saved watchlist is older than 36 hours.\"],", "")));
    }

    [Fact]
    public async Task ClientRequestsOnlyTheSavedWatchlistSnapshot()
    {
        var connection = new RecordingConnection();
        var client = new PythonSavedWatchlistWorkspaceClient(connection);

        var snapshot = await client.GetSnapshotAsync();

        Assert.Equal(1, connection.RequestCount);
        Assert.Equal(SavedWatchlistState.Stale, snapshot.State);
    }

    private static SavedWatchlistSnapshot Map(string json)
    {
        using var document = JsonDocument.Parse(json);
        return PythonSavedWatchlistSnapshotMapper.Map(document.RootElement);
    }

    private const string StalePayload =
        """
        {
          "schemaVersion": 1,
          "state": "STALE",
          "observedAt": "2026-07-23T15:00:00Z",
          "asOf": "2026-06-18T20:00:00Z",
          "watchlistDate": "2026-06-18",
          "summary": "STALE | Stored historical evidence only.",
          "sourceLabel": "watchlist-2026-06-18.json",
          "totalItemCount": 3,
          "usableItemCount": 2,
          "displayedItemCount": 2,
          "warnings": ["The latest saved watchlist is older than 36 hours."],
          "items": [
            {
              "sourceRank": 1,
              "symbol": "CRWV",
              "company": "CoreWeave",
              "score": 82,
              "price": 118.50,
              "percentChange": 0.8,
              "volume": 1000,
              "relativeVolume": 0.2,
              "sector": "Technology",
              "industry": "Infrastructure",
              "freshness": "STALE",
              "savedAt": "2026-06-18T20:00:00Z",
              "freshestHeadline": "Stored headline",
              "userNotes": "Stored note"
            },
            {
              "sourceRank": 3,
              "symbol": "EQX",
              "company": "",
              "score": null,
              "price": null,
              "percentChange": null,
              "volume": null,
              "relativeVolume": null,
              "sector": "",
              "industry": "",
              "freshness": "",
              "savedAt": null,
              "freshestHeadline": "",
              "userNotes": ""
            }
          ]
        }
        """;

    private sealed class RecordingConnection : IPythonEngineHostConnection
    {
        public int RequestCount { get; private set; }

        public Task<JsonElement> GetSavedWatchlistSnapshotAsync(CancellationToken cancellationToken = default)
        {
            RequestCount++;
            using var document = JsonDocument.Parse(StalePayload);
            return Task.FromResult(document.RootElement.Clone());
        }

        public Task<PythonEngineHostSnapshot> EnsureConnectedAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PythonEngineHostSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PythonEngineHostCommandResult> SendCommandAsync(
            string command,
            string commandId,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }
}
