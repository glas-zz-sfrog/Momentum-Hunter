# ARGUS-ROADMAP-002 Goal Charter - Current-Master Reconciliation

## Goal

Reconcile the validated continuous-intraday architecture from divergent source
branch `bae053b` onto current canonical base `1d0ca95` without importing stale
Roadmap/governance state or changing runtime behavior.

## Operator Outcome

Steven and future builders have one preserved architecture package that states
what is already canonical, what is validated but unmerged, what remains Ready
or gated, and which provider/execution boundaries still apply.

## Source Evidence

- Source branch: `codex/ARGUS-ROADMAP-002-continuous-intraday-awareness`
- Source implementation: `013cafd`
- Source closeout: `bae053b`
- Merge base with current master: `0bd8a18`
- Divergence at preflight: current master 25 commits ahead; source branch two
  commits ahead
- Source artifacts and SHA-256 values are frozen in
  [CONTINUOUS_INTRADAY_MARKET_AWARENESS.md](../architecture/CONTINUOUS_INTRADAY_MARKET_AWARENESS.md)

## Scope

- Preserve and update the continuous-intraday architecture.
- Preserve R031B's historical task contract and terminal adjudication.
- Replace the source branch's obsolete linear sequence with a current-state
  dependency and integration contract.
- Add narrow branch/task/release evidence for this reconciliation.
- Update the separate authoritative Roadmap branch after this feature branch is
  proven; do not import that Roadmap into this branch.

## Non-Goals

- No application code or test change.
- No scoring, ranking, readiness, RVOL, setup, TradePlan, Risk Governor,
  allocation, FakeBroker, Shadow, Paper, live broker, account, credential,
  provider, service, scheduler, Engine Host, WPF, package, schema, capture, or
  generated-data change.
- No merge into `master`, installation, service refresh, job repin, provider
  call, account call, or order action.
- No copying of the source branch's stale `ROADMAP.md`, `GOALS.md`, decisions,
  risks, task log, changelog, or branch ledger wholesale.

## Acceptance Criteria

- [x] All three architecture/task-contract artifacts exist on a fresh branch
  from current master.
- [x] The five original source artifact hashes are recorded exactly.
- [x] R031B is identified as historical `COMPLETE` rather than pending work.
- [x] Canonical R032/R032B/R032C/R033 and DATA-002 through DATA-005A completion
  is stated truthfully.
- [x] MONITOR/REGIME/EVENT/CATALYST are identified as validated, dormant,
  unmerged work with exact heads.
- [x] BREAKOUT-001 remains research-only and Ready.
- [x] Alpaca Paper, FakeBroker, Schwab market data, and live-order boundaries
  are distinct.
- [x] Every local Markdown reference resolves or is explicitly external.
- [x] Contradiction, stale-status, protected-path, secret, and diff checks pass.
- [x] Canonical master, service manifest, and installed runtime remain unchanged.
- [x] Feature branch is committed and backed up without merge.

## Evidence Depth

- Inspect source commit ancestry and exact changed paths.
- Hash every original unique artifact before adaptation.
- Compare current implementation truth against canonical Git, task log,
  changelog, and canonical-code-path records.
- Scan the reconciliation diff for stale source statuses and unsupported claims.
- Recheck canonical Git/service identity after all branch-local work.

## Classification

`IMPLEMENTED_PENDING_INTEGRATION` after proof and feature-branch backup.
Scheduled-runtime pinning prevents canonical merge but does not invalidate the
artifacts. The separate authoritative Roadmap branch records scheduling truth.
