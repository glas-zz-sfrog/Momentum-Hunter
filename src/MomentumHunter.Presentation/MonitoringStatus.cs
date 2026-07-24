using MomentumHunter.Application;

namespace MomentumHunter.Presentation;

public sealed record MonitoringStatusView(
    string StateLabel,
    string Summary,
    string SourceDetail,
    string MonitoredSymbolsLabel,
    string CompletedCyclesLabel,
    string LastCompletedLabel)
{
    public static MonitoringStatusView From(BackgroundCollectionStatus status)
    {
        var summary = BackgroundStatusText.Detail(status);
        var sourceDetail = string.IsNullOrWhiteSpace(status.Detail) ||
                           status.Detail.Trim().Equals(summary, StringComparison.Ordinal)
            ? string.Empty
            : status.Detail.Trim();

        return new MonitoringStatusView(
            status.State.ToString().ToUpperInvariant(),
            summary,
            sourceDetail,
            status.MonitoredSymbolCount == 1
                ? "1 monitored symbol"
                : $"{Math.Max(0, status.MonitoredSymbolCount)} monitored symbols",
            status.CycleCount == 1
                ? "1 completed cycle"
                : $"{Math.Max(0, status.CycleCount)} completed cycles",
            status.LastCompletedCycleAt is { } completed
                ? $"{completed.ToUniversalTime():yyyy-MM-dd HH:mm:ss} UTC"
                : "No completed scan recorded");
    }
}
