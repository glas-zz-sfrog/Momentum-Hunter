using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record ChartViewportModel(
    IReadOnlyList<CandleSnapshot> Candles,
    int SlotCount,
    int LeadingEmptySlotCount)
{
    public double CenterPosition(int candleIndex)
    {
        if (candleIndex < 0 || candleIndex >= Candles.Count)
        {
            throw new ArgumentOutOfRangeException(nameof(candleIndex));
        }

        return (LeadingEmptySlotCount + candleIndex + 0.5d) / SlotCount;
    }

    public double? ToCandleNormalizedPosition(double viewportPosition)
    {
        if (Candles.Count == 0 ||
            double.IsNaN(viewportPosition) ||
            viewportPosition < 0d ||
            viewportPosition > 1d)
        {
            return null;
        }

        var candleRegionStart = LeadingEmptySlotCount / (double)SlotCount;
        var candleRegionWidth = Candles.Count / (double)SlotCount;
        if (viewportPosition < candleRegionStart ||
            viewportPosition > candleRegionStart + candleRegionWidth)
        {
            return null;
        }

        return Math.Clamp((viewportPosition - candleRegionStart) / candleRegionWidth, 0d, 1d);
    }
}

public static class ChartViewportScale
{
    public const double TargetSlotWidth = 6d;
    public const int MinimumSlotCount = 80;
    public const int MaximumSlotCount = 300;

    public static ChartViewportModel Create(
        IEnumerable<CandleSnapshot> candles,
        double plotWidth)
    {
        ArgumentNullException.ThrowIfNull(candles);
        if (double.IsNaN(plotWidth) || double.IsInfinity(plotWidth) || plotWidth < 0d)
        {
            throw new ArgumentOutOfRangeException(nameof(plotWidth));
        }

        var slotCount = Math.Clamp(
            (int)Math.Floor(plotWidth / TargetSlotWidth),
            MinimumSlotCount,
            MaximumSlotCount);
        var ordered = candles
            .OrderBy(candle => candle.Timestamp)
            .TakeLast(slotCount)
            .ToArray();

        return new ChartViewportModel(
            ordered,
            slotCount,
            slotCount - ordered.Length);
    }
}
