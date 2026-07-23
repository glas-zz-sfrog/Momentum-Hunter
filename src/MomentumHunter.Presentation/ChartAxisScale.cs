using System.Globalization;
using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record ChartPriceTick(decimal Value, string Label, double Position);

public sealed record ChartTimeTick(DateTimeOffset Timestamp, string Label, double Position);

public sealed record ChartAxisModel(
    decimal MinimumPrice,
    decimal MaximumPrice,
    IReadOnlyList<ChartPriceTick> PriceTicks,
    IReadOnlyList<ChartTimeTick> TimeTicks)
{
    public static ChartAxisModel Empty { get; } = new(0m, 1m, [], []);
}

public static class ChartAxisScale
{
    public static ChartAxisModel Create(
        IEnumerable<CandleSnapshot> candles,
        string interval,
        int priceTickTarget = 5,
        int timeTickTarget = 5)
    {
        ArgumentNullException.ThrowIfNull(candles);
        if (priceTickTarget < 2)
        {
            throw new ArgumentOutOfRangeException(nameof(priceTickTarget));
        }

        if (timeTickTarget < 2)
        {
            throw new ArgumentOutOfRangeException(nameof(timeTickTarget));
        }

        var ordered = candles.OrderBy(candle => candle.Timestamp).ToArray();
        if (ordered.Length == 0)
        {
            return ChartAxisModel.Empty;
        }

        var minimum = ordered.Min(candle => candle.Low);
        var maximum = ordered.Max(candle => candle.High);
        if (maximum <= minimum)
        {
            var expansion = Math.Max(0.01m, Math.Abs(minimum) * 0.005m);
            minimum -= expansion;
            maximum += expansion;
        }

        var step = NiceStep((maximum - minimum) / (priceTickTarget - 1));
        var axisMinimum = Math.Max(0m, decimal.Floor(minimum / step) * step);
        var axisMaximum = decimal.Ceiling(maximum / step) * step;
        if (axisMaximum <= axisMinimum)
        {
            axisMaximum = axisMinimum + step;
        }

        var priceTicks = BuildPriceTicks(axisMinimum, axisMaximum, step);
        var timeTicks = BuildTimeTicks(ordered, interval, timeTickTarget);
        return new ChartAxisModel(axisMinimum, axisMaximum, priceTicks, timeTicks);
    }

    private static decimal NiceStep(decimal rawStep)
    {
        if (rawStep <= 0m)
        {
            return 0.01m;
        }

        var exponent = Math.Clamp(Math.Floor(Math.Log10((double)rawStep)), -8, 8);
        var magnitude = (decimal)Math.Pow(10d, exponent);
        var normalized = rawStep / magnitude;
        var factor = normalized switch
        {
            <= 1m => 1m,
            <= 2m => 2m,
            <= 5m => 5m,
            _ => 10m,
        };
        return factor * magnitude;
    }

    private static IReadOnlyList<ChartPriceTick> BuildPriceTicks(
        decimal minimum,
        decimal maximum,
        decimal step)
    {
        var ticks = new List<ChartPriceTick>();
        var range = maximum - minimum;
        var decimals = PriceLabelDecimals(step);
        for (var value = minimum; value <= maximum + step / 2m && ticks.Count < 20; value += step)
        {
            var position = (double)((maximum - value) / range);
            ticks.Add(new ChartPriceTick(
                value,
                value.ToString($"N{decimals}", CultureInfo.InvariantCulture),
                Math.Clamp(position, 0d, 1d)));
        }

        return ticks;
    }

    private static int PriceLabelDecimals(decimal step)
    {
        if (step >= 1m)
        {
            return 2;
        }

        var decimals = (int)Math.Ceiling(-Math.Log10((double)step));
        return Math.Clamp(Math.Max(2, decimals), 2, 6);
    }

    private static IReadOnlyList<ChartTimeTick> BuildTimeTicks(
        IReadOnlyList<CandleSnapshot> candles,
        string interval,
        int target)
    {
        var count = Math.Min(target, candles.Count);
        var indexes = new SortedSet<int>();
        if (count == 1)
        {
            indexes.Add(0);
        }
        else
        {
            for (var tick = 0; tick < count; tick++)
            {
                indexes.Add((int)Math.Round(
                    tick * (candles.Count - 1d) / (count - 1d),
                    MidpointRounding.AwayFromZero));
            }
        }

        var daily = string.Equals(interval, "Daily", StringComparison.OrdinalIgnoreCase);
        var crossesDate = candles[0].Timestamp.UtcDateTime.Date != candles[^1].Timestamp.UtcDateTime.Date;
        var crossesYear = candles[0].Timestamp.UtcDateTime.Year != candles[^1].Timestamp.UtcDateTime.Year;
        var ticks = new List<ChartTimeTick>(indexes.Count);
        foreach (var index in indexes)
        {
            var timestamp = candles[index].Timestamp;
            var format = daily
                ? crossesYear ? "yyyy MMM d" : "MMM d"
                : crossesDate ? "MMM d HH:mm" : "HH:mm";
            ticks.Add(new ChartTimeTick(
                timestamp,
                timestamp.UtcDateTime.ToString(format, CultureInfo.InvariantCulture),
                (index + 0.5d) / candles.Count));
        }

        return ticks;
    }
}
