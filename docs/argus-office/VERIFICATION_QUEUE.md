# Momentum Hunter Verification Queue

## Purpose

This is the durable list of exact checks Steven still needs to perform. The Roadmap
remains the authority for current status and next work. A manual pass does not by
itself authorize a merge, push, credential, broker connection, Paper mode, or Live
mode.

## Status Legend

- `AUTOMATED_PASS`: Codex compile, tests, source review, and available proof passed.
- `AUTOMATED_IN_PROGRESS`: the branch exists but its complete proof gate is still running.
- `AUTOMATED_FAIL`: Codex found a defect.
- `MANUAL_PENDING`: Steven can perform the listed operator check now.
- `MANUAL_NOT_YET_AVAILABLE`: implementation exists below the current operator UI.
- `MANUAL_PASS`: Steven completed and accepted every numbered check.
- `MANUAL_FAIL`: Steven found a defect; record the failed step.
- `MERGE_APPROVED`: Steven explicitly authorized local integration; this does not imply every manual check was separately reported.
- `CEO_DECISION_PENDING`: Steven must choose the recorded direction.
- `BLOCKED_VENDOR_CAPABILITY`: the required vendor capability does not exist.
- `NOT_STARTED`: the operational evidence run has not begun.

## Queue Summary

| Task | Automated status | Steven status | Merge state | What Steven is checking |
| --- | --- | --- | --- | --- |
| ARGUS-SHADOW-001 prospective lifecycle | `AUTOMATED_PASS` | `MANUAL_PENDING` through Shadow-002 | Integrated into local `master` at `bb962be`; remotely backed up on its feature branch | Confirm the frozen Python lifecycle is represented read-only and without order authority in Shadow-002 |
| ARGUS-SHADOW-002 WPF Shadow Review | `AUTOMATED_PASS` | `MERGE_APPROVED` | Integrated into local `master`; not pushed | The preserved checklist remains an audit reference; merge approval does not start the official sample |
| ARGUS-SHADOW-003 sample readiness gate | `AUTOMATED_PASS` | `MERGE_APPROVED`; visual checklist remains available | Integrated into local `master`; not pushed | Confirm the UI says prepared but locked, identifies the exact sample definition, withholds metrics, and exposes no start or broker action |
| Credential-free Schwab setup CLI | `AUTOMATED_PASS` | `MANUAL_PENDING` | Integrated locally as part of ARGUS-SHADOW-001 | The command is visibly locked, asks for no credential, opens no browser, and contacts no broker |
| Official Shadow sample | `NOT_STARTED` | `MANUAL_NOT_YET_AVAILABLE` | Shadow-003 is integrated locally; sample authorization has not been granted | Do not collect trade 1 until Steven separately authorizes the exact frozen sample definition |
| Schwab automated-paper capability | `BLOCKED_VENDOR_CAPABILITY` | No decision required now | Vendor answer is recorded; no adapter exists | Trader API cannot access paperMoney and has no sandbox; use FakeBroker plus manual paperMoney reconciliation only |
| R026 Phase 12 combined WPF review | `AUTOMATED_PASS` on its own branch | Superseded by R027 combined review | Source parent for R027; not merged to master | Preserve the isolated proof as audit evidence; do not merge R026 directly |
| R027 Shadow + Phase 12 combined WPF review | `AUTOMATED_PASS`; fresh repair verification passes 162 focused and 209 total .NET tests, 641 Python tests, Python compileall, and a zero-warning Release build | `MANUAL_IN_PROGRESS`; checks 5-7 and 15-17 pass, check 11 is independently verified, checks 4, 8-10, and 14 are `CODEX_UI_PASS` pending Steven acceptance, and checks 12-13 are unavailable with zero test trades | `IMPLEMENTED_PENDING_MERGE`; repair commit `f84106a` is not merged or pushed | Steven accepts or rejects the four repaired visual surfaces in the `R027-manual-qa-repair-review` build; Git mechanics do not require a separate operator review |

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

Steven status: `MERGE_APPROVED`; the numbered checklist remains available as an audit
reference.

Integration status: `COMPLETE` on local `master` after Steven's explicit fast-forward
approval on 2026-07-24. Nothing was pushed.

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

This proof uses synthetic fixtures. Steven separately granted local merge approval on
2026-07-24; that approval is not recorded as a claim that every manual item was
individually reported. The proof and merge do not count a trade, start the official
sample, authorize a push, or create broker authority.

