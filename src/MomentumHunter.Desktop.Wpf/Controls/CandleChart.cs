using System.Collections;
using System.Collections.Specialized;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using MomentumHunter.Contracts;
using MomentumHunter.Presentation;

namespace MomentumHunter.Desktop.Wpf.Controls;

public sealed class CandleChart : FrameworkElement
{
    private const double PlotLeft = 10;
    private const double PlotTop = 10;
    private const double TimeAxisHeight = 28;
    private const double VolumeBandHeight = 30;

    public static readonly DependencyProperty CandlesProperty = DependencyProperty.Register(
        nameof(Candles),
        typeof(IEnumerable),
        typeof(CandleChart),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.AffectsRender, OnCandlesChanged));

    public static readonly DependencyProperty EmptyStateTextProperty = DependencyProperty.Register(
        nameof(EmptyStateText),
        typeof(string),
        typeof(CandleChart),
        new FrameworkPropertyMetadata("No deterministic candles available", FrameworkPropertyMetadataOptions.AffectsRender));

    public static readonly DependencyProperty IntervalProperty = DependencyProperty.Register(
        nameof(Interval),
        typeof(string),
        typeof(CandleChart),
        new FrameworkPropertyMetadata("5m", FrameworkPropertyMetadataOptions.AffectsRender));

    public static readonly DependencyProperty InspectedCandleProperty = DependencyProperty.Register(
        nameof(InspectedCandle),
        typeof(CandleSnapshot),
        typeof(CandleChart),
        new FrameworkPropertyMetadata(
            null,
            FrameworkPropertyMetadataOptions.AffectsRender |
            FrameworkPropertyMetadataOptions.BindsTwoWayByDefault));

    public CandleChart()
    {
        Cursor = Cursors.Cross;
    }

    public IEnumerable? Candles
    {
        get => (IEnumerable?)GetValue(CandlesProperty);
        set => SetValue(CandlesProperty, value);
    }

    public string EmptyStateText
    {
        get => (string)GetValue(EmptyStateTextProperty);
        set => SetValue(EmptyStateTextProperty, value);
    }

    public string Interval
    {
        get => (string)GetValue(IntervalProperty);
        set => SetValue(IntervalProperty, value);
    }

    public CandleSnapshot? InspectedCandle
    {
        get => (CandleSnapshot?)GetValue(InspectedCandleProperty);
        set => SetValue(InspectedCandleProperty, value);
    }

    private static void OnCandlesChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs args)
    {
        var chart = (CandleChart)dependencyObject;
        if (args.OldValue is INotifyCollectionChanged oldCollection)
        {
            oldCollection.CollectionChanged -= chart.OnCollectionChanged;
        }

        if (args.NewValue is INotifyCollectionChanged newCollection)
        {
            newCollection.CollectionChanged += chart.OnCollectionChanged;
        }

        chart.ClearInspection();
    }

    private void OnCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        ClearInspection();
        InvalidateVisual();
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        var allCandles = OrderedCandles();
        if (allCandles.Length == 0 || !TryGetPlotBounds(out var plotBounds))
        {
            ClearInspection();
            return;
        }

        var position = e.GetPosition(this);
        if (!plotBounds.Contains(position))
        {
            ClearInspection();
            return;
        }

        var normalizedPosition = (position.X - plotBounds.Left) / plotBounds.Width;
        var viewport = ChartViewportScale.Create(allCandles, plotBounds.Width);
        var candlePosition = viewport.ToCandleNormalizedPosition(normalizedPosition);
        if (candlePosition is null)
        {
            ClearInspection();
            return;
        }

        var inspection = ChartInspectionScale.SelectNearest(viewport.Candles, candlePosition.Value);
        SetCurrentValue(InspectedCandleProperty, inspection?.Candle);
    }

    protected override void OnMouseLeave(MouseEventArgs e)
    {
        base.OnMouseLeave(e);
        ClearInspection();
    }

    protected override void OnRender(DrawingContext drawingContext)
    {
        base.OnRender(drawingContext);
        var bounds = new Rect(0, 0, ActualWidth, ActualHeight);
        drawingContext.DrawRectangle(new SolidColorBrush(Color.FromRgb(16, 22, 29)), null, bounds);
        var allCandles = OrderedCandles();
        if (allCandles.Length == 0)
        {
            DrawEmptyState(drawingContext, bounds, EmptyStateText);
            return;
        }

        if (ActualWidth < 160 || ActualHeight < 110)
        {
            DrawEmptyState(drawingContext, bounds, "Chart pane is too small to render");
            return;
        }

        var priceAxisWidth = ActualWidth >= 500 ? 66d : 54d;
        var plotRight = ActualWidth - priceAxisWidth;
        var plotBottom = ActualHeight - TimeAxisHeight;
        var priceBottom = plotBottom - VolumeBandHeight - 4;
        var priceHeight = priceBottom - PlotTop;
        var plotWidth = plotRight - PlotLeft;
        var viewport = ChartViewportScale.Create(allCandles, plotWidth);
        var candles = viewport.Candles.ToArray();
        var axis = ChartAxisScale.Create(candles, Interval);
        var range = Math.Max(0.01m, axis.MaximumPrice - axis.MinimumPrice);
        var step = plotWidth / viewport.SlotCount;
        var bodyWidth = Math.Clamp(step * 0.62, 1.25, 7);
        var gridPen = new Pen(new SolidColorBrush(Color.FromRgb(45, 61, 74)), 1);
        var axisPen = new Pen(new SolidColorBrush(Color.FromRgb(69, 87, 101)), 1);
        var labelBrush = new SolidColorBrush(Color.FromRgb(153, 169, 183));

        foreach (var tick in axis.PriceTicks)
        {
            var y = PlotTop + priceHeight * tick.Position;
            drawingContext.DrawLine(gridPen, new Point(PlotLeft, y), new Point(plotRight, y));
            var text = CreateText(tick.Label, 10, labelBrush);
            drawingContext.DrawText(
                text,
                new Point(plotRight + 6, Math.Clamp(y - text.Height / 2, 0, ActualHeight - text.Height)));
        }

        var nextTimeLabelLeft = double.PositiveInfinity;
        foreach (var tick in axis.TimeTicks.Reverse())
        {
            var tickIndex = Array.FindIndex(candles, candle => candle.Timestamp == tick.Timestamp);
            if (tickIndex < 0)
            {
                continue;
            }

            var x = PlotLeft + plotWidth * viewport.CenterPosition(tickIndex);
            var text = CreateText(tick.Label, 10, labelBrush);
            var labelX = Math.Clamp(x - text.Width / 2, PlotLeft, plotRight - text.Width);
            if (labelX + text.Width + 8 > nextTimeLabelLeft)
            {
                continue;
            }

            drawingContext.DrawLine(gridPen, new Point(x, PlotTop), new Point(x, plotBottom));
            drawingContext.DrawText(text, new Point(labelX, plotBottom + 6));
            nextTimeLabelLeft = labelX;
        }

        drawingContext.DrawLine(axisPen, new Point(plotRight, PlotTop), new Point(plotRight, plotBottom));
        drawingContext.DrawLine(axisPen, new Point(PlotLeft, plotBottom), new Point(plotRight, plotBottom));
        drawingContext.DrawLine(axisPen, new Point(PlotLeft, priceBottom + 4), new Point(plotRight, priceBottom + 4));
        drawingContext.DrawText(CreateText("UTC", 9, labelBrush), new Point(plotRight + 6, plotBottom + 7));

        var maximumVolume = candles.Max(item => item.Volume);
        drawingContext.PushClip(new RectangleGeometry(new Rect(PlotLeft, PlotTop, plotWidth, plotBottom - PlotTop)));
        for (var index = 0; index < candles.Length; index++)
        {
            var candle = candles[index];
            var x = PlotLeft + plotWidth * viewport.CenterPosition(index);
            var highY = ToY(candle.High, axis.MinimumPrice, range, PlotTop, priceHeight);
            var lowY = ToY(candle.Low, axis.MinimumPrice, range, PlotTop, priceHeight);
            var openY = ToY(candle.Open, axis.MinimumPrice, range, PlotTop, priceHeight);
            var closeY = ToY(candle.Close, axis.MinimumPrice, range, PlotTop, priceHeight);
            var isUp = candle.Close >= candle.Open;
            var brush = new SolidColorBrush(isUp ? Color.FromRgb(74, 199, 182) : Color.FromRgb(221, 106, 106));
            var pen = new Pen(brush, 1);
            if (candle.IsInProgress)
            {
                pen.DashStyle = DashStyles.Dash;
            }
            if (candle.HasGapBefore)
            {
                var gapPen = new Pen(new SolidColorBrush(Color.FromArgb(190, 217, 164, 65)), 1)
                {
                    DashStyle = DashStyles.Dot,
                };
                drawingContext.DrawLine(
                    gapPen,
                    new Point(Math.Max(PlotLeft, x - step / 2), PlotTop),
                    new Point(Math.Max(PlotLeft, x - step / 2), plotBottom));
            }
            drawingContext.DrawLine(pen, new Point(x, highY), new Point(x, lowY));
            var body = new Rect(x - bodyWidth / 2, Math.Min(openY, closeY), bodyWidth, Math.Max(1.5, Math.Abs(closeY - openY)));
            drawingContext.DrawRectangle(candle.IsInProgress ? null : brush, pen, body);
            if (string.Equals(candle.State, "CORRECTED", StringComparison.Ordinal))
            {
                drawingContext.DrawRectangle(
                    null,
                    new Pen(new SolidColorBrush(Color.FromRgb(217, 164, 65)), 1.5),
                    body);
            }

            var volumeHeight = maximumVolume > 0
                ? Math.Max(1, (double)(candle.Volume / maximumVolume) * (VolumeBandHeight - 4))
                : 1;
            var volumeBrush = new SolidColorBrush(Color.FromArgb(100, isUp ? (byte)74 : (byte)221, isUp ? (byte)199 : (byte)106, isUp ? (byte)182 : (byte)106));
            drawingContext.DrawRectangle(volumeBrush, null, new Rect(x - bodyWidth / 2, plotBottom - volumeHeight, bodyWidth, volumeHeight));
        }

        var inspectedIndex = Array.FindIndex(candles, candle => candle == InspectedCandle);
        if (inspectedIndex >= 0)
        {
            var inspected = candles[inspectedIndex];
            var x = PlotLeft + plotWidth * viewport.CenterPosition(inspectedIndex);
            var closeY = ToY(inspected.Close, axis.MinimumPrice, range, PlotTop, priceHeight);
            var crosshairBrush = new SolidColorBrush(Color.FromArgb(210, 232, 186, 73));
            var crosshairPen = new Pen(crosshairBrush, 1)
            {
                DashStyle = DashStyles.Dash,
            };
            drawingContext.DrawLine(crosshairPen, new Point(x, PlotTop), new Point(x, plotBottom));
            drawingContext.DrawLine(crosshairPen, new Point(PlotLeft, closeY), new Point(plotRight, closeY));
            drawingContext.DrawEllipse(crosshairBrush, null, new Point(x, closeY), 2.5, 2.5);
        }

        drawingContext.Pop();
    }

    private CandleSnapshot[] OrderedCandles() =>
        Candles?
            .OfType<CandleSnapshot>()
            .OrderBy(candle => candle.Timestamp)
            .ToArray() ?? [];

    private bool TryGetPlotBounds(out Rect plotBounds)
    {
        var priceAxisWidth = ActualWidth >= 500 ? 66d : 54d;
        var plotRight = ActualWidth - priceAxisWidth;
        var plotBottom = ActualHeight - TimeAxisHeight;
        var plotWidth = plotRight - PlotLeft;
        var plotHeight = plotBottom - PlotTop;
        if (ActualWidth < 160 || ActualHeight < 110 || plotWidth <= 0 || plotHeight <= 0)
        {
            plotBounds = Rect.Empty;
            return false;
        }

        plotBounds = new Rect(PlotLeft, PlotTop, plotWidth, plotHeight);
        return true;
    }

    private void ClearInspection()
    {
        if (InspectedCandle is not null)
        {
            SetCurrentValue(InspectedCandleProperty, null);
        }
    }

    private static double ToY(decimal value, decimal min, decimal range, double top, double height) =>
        top + (double)(min + range - value) / (double)range * height;

    private static void DrawEmptyState(DrawingContext context, Rect bounds, string message)
    {
        var text = CreateText(
            string.IsNullOrWhiteSpace(message) ? "No deterministic candles available" : message,
            13,
            new SolidColorBrush(Color.FromRgb(153, 169, 183)));
        context.DrawText(text, new Point(Math.Max(12, (bounds.Width - text.Width) / 2), Math.Max(12, (bounds.Height - text.Height) / 2)));
    }

    private static FormattedText CreateText(string text, double size, Brush brush) =>
        new(
            text,
            System.Globalization.CultureInfo.InvariantCulture,
            FlowDirection.LeftToRight,
            new Typeface("Segoe UI"),
            size,
            brush,
            1);
}
