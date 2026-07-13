using MomentumHunter.Application;
using MomentumHunter.Contracts;

namespace MomentumHunter.EngineBridge;

/// <summary>
/// Deterministic local data for the workstation shell spike. It is intentionally
/// provider-neutral and has no network, credential, broker, or order path.
/// </summary>
public sealed class MockEngineClient : IEngineClient
{
    private static readonly DateTimeOffset SnapshotTime = new(2026, 7, 13, 14, 30, 0, TimeSpan.Zero);

    private static readonly IReadOnlyList<CandidateSnapshot> Candidates =
    [
        Candidate("NVDA", "NVIDIA Corporation", 176.42m, 3.18m, 84700112, 2.4m, "Semiconductor leadership", ReadinessState.ReadyForSimulation, "Fresh evidence", 96, "Highly liquid"),
        Candidate("CRWD", "CrowdStrike Holdings", 488.13m, 2.06m, 6330941, 1.8m, "Enterprise security strength", ReadinessState.NeedsEvidence, "Catalyst source needs review", 89, "Liquid"),
        Candidate("PLTR", "Palantir Technologies", 151.81m, 4.52m, 72511683, 2.9m, "Data-platform expansion", ReadinessState.ReadyForSimulation, "Fresh evidence", 94, "Highly liquid"),
        Candidate("AMD", "Advanced Micro Devices", 162.58m, 1.73m, 51002139, 1.5m, "AI infrastructure demand", ReadinessState.StaleData, "Daily context is aging", 83, "Highly liquid"),
        Candidate("MSTR", "Strategy Incorporated", 382.45m, 2.41m, 297551, 1.2m, "Digital asset proxy demand", ReadinessState.Blocked, "Risk evidence incomplete", 71, "Thin relative liquidity"),
    ];

    private static CandidateSnapshot Candidate(
        string symbol,
        string company,
        decimal lastPrice,
        decimal changePercent,
        long volume,
        decimal relativeVolume,
        string catalyst,
        ReadinessState readiness,
        string quality,
        int score,
        string liquidity) => new(
        symbol,
        company,
        lastPrice,
        changePercent,
        volume,
        relativeVolume,
        catalyst,
        readiness,
        quality,
        SnapshotTime,
        score,
        liquidity,
        new CatalystSummary(catalyst, "Deterministic local fixture", SnapshotTime),
        new DataLineage("Mock engine fixture", SnapshotTime, "Deterministic local fixture; research display only."));

    public Task<IReadOnlyList<CandidateSnapshot>> GetCandidatesAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(Candidates);

    public Task<IReadOnlyList<CandleSnapshot>> GetCandlesAsync(
        string symbol,
        string interval,
        CancellationToken cancellationToken = default)
    {
        var anchor = Candidates.FirstOrDefault(candidate => candidate.Symbol == symbol)?.LastPrice ?? 100m;
        var minutes = interval == "1m" ? 1 : interval == "5m" ? 5 : interval == "15m" ? 15 : interval == "Daily" ? 1_440 : 60;
        var candles = Enumerable.Range(0, 60)
            .Select(index =>
            {
                var wobble = (decimal)((index % 7) - 3) * 0.18m;
                var trend = index * 0.035m;
                var open = anchor - 2.1m + trend + wobble;
                var close = open + (index % 3 == 0 ? 0.29m : -0.08m);
                return new CandleSnapshot(
                    SnapshotTime.AddMinutes((index - 59) * minutes),
                    open,
                    Math.Max(open, close) + 0.24m,
                    Math.Min(open, close) - 0.19m,
                    close,
                    750000 + index * 12350L);
            })
            .ToArray();
        return Task.FromResult<IReadOnlyList<CandleSnapshot>>(candles);
    }