## ARGUS-SHADOW-003 - Sample Readiness Gate

Branch: `codex/ARGUS-SHADOW-003-sample-readiness-gate`

Implementation commit: `9002df0`

Automated result: `AUTOMATED_PASS`

Steven status: `MERGE_APPROVED`; the numbered visual checklist remains available as an
audit reference and has not been converted into sample-start authorization.

Integration status: `COMPLETE` on local `master` after Steven's explicit fast-forward
approval. Nothing was pushed.

Automated proof:

- Every new Shadow Trade and nontransmitting ticket freezes sample version,
  strategy/configuration fingerprint, fill-model version, and evidence-schema version.
- The fingerprint is deterministic from the existing Shadow execution policy and
  versioned strategy/fill/evidence contracts.
- Legacy/unversioned state remains byte-identical when read and is excluded rather
  than backfilled. Tampered, malformed, unauthorized, obsolete, or configuration-
  mismatched records fail closed.
- Both raw and review aggregate metric paths are withheld below 30 eligible completed
  records and exclude records outside the exact active sample definition.
- Default runtime readiness is `BLOCKED`; opening a snapshot creates no state. The
  engineering pass object has no start method, broker method, or side effect.
- Python compileall, 112 bounded Python tests, all 100 .NET tests, and the zero-warning
  Release build passed. Ninety of 92 bounded Python test modules passed; unchanged
  legacy Qt modules `tests.test_entry_plans` and `tests.test_gui_states` exceeded a
  fresh 120-second bound.

Check these one by one:

1. Open
   `docs/argus-office/reports/releases/ARGUS-SHADOW-003-sample-readiness-gate-overview-proof.png`.
2. Confirm the pane says `SAMPLE START LOCKED` and explains that official sample
   collection has not received its separate authorization checkpoint.
3. Confirm the definition line identifies `engineering-preflight-v1`, fill model
   `prospective-fakebroker-v1`, evidence schema `v1`, and a configuration fingerprint.
4. Confirm the pane says `Prospective Shadow Trades: 0 / 30`, all aggregate metrics are
   `Withheld`, and every synthetic preflight record is `EXCLUDED`.
5. Confirm the workstation remains `REVIEW - Read Only` and the pane says
   `FAKEBROKER - NONTRANSMITTING`.
6. Confirm there is no start-sample, create-trade, submit, replace, cancel, broker,
   Paper, Live, credential, OAuth, account, or thinkorswim automation action.
7. Report `PASS SHADOW-003 UI PROOF` if checks 1-6 pass. On failure, report the failed
   step and attach the marked screenshot.

Steven separately approved the local fast-forward. Passing this checklist still does
not authorize official sample trade 1. Exact sample-start authorization remains a
separate Steven decision.

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

Status: `NOT_STARTED`; the engineering gate is implemented on an unmerged branch, and
official sample authorization has not been granted.

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

This is the isolated source review branch. Steven authorized R027 to reconcile it with
the current Shadow baseline. Preserve this checklist as historical evidence; review
R027 rather than merging R026 directly.

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

## R027 Shadow + Phase 12 Combined WPF Review

Branch: `codex/ARGUS-R027-integrate-r026-with-shadow-baseline`

Automated result: `AUTOMATED_PASS`

Integration state: `IMPLEMENTED_PENDING_MERGE` on the branch only; local `master`
remains `164e32e`. Nothing is pushed, and the official Shadow sample remains locked.

Automated evidence: fresh Python compileall, 641 full-discovery Python tests, 162
focused presentation tests, all 209 .NET tests, zero-warning Release build,
protected-path review, source-nonmutation checks, and fresh nonblank R027 proof
artifacts pass.

Manual evidence recorded 2026-07-24:

- Manual review display convention: strikethrough means Steven addressed the item,
  orange means a newly added finding that still requires repair or physical
  reverification, and plain text means Steven has not addressed the item.
- Check 5: `MANUAL_PASS` for the required `CRWV` / `5m` proof case. The persisted
  minute-bar source contains only `CRWV`; other symbols must show an honest no-candles
  state rather than fallback or fabricated candles. Daily OHLC coverage is broader
  and is a separate source.
- Check 6: `MANUAL_PASS`; hover inspection changes the inspected candle evidence.
- Check 7: `MANUAL_PASS_PROVISIONAL`; `Plan`, `Why`, `Research`, and `History` look
  acceptable for the evidence currently available. A deeper content-quality review is
  deferred until broader market data exists; this pass does not claim that `CRWV`
  proves broader evidence quality.
