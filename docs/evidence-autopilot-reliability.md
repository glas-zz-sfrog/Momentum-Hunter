# Evidence Autopilot Reliability

The Evidence Autopilot reliability report summarizes the latest autopilot run and whether the evidence loop completed.

Run:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.evidence_autopilot_reliability
```

Outputs:

- `MomentumHunterData/data/reports/evidence-autopilot-latest.json`
- `MomentumHunterData/data/reports/evidence-autopilot-latest.md`

The report shows:

- latest run state and duration
- whether the latest evidence work is a background process, active monitor loop, or on-demand run
- what is known about behavior when the app is closed
- whether the monitor cycle completed
- whether the outcome updater completed
- whether evidence health and daily brief artifacts were generated
- targets checked
- alerts added, active alerts, tracked alerts
- completed, pending, and unscorable alert counts
- missing minute-bar and missing-outcome counts
- warnings and next recommended action

Evidence Autopilot remains a measurement and reliability tool. It does not change signal generation, scoring, readiness, ranking, or trade-planning rules.

Current limitation: a completed status file proves the last run completed; it does not prove Evidence Autopilot is continuously running in the background or that it survives app closure unless a separate scheduler or monitor loop is active and verified.
