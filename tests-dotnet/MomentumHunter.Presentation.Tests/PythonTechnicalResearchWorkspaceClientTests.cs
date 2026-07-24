using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonTechnicalResearchWorkspaceClientTests
{
    [Fact]
    public void MapperPreservesStoredStaleEventAndStudyEvidence()
    {
        using var document = JsonDocument.Parse(SnapshotJson());

        var snapshot = PythonTechnicalResearchSnapshotMapper.Map(document.RootElement);

        Assert.Equal(TechnicalResearchState.Stale, snapshot.State);
        Assert.Equal("NVDA", snapshot.Symbol);
        Assert.Equal(DateTimeOffset.Parse("2026-07-23T14:30:00Z"), snapshot.AsOf);
        Assert.Equal(23860, snapshot.GlobalEventCount);
        Assert.Equal(2, snapshot.SymbolEventCount);
        var signal = Assert.Single(snapshot.Events);
        Assert.Equal("event-1", signal.EventId);
        Assert.Equal("donchian_20_day_breakout", signal.EventType);
        Assert.Equal(125.50m, signal.TriggerPrice);
        Assert.Equal(2.25m, signal.RelativeVolume);
        Assert.True(signal.VolumeConfirmed);
        Assert.False(signal.RelativeStrengthConfirmed);
        var study = Assert.Single(snapshot.Studies);
        Assert.Equal("Breakout failed", study.Status);
        Assert.Equal(4.50m, study.Return5DayPercent);
        Assert.Equal(-2.00m, study.MaxAdverseExcursionPercent);
        Assert.True(study.FailedBackBelowBreakoutLevel);
        Assert.Null(study.Return5MinutePercent);
        Assert.Equal(["Stored report warning."], snapshot.Warnings);
    }

    [Theory]
    [InlineData("AVAILABLE", TechnicalResearchState.Available)]
    [InlineData("PARTIAL", TechnicalResearchState.Partial)]
    [InlineData("EMPTY", TechnicalResearchState.Empty)]
    [InlineData("UNAVAILABLE", TechnicalResearchState.Unavailable)]
    public void MapperPreservesExplicitSourceState(string wireState, TechnicalResearchState expected)
    {
        using var document = JsonDocument.Parse(SnapshotJson(
            state: wireState,
            eventRows: wireState is "EMPTY" or "UNAVAILABLE" ? "[]" : null,
            studyRows: wireState is "EMPTY" or "UNAVAILABLE" ? "[]" : null));

        var snapshot = PythonTechnicalResearchSnapshotMapper.Map(document.RootElement);

        Assert.Equal(expected, snapshot.State);
    }

    [Fact]
    public void MapperPreservesMissingTimesAndIdentityWithoutInventingValues()
    {
        using var document = JsonDocument.Parse(SnapshotJson(
            asOf: "null",
            eventTimestamp: "null",
            studyTimestamp: "null",
            eventId: string.Empty));

        var snapshot = PythonTechnicalResearchSnapshotMapper.Map(document.RootElement);

        Assert.Null(snapshot.AsOf);
        Assert.Null(snapshot.Events[0].EventTimestamp);
        Assert.Empty(snapshot.Events[0].EventId);
        Assert.Null(snapshot.Studies[0].EventTimestamp);
    }

    [Fact]
    public void MapperRejectsUnsupportedSchemaNegativeCountsAndRowsInEmptyState()
    {
        using var unsupported = JsonDocument.Parse(SnapshotJson(schemaVersion: 2));
        using var negative = JsonDocument.Parse(SnapshotJson(globalEventCount: -1));
        using var dishonestEmpty = JsonDocument.Parse(SnapshotJson(state: "EMPTY"));

        Assert.Throws<InvalidDataException>(
            () => PythonTechnicalResearchSnapshotMapper.Map(unsupported.RootElement));
        Assert.Throws<InvalidDataException>(
            () => PythonTechnicalResearchSnapshotMapper.Map(negative.RootElement));
        Assert.Throws<InvalidDataException>(
            () => PythonTechnicalResearchSnapshotMapper.Map(dishonestEmpty.RootElement));
    }

    [Fact]
    public async Task ClientNormalizesSymbolAndRejectsMismatchedResponseIdentity()
    {
        var connection = new RecordingConnection();
        var client = new PythonTechnicalResearchWorkspaceClient(connection);

        var snapshot = await client.GetSnapshotAsync(" nvda ");

        Assert.Equal("NVDA", connection.Symbol);
        Assert.Equal("NVDA", snapshot.Symbol);

        var mismatch = new PythonTechnicalResearchWorkspaceClient(new RecordingConnection("AMD"));
        await Assert.ThrowsAsync<InvalidDataException>(() => mismatch.GetSnapshotAsync("NVDA"));
    }

    [Fact]
    public async Task ClientRejectsBlankSymbolBeforeCallingHost()
    {
        var connection = new RecordingConnection();
        var client = new PythonTechnicalResearchWorkspaceClient(connection);

        await Assert.ThrowsAsync<ArgumentException>(() => client.GetSnapshotAsync(" "));

        Assert.Null(connection.Symbol);
    }

    private static string SnapshotJson(
        int schemaVersion = 1,
        string state = "STALE",
        int globalEventCount = 23860,
        string asOf = "\"2026-07-23T14:30:00Z\"",
        string eventTimestamp = "\"2026-07-23T14:00:00Z\"",
        string studyTimestamp = "\"2026-07-23T14:00:00Z\"",
        string eventId = "event-1",
        string? eventRows = null,
        string? studyRows = null)
    {
        eventRows ??=
            $$"""
            [
              {
                "eventId": "{{eventId}}",
                "eventTimestamp": {{eventTimestamp}},
                "eventType": "donchian_20_day_breakout",
                "timeframe": "daily",
                "status": "Breakout present",
                "qualityFlag": "HIGH",
                "dataSufficiency": "Sufficient",
                "triggerPrice": 125.50,
                "distanceAboveTriggerPct": 1.25,
                "relativeVolume": 2.25,
                "volumeConfirmed": true,
                "relativeStrengthConfirmed": false,
                "notes": "Stored event note."
              }
            ]
            """;
        studyRows ??=
            $$"""
            [
              {
                "eventId": "event-1",
                "eventTimestamp": {{studyTimestamp}},
                "eventType": "donchian_20_day_breakout",
                "timeframe": "daily",
                "status": "Breakout failed",
                "dataSufficiency": "Sufficient",
                "return5mPct": null,
                "return15mPct": null,
                "return60mPct": null,
                "return1dPct": 1.0,
                "return5dPct": 4.50,
                "return10dPct": -1.0,
                "maxFavorableExcursionPct": 6.0,
                "maxAdverseExcursionPct": -2.0,
                "heldAboveBreakoutLevel": false,
                "failedBackBelowBreakoutLevel": true,
                "becameExtended": false,
                "volumeConfirmed": true,
                "notes": "No study notes were stored."
              }
            ]
            """;
        return
            $$"""
            {
              "schemaVersion": {{schemaVersion}},
              "symbol": "NVDA",
              "state": "{{state}}",
              "observedAt": "2026-07-23T15:00:00Z",
              "asOf": {{asOf}},
              "summary": "Stored technical research only.",
              "sourceLabel": "technical-breakout-events-latest.json + technical-breakout-study-latest.json",
              "globalEventCount": {{globalEventCount}},
              "globalStudyCount": 23857,
              "symbolEventCount": 2,
              "symbolStudyCount": 1,
              "presentEventCount": 1,
              "failedStudyCount": 1,
              "insufficientDataCount": 1,
              "warnings": ["Stored report warning."],
              "events": {{eventRows}},
              "studies": {{studyRows}}
            }
            """;
    }

    private sealed class RecordingConnection : IPythonEngineHostConnection
    {
        private readonly string _responseSymbol;

        public RecordingConnection(string responseSymbol = "NVDA")
        {
            _responseSymbol = responseSymbol;
        }

        public string? Symbol { get; private set; }

        public Task<JsonElement> GetTechnicalResearchSnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default)
        {
            Symbol = symbol;
            using var document = JsonDocument.Parse(
                SnapshotJson().Replace("\"symbol\": \"NVDA\"", $"\"symbol\": \"{_responseSymbol}\"", StringComparison.Ordinal));
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