    public Task<TradePlanSnapshot> GetTradePlanAsync(string symbol, CancellationToken cancellationToken = default)
    {
        var candidate = Candidates.FirstOrDefault(item => item.Symbol == symbol) ?? Candidates[0];
        var entry = candidate.LastPrice;
        var blocked = candidate.Readiness is ReadinessState.Blocked or ReadinessState.StaleData or ReadinessState.NeedsEvidence;
        var checks = new[]
        {
            new ReadinessCheck("Structured entry", true, "Entry uses the current research snapshot."),
            new ReadinessCheck("Protective stop", !blocked, blocked ? "Evidence is incomplete; stop confidence is unavailable." : "Stop is based on a defined invalidation level."),
            new ReadinessCheck("Data freshness", candidate.Readiness != ReadinessState.StaleData, candidate.QualityLabel),
            new ReadinessCheck("Simulation gate", candidate.Readiness == ReadinessState.ReadyForSimulation, "Simulation remains explicitly non-transmitting."),
        };
        var stop = entry - Math.Max(2m, entry * 0.018m);
        var target = entry + Math.Max(4m, entry * 0.036m);
        var plan = new TradePlanSnapshot(
            candidate.Symbol,
            entry,
            stop,
            target,
            entry - stop,
            50,
            Math.Round((target - entry) / (entry - stop), 2),
            candidate.Readiness,
            checks,
            blocked ? "Refresh evidence before simulation" : "Review plan in simulation",
            candidate.DataLineage ?? new DataLineage("Mock engine fixture", SnapshotTime, "Deterministic local fixture; research display only."),
            [
                new TradeLevel("Entry", entry, "Research display level"),
                new TradeLevel("Stop", stop, "Defined invalidation level"),
                new TradeLevel("Target", target, "Research objective level"),
            ],
            new RiskDecision(!blocked, blocked ? "Blocked" : "Ready", blocked ? "Evidence must be repaired before this plan can enter a simulation review." : "Plan has a complete mock evidence chain for review.", checks.Where(check => !check.Passed).Select(check => check.Detail).ToArray()));
        return Task.FromResult(plan);
    }

    public Task<IReadOnlyList<ActivityEvent>> GetActivityAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyList<ActivityEvent>>(
        [
            new(SnapshotTime, "Research", "Candidate state refreshed from deterministic shell data.", "NVDA", HealthState.Healthy),
            new(SnapshotTime.AddMinutes(-4), "Readiness", "CRWD requires a catalyst-source review.", "CRWD", HealthState.Degraded),
            new(SnapshotTime.AddMinutes(-11), "Simulation", "No broker path is configured in this workstation spike.", string.Empty, HealthState.Healthy),
        ]);

    public Task<SystemHealthSnapshot> GetSystemHealthAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(new SystemHealthSnapshot(
        [
            new("Engine bridge", HealthState.Healthy, "Deterministic local fixture", SnapshotTime),
            new("Research evidence", HealthState.Degraded, "One candidate needs source review", SnapshotTime),
            new("Broker connectivity", HealthState.Unavailable, "Not configured by design", SnapshotTime),
        ], SnapshotTime));

    public Task<ReplaySnapshot> GetReplaySessionAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(new ReplaySnapshot(
            "mock-replay-20260713-1430",
            SnapshotTime.AddDays(-1),
            "NVDA",
            "5m",
            "Deterministic historical fixture; replay cannot alter current research."));

    public async Task<SimulationResult> RunSimulationAsync(string symbol, CancellationToken cancellationToken = default)
    {
        var plan = await GetTradePlanAsync(symbol, cancellationToken);
        var risk = plan.RiskDecision ?? new RiskDecision(false, "Blocked", "Risk evidence is unavailable.", ["Missing risk decision."]);
        return new SimulationResult(
            risk.Allowed ? SimulationResultState.Completed : SimulationResultState.Blocked,
            plan.Symbol,
            risk.Allowed ? "Simulation review recorded with deterministic local data." : "Simulation review was blocked by the readiness gate.",
            risk,
            new ExecutionAuditSnapshot(
                $"mock-audit-{plan.Symbol.ToLowerInvariant()}",
                EnvironmentMode.Simulation,
                risk.Allowed ? "Recorded" : "Blocked",
                "Local fixture only; no broker, provider, credential, or order path is present.",
                SnapshotTime));
    }

    public async Task<TradePlanSnapshot> ResolveMissingDataAsync(string symbol, CancellationToken cancellationToken = default)
    {
        var plan = await GetTradePlanAsync(symbol, cancellationToken);
        return plan with
        {
            PrimaryAction = "Evidence repair unavailable",
            RiskDecision = (plan.RiskDecision ?? new RiskDecision(false, "Blocked", "Risk evidence unavailable.", []) ) with
            {
                Summary = "The shell requested a repair, but this deterministic fixture does not mutate evidence or fetch providers.",
            },
        };
    }
}
