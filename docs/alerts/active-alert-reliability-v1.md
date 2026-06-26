# Active Alert Reliability v1

Active Alert Reliability v1 is a read-only report for checking whether Momentum Hunter's alert evidence chain is trustworthy enough for monitoring and later performance analysis.

It answers:

- Is the active monitor status current?
- Did the latest monitor cycle produce expected artifacts?
- Are alert IDs stable and duplicate-free?
- Are any alerts missing required evidence such as price or timestamp?
- Are pending, completed, and unscorable alerts separated?
- Did the alert outcome updater hand off results correctly?
- Does the SQLite alert mirror still match file-authoritative alert state?

## Command

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.active_alert_reliability
```

Outputs:

```text
MomentumHunterData\data\reports\active-alert-reliability-latest.json
MomentumHunterData\data\reports\active-alert-reliability-latest.md
```

## Inputs

- `MomentumHunterData/data/active-monitor-status.json`
- latest `MomentumHunterData/data/reports/active-monitor-cycle-*.json`
- `MomentumHunterData/data/opportunity-alerts.json`
- `MomentumHunterData/data/alert-outcome-update-status.json`
- `MomentumHunterData/data/reports/sqlite-validation-latest.json`

If the latest SQLite validation report is unavailable or unreadable, the report attempts a read-only SQLite validation build. It does not import rows, repair mirrors, or promote SQLite to source of truth.

## Checks

Active monitor:

- active monitor status exists
- active monitor is not failed
- latest cycle age is not stale
- latest cycle report is readable
- monitor warnings are surfaced

Alert store:

- duplicate alert IDs
- duplicate symbol/timestamp/type semantic keys
- alert IDs that do not match stable ID strategy
- missing or non-positive alert price
- invalid alert timestamps
- missing source report references
- missing source report files
- pending alerts
- unscorable alerts

Outcome handoff:

- alert outcome updater status exists
- completed, pending, and unscorable counts are visible
- outcome updater warnings are surfaced

SQLite mirror:

- overall SQLite validation status
- `opportunity_alerts` mirror check
- `alert_outcomes` mirror check

## Status Meaning

`READY` means no active reliability warnings were detected.

`WARNING` means the alert evidence chain can still be inspected, but some condition needs operator attention, such as a stale monitor cycle, pending alerts, unscorable alerts, or missing outcome status.

`FAILED` means evidence integrity is not trustworthy enough for alert performance analysis, usually because of duplicate alert IDs, invalid alert timestamps, failed active monitor status, or alert/outcome mirror mismatch.

## Safety Boundary

This report does not:

- generate alerts
- run the active monitor
- fetch market data
- change alert thresholds
- change readiness rules
- change scoring
- change outcome classification
- change trade-planning logic
- mutate raw captures
- mutate user-authored files
- make SQLite authoritative

It writes only derived report artifacts under `MomentumHunterData/data/reports`.

## Recommended Use

Run this after active monitor cycles and outcome updates. If it reports `STALE_ACTIVE_MONITOR_CYCLE`, run a fresh active monitor cycle before trusting current alert state. If it reports SQLite mirror mismatch, refresh the relevant safe SQLite import slice and rerun validation before using SQLite reports.
