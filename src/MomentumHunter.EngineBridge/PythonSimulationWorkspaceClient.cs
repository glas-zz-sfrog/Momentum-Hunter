using System.Globalization;
using System.Text.Json;
using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

/// <summary>
/// Maps the Python host's persisted-plan/FakeBroker simulation boundary. This client
/// has no provider, credential, Paper, or Live operation surface.
/// </summary>
public sealed class PythonSimulationWorkspaceClient : ISimulationWorkspaceClient
{
    private readonly IPythonEngineHostConnection _connection;

    public PythonSimulationWorkspaceClient(IPythonEngineHostConnection connection)
    {
        _connection = connection;
    }

    public async Task<SimulationWorkspaceSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
        PythonSimulationWorkspaceSnapshotMapper.Map(await _connection.GetSimulationWorkspaceSnapshotAsync(cancellationToken));

    public async Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default) =>
        PythonSimulationWorkspaceSnapshotMapper.MapResult(await _connection.RunSimulationAsync(symbol, cancellationToken));
}

public static class PythonSimulationWorkspaceSnapshotMapper
{
    private const string SimulationMode = "SIMULATION_ONLY_FAKE_BROKER";

    public static SimulationWorkspaceSnapshot Map(JsonElement root)
    {
        RequireSimulationMode(root);
        var observedAt = Timestamp(root, "observedAt", DateTimeOffset.UtcNow);
        var workspace = PythonReadOnlyWorkspaceSnapshotMapper.Map(Object(root, "workspace"));
        var candidatesBySymbol = workspace.Candidates.ToDictionary(candidate => candidate.Symbol, StringComparer.OrdinalIgnoreCase);
        var plans = Array(root, "plans").Select(item => TradePlan(item, candidatesBySymbol, observedAt)).ToArray();
        return new SimulationWorkspaceSnapshot(
            Integer(root, "schemaVersion") ?? 0,
            observedAt,
            String(root, "summary") ?? "Python simulation workspace snapshot.",
            workspace,
            plans,
            Boolean(root, "planningAvailable"));
    }

    public static SimulationResult MapResult(JsonElement root)
    {
        RequireSimulationMode(root);
        var symbol = String(root, "symbol") ?? string.Empty;
        var state = String(root, "state")?.Trim().ToUpperInvariant() switch
        {
            "COMPLETED" => SimulationResultState.Completed,
            "BLOCKED" => SimulationResultState.Blocked,
            _ => SimulationResultState.Unavailable,
        };
        var risk = RiskDecision(Object(root, "risk"));
        var audit = Object(root, "audit");
        var auditState = String(audit, "state") ?? "FAIL";
        return new SimulationResult(
            state,
            symbol,
            String(root, "summary") ?? "FakeBroker simulation did not return a summary.",
            risk,
            new ExecutionAuditSnapshot(
                $"python-simulation-{risk.State}-{symbol}",
                EnvironmentMode.Simulation,
                auditState,
                String(audit, "summary") ?? "Simulation audit detail was unavailable.",
                Timestamp(root, "observedAt", DateTimeOffset.UtcNow)));
    }

