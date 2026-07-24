using MomentumHunter.Contracts;
using MomentumHunter.Presentation;

namespace MomentumHunter.Presentation.Tests;

public sealed class ChartReadabilityTests
{
    [Fact]
    public void PriceAxisUsesDeterministicNiceBoundsThatContainEveryCandle()
    {
        var candles = Candles(
            ("2026-07-23T14:30:00Z", 100.10m, 100.40m, 99.91m, 100.20m, 1000L),
            ("2026-07-23T14:35:00Z", 100.20m, 101.06m, 100.10m, 100.90m, 1500L));

        var first = ChartAxisScale.Create(candles, "5m");
        var second = ChartAxisScale.Create(candles, "5m");

        Assert.Equal(99.50m, first.MinimumPrice);
        Assert.Equal(101.50m, first.MaximumPrice);
        Assert.Equal(
            ["99.50", "100.00", "100.50", "101.00", "101.50"],
            first.PriceTicks.Select(tick => tick.Label));
        Assert.Equal(
            first.PriceTicks.Select(tick => (tick.Value, tick.Label, tick.Position)),
            second.PriceTicks.Select(tick => (tick.Value, tick.Label, tick.Position)));
        Assert.All(candles, candle =>
        {
            Assert.True(candle.Low >= first.MinimumPrice);
            Assert.True(candle.High <= first.MaximumPrice);
        });
    }

    [Fact]
    public void FlatPriceRangeExpandsSafely()
    {
        var candles = Candles(
            ("2026-07-23T14:30:00Z", 50m, 50m, 50m, 50m, 0L),
            ("2026-07-23T14:35:00Z", 50m, 50m, 50m, 50m, 0L));

        var axis = ChartAxisScale.Create(candles, "5m");

        Assert.True(axis.MinimumPrice < 50m);
        Assert.True(axis.MaximumPrice > 50m);
        Assert.NotEmpty(axis.PriceTicks);
        Assert.All(axis.PriceTicks, tick => Assert.InRange(tick.Position, 0d, 1d));
    }

    [Fact]
    public void IntradayTimeAxisUsesUtcClockLabelsAndCandleCenters()
    {
        var candles = Candles(
            ("2026-07-23T14:30:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-07-23T14:35:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-07-23T14:40:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-07-23T14:45:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-07-23T14:50:00Z", 10m, 11m, 9m, 10m, 1L));

        var axis = ChartAxisScale.Create(candles, "5m");

        Assert.Equal(["14:30", "14:35", "14:40", "14:45", "14:50"], axis.TimeTicks.Select(tick => tick.Label));
        Assert.Equal(0.1d, axis.TimeTicks[0].Position, 6);
        Assert.Equal(0.9d, axis.TimeTicks[^1].Position, 6);
    }

    [Fact]
    public void DailyTimeAxisUsesCalendarLabels()
    {
        var candles = Candles(
            ("2025-12-31T00:00:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-01-02T00:00:00Z", 10m, 11m, 9m, 10m, 1L));

        var axis = ChartAxisScale.Create(candles, "Daily");

        Assert.Equal(["2025 Dec 31", "2026 Jan 2"], axis.TimeTicks.Select(tick => tick.Label));
    }

    [Fact]
    public void TickTargetsBelowTwoAreRejected()
    {
        var candles = Candles(("2026-07-23T14:30:00Z", 10m, 11m, 9m, 10m, 1L));

        Assert.Throws<ArgumentOutOfRangeException>(() => ChartAxisScale.Create(candles, "5m", priceTickTarget: 1));
        Assert.Throws<ArgumentOutOfRangeException>(() => ChartAxisScale.Create(candles, "5m", timeTickTarget: 1));
    }

    [Theory]
    [InlineData(0.00, 0, 0.125)]
    [InlineData(0.24, 0, 0.125)]
    [InlineData(0.25, 1, 0.375)]
    [InlineData(0.74, 2, 0.625)]
    [InlineData(0.75, 3, 0.875)]
    [InlineData(1.00, 3, 0.875)]
    public void InspectionSelectsNearestChronologicalCandle(
        double normalizedPosition,
        int expectedIndex,
        double expectedCenter)
    {
        var candles = Candles(
            ("2026-07-23T14:45:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-07-23T14:30:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-07-23T14:40:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-07-23T14:35:00Z", 10m, 11m, 9m, 10m, 1L));

        var inspection = ChartInspectionScale.SelectNearest(candles, normalizedPosition);

        Assert.NotNull(inspection);
        Assert.Equal(expectedIndex, inspection.Index);
        Assert.Equal(expectedCenter, inspection.Position, 6);
        Assert.Equal(
            DateTimeOffset.Parse("2026-07-23T14:30:00Z").AddMinutes(expectedIndex * 5),
            inspection.Candle.Timestamp);
    }

    [Fact]
    public void InspectionRejectsMissingOrOutOfPlotPositions()
    {
        var candles = Candles(("2026-07-23T14:30:00Z", 10m, 11m, 9m, 10m, 1L));

        Assert.Null(ChartInspectionScale.SelectNearest([], 0.5d));
        Assert.Null(ChartInspectionScale.SelectNearest(candles, -0.001d));
        Assert.Null(ChartInspectionScale.SelectNearest(candles, 1.001d));
        Assert.Null(ChartInspectionScale.SelectNearest(candles, double.NaN));
        Assert.Null(ChartInspectionScale.SelectNearest(candles, double.PositiveInfinity));
    }

