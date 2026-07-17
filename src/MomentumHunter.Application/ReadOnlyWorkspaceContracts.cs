using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

/// <summary>
/// Supplies persisted Python evidence to the workstation without exposing planning,
/// simulation, provider, broker, Paper, or Live commands.
/// </summary>
public interface IReadOnlyWorkspaceClient
{
    Task<ReadOnlyWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default);
}
