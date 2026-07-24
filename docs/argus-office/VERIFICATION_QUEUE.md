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
- `BLOCKED_VENDOR_CAPABILITY`: the required vendor capability does not exist.
- `NOT_STARTED`: the operational evidence run has not begun.

## Queue Summary

| Task | Automated status | Steven status | Merge state | What Steven is checking |
| --- | --- | --- | --- | --- |
| ARGUS-SHADOW-001 prospective lifecycle | `AUTOMATED_PASS` | `MANUAL_PENDING` through Shadow-002 | Integrated into local `master` at `bb962be`; remotely backed up on its feature branch | Confirm the frozen Python lifecycle is represented read-only and without order authority in Shadow-002 |
| ARGUS-SHADOW-002 WPF Shadow Review | `AUTOMATED_PASS` | `MANUAL_PENDING` | Feature branch at implementation commit `7fee390`; not merged or pushed | Review the preserved UI proof, sample counts/gating, lock evidence, execution detail, linked panes, and absence of order actions |
| Credential-free Schwab setup CLI | `AUTOMATED_PASS` | `MANUAL_PENDING` | Integrated locally as part of ARGUS-SHADOW-001 | The command is visibly locked, asks for no credential, opens no browser, and contacts no broker |
| Official Shadow sample start gate | `NOT_STARTED` | `MANUAL_NOT_YET_AVAILABLE` | Requires accepted/merged Shadow-002 plus a separate gate proof | Prove versioning, immutable identity/evidence, deterministic execution assumptions, eligibility, and checkpoint rules before collecting trade 1 |
| Schwab automated-paper capability | `BLOCKED_VENDOR_CAPABILITY` | No decision required now | Vendor answer is recorded; no adapter exists | Trader API cannot access paperMoney and has no sandbox; use FakeBroker plus manual paperMoney reconciliation only |
| R026 Phase 12 combined WPF review | `AUTOMATED_PASS` on its own branch | `MANUAL_PENDING` | Separate branch; not merged here | Complete the R026 workstation checklist from its isolated review build; it is not part of ARGUS-SHADOW-001 |

## ARGUS-SHADOW-001 - Prospective Shadow Trading

Branch: `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit`

Automated result: `AUTOMATED_PASS`

Integration state: `COMPLETE` on local `master` at `bb962be`; the matching feature
branch is remotely backed up. Remote `master` remains at `69feedf`.

- The decision freezes the exact source-report text, source hash, candidate row,
  decision timestamp, canonical TradePlan, plan fingerprint, and Risk Governor result.
- Stable candidate, evidence, plan, risk, command, order, ledger, position, trade, and
  outcome identifiers are persisted in atomic versioned JSON state.
- Quote-driven FakeBroker behavior covers delayed, partial, unfilled, stale, missing,
  halted, extended-session, wide-spread, slippage, gap-through-stop, ambiguous-exit,
  buying-power, position-count, daily-loss, restart, and duplicate-command cases.
- A nontransmitting JSON and Markdown ticket contains manual thinkorswim paperMoney
  entry and reconciliation fields.
- Shadow-001 intentionally added no WPF mutation control. Shadow-002 now supplies a
  separate read-only review surface; it still adds no Start, advance, submit, cancel,
  modify, Paper, Live, credential, broker, or thinkorswim automation control.
- Sixty focused Shadow/Schwab/host/simulation tests and 68 adjacent tests pass. Python
  compileall, all 88 .NET tests, and the zero-warning Release build pass. Repository-wide
  Python discovery timed out after 10 minutes and is not represented as a pass.

Steven status: review through the separate Shadow-002 checklist below.

Shadow-001 is already integrated locally. Reviewing Shadow-002 does not reopen or
rewrite its frozen Python evidence lifecycle.

## ARGUS-SHADOW-002 - WPF Shadow Review

Branch: `codex/ARGUS-SHADOW-002-wpf-shadow-review`

Implementation commit: `7fee390`

Automated result: `AUTOMATED_PASS`

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Open
   `docs/argus-office/reports/releases/ARGUS-SHADOW-002-wpf-shadow-review-overview-proof.png`.