    [Fact]
    public void LatestBarDetailsUseChronologicallyNewestCandle()
    {
        var pane = Pane("5m");
        var earlier = Candle("2026-07-23T14:30:00Z", 118.90m, 119.20m, 118.70m, 119.10m, 0L);
        var latest = Candle("2026-07-23T14:35:00Z", 119.10m, 119.40m, 118.80m, 119.00m, 1500L);
        var viewModel = new ChartPaneViewModel(pane, Snapshot(pane, ChartDataState.Stale, [latest, earlier]));

        Assert.Equal(latest, viewModel.LatestBar);
        Assert.Equal(
            "2026-07-23 14:35 UTC  |  O 119.10  H 119.40  L 118.80  C 119.00  |  V 1,500",
            viewModel.LatestBarSummary);
    }

    [Fact]
    public void LatestBarDetailsClearWhenSnapshotBecomesUnavailable()
    {
        var pane = Pane("Daily");
        var viewModel = new ChartPaneViewModel(
            pane,
            Snapshot(
                pane,
                ChartDataState.Available,
                [Candle("2026-07-23T00:00:00Z", 18.1m, 18.6m, 17.9m, 18.4m, 900L)]));

        viewModel.ApplySnapshot(Snapshot(pane, ChartDataState.Unavailable, []));

        Assert.Null(viewModel.LatestBar);
        Assert.Equal("Latest bar unavailable", viewModel.LatestBarSummary);
    }

    [Fact]
    public void DailyLatestBarOmitsAnInventedIntradayTime()
    {
        var pane = Pane("Daily");
        var viewModel = new ChartPaneViewModel(
            pane,
            Snapshot(
                pane,
                ChartDataState.Available,
                [Candle("2026-07-23T00:00:00Z", 0.8123m, 0.8456m, 0.8001m, 0.8321m, 4200L)]));

        Assert.StartsWith("2026-07-23 UTC", viewModel.LatestBarSummary, StringComparison.Ordinal);
        Assert.Contains("O 0.8123", viewModel.LatestBarSummary, StringComparison.Ordinal);
    }

    [Fact]
    public void InspectedBarTemporarilyReplacesLatestBarDetails()
    {
        var pane = Pane("5m");
        var inspected = Candle("2026-07-23T14:30:00Z", 118.90m, 119.20m, 118.70m, 119.10m, 1000L);
        var latest = Candle("2026-07-23T14:35:00Z", 119.10m, 119.40m, 118.80m, 119.00m, 1500L);
        var viewModel = new ChartPaneViewModel(
            pane,
            Snapshot(pane, ChartDataState.Available, [latest, inspected]));

        viewModel.InspectedBar = inspected;

        Assert.Equal("INSPECTED BAR", viewModel.ActiveBarLabel);
        Assert.Equal(
            "2026-07-23 14:30 UTC  |  O 118.90  H 119.20  L 118.70  C 119.10  |  V 1,000",
            viewModel.ActiveBarSummary);
        Assert.Equal(latest, viewModel.LatestBar);

        viewModel.InspectedBar = null;

        Assert.Equal("LATEST BAR", viewModel.ActiveBarLabel);
        Assert.Equal(viewModel.LatestBarSummary, viewModel.ActiveBarSummary);
    }

    [Fact]
    public void SnapshotReplacementClearsInspectionFromPreviousContext()
    {
        var pane = Pane("5m");
        var first = Candle("2026-07-23T14:30:00Z", 10m, 11m, 9m, 10.5m, 100L);
        var replacement = Candle("2026-07-23T15:00:00Z", 20m, 21m, 19m, 20.5m, 200L);
        var viewModel = new ChartPaneViewModel(
            pane,
            Snapshot(pane, ChartDataState.Available, [first]));
        viewModel.InspectedBar = first;

        viewModel.ApplySnapshot(Snapshot(pane, ChartDataState.Available, [replacement]));

        Assert.Null(viewModel.InspectedBar);
        Assert.Equal("LATEST BAR", viewModel.ActiveBarLabel);
        Assert.Contains("2026-07-23 15:00 UTC", viewModel.ActiveBarSummary, StringComparison.Ordinal);
    }

    private static PaneState Pane(string interval) => new(
        PaneKind.Chart,
        "Chart",
        LinkGroup.A,
        DockRegion.Center,
        "NVDA",
        interval,
        0);

    private static ChartSnapshot Snapshot(
        PaneState pane,
        ChartDataState state,
        IReadOnlyList<CandleSnapshot> candles)
    {
        var at = DateTimeOffset.Parse("2026-07-23T15:00:00Z");
        return new ChartSnapshot(
            1,
            pane.Symbol,
            pane.Interval,
            state,
            at,
            at,
            state.ToString(),
            new DataLineage("stored-bars.json", at, "Read-only local evidence."),
            candles);
    }

    private static CandleSnapshot[] Candles(
        params (string At, decimal Open, decimal High, decimal Low, decimal Close, long Volume)[] rows) =>
        rows.Select(row => Candle(row.At, row.Open, row.High, row.Low, row.Close, row.Volume)).ToArray();

    private static CandleSnapshot Candle(
        string at,
        decimal open,
        decimal high,
        decimal low,
        decimal close,
        long volume) =>
        new(DateTimeOffset.Parse(at), open, high, low, close, volume);
}
