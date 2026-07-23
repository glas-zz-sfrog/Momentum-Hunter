using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

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
}
