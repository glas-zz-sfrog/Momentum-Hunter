using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonChartWorkspaceClientTests
{
    [Fact]
    public void MapperPreservesStaleCandlesAndSourceLineage()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "schemaVersion": 1,
              "symbol": "CRWV",
              "interval": "5m",
              "state": "STALE",
              "observedAt": "2026-07-23T05:03:00Z",
              "asOf": "2026-06-18T20:00:00Z",
              "summary": "STALE | 2 stored 5m candles | no provider fetch",
              "lineage": {
                "sourceLabel": "opportunity-minute-bars.json",
                "asOf": "2026-06-18T20:00:00Z",
                "summary": "Read-only local OHLC evidence."
              },
              "candles": [
                {
                  "timestamp": "2026-06-18T19:50:00Z",
                  "open": 118.90,
                  "high": 119.20,
                  "low": 118.70,
                  "close": 119.10,
                  "volume": 0
                },
                {
                  "timestamp": "2026-06-18T19:55:00Z",
                  "open": 119.10,
                  "high": 119.40,
                  "low": 118.80,
                  "close": 119.00,
                  "volume": 1500
                }
              ]
            }
            """);

        var snapshot = PythonChartSnapshotMapper.Map(document.RootElement);

        Assert.Equal(ChartDataState.Stale, snapshot.State);
        Assert.Equal("CRWV", snapshot.Symbol);
        Assert.Equal("5m", snapshot.Interval);
        Assert.Equal(2, snapshot.Candles.Count);
        Assert.Equal(0, snapshot.Candles[0].Volume);
        Assert.Equal(119.40m, snapshot.Candles[1].High);
        Assert.Equal("opportunity-minute-bars.json", snapshot.DataLineage.SourceLabel);
        Assert.Contains("no provider fetch", snapshot.Summary, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void MapperPreservesExplicitUnavailableStateWithoutCreatingCandles()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "schemaVersion": 1,
              "symbol": "EQX",
              "interval": "5m",
              "state": "UNAVAILABLE",
              "observedAt": "2026-07-23T05:03:00Z",
              "asOf": "2026-07-23T05:03:00Z",
              "summary": "UNAVAILABLE | No stored 5m bars are available. No simulated fallback was created.",
              "lineage": {
                "sourceLabel": "opportunity-minute-bars.json",
                "asOf": "2026-07-23T05:03:00Z",
                "summary": "Expected local evidence was unavailable."
              },
              "candles": []
            }
            """);

        var snapshot = PythonChartSnapshotMapper.Map(document.RootElement);

        Assert.Equal(ChartDataState.Unavailable, snapshot.State);
        Assert.Empty(snapshot.Candles);
        Assert.Contains("No simulated fallback", snapshot.Summary, StringComparison.Ordinal);
    }

    [Fact]
    public void MapperRejectsImpossibleOhlcGeometry()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "schemaVersion": 1,
              "symbol": "AAA",
              "interval": "Daily",
              "state": "AVAILABLE",
              "observedAt": "2026-01-06T12:00:00Z",
              "asOf": "2026-01-05T00:00:00Z",
              "summary": "Available",
              "lineage": {},
              "candles": [
                {
                  "timestamp": "2026-01-05T00:00:00Z",
                  "open": 12,
                  "high": 11,
                  "low": 10,
                  "close": 12,
                  "volume": 100
                }
              ]
            }
            """);

        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsUnsupportedSchemaVersion()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "schemaVersion": 2,
              "symbol": "AAA",
              "interval": "Daily",
              "state": "AVAILABLE",
              "observedAt": "2026-01-06T12:00:00Z",
              "asOf": "2026-01-05T00:00:00Z",
              "summary": "Available",
              "lineage": {},
              "candles": []
            }
            """);

        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public async Task ClientForwardsNormalizedChartRequestToHostConnection()
    {
        var connection = new RecordingChartConnection();
        var client = new PythonChartWorkspaceClient(connection);

        var snapshot = await client.GetSnapshotAsync("crwv", "Daily");

        Assert.Equal("CRWV", connection.Symbol);
        Assert.Equal("Daily", connection.Interval);
        Assert.Equal(ChartDataState.Unavailable, snapshot.State);
    }

    [Fact]
    public async Task ClientRejectsSnapshotForDifferentSymbolOrInterval()
    {
        var symbolMismatch = new PythonChartWorkspaceClient(
            new RecordingChartConnection(responseSymbol: "EQX"));
        var intervalMismatch = new PythonChartWorkspaceClient(
            new RecordingChartConnection(responseInterval: "Daily"));

        await Assert.ThrowsAsync<InvalidDataException>(
            () => symbolMismatch.GetSnapshotAsync("NVDA", "5m"));
        await Assert.ThrowsAsync<InvalidDataException>(
            () => intervalMismatch.GetSnapshotAsync("NVDA", "5m"));
    }

    private sealed class RecordingChartConnection : IPythonEngineHostConnection
    {
        private readonly string? _responseSymbol;
        private readonly string? _responseInterval;

        public RecordingChartConnection(
            string? responseSymbol = null,
            string? responseInterval = null)
        {
            _responseSymbol = responseSymbol;
            _responseInterval = responseInterval;
        }

        public string? Symbol { get; private set; }

        public string? Interval { get; private set; }

        public Task<JsonElement> GetChartSnapshotAsync(
            string symbol,
            string interval,
            CancellationToken cancellationToken = default)
        {
            Symbol = symbol.ToUpperInvariant();
            Interval = interval;
            using var document = JsonDocument.Parse(
                $$"""
                {
                  "schemaVersion": 1,
                  "symbol": "{{_responseSymbol ?? Symbol}}",
                  "interval": "{{_responseInterval ?? Interval}}",
                  "state": "UNAVAILABLE",
                  "observedAt": "2026-07-23T05:03:00Z",
                  "asOf": "2026-07-23T05:03:00Z",
                  "summary": "UNAVAILABLE",
                  "lineage": {},
                  "candles": []
                }
                """);
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
