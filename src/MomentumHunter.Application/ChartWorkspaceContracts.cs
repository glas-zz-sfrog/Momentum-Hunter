using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

public enum ChartSourceMode
{
    Stored,
    StagedPreview,
}

/// <summary>
/// Supplies stored OHLC evidence for one symbol and interval. Implementations may
/// not fetch providers, synthesize bars, or expose planning or execution behavior.
/// </summary>
public interface IChartWorkspaceClient
{
    Task<ChartSnapshot> GetSnapshotAsync(
        string symbol,
        string interval,
        CancellationToken cancellationToken = default);

    Task<ChartSnapshot> GetStagedPreviewAsync(
        string symbol,
        string interval,
        CancellationToken cancellationToken = default) =>
        Task.FromException<ChartSnapshot>(
            new NotSupportedException("This chart workspace does not expose inactive staged previews."));
}
