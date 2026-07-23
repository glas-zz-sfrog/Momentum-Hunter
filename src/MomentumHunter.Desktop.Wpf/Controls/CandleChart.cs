using System.Collections;
using System.Collections.Specialized;
using System.Windows;
using System.Windows.Media;
using MomentumHunter.Contracts;
using MomentumHunter.Presentation;

namespace MomentumHunter.Desktop.Wpf.Controls;

public sealed class CandleChart : FrameworkElement
{
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
    }

    private void OnCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e) => InvalidateVisual();

    protected override void OnRender(DrawingContext drawingContext)
    {
        base.OnRender(drawingContext);
        var bounds = new Rect(0, 0, ActualWidth, ActualHeight);
        drawingContext.DrawRectangle(new SolidColorBrush(Color.FromRgb(16, 22, 29)), null, bounds);
        var candles = Candles?
            .OfType<CandleSnapshot>()
            .OrderBy(candle => candle.Timestamp)
            .ToArray() ?? [];
        if (candles.Length == 0)
        {
            DrawEmptyState(drawingContext, bounds, EmptyStateText);
            return;
        }

        if (ActualWidth < 160 || ActualHeight < 110)
        {
            DrawEmptyState(drawingContext, bounds, "Chart pane is too small to render");
            return;
        }

        var axis = ChartAxisScale.Create(candles, Interval);
        const double plotLeft = 10;
        const double plotTop = 10;
        var priceAxisWidth = ActualWidth >= 500 ? 66d : 54d;
        const double timeAxisHeight = 28;
        const double volumeBandHeight = 30;
        var plotRight = ActualWidth - priceAxisWidth;
        var plotBottom = ActualHeight - timeAxisHeight;
        var priceBottom = plotBottom - volumeBandHeight - 4;
        var priceHeight = priceBottom - plotTop;
        var plotWidth = plotRight - plotLeft;
        var range = Math.Max(0.01m, axis.MaximumPrice - axis.MinimumPrice);
        var step = plotWidth / candles.Length;
        var bodyWidth = Math.Clamp(step * 0.62, 1.5, 12);
        var gridPen = new Pen(new SolidColorBrush(Color.FromRgb(45, 61, 74)), 1);
        var axisPen = new Pen(new SolidColorBrush(Color.FromRgb(69, 87, 101)), 1);
        var labelBrush = new SolidColorBrush(Color.FromRgb(153, 169, 183));

        foreach (var tick in axis.PriceTicks)
        {
            var y = plotTop + priceHeight * tick.Position;
            drawingContext.DrawLine(gridPen, new Point(plotLeft, y), new Point(plotRight, y));
            var text = CreateText(tick.Label, 10, labelBrush);
            drawingContext.DrawText(
                text,
                new Point(plotRight + 6, Math.Clamp(y - text.Height / 2, 0, ActualHeight - text.Height)));
        }

        foreach (var tick in axis.TimeTicks)
        {
            var x = plotLeft + plotWidth * tick.Position;
            drawingContext.DrawLine(gridPen, new Point(x, plotTop), new Point(x, plotBottom));
            var text = CreateText(tick.Label, 10, labelBrush);
            var labelX = Math.Clamp(x - text.Width / 2, plotLeft, plotRight - text.Width);
            drawingContext.DrawText(text, new Point(labelX, plotBottom + 6));
        }

        drawingContext.DrawLine(axisPen, new Point(plotRight, plotTop), new Point(plotRight, plotBottom));
        drawingContext.DrawLine(axisPen, new Point(plotLeft, plotBottom), new Point(plotRight, plotBottom));
        drawingContext.DrawLine(axisPen, new Point(plotLeft, priceBottom + 4), new Point(plotRight, priceBottom + 4));
        drawingContext.DrawText(CreateText("UTC", 9, labelBrush), new Point(plotRight + 6, plotBottom + 7));

        var maximumVolume = candles.Max(item => item.Volume);
        drawingContext.PushClip(new RectangleGeometry(new Rect(plotLeft, plotTop, plotWidth, plotBottom - plotTop)));
        for (var index = 0; index < candles.Length; index++)
        {
            var candle = candles[index];
            var x = plotLeft + index * step + step / 2;
            var highY = ToY(candle.High, axis.MinimumPrice, range, plotTop, priceHeight);
            var lowY = ToY(candle.Low, axis.MinimumPrice, range, plotTop, priceHeight);
            var openY = ToY(candle.Open, axis.MinimumPrice, range, plotTop, priceHeight);
            var closeY = ToY(candle.Close, axis.MinimumPrice, range, plotTop, priceHeight);
            var isUp = candle.Close >= candle.Open;
            var brush = new SolidColorBrush(isUp ? Color.FromRgb(74, 199, 182) : Color.FromRgb(221, 106, 106));
            var pen = new Pen(brush, 1);
            drawingContext.DrawLine(pen, new Point(x, highY), new Point(x, lowY));
            drawingContext.DrawRectangle(brush, null, new Rect(x - bodyWidth / 2, Math.Min(openY, closeY), bodyWidth, Math.Max(1.5, Math.Abs(closeY - openY))));

            var volumeHeight = maximumVolume > 0
                ? Math.Max(1, candle.Volume / (double)maximumVolume * (volumeBandHeight - 4))
                : 1;
            var volumeBrush = new SolidColorBrush(Color.FromArgb(100, isUp ? (byte)74 : (byte)221, isUp ? (byte)199 : (byte)106, isUp ? (byte)182 : (byte)106));
            drawingContext.DrawRectangle(volumeBrush, null, new Rect(x - bodyWidth / 2, plotBottom - volumeHeight, bodyWidth, volumeHeight));
        }
        drawingContext.Pop();
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