2. Confirm the workstation says `REVIEW - Read Only` and the Shadow pane says
   `FAKEBROKER - NONTRANSMITTING`.
3. Confirm the pane shows `Prospective Shadow Trades: 1 / 30` and separate counts for
   completed, active, unfilled, risk-rejected, data-invalid, and excluded records.
4. Confirm win rate, average win/loss, expectancy, average R, maximum drawdown, profit
   factor, and ideal/executable gap are visibly `Withheld` below 30 eligible completed
   trades.
5. Confirm the selected record shows `Evidence frozen`, `Plan frozen`, no
   post-decision correction, decision/evidence timestamps, lifecycle, and eligibility.
6. Confirm the record detail distinguishes proposed entry from simulated fill and
   exposes spread, slippage, stop, targets, exit, exit reason, P&L, R, MFE, MAE, and
   duration where the selected lifecycle makes them available.
7. Confirm the linked Chart, frozen Trade Plan, Why context, and History/Activity
   review remain read-only and use the selected Shadow symbol.
8. Confirm date/session, setup, catalyst, regime, outcome, and evidence-eligibility
   filters are present.
9. Confirm there is no Start Trade, submit, replace, cancel, broker, Paper, Live,
   credential, OAuth, account, or thinkorswim automation action.
10. Report `PASS SHADOW-002 UI PROOF` if checks 1-9 pass. On failure, report the step
    and attach the marked screenshot.

This proof uses synthetic fixtures. Passing it approves the review design only; it does
not count a trade, start the official sample, authorize a merge/push, or create broker
authority.

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

## Official Shadow Sample Start Gate

Status: `NOT_STARTED`

The first accepted operational run must:

1. Start only after Shadow-001 is in the active baseline, Shadow-002 is accepted and
   merged, and a separate sample-start proof passes.
2. Record `SampleVersion`, strategy/configuration fingerprint, fill-model version, and
   evidence-schema version on every counted Shadow Trade.
3. Freeze candidate evidence, TradePlan, Risk Governor decision, and execution rules
   prospectively before later quotes are consumed.
4. Prove stable candidate/evidence/plan/risk/command/ledger/outcome identities,
   duplicate-command prevention, and restart recovery without duplicate trades or
   positions.
5. Prove reproducible P&L, R, MFE, and MAE; documented and locked fill/spread/slippage
   assumptions; aware timestamp/session behavior; and deterministic data-quality
   eligibility.
6. Use FakeBroker only and supplied Momentum Hunter observations. Reconcile selected
   tickets manually in thinkorswim paperMoney without GUI automation.
7. Track ideal setup results separately from estimated executable results and use the
   estimated executable result as the primary evidence metric.
8. Preserve every unfilled, blocked, partial, ambiguous, invalid, excluded, and failed
   record. Do not backfill history, delete losers, select exclusions, or silently
   recompute evidence.
9. Make no scoring, readiness, risk, entry, stop, target, spread, slippage, or fill-model
   change after a sample version begins. A material defect closes and preserves that
   version before a fixed version starts.
10. Report mechanics and evidence quality at 5, 10, 20, and 30 completed eligible
    trades without tuning the strategy to the developing sample.
11. Treat 30 trades as an initial engineering gate, not proof of profitability, a
    durable edge, broker readiness, or permission to transmit an order.

## Schwab Vendor Capability And Direction

Status: `BLOCKED_VENDOR_CAPABILITY`

Schwab Support states Trader API works with live brokerage accounts only, cannot access
paperMoney balances, positions, or orders, and has no current sandbox.

Current direction: continue credential-free FakeBroker Shadow evidence plus manual
thinkorswim paperMoney ticket/reconciliation. Schwab Trader API remains the eventual
read-only and separately supervised-live target after developer access and separate
Steven checkpoints. No interim alternate broker is approved.

This status does not authorize use of the $100 live account, credentials, OAuth,
account access, broker reads, preview, order transmission, Paper controls, or Live
controls.

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