- Check 4: `CODEX_UI_PASS`, `STEVEN_ACCEPTANCE_PENDING`. Live Windows automation
  confirms the palette states `14 current Hunter symbols | Commands: chart, activity,
  diagnostics`; initially shows `Add chart` and `CRWV`; reports that `nvda` is not in
  the current Hunter list and suggests available symbols; and closes on `Esc`.
- Operator-language finding: `Link A` / `Link B` has no useful meaning to Steven.
  Replace the internal group designator with an explicit state such as `Follows Hunter
  selection`, `Pinned to CRWV`, or `Independent`, while preserving the existing link
  behavior.
- Checks 8-9: `CODEX_UI_PASS`, `STEVEN_ACCEPTANCE_PENDING`. The live Current pane
  menu lists every expected standard pane with `Visible` / `Focus` or `Hidden` /
  `Open`; opening `Research Maturity` produces the correctly titled pane with
  `STRATEGY OPTIMIZATION LOCKED`, `Allowed now: Collect evidence only`, the separate
  maturity/census denominators, and the three evidence tabs.
- Check 10: `CODEX_UI_PASS`, `STEVEN_ACCEPTANCE_PENDING`. The live Review workspace
  shows one global `REVIEW ONLY` state and the first-class `Test Trade Review` pane
  with the sentence `Review simulated test trades and their evidence. No brokerage
  connection.` No repeated technical warning badge appears on ordinary controls.
- Check 14: `CODEX_UI_PASS`, `STEVEN_ACCEPTANCE_PENDING`. The canonical final
  `1180 x 820` proof and the `1440 x 900` proof show `Daily`, search, save, restore,
  `Panes`, mode, Activity, Health, and Menu without overlap. The prior canonical
  compact capture was replaced after screenshot review found it predated the final
  icon-width repair. Steven only needs to judge whether the compact presentation is
  acceptable; no manual pixel measurement is required.
- Check 15: `MANUAL_PASS`; hiding and reopening panes works without duplicates.
- Check 16: `MANUAL_PASS`; no prohibited provider, scoring, readiness, replay,
  alert, watchlist, broker, Paper, Live-money, credential, sample-start, or
  real-order action was found.
- Check 17: `MANUAL_PASS`; rejected icon artwork remains absent.
- Check 11: `CODEX_VERIFIED`. The canonical snapshot and rendered UI agree:
  `SAMPLE START LOCKED`, official authorization false, gate false, `0 / 30`,
  completed/active/unfilled/risk-rejected/data-invalid/excluded all zero, sample
  status `INSUFFICIENT_SAMPLE`, and every profitability metric withheld.
- Checks 12-13: `MANUAL_NOT_YET_AVAILABLE`. The canonical review snapshot contains
  zero test trades, so there is no row to select and no populated result set through
  which filters can be behaviorally verified. Do not fabricate a trade or start the
  official sample merely to satisfy UI review.
- New visual findings: pane-menu actions are too large, `Shadow Review` is unclear
  operator language, and technical safety labels create clutter. Keep one prominent
  global mode indicator; reserve a future red `LIVE MONEY` treatment for a separately
  approved real brokerage mode rather than repeating warnings on ordinary controls.

Manual-QA repair implemented in the working tree:

- The pane menu now labels each standard pane `Visible` or `Hidden` and offers
  `Focus` or `Open`; focusing activates the corresponding dock tab.
- Destructive `Remove` is no longer exposed in the standard pane menu. The small
  title-bar `X` is explicitly described as hiding the pane.
- Loading a saved layout restores standard pane records that an earlier build
  permanently removed. Read-only inspection of the running repair build's latest
  saved Live layout confirms all 13 standard Live pane records are present.
- Hidden secondary chart panes use the same restore-and-focus path as every other
  pane.
- Sync labels now use `Follows Hunter`, `Independent`, or `Pinned to SYMBOL`.
- The interval toolbar allocation is widened so `Daily` is no longer constrained by
  the previous 180-pixel group.
- The `Live` workspace label is now `Current`, while its internal workspace identity
  remains unchanged. The single top mode badge is concise and exposes exact boundary
  detail by tooltip.
- `Shadow Review` is now displayed as `Test Trade Review`; the repeated technical
  badge inside the pane is removed.
