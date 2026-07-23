using System.Text.Json;
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

    Task<JsonElement> GetReadOnlyWorkspaceSnapshotAsync(CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(new NotSupportedException("This Python Engine Host connection does not expose read-only workspace snapshots."));

    Task<JsonElement> GetSimulationWorkspaceSnapshotAsync(CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(new NotSupportedException("This Python Engine Host connection does not expose simulation workspace snapshots."));

    Task<JsonElement> GetChartSnapshotAsync(
        string symbol,
        string interval,
        CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(new NotSupportedException("This Python Engine Host connection does not expose read-only chart snapshots."));

    Task<JsonElement> GetTechnicalResearchSnapshotAsync(
        string symbol,
        CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(new NotSupportedException("This Python Engine Host connection does not expose read-only technical research snapshots."));

    Task<JsonElement> GetSavedWatchlistSnapshotAsync(CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(new NotSupportedException("This Python Engine Host connection does not expose saved-watchlist snapshots."));

    Task<JsonElement> GetDailyWorkflowSnapshotAsync(CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(new NotSupportedException("This Python Engine Host connection does not expose read-only Daily Workflow snapshots."));

    Task<JsonElement> GetCandidateStorySnapshotAsync(
        string symbol,
        CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(new NotSupportedException("This Python Engine Host connection does not expose read-only Candidate Story snapshots."));

    Task<JsonElement> GetResearchMaturitySnapshotAsync(
        CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(
            new NotSupportedException(
                "This Python Engine Host connection does not expose read-only research-maturity snapshots."));

    Task<JsonElement> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default) =>
        Task.FromException<JsonElement>(new NotSupportedException("This Python Engine Host connection does not expose FakeBroker simulation commands."));
}
