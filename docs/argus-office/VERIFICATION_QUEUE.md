# Momentum Hunter Verification Queue

## Purpose

This is the durable list of exact checks Steven still needs to perform. The Roadmap
remains the authority for current status and next work. A manual pass does not by
itself authorize a merge, push, credential, broker connection, Paper mode, or Live
mode.

## Status Legend

- `AUTOMATED_PASS`: Codex compile, tests, source review, and available proof passed.
- `AUTOMATED_FAIL`: Codex found a defect.
- `MANUAL_PENDING`: Steven can perform the listed operator check now.
- `MANUAL_NOT_YET_AVAILABLE`: implementation exists below the current operator UI.
- `MANUAL_PASS`: Steven completed and accepted every numbered check.
- `MANUAL_FAIL`: Steven found a defect; record the failed step.
- `CEO_DECISION_PENDING`: Steven must choose the recorded direction.
- `NOT_STARTED`: the operational evidence run has not begun.

## Queue Summary

| Task | Automated status | Steven status | Merge state | What Steven is checking |
| --- | --- | --- | --- | --- |
| ARGUS-SHADOW-001 prospective lifecycle | `AUTOMATED_PASS` | `MANUAL_NOT_YET_AVAILABLE` | Feature branch only; remotely backed up; not merged | No WPF control was added; review is code/evidence until an operator surface is separately approved |
| Credential-free Schwab setup CLI | `AUTOMATED_PASS` | `MANUAL_PENDING` | Part of ARGUS-SHADOW-001 | The command is visibly locked, asks for no credential, opens no browser, and contacts no broker |
| First 30 completed Shadow Trades | `NOT_STARTED` | `MANUAL_NOT_YET_AVAILABLE` | Requires accepted Shadow foundation | Prospective results and manual paperMoney reconciliation, not historical backfill |
| Schwab automated-paper direction | `AUTOMATED_PASS` | `CEO_DECISION_PENDING` | Vendor response is branch-only evidence | Wait for a Schwab sandbox, research an alternate paper broker, or defer automated paper execution |
| R026 Phase 12 combined WPF review | `AUTOMATED_PASS` on its own branch | `MANUAL_PENDING` | Separate branch; not merged here | Complete the R026 workstation checklist from its isolated review build; it is not part of ARGUS-SHADOW-001 |

## ARGUS-SHADOW-001 - Prospective Shadow Trading

Branch: `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit`

Automated result: `AUTOMATED_PASS`

- The decision freezes the exact source-report text, source hash, candidate row,
  decision timestamp, canonical TradePlan, plan fingerprint, and Risk Governor result.
- Stable candidate, evidence, plan, risk, command, order, ledger, position, trade, and
  outcome identifiers are persisted in atomic versioned JSON state.
- Quote-driven FakeBroker behavior covers delayed, partial, unfilled, stale, missing,
  halted, extended-session, wide-spread, slippage, gap-through-stop, ambiguous-exit,
  buying-power, position-count, daily-loss, restart, and duplicate-command cases.
- A nontransmitting JSON and Markdown ticket contains manual thinkorswim paperMoney
  entry and reconciliation fields.
- The current WPF workstation has no Start Shadow Trade, Shadow Positions, Shadow
  Outcomes, or paperMoney reconciliation control. Nothing new is available for Steven
  to click in the UI, and the absence of those controls is intentional for this slice.
- Sixty focused Shadow/Schwab/host/simulation tests and 68 adjacent tests pass. Python
  compileall, all 88 .NET tests, and the zero-warning Release build pass. Repository-wide
  Python discovery timed out after 10 minutes and is not represented as a pass.

Steven status: `MANUAL_NOT_YET_AVAILABLE`

Do not broadly check the current app for this task. The next operator-facing slice must
first add a safe review surface. When that separate slice exists, it must provide exact
checks for starting one frozen decision, observing order/position chronology, reading
the outcome, exporting the ticket, and confirming Paper/Live remain absent.

## Credential-Free Schwab Setup CLI

Automated result: `AUTOMATED_PASS`

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Open PowerShell in the repository root.
2. Run `.\.venv\Scripts\python.exe -B -m momentum_hunter.schwab_setup --show-callback-recommendation`.
3. Confirm the first notice says to enter Schwab application credentials only and
   never a Schwab username, password, or MFA code.
4. Confirm the command does not ask for any value, open a browser, start a callback
   listener, or contact Schwab.