- The Command Palette now states that it searches current Hunter symbols plus named
  workstation commands, and a miss names available examples instead of implying a
  broken global ticker lookup.
- Pane-menu actions are compact right-aligned buttons rather than filling the row.
- Search, save-layout, and restore-layout icons use a dedicated `34 x 30` toolbar
  style with centered glyphs, zero inherited padding, fast tooltips, and explicit
  accessibility help text.
- Fresh verification passes 162/162 presentation tests, 209/209 complete .NET
  solution tests, 641/641 Python tests, Python compileall, and a zero-warning Release
  build.
- UI proof:
  `reports/releases/ARGUS-R027-manual-qa-repair-1180x820.png`,
  `reports/releases/ARGUS-R027-manual-qa-repair-1440x900.png`, and
  `reports/releases/ARGUS-R027-manual-qa-repair-panes.png`.
- Review-state proof:
  `reports/releases/ARGUS-R027-manual-qa-repair-test-trade-review-empty.png`.
- During physical review, a Python Engine Host left running since 2026-07-23
  returned `UNSUPPORTED_COMMAND` for the newer review contract. It was shut down
  through its authenticated local protocol; the current packaged host replaced it
  and the UI then rendered the canonical locked snapshot. No state or sample data
  was created.
- Review build:
  `%LOCALAPPDATA%\MomentumHunter\Builds\R027-manual-qa-repair-review\Launch R027 Manual QA Repair Review.lnk`
- These repairs remain `MANUAL_RECHECK_REQUIRED`; they are not accepted merely
  because automated checks pass.

Check these one by one:

