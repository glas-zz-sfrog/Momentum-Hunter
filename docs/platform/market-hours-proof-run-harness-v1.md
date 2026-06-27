# Market-Hours Proof Run Harness v1

Purpose: provide one bounded command that can later prove the market-hours evidence pipeline without changing scoring, readiness, alert thresholds, outcome classification, trade planning, raw captures, user-authored files, or SQLite authority.

## Default Mode

The default command is a dry run:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.market_hours_proof_harness
```

Dry-run mode writes:

```text
MomentumHunterData/data/reports/market-hours-proof-harness-latest.json
MomentumHunterData/data/reports/market-hours-proof-harness-latest.md
```

It lists every planned command and does not execute proof steps.

## Safe Backend Execution

To refresh safe derived backend reports while skipping live/delayed market-tape proof:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.market_hours_proof_harness --execute
```

Market-data-dependent steps are skipped as `SKIPPED_MARKET_HOURS_REQUIRED`.

## Market-Hours Execution

Only when live/delayed market data is expected to be available and Steven explicitly wants a proof run:

```powershell
.\.venv\Scripts\python.exe -B -m momentum_hunter.market_hours_proof_harness --execute --allow-live-market
```

This enables the active-monitor market-data step. It still uses existing monitor, evidence, outcome, SQLite, and readiness logic. It does not tune strategy or create trade recommendations.

## Proof Sequence

The harness coordinates:

- provider field quality
- active monitor cycle
- evidence autopilot
- alert outcome updater
- SQLite all-safe import
- SQLite validation
- SQLite shadow compare
- system readiness
- active alert reliability
- evidence autopilot reliability
- report index
- evidence census
- SQLite analytics
- operational reliability

## Stop Rules

If a step fails, inspect the generated report before rerunning. Do not use this harness to tune alert thresholds, readiness thresholds, scoring, or trade-planning rules.
