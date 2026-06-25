# Autonomous Reliability Sprint v1

Momentum Hunter is in evidence-based learning mode. This sprint adds operator-facing reliability reports so Argus can answer whether the system is healthy enough to trust for review, monitoring, and evidence collection.

This sprint does not change scoring math, readiness thresholds, alert generation, trade-planning rules, scanner thresholds, broker behavior, or automated trading behavior.

## Added Report Layers

- Data Quality Audit: `python -m momentum_hunter.data_quality`
- Evidence Autopilot Reliability: `python -m momentum_hunter.evidence_autopilot_reliability`
- System Readiness: `python -m momentum_hunter.system_readiness`

These commands write latest reports under `MomentumHunterData/data/reports/`.

## Operator Questions Answered

- Can I trust live/monitor market data right now?
- Did Evidence Autopilot run and produce the expected artifacts?
- Are alerts completed, pending, or terminally unscorable?
- Are captures, watchlists, research stores, schedules, and storage metadata present?
- What should I fix before trusting Momentum Hunter today?

## Safety Contract

The reliability reports read existing stores and write derived reports only. They do not mutate raw captures or alter candidate scores, readiness states, alert thresholds, trade plans, or broker/order behavior.

## Validation Style

Use bounded, focused non-Qt tests first. Avoid broad Qt unittest modules during reliability work unless the specific change touches UI behavior.
