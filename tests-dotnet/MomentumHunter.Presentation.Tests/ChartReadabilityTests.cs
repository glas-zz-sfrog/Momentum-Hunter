using System.Runtime.CompilerServices;
using System.Xml.Linq;
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
            "2026-07-23 14:35 UTC  |  O 119.10  H 119.40  L 118.80  C 119.00  |  V 1,500  |  RECONCILED",
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
            "2026-07-23 14:30 UTC  |  O 118.90  H 119.20  L 118.70  C 119.10  |  V 1,000  |  RECONCILED",
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

    [Fact]
    public void SparseSeriesUsesDenseRightAlignedViewportSlots()
    {
        var candles = Candles(
            ("2026-08-05T14:30:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-08-05T14:31:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-08-05T14:32:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-08-05T14:33:00Z", 10m, 11m, 9m, 10m, 1L));

        var viewport = ChartViewportScale.Create(candles, 720d);

        Assert.Equal(120, viewport.SlotCount);
        Assert.Equal(116, viewport.LeadingEmptySlotCount);
        Assert.Equal(0.970833d, viewport.CenterPosition(0), 6);
        Assert.Equal(0.995833d, viewport.CenterPosition(3), 6);
        Assert.True(viewport.CenterPosition(3) - viewport.CenterPosition(0) < 0.03d);
    }

    [Fact]
    public void DenseSeriesKeepsLatestCandlesInsideBoundedViewport()
    {
        var start = DateTimeOffset.Parse("2026-08-05T13:30:00Z");
        var candles = Enumerable.Range(0, 200)
            .Select(index => new CandleSnapshot(
                start.AddMinutes(index),
                100m,
                101m,
                99m,
                100m,
                1m))
            .ToArray();

        var viewport = ChartViewportScale.Create(candles, 720d);

        Assert.Equal(120, viewport.Candles.Count);
        Assert.Equal(0, viewport.LeadingEmptySlotCount);
        Assert.Equal(start.AddMinutes(80), viewport.Candles[0].Timestamp);
        Assert.Equal(start.AddMinutes(199), viewport.Candles[^1].Timestamp);
    }

    [Fact]
    public void SparseViewportInspectionIgnoresEmptyHistoryAndMapsVisibleCandles()
    {
        var candles = Candles(
            ("2026-08-05T14:30:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-08-05T14:31:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-08-05T14:32:00Z", 10m, 11m, 9m, 10m, 1L),
            ("2026-08-05T14:33:00Z", 10m, 11m, 9m, 10m, 1L));
        var viewport = ChartViewportScale.Create(candles, 720d);

        Assert.Null(viewport.ToCandleNormalizedPosition(0.5d));
        Assert.Equal(0.125d, viewport.ToCandleNormalizedPosition(viewport.CenterPosition(0))!.Value, 6);
        Assert.Equal(0.875d, viewport.ToCandleNormalizedPosition(viewport.CenterPosition(3))!.Value, 6);
    }

    [Fact]
    public void QualityLabelsSeparateCompletedReceiptIntegrityAndInProgressState()
    {
        var pane = Pane("1m");
        var completed = Candle("2026-08-05T14:30:00Z", 118.90m, 119.20m, 118.70m, 119.10m, 1000L);
        var provisional = new CandleSnapshot(
            DateTimeOffset.Parse("2026-08-05T14:31:00Z"),
            119.10m,
            119.40m,
            118.80m,
            119.00m,
            1100.25m,
            "IN_PROGRESS",
            "SCHWAB_CHART_EQUITY",
            DateTimeOffset.Parse("2026-08-05T14:31:00Z"),
            DateTimeOffset.Parse("2026-08-05T14:31:30Z"),
            false,
            true);
        var at = DateTimeOffset.Parse("2026-08-05T14:31:45Z");
        var quality = new ChartQualitySnapshot(
            "Schwab Trader API",
            "Schwab CHART_EQUITY + price history",
            "PARTIAL",
            ["2026-08-05"],
            completed.Timestamp,
            provisional.Timestamp,
            provisional.ProviderTimestamp,
            provisional.ReceivedAt,
            0m,
            false,
            2,
            1,
            0,
            1,
            1,
            ["GAPS:2", "CORRECTIONS:1", "IN_PROGRESS_BAR_PRESENT"]);
        var snapshot = new ChartSnapshot(
            2,
            pane.Symbol,
            pane.Interval,
            ChartDataState.Partial,
            at,
            provisional.Timestamp,
            "PARTIAL | Schwab Trader API",
            new DataLineage("Schwab CHART_EQUITY + price history", at, "Read-only stored evidence."),
            [completed, provisional],
            quality);

        var viewModel = new ChartPaneViewModel(pane, snapshot);

        Assert.Equal("Schwab Trader API  |  PARTIAL", viewModel.ProviderStatusLabel);
        Assert.Contains("Complete 2026-08-05 14:30 UTC", viewModel.TimingStatusLabel, StringComparison.Ordinal);
        Assert.Contains("received 2026-08-05 14:31 UTC", viewModel.TimingStatusLabel, StringComparison.Ordinal);
        Assert.Equal("Gaps 2  |  Corrected 1  |  Unreconciled 0", viewModel.IntegrityStatusLabel);
        Assert.Equal("In progress 2026-08-05 14:31 UTC", viewModel.InProgressStatusLabel);
        Assert.Contains("IN PROGRESS", viewModel.LatestBarSummary, StringComparison.Ordinal);
        Assert.Contains("1,100.25", viewModel.LatestBarSummary, StringComparison.Ordinal);
    }

    [Fact]
    public void AutomaticHistoryLoadHasPlainVisibleLoadingAndFailureStates()
    {
        var pane = Pane("1m");
        var at = DateTimeOffset.Parse("2026-08-06T14:00:00Z");
        var loadingQuality = new ChartQualitySnapshot(
            "UNAVAILABLE",
            "Schwab CHART_EQUITY + price history",
            "UNAVAILABLE",
            [],
            null,
            null,
            null,
            null,
            null,
            true,
            0,
            0,
            0,
            0,
            0,
            ["SOURCE_UNAVAILABLE", "HISTORY_LOAD_QUEUED"],
            "QUEUED",
            "No stored 1m history is available.");
        var loading = new ChartPaneViewModel(
            pane,
            new ChartSnapshot(
                2,
                pane.Symbol,
                pane.Interval,
                ChartDataState.Unavailable,
                at,
                at,
                "LOADING HISTORY | UNAVAILABLE",
                new DataLineage("Schwab CHART_EQUITY + price history", at, "Expected source."),
                [],
                loadingQuality));

        Assert.True(loading.IsHistoryLoading);
        Assert.Equal("UNAVAILABLE  |  LOADING HISTORY", loading.ProviderStatusLabel);
        Assert.Equal("Loading Schwab candle history...", loading.EmptyStateText);
        Assert.Equal("No stored 1m history is available.", loading.HistoryLoadDetail);

        var failedQuality = loadingQuality with
        {
            HistoryLoadStatus = "FAILED",
            HistoryLoadDetail = "Automatic candle history load failed.",
        };
        loading.ApplySnapshot(new ChartSnapshot(
            2,
            pane.Symbol,
            pane.Interval,
            ChartDataState.Unavailable,
            at,
            at,
            "UNAVAILABLE",
            new DataLineage("Schwab CHART_EQUITY + price history", at, "Expected source."),
            [],
            failedQuality));

        Assert.False(loading.IsHistoryLoading);
        Assert.True(loading.HasHistoryLoadFailure);
        Assert.Equal("UNAVAILABLE  |  HISTORY LOAD FAILED", loading.ProviderStatusLabel);
        Assert.Equal("Candle history load failed", loading.EmptyStateText);
    }

    [Fact]
    public void ChartEvidenceLabelsWrapInsteadOfHidingOperationalDetail()
    {
        var document = XDocument.Load(Path.Combine(
            FindRepositoryRoot(),
            "src",
            "MomentumHunter.Desktop.Wpf",
            "MainWindow.xaml"));
        var requiredBindings = new[]
        {
            "{Binding ChartSourceLabel}",
            "{Binding PrimaryChart.TimingStatusLabel}",
            "{Binding PrimaryChart.IntegrityStatusLabel}",
            "{Binding PrimaryChart.ActiveBarSummary}",
        };

        foreach (var binding in requiredBindings)
        {
            var textBlock = Assert.Single(document
                .Descendants()
                .Where(element =>
                    element.Name.LocalName == "TextBlock" &&
                    (string?)element.Attribute("Text") == binding));

            Assert.Equal("Wrap", (string?)textBlock.Attribute("TextWrapping"));
            Assert.Null(textBlock.Attribute("TextTrimming"));
        }

        var badge = Assert.Single(document
            .Descendants()
            .Where(element =>
                element.Name.LocalName == "Border" &&
                (string?)element.Attribute("ToolTip") == "{Binding EvidenceDetail}"));
        Assert.Contains(
            badge.Descendants(),
            element => element.Name.LocalName == "Run"
                && (string?)element.Attribute("Text") == "{Binding EvidenceLabel}");
    }

    [Theory]
    [InlineData(ReadinessState.ReadyForSimulation, "READY")]
    [InlineData(ReadinessState.NeedsEvidence, "NEEDS DATA")]
    [InlineData(ReadinessState.StaleData, "STALE")]
    [InlineData(ReadinessState.Blocked, "BLOCKED")]
    public void CandidateBadgeUsesCompactReadinessWithoutReplacingSourceDetail(
        ReadinessState readiness,
        string expectedBadge)
    {
        var candidate = new CandidateSnapshot(
            "NVDA",
            "NVIDIA",
            218.50m,
            1.5m,
            1_000_000,
            1.2m,
            "Catalyst",
            readiness,
            "Stored evidence",
            DateTimeOffset.Parse("2026-08-05T14:35:00Z"),
            SourceReadinessLabel: "DO_NOT_TRADE_UNTRUSTED_EVIDENCE");

        Assert.Equal(expectedBadge, candidate.OperatorBadge);
        Assert.Equal("DO_NOT_TRADE_UNTRUSTED_EVIDENCE", candidate.OperatorState);
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

    private static string FindRepositoryRoot([CallerFilePath] string sourceFilePath = "") =>
        Path.GetFullPath(Path.Combine(Path.GetDirectoryName(sourceFilePath)!, "..", ".."));
}
