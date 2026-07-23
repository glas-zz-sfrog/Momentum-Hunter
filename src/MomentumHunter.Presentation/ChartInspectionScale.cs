using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record ChartInspection(
    CandleSnapshot Candle,
    int Index,
    double Position);

public static class ChartInspectionScale
{
    public static ChartInspection? SelectNearest(
        IEnumerable<CandleSnapshot> candles,
        double normalizedPosition)
    {
        ArgumentNullException.ThrowIfNull(candles);

        if (!double.IsFinite(normalizedPosition) ||
            normalizedPosition < 0d ||
            normalizedPosition > 1d)
        {
            return null;
        }

        var ordered = candles
            .OrderBy(candle => candle.Timestamp)
            .ToArray();
        if (ordered.Length == 0)
        {
            return null;
        }

        var index = Math.Min(
            (int)Math.Floor(normalizedPosition * ordered.Length),
            ordered.Length - 1);
        return new ChartInspection(
            ordered[index],
            index,
            (index + 0.5d) / ordered.Length);
    }
}