    private static TradePlanSnapshot TradePlan(
        JsonElement item,
        IReadOnlyDictionary<string, CandidateSnapshot> candidatesBySymbol,
        DateTimeOffset observedAt)
    {
        var symbol = String(item, "symbol") ?? string.Empty;
        candidatesBySymbol.TryGetValue(symbol, out var candidate);
        var risk = RiskDecision(Object(item, "risk"));
        var checks = Array(Object(item, "risk"), "gates")
            .Select(gate => new ReadinessCheck(
                String(gate, "name") ?? "Risk gate",
                !string.Equals(String(gate, "state"), "Blocked", StringComparison.OrdinalIgnoreCase),
                String(gate, "reason") ?? "No gate detail supplied."))
            .ToArray();
        var entry = Decimal(item, "entry") ?? 0m;
        var stop = Decimal(item, "stop") ?? 0m;
        var target = Decimal(item, "target") ?? 0m;
        return new TradePlanSnapshot(
            symbol,
            entry,
            stop,
            target,
            Decimal(item, "riskPerShare") ?? 0m,
            Integer(item, "simulatedQuantity") ?? 0,
            Decimal(item, "rewardToRisk") ?? 0m,
            Readiness(String(item, "sourceReadinessLabel")),
            checks,
            String(item, "primaryAction") ?? "Risk review required",
            candidate?.DataLineage ?? new DataLineage(
                "Persisted trade-planning report",
                observedAt,
                "No source-lineage candidate matched this persisted TradePlan."),
            [
                new TradeLevel("Entry", entry, entry > 0m ? "Persisted TradePlan entry." : "Entry unavailable in persisted TradePlan."),
                new TradeLevel("Stop", stop, stop > 0m ? "Persisted TradePlan stop." : "Stop unavailable in persisted TradePlan."),
                new TradeLevel("Target", target, target > 0m ? "Persisted TradePlan target." : "Target unavailable in persisted TradePlan."),
            ],
            risk);
    }

    private static RiskDecision RiskDecision(JsonElement item)
    {
        var reasons = Array(item, "reasons").Select(reason => reason.ValueKind == JsonValueKind.String ? reason.GetString() ?? string.Empty : string.Empty)
            .Where(reason => !string.IsNullOrWhiteSpace(reason))
            .ToArray();
        var allowed = Boolean(item, "allowsSimulation");
        var state = String(item, "status") ?? "Unavailable";
        var summary = reasons.Length > 0 ? string.Join(" | ", reasons) : allowed
            ? "Risk Governor permits FakeBroker simulation only."
            : "Risk Governor evidence is unavailable.";
        return new RiskDecision(allowed, state, summary, reasons);
    }

    private static void RequireSimulationMode(JsonElement root)
    {
        if (!string.Equals(String(root, "mode"), SimulationMode, StringComparison.Ordinal))
        {
            throw new InvalidDataException("The Python host payload is not the FakeBroker-only simulation workspace contract.");
        }
    }

    private static ReadinessState Readiness(string? label)
    {
        var normalized = label?.Trim().ToUpperInvariant() ?? string.Empty;
        if (normalized.StartsWith("EXECUTION_READY", StringComparison.Ordinal))
        {
            return ReadinessState.ReadyForSimulation;
        }
        if (normalized.Contains("PLANNING", StringComparison.Ordinal) || normalized.Contains("EVIDENCE", StringComparison.Ordinal))
        {
            return ReadinessState.NeedsEvidence;
        }
        if (normalized.Contains("DO_NOT_TRADE", StringComparison.Ordinal) || normalized.Contains("BLOCKED", StringComparison.Ordinal))
        {
            return ReadinessState.Blocked;
        }
        return ReadinessState.StaleData;
    }

    private static JsonElement Object(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value
            : default;

    private static IEnumerable<JsonElement> Array(JsonElement item, string name)
    {
        if (item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array)
        {
            return value.EnumerateArray().ToArray();
        }
        return [];
    }

    private static string? String(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int? Integer(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            return null;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String && int.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
            ? number
            : null;
    }

    private static decimal? Decimal(JsonElement item, string name)
    {
        if (!Property(item, name, out var value))
        {
            return null;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String && decimal.TryParse(value.GetString(), NumberStyles.Number, CultureInfo.InvariantCulture, out number)
            ? number
            : null;
    }

    private static bool Boolean(JsonElement item, string name) =>
        Property(item, name, out var value) && value.ValueKind == JsonValueKind.True;

    private static DateTimeOffset Timestamp(JsonElement item, string name, DateTimeOffset fallback) =>
        DateTimeOffset.TryParse(String(item, name), CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var value)
            ? value
            : fallback;

    private static bool Property(JsonElement item, string name, out JsonElement value)
    {
        value = default;
        return item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out value) && value.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined;
    }
}
