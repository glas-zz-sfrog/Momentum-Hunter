using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

/// <summary>
/// Supplies persisted, research-only technical-breakout evidence for one symbol.
/// Implementations may not regenerate reports, fetch providers, mutate evidence,
/// alter production signals, or expose planning or execution behavior.
/// </summary>
public interface ITechnicalResearchWorkspaceClient
{
    Task<TechnicalResearchSnapshot> GetSnapshotAsync(
        string symbol,
        CancellationToken cancellationToken = default);
}
