using MomentumHunter.Contracts;

namespace MomentumHunter.Application;

public interface IEngineClient
{
    Task<IReadOnlyList<CandidateSnapshot>> GetCandidatesAsync(CancellationToken cancellationToken = default);

    Task<IReadOnlyList<CandleSnapshot>> GetCandlesAsync(
        string symbol,
        string interval,
        CancellationToken cancellationToken = default);

    Task<TradePlanSnapshot> GetTradePlanAsync(string symbol, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<ActivityEvent>> GetActivityAsync(CancellationToken cancellationToken = default);

    Task<SystemHealthSnapshot> GetSystemHealthAsync(CancellationToken cancellationToken = default);

    Task<ReplaySnapshot> GetReplaySessionAsync(CancellationToken cancellationToken = default);

    Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default);

    Task<TradePlanSnapshot> ResolveMissingDataAsync(string symbol, CancellationToken cancellationToken = default);
}

public interface IWorkspaceLayoutStore
{
    Task SaveAsync(WorkspaceLayoutSnapshot snapshot, CancellationToken cancellationToken = default);

    Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(
        WorkspaceKind workspace,
        CancellationToken cancellationToken = default);

    Task<WorkspaceLayoutSnapshot?> LoadLatestValidAsync(CancellationToken cancellationToken = default);

    Task<IReadOnlyList<WorkspaceLayoutSnapshot>> ListAsync(
        WorkspaceKind workspace,
        CancellationToken cancellationToken = default);

    Task<WorkspaceLayoutSnapshot?> LoadNamedAsync(
        WorkspaceKind workspace,
        string name,
        CancellationToken cancellationToken = default);
}