5. Confirm it says authenticated setup is locked.
6. Confirm the callback recommendation says the path, HTTPS rule, and certificate rule
   remain unconfirmed until authenticated official-document review.
7. Report `PASS SCHWAB SETUP SKELETON` if all checks pass. On failure, report the step
   number and the exact visible text. Do not provide any credential or account number.

Passing this check proves only the locked credential-free CLI. It does not authorize
OAuth, an account connection, a callback registration, or broker requests.

## First Prospective Sample

Status: `NOT_STARTED`

The first accepted operational run must:

1. Start only after the Shadow foundation is merged and a bounded operator workflow is
   approved.
2. Freeze decisions prospectively before later quotes are consumed.
3. Use FakeBroker only and supplied Momentum Hunter observations.
4. Reconcile selected tickets manually in thinkorswim paperMoney without GUI automation.
5. Accumulate at least 30 completed Shadow Trades before any strategy comparison.
6. Keep ideal results separate from estimated executable results.
7. Record every unfilled, blocked, partial, ambiguous, and failed trade rather than
   deleting inconvenient evidence.

## Schwab Automated-Paper Decision

Automated evidence: `AUTOMATED_PASS`

Schwab Support states Trader API works with live brokerage accounts only, cannot access
paperMoney balances, positions, or orders, and has no current sandbox.

Steven status: `CEO_DECISION_PENDING`

Choose one later:

1. `WAIT_FOR_SCHWAB_SANDBOX` - recommended; continue Shadow plus manual paperMoney.
2. `RESEARCH_ALTERNATE_PAPER_BROKER` - research only; no adapter is approved.
3. `DEFER_BROKER_AUTOMATION` - remain on Shadow plus manual reconciliation.

None of these choices authorizes use of the $100 live account, credentials, OAuth,
broker reads, order transmission, Paper controls, or Live controls.

## R026 Phase 12 Combined WPF Review

Branch: `codex/ARGUS-R026-wpf-phase12-clean-room-integration`

This is a separate review branch. It is not included in ARGUS-SHADOW-001 and requires
its own merge approval.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Exit any current Momentum Hunter process using `Menu` and the explicit Exit command.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R026-phase12-integrated-review\Launch R026 Phase 12 Integrated Review.lnk`; do not use the pinned shortcut.
3. Confirm the title is `Momentum Hunter Workstation` and the top label says
   `SIMULATION` / `Python FakeBroker Only`. No Paper, Live-broker, credential, or real
   order mode may appear.
4. Press `Ctrl+K`; confirm the Command Palette opens, filters candidate symbols and
   commands, opens an exact candidate, shows a no-match state for nonsense input, and
   closes with `Esc`.
5. Select `CRWV` and `5m`; confirm real stored candles, wicks, volume, price/time axes,
   source lineage, `STALE`, and latest UTC/OHLCV are visible. No mock candle fallback is
   acceptable.
6. Hover candles; confirm the crosshair snaps to the nearest candle, inspected
   UTC/OHLCV changes, and leaving the chart restores latest-bar details.
7. In Trade Plan, confirm `Simulation-only`, populated plan/risk evidence, and persisted
   Why/Research facts. Candidate changes must update unpinned panes.
8. Open Diagnostics, Replay Events, Automation, Activity, Outcomes, Research,
   Watchlist, Daily Workflow, Candidate Story, and Research Maturity. Confirm each
   shows persisted source/state/time/count evidence and an honest unavailable, partial,
   or stale state where applicable.
9. In Research Maturity, confirm `STRATEGY OPTIMIZATION LOCKED`, `Collect evidence only`,
   maturity and census denominators remain separate, and the evidence gate remains
   below strategy-modification authority.
10. Resize to roughly 1440x900 and then 1180x820. Confirm panes remain readable or
    scrollable with no overlapping controls or clipped longest words.
11. Close and reopen optional panes through `Panes`; confirm one pane returns at a
    useful size and no duplicate is created.
12. Confirm no provider-refresh, score-change, readiness-change, replay-selection,
    alert-generation, watchlist-generation, broker, Paper, Live, credential, or real
    order action exists. FakeBroker simulation must remain the only order-like action.
13. Ignore the generic application icon for this review; rejected R012A/R012B artwork
    must remain absent.
14. Report `PASS R026` if checks 1-13 pass. On failure, report the failed step, selected
    workspace/symbol/interval, visible state/count, window size, and attach a screenshot.

Passing this checklist does not authorize a merge or push.
