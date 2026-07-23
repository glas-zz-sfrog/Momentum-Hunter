using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

/// <summary>
/// Supplies already-persisted research-maturity evidence without rebuilding
/// outcomes, readiness gates, scores, alerts, plans, or broker state.
/// </summary>
public interface IResearchMaturityWorkspaceClient
{
    Task<ResearchMaturitySnapshot> GetSnapshotAsync(
        CancellationToken cancellationToken = default);
}
