# Argus Machine Console Spec

## Goal
The Argus Machine Console is the operator-facing machine room for autonomous planning and supervision.

## Required Panels
- Machine Status Bar.
- Candidate Queue.
- Top 5 Trade Plan Candidates.
- Selected Candidate Workbench.
- Trade Plan Ladder.
- Risk Governor.
- Order Console.
- Machine Log.
- Execution Ledger link or summary.

## Machine Status Bar
Show mode, data freshness, adapter type, risk state, execution lock, and latest machine event.

## Candidate Queue
Show candidate setups beyond the Top 5. It can be collapsed in early versions if the Top 5 area is visible.

## Top 5 Trade Plan Candidates
Show five candidate plan rows or buttons. Each item should include ticker, setup label, plan status, and risk/gate state when available. Ticker clicks populate the Trade Plan Ladder.

## Selected Candidate Workbench
Show evidence for the selected candidate: setup notes, source data status, plan generation state, stale-data warnings, and missing-field blockers.

## Trade Plan Ladder
Show the complete structured plan for the selected ticker. If no ticker is selected, show a neutral empty state that tells Steven to pick a Top 5 candidate.

## Risk Governor
Show the current gate state and the reason. It must distinguish blocked, needs review, simulation-only, paper-eligible, preview-only, and approved-for-current-mode.

## Order Console
Locked by default. Early versions should show no active live order controls. Future preview controls must be disabled until a separate approved task unlocks them.

## Machine Log
Show recent machine events with timestamps, mode, ticker when relevant, and outcome.

## Execution Ledger
The ledger is the audit trail. Console should make it visible that order-like activity must be recorded before any future broker path is trusted.

## Initial Skeleton Acceptance
ARGUS-A003 can render placeholder panels with honest labels. It does not need live candidate data, broker data, or real TradePlan generation.