1. Exit any current Momentum Hunter process using `Menu` and the explicit Exit command.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R027-manual-qa-repair-review\Launch R027 Manual QA Repair Review.lnk`. Do not use the pinned shortcut.
3. Confirm the title is `Momentum Hunter Workstation` and the single top mode badge
   says `SIMULATION`. Hover that badge and confirm the tooltip says there is no
   brokerage connection. No Paper, Live-money, credential, or real-order mode may
   appear.
4. Press `Ctrl+K`. Confirm the scope line names the current Hunter symbol count and
   the commands `chart`, `activity`, and `diagnostics`. Search `CRWV` and confirm it
   appears. Search `nvda`; because it is not in the current Hunter list, confirm the
   message says that directly and suggests available symbols. Search `chart` and
   confirm `Add chart` appears. Press `Esc` and confirm the palette closes.
5. Stay in `Current`. In the left `Hunter` pane, select `CRWV`, then click `5m` in the
   top interval bar. In the center `Chart`, confirm the title is `CRWV`; candle bodies,
   wicks, volume bars, price labels, and time labels are visible; the source line sits
   directly below the symbol; and the strip below the chart shows latest UTC/OHLCV.
   This check is specifically for `CRWV`: it is the only symbol in the persisted
   minute-bar source. Selecting another symbol must show an honest no-candles state,
   not a daily or mock fallback.
6. Still on `CRWV` / `5m`, move the pointer over several candle bodies and wicks in
   the center chart. Confirm the crosshair snaps to the nearest candle and the strip
   below the chart changes to that candle's UTC/OHLCV. Move the pointer out of the
   plot area and confirm the strip returns to the latest-bar UTC/OHLCV.
7. There is no standalone pane named `Evidence`. Use the visible right-side
   `Trade Plan` pane for candidate evidence. With `CRWV` selected, inspect:
   `Plan` for Entry, Stop, Target, Reward/Risk, Readiness Gate checks, and the Risk
   Governor summary; `Why` for persisted catalyst, source/time, source state, and
   liquidity; and `Research` for evidence quality, source lineage, and opportunity
   notes. The pane must remain simulation-only. Leave Chart and Trade Plan as
   `Follows Hunter` and unpinned, select another Hunter row, and confirm both panes
   change to that symbol without inventing a plan or chart when its persisted
   evidence is absent.
8. Optional panes are hidden by default. In `Current`, click the top `Panes` button,
   confirm each row says `Visible` / `Focus` or `Hidden` / `Open`, and use its action
   for `Activity`,
   `Diagnostics`, `Automation`, `Research`, `Watchlist`, `Daily Workflow`,
   `Candidate Story`, and `Research Maturity`. Confirm the opened pane title matches
   the row and its body shows a persisted source/state/time/count or an explicit
   unavailable/partial/stale explanation. Switch to `Replay`, then use
   `Panes > Replay Events > Open`. Switch to `Review`, then use
   `Panes > Outcomes > Open`. Close each optional pane with its pane `X` before
   opening the next one if screen space becomes crowded. If a named row is absent
   from `Panes`, or `Open` produces no pane, record that exact name as a failure.
9. Return to `Current`, click `Panes`, locate `Research Maturity`, and click `Open`.
   The bottom pane must be titled `Research Maturity`. At its top, confirm
   `STRATEGY OPTIMIZATION LOCKED` and `Allowed now: Collect evidence only`. Confirm
   the separate cards `Maturity Outcome Coverage` / `Scorable denominator only` and
   `Census Outcome Coverage` / `All-alert denominator`. Open the `Evidence Gates`,
   `Census Counts`, and `Research Questions` tabs. There must be no button or command
   that modifies a strategy, score, readiness state, alert threshold, plan, or order.
10. Switch to `Review` and confirm `Test Trade Review` appears as a first-class pane.
    The single top mode badge must say `REVIEW ONLY`; the pane should explain in one
    sentence that it reviews simulated test trades with no brokerage connection.
    It must not repeat technical warning badges on ordinary controls.
11. `CODEX_VERIFIED`: Test Trade Review shows `SAMPLE START LOCKED`, the exact
    sample/configuration/fill/evidence definition, `0 / 30`, zero lifecycle counts,
    and withheld aggregate metrics. There is no start button.
12. `MANUAL_NOT_YET_AVAILABLE`: no test-trade row exists. When a separately
    authorized non-official fixture or real future test trade exists, select it and
    confirm linked unpinned Chart, Trade Plan, Why, and History display its frozen
    identity without changing stored plan or evidence.
13. `MANUAL_NOT_YET_AVAILABLE`: filters have no rows to exercise. Verify them only
    after a safe test-trade fixture or future test-trade record exists.
14. If the app is maximized, click the overlapping-squares `Restore Down` control
    beside the title-bar `X`. Drag the lower-right window corner inward until the
    workstation is roughly two-thirds of the screen width. Confirm `Daily` remains
    fully visible and panes remain readable or scrollable without overlaps. Exact
    pixel measurement is not required from Steven.
15. Hide an optional pane with the small `X` in its dock title. Confirm the row
    remains in `Panes` as `Hidden` / `Open`, then reopen it and confirm it returns
    once at a useful size with no duplicate. Confirm there is no destructive
    `Remove` action in the standard pane menu.
16. Confirm no provider-refresh, score-change, readiness-change, replay-selection,
    alert-generation, watchlist-generation, broker, Paper, Live, credential, sample-
    start, or real-order action exists. FakeBroker simulation remains the only
    automated order-like boundary.
17. Confirm rejected R012A/R012B icon artwork remains absent.
18. Report `PASS R027` if checks 1-17 pass. On failure, report the failed step,
    workspace/symbol/interval, visible state/count, window size, and attach a
    screenshot.

Passing this checklist will not itself authorize merge or push.

## R028 Integrated Workstation Chrome

Status: `APPROVED_DIRECTION_NOT_STARTED`

Steven approved replacing the separate light Windows title strip with an integrated
dark workstation surface after R027 closes. The thinkorswim screenshot supplied as
visual reference is intentionally not stored in the repository because it contains
account information.

When implemented, verify these one by one:

1. Confirm no separate light Windows title strip appears above the workstation.
2. Confirm app identity, workspace navigation, the single global mode state, and
   minimize/maximize/close controls form one continuous dark top surface.
3. Drag the window from empty space in the integrated top surface and confirm it
   moves normally.
4. Double-click that draggable area and confirm maximize/restore works.
5. Drag the window to each screen edge and confirm Windows Snap still works.
6. Confirm every resize edge and corner remains usable.
7. Confirm minimize, maximize/restore, close, and `Alt+Space` behavior remain
   available through mouse and keyboard.
8. Move the window between monitors with different scaling, when available, and
   confirm the top surface stays aligned and readable.
9. Confirm `SIMULATION` and `REVIEW ONLY` remain concise global states. No ordinary
   control should repeat brokerage warnings.
10. Confirm any future separately approved real-money mode uses one unmistakable
    global red treatment, without authorizing or adding live execution in this task.
11. At compact and maximized sizes, confirm top controls do not clip, overlap, or
    steal space needed by the workspace panes.

This item is visual shell work only. It does not authorize broker integration,
credentials, paper/live execution, or changes to trading behavior.
