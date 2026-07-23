using System.Text.Json;

namespace MomentumHunter.Contracts;

public static class PythonEngineHostProtocol
{
    public const string Version = "1.0";
    public const string GetHostSnapshot = "get_host_snapshot";
    public const string PauseCollection = "pause_collection";
    public const string ResumeCollection = "resume_collection";
    public const string RunCollectionCycle = "run_collection_cycle";
    public const string ShutdownHost = "shutdown_host";
    public const string GetReadOnlyWorkspaceSnapshot = "get_readonly_workspace_snapshot";
    public const string GetSimulationWorkspaceSnapshot = "get_simulation_workspace_snapshot";
    public const string GetChartSnapshot = "get_chart_snapshot";
    public const string RunSimulation = "run_simulation";
}

public sealed record PythonEngineHostIdentity(
    string ProtocolVersion,
    string HostInstanceId,
    int ProcessId,
    DateTimeOffset StartedAtUtc,
    string Transport);

public sealed record PythonEngineHostHealthSnapshot(
    string State,
    DateTimeOffset ObservedAtUtc,
    string Detail);

public sealed record PythonEngineCollectionSnapshot(
    string State,
    bool IsPaused,
    bool CycleInProgress,
    int CycleCount,
    int MonitoredSymbolCount,
    DateTimeOffset? LastCompletedCycleAtUtc,
    DateTimeOffset? NextScheduledCycleAtUtc,
    string Detail);

public sealed record PythonEngineHostSnapshot(
    int SchemaVersion,
    PythonEngineHostIdentity Identity,
    PythonEngineHostHealthSnapshot Health,
    PythonEngineCollectionSnapshot Collection,
    IReadOnlyList<string> Capabilities);

public sealed record PythonEngineHostCommandResult(
    bool Accepted,
    string Code,
    string Summary,
    PythonEngineHostSnapshot Snapshot,
    JsonElement? Payload = null);
