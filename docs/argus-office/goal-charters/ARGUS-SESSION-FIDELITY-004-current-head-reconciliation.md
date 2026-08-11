# ARGUS-SESSION-FIDELITY-004 Goal Charter

## Goal

Reconcile the proven read-only SESSION-FIDELITY-001 through 003 observer and
premarket-retry tooling onto the current canonical codebase without changing
the frozen August 12 retry tasks or any production runtime path.

## Operator Value

Momentum Hunter retains the exact code that explains and can reproduce the
session-fidelity evidence program. The Roadmap tells the truth that the August
11 A/B/C jobs captured valid Schwab evidence but failed to finalize their
Alpaca comparison, and that a prospective Alpaca-only retry is already frozen
for August 12.

## In Scope

- Restore the exact observer, runner, installer, and focused-test artifacts
  from source head `799f07b` onto current base `a46d31b`.
- Preserve the original August 11 evidence and the immutable August 12 retry
  identity.
- Prove that the reconciled code remains read-only, nonpersisting with respect
  to production stores, and disconnected from account, position, order,
  Shadow, service, Engine Host, WPF, and strategy authority.
- Reconcile Roadmap, task, branch, risk, and release records from observed Git,
  Task Scheduler, and write-once evidence.

## Out Of Scope

- Contacting Schwab or Alpaca.
- Querying account, position, preview, or order state.
- Launching, replacing, rescheduling, or repairing the frozen retry tasks.
- Changing production service, scheduler, candle stores, Shadow, scoring,
  readiness, TradePlan, allocation, broker, credential, or UI behavior.
- Interpreting the August 12 result before it exists.

## Acceptance Evidence

- Restored source artifacts are byte-identical to `799f07b`.
- Compileall and focused observer/retry tests pass on current head.
- Adjacent market-data and broader bounded regression tests pass.
- Static scans find no production-runtime import, credential material, live
  endpoint, account, position, preview, order, or transmission capability.
- The August 12 tasks remain Ready at 03:05, 05:55, and 06:05 Central and
  continue to reference clean frozen head `799f07b`.
- Git diff and protected-path review show only the intended dormant observer,
  tests, tools, and governance records.

## Completion Rule

Branch-only work is `IMPLEMENTED_PENDING_INTEGRATION`. It becomes `COMPLETE`
only after clean fast-forward integration, non-force backup, exact-head
opening/Paper schedule repin, and a clean synchronized canonical worktree.
The external August 12 retry remains separately
`PENDING_MARKET_SESSION_EVIDENCE` until its persisted result is audited.
