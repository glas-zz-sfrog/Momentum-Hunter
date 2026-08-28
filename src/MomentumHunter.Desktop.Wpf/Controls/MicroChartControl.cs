using System.Windows;
using System.Windows.Media;
using MomentumHunter.Presentation;

namespace MomentumHunter.Desktop.Wpf.Controls;

/// <summary>
/// Presentation-only renderer for bounded, already-persisted Command Center
/// history.  It performs no aggregation, interpolation, fetching, or ranking.
/// </summary>
public sealed class MicroChartControl : FrameworkElement
{
    public static readonly DependencyProperty SeriesProperty = DependencyProperty.Register(
        nameof(Series),
        typeof(DisplayMiniChartSeries),
        typeof(MicroChartControl),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.AffectsRender));

    public DisplayMiniChartSeries? Series
    {
        get => (DisplayMiniChartSeries?)GetValue(SeriesProperty);
        set => SetValue(SeriesProperty, value);
    }

    protected override void OnRender(DrawingContext drawingContext)
    {
        base.OnRender(drawingContext);
        var bounds = new Rect(0, 0, ActualWidth, ActualHeight);
        drawingContext.DrawRoundedRectangle(
            new SolidColorBrush(Color.FromRgb(8, 24, 37)),
            new Pen(new SolidColorBrush(Color.FromRgb(28, 56, 77)), 1),
            bounds,
            3,
            3);

        var points = Series?.Points;
        if (points is null || points.Count < 2 || ActualWidth < 8 || ActualHeight < 8)
        {
            var unavailable = new Pen(new SolidColorBrush(Color.FromRgb(77, 98, 116)), 1)
            {
                DashStyle = DashStyles.Dash,
            };
            drawingContext.DrawLine(unavailable, new Point(5, ActualHeight / 2), new Point(Math.Max(5, ActualWidth - 5), ActualHeight / 2));
            return;
        }

        var minimum = points.Min(item => item.Close);
        var maximum = points.Max(item => item.Close);
        var range = maximum - minimum;
        var firstTimestamp = points[0].Timestamp;
        var lastTimestamp = points[^1].Timestamp;
        var timeRange = Math.Max(1d, (lastTimestamp - firstTimestamp).TotalSeconds);
        const double padding = 4d;
        var width = Math.Max(1d, ActualWidth - padding * 2);
        var height = Math.Max(1d, ActualHeight - padding * 2);

        Point Project(int index)
        {
            var item = points[index];
            var x = padding + (item.Timestamp - firstTimestamp).TotalSeconds / timeRange * width;
            var normalized = range == 0m ? 0.5d : (double)((item.Close - minimum) / range);
            return new Point(x, padding + (1d - normalized) * height);
        }

        var geometry = new StreamGeometry();
        using (var context = geometry.Open())
        {
            context.BeginFigure(Project(0), isFilled: false, isClosed: false);
            for (var index = 1; index < points.Count; index++)
            {
                context.LineTo(Project(index), isStroked: true, isSmoothJoin: true);
            }
        }
        geometry.Freeze();

        var lineColor = points[^1].Close.CompareTo(points[0].Close) switch
        {
            > 0 => Color.FromRgb(80, 220, 112),
            < 0 => Color.FromRgb(244, 88, 92),
            _ => Color.FromRgb(114, 168, 209),
        };
        drawingContext.DrawGeometry(null, new Pen(new SolidColorBrush(lineColor), 1.25), geometry);

        if (Series?.TransitionTimestamp is { } transition
            && transition >= firstTimestamp
            && transition <= lastTimestamp)
        {
            var transitionX = padding + (transition - firstTimestamp).TotalSeconds / timeRange * width;
            var marker = new Pen(new SolidColorBrush(Color.FromRgb(157, 173, 186)), 1)
            {
                DashStyle = DashStyles.Dot,
            };
            drawingContext.DrawLine(marker, new Point(transitionX, padding), new Point(transitionX, ActualHeight - padding));
        }
    }
}
