using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

public interface IPythonEngineHostConnection
{
    Task<PythonEngineHostSnapshot> EnsureConnectedAsync(CancellationToken cancellationToken = default);

    Task<PythonEngineHostSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default);

    Task<PythonEngineHostCommandResult> SendCommandAsync(
        string command,
        string commandId,
        CancellationToken cancellationToken = default);
}
