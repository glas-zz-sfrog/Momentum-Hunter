using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonChartWorkspaceClientTests
{
    [Fact]
    public void MapperPreservesPartialQualityCanonicalAndProvisionalBars()
    {
        using var document = JsonDocument.Parse(ValidSnapshotJson());

        var snapshot = PythonChartSnapshotMapper.Map(document.RootElement);

        Assert.Equal(ChartDataState.Partial, snapshot.State);
        Assert.Equal("NVDA", snapshot.Symbol);
        Assert.Equal("1m", snapshot.Interval);
        Assert.Equal(2, snapshot.Candles.Count);
        Assert.Equal(1000m, snapshot.Candles[0].Volume);
        Assert.True(snapshot.Candles[0].IsCanonical);
        Assert.Equal("CORRECTED", snapshot.Candles[0].State);
        Assert.Equal(["close"], snapshot.Candles[0].DiscrepancyFields);
        Assert.Equal(1100.25m, snapshot.Candles[1].Volume);
        Assert.True(snapshot.Candles[1].IsInProgress);
        Assert.False(snapshot.Candles[1].IsCanonical);
        Assert.Equal("Schwab Trader API", snapshot.Quality!.Provider);
        Assert.Equal(1, snapshot.Quality.CorrectionCount);
        Assert.Equal(1, snapshot.Quality.InProgressCount);
        Assert.Equal("RUNNING", snapshot.Quality.HistoryLoadStatus);
        Assert.Equal("Loading bounded Schwab history.", snapshot.Quality.HistoryLoadDetail);
        Assert.Equal(DateTimeOffset.Parse("2026-08-05T14:31:00Z"), snapshot.Quality.LatestInProgressBarAt);
    }

    [Fact]
    public void MapperPreservesExplicitUnavailableStateWithoutCreatingCandles()
    {
        using var document = JsonDocument.Parse(UnavailableSnapshotJson("EQX", "5m"));

        var snapshot = PythonChartSnapshotMapper.Map(document.RootElement);

        Assert.Equal(ChartDataState.Unavailable, snapshot.State);
        Assert.Empty(snapshot.Candles);
        Assert.Contains("No simulated", snapshot.Summary, StringComparison.Ordinal);
        Assert.Equal("UNAVAILABLE", snapshot.Quality!.Status);
    }

    [Fact]
    public void MapperRejectsImpossibleOhlcGeometry()
    {
        using var document = JsonDocument.Parse(ValidSnapshotJson().Replace("\"high\": 119.20", "\"high\": 117.00", StringComparison.Ordinal));

        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsUnsupportedLegacySchemaVersion()
    {
        using var document = JsonDocument.Parse(ValidSnapshotJson().Replace("\"schemaVersion\": 2", "\"schemaVersion\": 1", StringComparison.Ordinal));

        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(document.RootElement));
    }

    [Fact]
    public void MapperRejectsContradictoryLifecycleAndQualityCounts()
    {
        using var lifecycle = JsonDocument.Parse(ValidSnapshotJson().Replace("\"isInProgress\": true", "\"isInProgress\": false", StringComparison.Ordinal));
        using var counts = JsonDocument.Parse(ValidSnapshotJson().Replace("\"completedCount\": 1", "\"completedCount\": 2", StringComparison.Ordinal));
        using var gaps = JsonDocument.Parse(ValidSnapshotJson().Replace("\"gapCount\": 0", "\"gapCount\": 1", StringComparison.Ordinal));

        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(lifecycle.RootElement));
        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(counts.RootElement));
        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(gaps.RootElement));
    }

    [Fact]
    public void MapperRejectsUnknownOrContradictoryStateAndLineage()
    {
        using var unknownState = JsonDocument.Parse(ValidSnapshotJson().Replace(
            "\"state\": \"PARTIAL\"",
            "\"state\": \"UNKNOWN\"",
            StringComparison.Ordinal));
        using var statusMismatch = JsonDocument.Parse(ValidSnapshotJson().Replace(
            "\"status\": \"PARTIAL\"",
            "\"status\": \"AVAILABLE\"",
            StringComparison.Ordinal));
        using var lineageMismatch = JsonDocument.Parse(ReplaceFirst(
            ValidSnapshotJson(),
            "\"sourceLabel\": \"Schwab CHART_EQUITY + price history\"",
            "\"sourceLabel\": \"Different source\""));

        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(unknownState.RootElement));
        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(statusMismatch.RootElement));
        Assert.Throws<InvalidDataException>(() => PythonChartSnapshotMapper.Map(lineageMismatch.RootElement));
    }

    [Fact]
    public async Task ClientForwardsNormalizedChartRequestToHostConnection()
    {
        var connection = new RecordingChartConnection();
        var client = new PythonChartWorkspaceClient(connection);

        var snapshot = await client.GetSnapshotAsync("nvda", "Daily");

        Assert.Equal("NVDA", connection.Symbol);
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

    private static string ValidSnapshotJson() =>
        """
        {
          "schemaVersion": 2,
          "symbol": "NVDA",
          "interval": "1m",
          "state": "PARTIAL",
          "observedAt": "2026-08-05T14:31:45Z",
          "asOf": "2026-08-05T14:31:00Z",
          "summary": "PARTIAL | Schwab Trader API | read-only persisted evidence",
          "lineage": {
            "sourceLabel": "Schwab CHART_EQUITY + price history",
            "asOf": "2026-08-05T14:31:00Z",
            "summary": "No provider call, legacy candle, interpolation, or fallback was used."
          },
          "quality": {
            "provider": "Schwab Trader API",
            "sourceLabel": "Schwab CHART_EQUITY + price history",
            "status": "PARTIAL",
            "sessionDates": ["2026-08-05"],
            "latestCompletedBarAt": "2026-08-05T14:30:00Z",
            "latestInProgressBarAt": "2026-08-05T14:31:00Z",
            "latestProviderTimestamp": "2026-08-05T14:31:00Z",
            "latestReceiptAt": "2026-08-05T14:31:30Z",
            "ageSeconds": 0,
            "stale": false,
            "gapCount": 0,
            "correctionCount": 1,
            "unreconciledCount": 0,
            "inProgressCount": 1,
            "completedCount": 1,
            "findings": ["CORRECTIONS:1", "IN_PROGRESS_BAR_PRESENT", "HISTORY_LOAD_RUNNING"],
            "historyLoadStatus": "RUNNING",
            "historyLoadDetail": "Loading bounded Schwab history."
          },
          "candles": [
            {
              "timestamp": "2026-08-05T14:30:00Z",
              "open": 118.90,
              "high": 119.20,
              "low": 118.70,
              "close": 119.10,
              "volume": 1000,
              "state": "CORRECTED",
              "source": "SCHWAB_PRICE_HISTORY",
              "providerTimestamp": "2026-08-05T14:30:00Z",
              "receivedAt": "2026-08-05T14:31:05Z",
              "isCanonical": true,
              "isInProgress": false,
              "hasGapBefore": false,
              "discrepancyFields": ["close"],
              "presentMinuteCount": 1,
              "expectedMinuteCount": 1
            },
            {
              "timestamp": "2026-08-05T14:31:00Z",
              "open": 119.10,
              "high": 119.40,
              "low": 118.80,
              "close": 119.00,
              "volume": 1100.25,
              "state": "IN_PROGRESS",
              "source": "SCHWAB_CHART_EQUITY",
              "providerTimestamp": "2026-08-05T14:31:00Z",
              "receivedAt": "2026-08-05T14:31:30Z",
              "isCanonical": false,
              "isInProgress": true,
              "hasGapBefore": false,
              "discrepancyFields": [],
              "presentMinuteCount": 1,
              "expectedMinuteCount": 1
            }
          ]
        }
        """;

    private static string UnavailableSnapshotJson(string symbol, string interval) =>
        $$"""
        {
          "schemaVersion": 2,
          "symbol": "{{symbol}}",
          "interval": "{{interval}}",
          "state": "UNAVAILABLE",
          "observedAt": "2026-08-05T14:31:45Z",
          "asOf": "2026-08-05T14:31:45Z",
          "summary": "UNAVAILABLE | No simulated, legacy, or cross-timeframe fallback was created.",
          "lineage": {
            "sourceLabel": "Schwab CHART_EQUITY + price history",
            "asOf": "2026-08-05T14:31:45Z",
            "summary": "Expected read-only OHLC evidence was unavailable."
          },
          "quality": {
            "provider": "UNAVAILABLE",
            "sourceLabel": "Schwab CHART_EQUITY + price history",
            "status": "UNAVAILABLE",
            "sessionDates": [],
            "latestCompletedBarAt": null,
            "latestInProgressBarAt": null,
            "latestProviderTimestamp": null,
            "latestReceiptAt": null,
            "ageSeconds": null,
            "stale": true,
            "gapCount": 0,
            "correctionCount": 0,
            "unreconciledCount": 0,
            "inProgressCount": 0,
            "completedCount": 0,
            "findings": ["SOURCE_UNAVAILABLE"]
          },
          "candles": []
        }
        """;

    private static string ReplaceFirst(string source, string oldValue, string newValue)
    {
        var index = source.IndexOf(oldValue, StringComparison.Ordinal);
        Assert.True(index >= 0, $"Fixture marker not found: {oldValue}");
        return source[..index] + newValue + source[(index + oldValue.Length)..];
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
                UnavailableSnapshotJson(_responseSymbol ?? Symbol, _responseInterval ?? Interval));
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
