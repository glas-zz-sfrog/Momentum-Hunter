using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

/// <summary>
/// Supplies persisted Daily Workflow evidence without exposing review, watchlist,
/// provider, scoring, readiness, broker, Paper, or Live actions.
/// </summary>
public interface IDailyWorkflowWorkspaceClient
{
    Task<DailyWorkflowSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default);
}
