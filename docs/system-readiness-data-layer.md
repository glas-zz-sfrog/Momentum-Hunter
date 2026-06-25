# System Readiness Data Layer

The system-readiness report answers: Can I trust Momentum Hunter right now?

Run:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.system_readiness
```

To refresh the supporting reports first:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.system_readiness --refresh-data-quality --refresh-autopilot
```

Outputs:

- `MomentumHunterData/data/reports/system-readiness-latest.json`
- `MomentumHunterData/data/reports/system-readiness-latest.md`

Sections:

- Market Data
- Scanner
- Captures
- Watchlist State
- Active Monitor
- Evidence Autopilot
- Outcome Tracking
- Research Data
- Storage Integrity
- Schedules
- Issues Requiring Attention

Each section is labeled `READY`, `WARNING`, `FAILED`, or `UNKNOWN` with facts and a recommended next action.

This report is a trust dashboard for the data layer. It does not place trades, alter signals, or modify raw captures.
