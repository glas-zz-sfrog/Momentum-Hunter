using System.Collections;
using System.Collections.Specialized;
using System.Windows;
using System.Windows.Media;
using MomentumHunter.Contracts;

namespace MomentumHunter.Desktop.Wpf.Controls;

public sealed class CandleChart : FrameworkElement
{
    public static readonly DependencyProperty CandlesProperty = DependencyProperty.Register(
        nameof(Candles),
        typeof(IEnumerable),
        typeof(CandleChart),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.AffectsRender, OnCandlesChanged));

    public IEnumerable? Candles
    {
        get => (IEnumerable?)GetValue(CandlesProperty);
        set => SetValue(CandlesProperty, value);
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
        var candles = Candles?.OfType<CandleSnapshot>().ToArray() ?? [];
        if (candles.Length == 0 || ActualWidth < 40 || ActualHeight < 40)
        {
            DrawEmptyState(drawingContext, bounds);
            return;
        }

        var min = candles.Min(candle => candle.Low);
        var max = candles.Max(candle => candle.High);
        var range = Math.Max(0.01m, max - min);
        const double chartTop = 12;
        var chartHeight = Math.Max(40, ActualHeight - 52);
        var step = Math.Max(3, ActualWidth / candles.Length);
        var bodyWidth = Math.Max(2, step * 0.62);
        var gridPen = new Pen(new SolidColorBrush(Color.FromRgb(45, 61, 74)), 1);
        for (var gridIndex = 1; gridIndex < 5; gridIndex++)
        {
            var y = chartTop + chartHeight * gridIndex / 5;
            drawingContext.DrawLine(gridPen, new Point(0, y), new Point(ActualWidth, y));
        }

        var maximumVolume = candles.Max(item => item.Volume);
        for (var index = 0; index < candles.Length; index++)
        {
            var candle = candles[index];
            var x = index * step + step / 2;
            var highY = ToY(candle.High, min, range, chartTop, chartHeight);
            var lowY = ToY(candle.Low, min, range, chartTop, chartHeight);
            var openY = ToY(candle.Open, min, range, chartTop, chartHeight);
            var closeY = ToY(candle.Close, min, range, chartTop, chartHeight);
            var isUp = candle.Close >= candle.Open;
            var brush = new SolidColorBrush(isUp ? Color.FromRgb(74, 199, 182) : Color.FromRgb(221, 106, 106));
            var pen = new Pen(brush, 1);
            drawingContext.DrawLine(pen, new Point(x, highY), new Point(x, lowY));
            drawingContext.DrawRectangle(brush, null, new Rect(x - bodyWidth / 2, Math.Min(openY, closeY), bodyWidth, Math.Max(1.5, Math.Abs(closeY - openY))));

            var volumeHeight = Math.Max(1, candle.Volume / (double)maximumVolume * 24);
            var volumeBrush = new SolidColorBrush(Color.FromArgb(100, isUp ? (byte)74 : (byte)221, isUp ? (byte)199 : (byte)106, isUp ? (byte)182 : (byte)106));
            drawingContext.DrawRectangle(volumeBrush, null, new Rect(x - bodyWidth / 2, ActualHeight - volumeHeight - 4, bodyWidth, volumeHeight));
        }
    }

    private static double ToY(decimal value, decimal min, decimal range, double top, double height) =>
        top + (double)(min + range - value) / (double)range * height;

    private static void DrawEmptyState(DrawingContext context, Rect bounds)
    {
        var text = new FormattedText(
            "No deterministic candles available",
            System.Globalization.CultureInfo.InvariantCulture,
            FlowDirection.LeftToRight,
            new Typeface("Segoe UI"),
            13,
            new SolidColorBrush(Color.FromRgb(153, 169, 183)),
            1);
        context.DrawText(text, new Point(Math.Max(12, (bounds.Width - text.Width) / 2), Math.Max(12, (bounds.Height - text.Height) / 2)));
    }
}
