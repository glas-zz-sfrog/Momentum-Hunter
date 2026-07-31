using MomentumHunter.Contracts;

namespace MomentumHunter.Presentation;

public sealed record OpenPositionView(
    string ShadowTradeId,
    string Symbol,
    string Side,
    int Quantity,
    decimal AverageFill,
    decimal? ExecutableMark,
    decimal? MarketValue,
    decimal? UnrealizedPnl,
    decimal? UnrealizedPercent,
    decimal? UnrealizedR,
    decimal? Stop,
    decimal? NextTarget,
    string State,
    string QuoteProvider,
    decimal? QuoteAgeSeconds,
    string PnlState)
{
    private static readonly HashSet<string> OpenStates =
    [
        "AHEAD",
        "BEHIND",
        "FLAT",
        "STALE",
        "HALTED",
        "EXIT_PENDING",
    ];

    public string QuantityDisplay => Quantity.ToString("N0");
    public string AverageFillDisplay => AverageFill.ToString("C4");
    public string ExecutableMarkDisplay => ExecutableMark?.ToString("C4") ?? "Unavailable";
    public string MarketValueDisplay => MarketValue?.ToString("C2") ?? "Unavailable";
    public string UnrealizedPnlDisplay => UnrealizedPnl?.ToString("C2") ?? "Unavailable";
    public string UnrealizedPercentDisplay => UnrealizedPercent is null ? "Unavailable" : $"{UnrealizedPercent:N2}%";
    public string UnrealizedRDisplay => UnrealizedR is null ? "Unavailable" : $"{UnrealizedR:N2} R";
    public string StopDisplay => Stop?.ToString("C4") ?? "Unavailable";
    public string NextTargetDisplay => NextTarget?.ToString("C4") ?? "Unavailable";
    public string QuoteAgeDisplay => QuoteAgeSeconds is null ? "Unavailable" : $"{QuoteAgeSeconds:N1}s";

    public static OpenPositionView? From(ShadowTradeReviewSnapshot trade)
    {
        ArgumentNullException.ThrowIfNull(trade);
        var mark = trade.ActiveMark;
        if (mark.Quantity <= 0
            || mark.SimulatedFill is not { } fill
            || !OpenStates.Contains(mark.DisplayState))
        {
            return null;
        }

        var side = string.Equals(mark.Direction, "SHORT", StringComparison.OrdinalIgnoreCase)
            ? "SHORT"
            : "LONG";
        var basis = Math.Abs(fill * mark.Quantity);
        decimal? unrealizedPercent = mark.UnrealizedPnl is { } pnl && basis > 0m
            ? pnl / basis * 100m
            : null;
        var nextTarget = FindNextTarget(mark.Targets, mark.CurrentExecutableMark ?? fill, side);
        var pnlState = mark.UnrealizedPnl switch
        {
            > 0m => "POSITIVE",
            < 0m => "NEGATIVE",
            0m => "FLAT",
            _ => "UNAVAILABLE",
        };

        return new OpenPositionView(
            trade.ShadowTradeId,
            trade.Symbol,
            side,
            mark.Quantity,
            fill,
            mark.CurrentExecutableMark,
            mark.CurrentExecutableMark is { } executableMark
                ? Math.Abs(executableMark * mark.Quantity)
                : null,
            mark.UnrealizedPnl,
            unrealizedPercent,
            mark.UnrealizedR,
            mark.Stop,
            nextTarget,
            mark.DisplayState,
            mark.QuoteProvider,
            mark.QuoteAgeSeconds,
            pnlState);
    }

    private static decimal? FindNextTarget(IReadOnlyList<decimal> targets, decimal mark, string side)
    {
        var nextTarget = side == "SHORT"
            ? targets.Where(target => target < mark).OrderByDescending(target => target).FirstOrDefault()
            : targets.Where(target => target > mark).Order().FirstOrDefault();
        return nextTarget > 0m ? nextTarget : null;
    }
}
