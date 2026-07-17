using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

/// <summary>
/// The only Phase 10 execution-facing boundary. Implementations may expose the
/// existing Python FakeBroker simulation path, never Paper or Live broker actions.
/// </summary>
public interface ISimulationWorkspaceClient
{
    Task<SimulationWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default);

    Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default);
}
