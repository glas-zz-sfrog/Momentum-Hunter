# Momentum Hunter Verification Queue

## Purpose

This is the durable list of exact visual/manual checks and anomaly decisions Steven
still needs to perform. The Roadmap remains the authority for current status and next
work. Routine nonvisual implementation, commits, clean fast-forward merges, and
non-force backup pushes use automated evidence and standing delegation; they do not
create a rubber-stamp Steven item.

## Status Legend

- `AUTOMATED_PASS`: Codex compile, tests, source review, and available proof passed.
- `AUTOMATED_IN_PROGRESS`: the branch exists but its complete proof gate is still running.
- `AUTOMATED_PENDING_INSTALL`: implementation proof passed, but a local privileged installation gate has not run.
- `AUTOMATED_FAIL`: Codex found a defect.
- `MANUAL_PENDING`: Steven can perform the listed operator check now.
- `MANUAL_NOT_YET_AVAILABLE`: implementation exists below the current operator UI.
- `MANUAL_PASS`: Steven completed and accepted every numbered check.
- `MANUAL_FAIL`: Steven found a defect; record the failed step.
- `USER_ACTION_REQUIRED`: Windows requires a local security interaction that Codex cannot and must not complete for Steven.
- `NO_STEVEN_ACTION`: automated evidence is sufficient for this nonvisual item.
- `STANDING_AUTHORIZED`: Codex should execute when documented invariants pass.
- `ANOMALY_DECISION_PENDING`: unexpected state requires a concrete Steven decision.
- `MERGE_APPROVED`: Steven explicitly authorized local integration; this does not imply every manual check was separately reported.
- `CEO_DECISION_PENDING`: Steven must choose the recorded direction.
- `BLOCKED_VENDOR_CAPABILITY`: the required vendor capability does not exist.
- `NOT_STARTED`: the operational evidence run has not begun.

## Queue Summary

| Task | Automated status | Steven status | Merge state | What Steven is checking |
| --- | --- | --- | --- | --- |
| ARGUS-R033 live Schwab chart integration | `AUTOMATED_PASS`; compileall, focused chart tests, a zero-warning Release build, and all 250 .NET tests pass after the density repair. The isolated R032B proof populated 39,165 minute-bar versions and 1,260 daily bars without account/order action. | `MANUAL_PASS`; Steven reviewed the dense live-chart build and directed integration on 2026-08-06 | `VISUAL_ACCEPTED_PENDING_MERGE` on `codex/ARGUS-R033-live-chart-engine-host-integration` | Git Steward must combine R032B/R033 on current master, bind Daily to the Schwab daily store, rerun full proof, and repin the remaining opening jobs. |
| Monday 2026-08-03 opening-capture readiness | `AUTOMATED_PASS`: opening fail-closed behavior, clock-task hardening, installation, independent live verification, and transient state-receipt lock recovery all pass. Evidence proves SYSTEM principal, exact `w32tm` action, startup delay `PT2M`, daily 08:15/08:25 triggers, wake enabled, no late-start catch-up, five two-minute retries, task result `0`, synchronized NIST time, Running/Automatic service, fresh heartbeat, Healthy Engine Host, 30 pending opening jobs, zero Shadow jobs, and transmission `UNAVAILABLE`. ARGUS-SERVICE-007 passed compileall, 26 focused tests, 74 affected tests, all 1,019 Python tests, a real Windows lock proof, and an installed twelve-lock stress with no process restart or Application error. | `NO_STEVEN_ACTION`; the required UAC interaction passed. Leave the computer powered on and plugged in through 08:40 Central Monday. | `COMPLETE_AND_BACKED_UP` through clock commits `30c25e5`/`3821490` and receipt-lock repair `252cdc7`; installed proof passed at 02:31 Central on 2026-08-01. | No product or visual check remains. Sunday 19:00 is a read-only preflight; Monday 08:35 is the capture and 08:50 is the terminal evidence audit. Observers must not launch, retry, repair, or fabricate evidence. |
| ARGUS-SERVICE-004/005 reboot-without-login canary | `AUTOMATED_PASS`; the final exact-time 2026-07-31 16:39 Central attempt proved a new kernel boot and service instance, Running/Automatic service, Session 0 execution with zero interactive sessions, completed runtime/Codex receipts, Healthy Engine Host, the unchanged sole `2573` individual cash binding, no position/order request, 30 preserved pending opening jobs, zero Shadow jobs, and transmission `UNAVAILABLE`. Earlier failed/invalid attempts remain preserved separately. | `NO_STEVEN_ACTION`; the reboot/sign-in-screen action is complete and no visual judgment remains. | Repairs through forced-restart commit `e24feed` are backed up; successful proof is archived and the operational gate is `PASS`. | No remaining manual check. The next evidence is the first ordinary 2026-08-03 opening-capture receipt and report; future service manifest job changes hot-reload without another restart. |
| ARGUS-R030 open positions console | `AUTOMATED_PASS`; zero-warning solution build, all 185 presentation tests, and all 237 .NET tests pass; stale/halted positions remain visible, the source is read-only canonical Shadow/FakeBroker evidence, and source review finds no brokerage/order control | `MANUAL_PASS`; Steven accepted the visible surface on 2026-07-31 | `COMPLETE_AND_BACKED_UP` on canonical `master` through `94e1708` plus Roadmap closeout | Checks 1-8 passed. The populated-row check remains deferred until canonical evidence contains an open Shadow position; do not fabricate production evidence for visual proof. |
| ARGUS-SHADOW-023 trusted-clock and host-response hardening | `AUTOMATED_PASS`; live CRWV/SPY/IWM quote proof passed against same-response HTTPS clock bounds, isolated 12/12 proof completed, exactly one IREN FakeBroker decision/trade and terminal handoff persisted, compileall passed, 138 affected tests and all 953 Python tests passed on the repair branch, and the combined integration passed all 976 Python tests, all 228 .NET tests, and a zero-warning build | `NO_STEVEN_ACTION`; this is nonvisual, isolated, nontransmitting evidence and does not count toward the official sample | `COMPLETE_AND_BACKED_UP` on canonical `master` through `cc2b1e2` | No manual product check. The remaining local Windows interaction is tracked under ARGUS-SERVICE-001; no future runtime may depend on a UAC response. |
| ARGUS-SERVICE-001 unattended automation host | `AUTOMATED_PASS` for installation, reboot-without-login operation, protected wake-task read-back, and current NIST synchronization: service is Running/Automatic under `BEASTCOMPUTER\steve`, the nonmarket account/DPAPI canary and exact-response Codex probe completed, and Engine Host is Healthy. | `NO_STEVEN_ACTION`; the local UAC clock-task gate passed on 2026-07-31. | Runtime installation and hardening are integrated and backed up, with zero Shadow jobs and order transmission `UNAVAILABLE`. | No service retest or product approval is pending. The next operational evidence is the ordinary Monday opening receipt and report. |
| ARGUS-SHADOW-017 live position marking | `AUTOMATED_PASS` for implementation and `AUTOMATED_FAIL` for the 2026-07-30 opening because the one-time task did not launch; no current log, attempt, capture, twelfth proof, arm, cycle, handoff, or trade exists | `MANUAL_PASS`; Steven passed all seven visual checks on 2026-07-29; no new Steven visual action | Implementation `94f5074`, proof repair `40a26a0`, and release `60d7c9a` are integrated/backed up; v3 remains activated-empty, unarmed, and `0 / 30`; the failed date will not be retried or reconstructed | No manual verification is pending. Codex must harden scheduler observability and missed-trigger reliability with nonmarket canaries before proposing a new prospective opening date |
| ARGUS-SHADOW-001 prospective lifecycle | `AUTOMATED_PASS` | `NO_STEVEN_ACTION`; later WPF representation was visually accepted through R027 | Integrated into local `master` at `bb962be`; remotely backed up on its feature branch | Historical evidence only; no approval remains pending |
| ARGUS-SHADOW-002 WPF Shadow Review | `AUTOMATED_PASS` | `MERGE_APPROVED` | Integrated and backed up through `origin/master` | The preserved checklist remains an audit reference; merge approval does not start the official sample |
| ARGUS-SHADOW-003 sample readiness gate | `AUTOMATED_PASS` | `MERGE_APPROVED`; visual checklist remains available | Integrated and backed up through `origin/master` | Confirm the UI says prepared but locked, identifies the exact sample definition, withholds metrics, and exposes no start or broker action |
| Credential-free Schwab setup CLI | `AUTOMATED_PASS` | `NO_STEVEN_ACTION` | Integrated locally as part of ARGUS-SHADOW-001 | Automated proof is sufficient because this is nonvisual and contacts no broker |
| SCHWAB-001B production-local certificate trust | `AUTOMATED_PASS`; version `20260725T004100Z-feaa7bc59097` is `TRUSTED_VERIFIED`, browser proof passed, and current-stack tests pass | Steven confirmed the exact Windows root warning; visible Chrome proof is `CODEX_UI_PASS` | Integrated and backed up through `origin/master` | No further certificate check is pending; credential onboarding and real OAuth remain separately gated |
| SCHWAB-003 discovery, CASH validation, and binding safety | `LIVE_BINDING_PASS`; same sole `2573` CASH identity revalidated, immutable DPAPI persistence succeeded, compileall, 123 bounded tests, 756 full tests, and exact tracked-value scan pass | `NO_STEVEN_ACTION`; no anomaly occurred | `COMPLETE` on local `master`; integrated baseline backed up through `origin/master` | No manual check pending; retain the pinned account and interrupt only on future identity, account-count, position, permission, or security anomaly |
| Official Shadow sample | `AUTOMATED_PASS`; immutable activation exists, stale June evidence was rejected, and no trade or selection-policy state exists | `MANUAL_PASS`; Steven accepted all six live WPF wording/layout checks on 2026-07-26 | `COMPLETE` on `master`; `ACTIVATED`; `SELECTOR_NOT_ARMED`; `0 / 30` | No visual action remains; the accepted pane truthfully shows the activated empty sample without implying that collection has begun |
| ARGUS-SHADOW-005 prospective evidence handoff | `AUTOMATED_PASS`; compileall, 16 focused, 109 adjacent, and 781 full Python tests plus live nonpersisting shape and temporary end-to-end proofs pass | `NO_STEVEN_ACTION`; this is nonvisual and adds no trade-selection or broker authority | `COMPLETE` on `master` as part of the integrated SHADOW-004/005/006 stack | Nothing to approve; the next genuine product decision was the selector policy, which Steven resolved in favor of the frozen automatic rule |
| ARGUS-SHADOW-006 automatic sample selector | `AUTOMATED_PASS`; deterministic selection, proof-artifact-backed immutable arming with runtime revalidation, nonmutating bundle-check CLI, exact-phrase guarded arm CLI, dedicated read-only regular-market proof CLI, multi-clock/current-quote gates, provider-time separation, guarded OAuth refresh, decision-cycle accounting, counterfactuals, portfolio/session rules, compileall, 110 focused tests, 844 full Python tests, all 216 .NET tests, production nonmutation proof, and live weekend stale/closed/extended rejection pass | `NO_STEVEN_ACTION`; implementation, commit, integration, and backup use standing delegation | `COMPLETE` on `master`; `SELECTOR_NOT_ARMED`; `0 / 30`; no policy, cycle, trade, or state file exists; quote transport has one exact-host GET, no account endpoint, guarded refresh-only account reads, and no order/transmitting method | Run the proof CLI during a regular market for the current candidate plus SPY/IWM, then assemble the actual immutable proof bundle before arming |
| ARGUS-SHADOW-007 selector-status truthfulness | `AUTOMATED_PASS`; 27 focused, 123 adjacent, 844 full Python, and 216 .NET tests pass; production status read left the activation file byte-identical and created no state | `NO_STEVEN_ACTION`; this is a nonvisual read-only CLI clarification | `COMPLETE` and backed up from `79e75b2` through the ledger closeout | `sample-status` now distinguishes activation `PASS` from `NOT_ARMED`, says automatic collection and official trade collection are false, and names the regular-market proof/bundle gate |
| ARGUS-SHADOW-008 production proof-bundle assembly | `AUTOMATED_PASS`; compileall, 26 focused builder tests, all 28 named proof-gate tests, 123 adjacent Shadow/Engine Host tests, 854 full Python tests, and 216 .NET tests pass; activation SHA-256 remains unchanged and no arm/policy/cycle/state/trade file exists | `NO_STEVEN_ACTION`; nonvisual, nontransmitting proof assembly is standing-authorized | `COMPLETE` and backed up at `fdcf898`; its ignored static bundle is preserved but stale after SHADOW-009 changes canonical Git/runtime identity | SHADOW-009 keeps the assembler but requires a newly prepared bundle and report-derived candidate identity |
| ARGUS-SHADOW-009 report-bound proof and opening cadence | `AUTOMATED_PASS`; compileall, 193 affected tests, all 37 named proof gates, 871 full Python tests, 216 .NET tests, PowerShell parsing, authenticated loopback snapshot/auto-launch, and production nonmutation pass | `NO_STEVEN_ACTION`; this is nonvisual and every consequential broker boundary remains closed | `COMPLETE` and backed up through `master`; production remains `SELECTOR_NOT_ARMED` at `0 / 30` | No manual check. The next automated evidence is installed-task inspection, SHADOW-009 static-bundle preparation, and one live 9:35 AM ET report-derived candidate plus SPY/IWM proof |
| ARGUS-SHADOW-010 automatic proof/arm ceremony | `AUTOMATED_PASS`; compileall, 235 affected tests, all 45 named proof gates, 880 full Python tests, 216 .NET tests, PowerShell parsing, protected-state review, and secret/order-path scanning pass | `NO_STEVEN_ACTION`; Steven approved unattended proof-gated operation, and every real-order/anomaly boundary remains an interruption gate | `COMPLETE` and backed up through `master`; production remains `SELECTOR_NOT_ARMED` at `0 / 30` until the live ceremony passes | No manual check. Review the resulting immutable proof/task log after the first market-day run; intervene only for a documented brokerage anomaly or consequential action |
| ARGUS-SHADOW-011 quote-proof timestamp ordering | `AUTOMATED_PASS`; compileall, direct request-latency and invalid-clock tests, all 46 named proof gates, 237 affected tests, 882 full Python tests, 216 .NET tests, protected-state review, and secret/order-path scanning pass | `NO_STEVEN_ACTION`; nonvisual pre-open defect repair under standing delegation | `COMPLETE` and backed up through `master`; no production state was created | No manual check. The regenerated final-HEAD bundle and exact 8:35 AM CT task replace the stale SHADOW-010 operational bundle |
| ARGUS-SHADOW-012 bounded scheduler retry | `AUTOMATED_PASS`; compileall, 18 focused, 46 proof-gate, and 237 affected tests plus PowerShell parsing and direct scheduled-task settings construction pass | `NO_STEVEN_ACTION`; nonvisual operational reliability repair under standing delegation | `COMPLETE` and backed up through `master`; production remains unarmed and unchanged | No manual check. Confirm the installed task reports three one-minute retries and points only to the final SHADOW-012 bundle |
| ARGUS-SHADOW-013/014 opening ceremony hardening and proof preparation | `AUTOMATED_PASS`; the 2026-07-28 proof-only task exited `0` on attempt 1, capture/report/task hashes match, candidate+SPY/IWM quote ages were below `0.6s`, HTTPS clock skew passed at `0.932s`, the finalized bundle passed 12/12 as of finalization, and Engine Host health remained `Healthy` | `NO_STEVEN_ACTION`; no visual acceptance, brokerage anomaly, or consequential action occurred | `COMPLETE_UNARMED_PROOF` at proof baseline `4c35181`; selector `NOT_ARMED`, sample `0 / 30`, and policy/cycle/state/handoff/trade are absent | No opening-proof check remains; SHADOW-015 now supplies the required synthetic negative-control evidence. |
| ARGUS-SHADOW-015 opening negative controls | `AUTOMATED_PASS`; fixed three-scenario drill passed `3 / 3`, compileall, 6 focused, 127 adjacent, all 50 bounded modules, and all 914 Python tests pass; activation hash is unchanged and generated reports remain ignored | `NO_STEVEN_ACTION`; synthetic, nonvisual, nontransmitting evidence requires no CEO rubber stamp | `COMPLETE` after clean fast-forward integration from `codex/ARGUS-SHADOW-015-negative-control-drills`; no arm, policy, cycle, state, handoff, or trade exists | No manual check. Prepare a new final-head static bundle and explicit one-time arm ceremony; fresh quote/clock proof and every anomaly gate still apply. |
| ARGUS-SHADOW-016 one-time arm scheduler | `AUTOMATED_PASS`; PowerShell parsing, 3 focused scheduling tests, 130 affected Shadow/Engine Host tests, all 917 Python tests, and all 216 .NET tests pass; unsafe recurring, broad, disabled, late, past, or wrong-time arm shapes are rejected before registration | `NO_STEVEN_ACTION`; this is historical nonvisual FakeBroker-only scheduling evidence | `HISTORICAL_COMPLETE`; the 2026-07-29 task ran and its evidence is preserved | No manual check. The resulting failed opening and successor repair are recorded in the Roadmap. |
| ARGUS-SHADOW-017 opening runtime repair | `AUTOMATED_PASS`; v1 failure and absence of cycle/state/handoff/trade are proven; stale-idle replacement, active-cycle refusal, rejected-snapshot refusal, stderr retry continuation, v1 preservation/v2 isolation, compileall, PowerShell parse, 185 focused tests, 923 full Python tests, 216 .NET tests, isolated zero-warning Release build, and live scheduler-contention canary pass | `NO_STEVEN_ACTION`; nonvisual FakeBroker-only repair under standing delegation | `COMPLETE / OPERATIONALLY_SUPERSEDED`; implementation `2213299` is integrated/backed up and v2 remains activated-empty at `0 / 30`; its 2026-07-30 task is now disabled for the material live-marking change | No manual check. Preserve the repair and v2 activation as history; follow the separate live-marking visual item above. |
| Schwab automated-paper capability | `BLOCKED_VENDOR_CAPABILITY` | No decision required now | Vendor answer is recorded; no adapter exists | Trader API cannot access paperMoney and has no sandbox; use FakeBroker plus manual paperMoney reconciliation only |
| R026 Phase 12 combined WPF review | `AUTOMATED_PASS` on its own branch | Superseded by R027 combined review | Source parent for R027; not merged to master | Preserve the isolated proof as audit evidence; do not merge R026 directly |
| R027 Shadow + Phase 12 combined WPF review | `AUTOMATED_PASS`; final recheck passes 210 total .NET tests, 672 Python tests, and a zero-warning Release build | `MANUAL_PASS`; Steven accepted the final wording and focus-persistence round-trip; checks 12-13 remain honestly unavailable with zero test trades | `COMPLETE` and backed up through `origin/master`; repair commits `f84106a` and `cd09f1b` are integrated | Preserve as accepted visual baseline; subsequent nonvisual roadmap work follows standing delegation |
| Actual candle-data cutover purge | `NOT_STARTED`; legacy JSON hash and 710 mirrored `CRWV` rows are identified | Destructive decision not yet due | Future market-data cutover task | Interrupt Steven immediately before deleting the exact legacy paths/rows; visual cutover proof remains manual |

## ARGUS-R033 - Live Schwab Chart Integration

Branch: `codex/ARGUS-R033-live-chart-engine-host-integration`

Automated result: `AUTOMATED_PASS`

Automated proof:

- `ARGUS-R033-live-chart-ui-proof-1180x820.png` - 1180x820, 122242 bytes,
  SHA-256 `52A369882FF2C320D760E08EF262BB2B0BFD4CEB474152C84F1328E6304920A5`.
- `ARGUS-R033-live-chart-ui-proof-1920x1080.png` - 1920x1080, 145150 bytes,
  SHA-256 `9D7701490BE0AB1EE87376A7098AD531543B581165820F3D50F97F04292A6602`.
- Both are nonblank; automated inspection finds visible candles/wicks/volume,
  Schwab source, complete quality labels, wrapped latest-bar detail, no unsafe
  order control, and no residual proof-only Engine Host process.

Steven result: `MANUAL_PASS`

Use the isolated R033 review build and check exactly these seven items:

1. Select `NVDA` and `1m`. Confirm actual stored Schwab proof candles appear
   with visible bodies, wicks, and volume. The chart must name Schwab as source;
   it must not mention simulated, legacy, CRWV, quote-derived, or fallback data.
2. Read the compact quality band above the chart. Confirm provider/state, latest
   completed bar, receipt time, age, gaps, corrections, unreconciled count, and
   any in-progress bar are readable without clipping in both restored and
   maximized layouts.
3. Switch among `1m`, `5m`, and `15m`. Confirm each chart refreshes and the
   interval label changes. Sparse 5m/15m evidence may honestly say `PARTIAL` or
   `INSUFFICIENT`; it must not invent a smooth chart. Select `Daily` and confirm
   missing daily evidence stays unavailable instead of reusing intraday bars.
4. Select `SHOP`, `ZETA`, and then `NVDA`. Confirm the unpinned primary chart
   follows Hunter selection. A symbol without stored candles must show an
   explicit empty/unavailable state rather than retaining the prior symbol's
   bars.
5. Pin the primary chart on `NVDA`, select a different candidate, and confirm
   the pinned chart remains `NVDA`. Unpin it and confirm it catches up to the
   current Hunter selection.
6. Leave the chart open for at least ten seconds. Confirm periodic refresh does
   not flicker, duplicate panes, reset the selected interval, or steal focus.
   Changing symbol or interval during refresh must still update promptly.
7. Confirm R033 added no Buy, Sell, Submit, Replace, Cancel, broker, account, or
   live-order control. The visible candidate readiness may remain blocked; the
   chart does not upgrade trade eligibility.

Report `PASS` only when all seven pass. Otherwise report the failed number and
the exact missing candle, clipping, misleading source/state, stale pane,
flicker, pin/link error, or unsafe control.

## ARGUS-R030 - Open Positions Console

Branch: `codex/ARGUS-R030-open-positions-console`

Automated result: `AUTOMATED_PASS`

Steven result: `MANUAL_PASS` on 2026-07-31

Check these nine items:

1. In the latest Momentum Hunter workstation, confirm a compact `Positions`
   button appears in the dark top bar without clipping nearby controls.
2. Click `Positions`. Confirm the pane opens inside the same workstation and
   the window remains focused; no separate taskbar window should appear.
3. Press `Ctrl+K`, type `positions`, and run the exact command. Confirm it opens
   or focuses the same Positions pane.
4. With the current canonical empty state, confirm the summary says Open `0`,
   Unrealized P&L `Unavailable`, Market Value `$0.00`, and Quote Health
   `No open marks`.
5. Confirm the pane clearly identifies `PAPER SHADOW / NONTRANSMITTING` and
   says Schwab account positions are not connected.
6. Confirm there are no Buy, Sell, Submit, Replace, Cancel, Close Position, or
   other order-execution controls in the pane.
7. Close the pane with its pane-level close control, then click the top-bar
   `Positions` button and confirm the pane returns.
8. Check the normal restored and maximized workstation layouts for clipped,
   overlapping, or unreadable Positions controls.
9. When canonical Shadow evidence eventually contains an open position, verify
   the table shows Symbol, Side, Qty, Avg Fill, Mark, Market Value, Unrealized,
   %, R, Stop, Next Target, State, Quote Age, and Source. This check is
   `MANUAL_NOT_YET_AVAILABLE` while the official sample has no open position.

Report `PASS` for checks 1-8 only when all eight pass. Check 9 remains deferred
without blocking acceptance of the empty-state surface. Report any failed
number and the exact clipping, wording, focus, reopen, or unsafe-control issue.

Steven accepted the visible surface after checks 1-8 on 2026-07-31. Check 9
remains `MANUAL_NOT_YET_AVAILABLE` and does not block integration.

## ARGUS-SHADOW-017 - Live Position Marking

Branch: `codex/ARGUS-SHADOW-017-live-position-marking`

Proof:
`docs/argus-office/reports/releases/ARGUS-SHADOW-017-synthetic-live-marking-ui-proof.png`

Automated result: `AUTOMATED_PASS`

Steven result: `MANUAL_PASS` on 2026-07-29

Steven confirmed all seven checks and approved commit, integration, rebinding,
and the remaining pre-run gates. This acceptance does not arm the selector and
does not authorize a real broker order.

Check only these seven items:

1. At 1180x820, all text in Test Trade Review is readable.
2. No labels, values, tabs, tables, or cards clip or overlap.
3. The current state is obvious: WORKING/AHEAD/BEHIND/STALE for open records,
   and WINNER/LOSER only for completed records.
4. Quote source, quote age, provider timestamp, and receipt timestamp are visible
   on the Active Test Trade card.
5. The WORKING order has no fill, executable P&L, R, MFE, or MAE.
6. Aggregate win rate, expectancy, profit factor, and drawdown remain withheld,
   and Counterfactuals remain a separate tab.
7. No Start, Submit, Replace, Cancel, Broker, Paper, Live, or other execution
   control exists in Test Trade Review.

Report `PASS` only when all seven pass. Otherwise report the failed number and
what is clipped, ambiguous, mislabeled, or unexpectedly actionable.

## ARGUS-SHADOW-001 - Prospective Shadow Trading

Branch: `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit`

Automated result: `AUTOMATED_PASS`

Integration state: `COMPLETE` on local `master` at `bb962be`; the matching feature
branch and the integrated baseline are remotely backed up through `origin/master`.

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
2. Confirm the pane says `SAMPLE START LOCKED`. Its historical authorization wording
   records the original proof state; current policy permits an automated start only
   after every frozen engineering prerequisite passes.
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

Steven separately approved the historical local fast-forward. Current policy does not
turn this old visual checklist into a new approval gate: Codex may start the official
FakeBroker-only sample after every frozen prerequisite passes, and must interrupt
Steven only if a prerequisite fails or the observed state is ambiguous.

## Credential-Free Schwab Setup CLI

Automated result: `AUTOMATED_PASS`

Steven status: `NO_STEVEN_ACTION`

Archived automated audit steps:

1. Open PowerShell in the repository root.
2. Run `.\.venv\Scripts\python.exe -B -m momentum_hunter.schwab_setup --show-callback-recommendation`.
3. Confirm the first notice says to enter Schwab application credentials only and
   never a Schwab username, password, or MFA code.
4. Confirm the command does not ask for any value, open a browser, start a callback
   listener, or contact Schwab.
5. Confirm it says authenticated setup is locked.
6. Confirm the callback recommendation says the path, HTTPS rule, and certificate rule
   remain unconfirmed until authenticated official-document review.
7. Record `AUTOMATED_PASS` if all checks pass. On failure, report the step number and
   the exact non-secret text. Do not provide any credential or account number.

This check proves only the locked credential-free CLI. Current standing delegation
separately permits bounded OAuth refresh and authenticated read-only account work;
real order transmission and account-scope anomalies remain interruption gates.

## Official Shadow Sample Start Gate

Status: `NOT_STARTED`; sample start is `STANDING_AUTHORIZED` after every frozen
engineering prerequisite passes. No separate Steven authorization is required unless
the precheck fails or the observed state is ambiguous.

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
thinkorswim paperMoney ticket/reconciliation. Schwab Trader API is the authenticated
read-only and separately supervised-live target. Routine OAuth refresh, expected
single-account reads, exact immutable binding, and documented nontransmitting preview
research may proceed under standing delegation. An alternate broker would be a product
direction change and therefore requires a concrete Steven decision.

This vendor limitation does not block those standing-authorized nonvisual steps. It
does block automated paperMoney. Real order transmission, replacement, cancellation,
or unattended-live enablement still requires Steven's explicit decision.

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

Integration state: `COMPLETE` on local `master` after Steven's explicit fast-forward
approval. Nothing is pushed, and the official Shadow sample remains locked.

Automated evidence: fresh Python compileall, 672 full-discovery Python tests, 163
presentation tests, all 210 .NET tests, zero-warning Release build,
protected-path review, source-nonmutation checks, and fresh nonblank R027 proof
artifacts pass.

Final integration evidence: pre-merge local `master` `164e32e` was an ancestor of
the clean accepted branch; `git diff --check master..HEAD` passed; full Python
discovery passed 672/672; all .NET tests passed 210/210; and the Release build passed
with warnings treated as errors and zero warnings. The integration used
`git merge --ff-only`; nothing was pushed.

Manual evidence recorded 2026-07-24:

- Manual review display convention: strikethrough means Steven addressed the item,
  orange means a newly added finding that still requires repair or physical
  reverification, and plain text means Steven has not addressed the item.
- Check 5: `MANUAL_PASS` for the required `CRWV` / `5m` proof case. Steven
  reconfirmed that only `CRWV` shows candles. The persisted minute-bar source contains
  only `CRWV`; other symbols correctly show an honest no-candles state rather than a
  fallback or fabricated chart. Daily OHLC coverage is broader and is a separate
  source.
- Check 6: `MANUAL_PASS`; hover inspection changes the inspected candle evidence.
- Check 7: `MANUAL_PASS_PROVISIONAL`; `Plan`, `Why`, `Research`, and `History` look
  acceptable for the evidence currently available. A deeper content-quality review is
  deferred until broader market data exists; this pass does not claim that `CRWV`
  proves broader evidence quality.
- Check 4: `MANUAL_PASS`. Steven accepted the final behavior after live Windows
  automation confirmed the palette states `14 current Hunter symbols | Commands: chart, activity,
  diagnostics`; initially shows `Add chart` and `CRWV`; reports that `nvda` is not in
  the current Hunter list and suggests available symbols; and closes on `Esc`.
  The initial WPF popup incorrectly dismissed itself when focus moved to Codex. The
  repaired palette is hosted inside the one main workstation window. With `nvda`
  still entered, Codex switched away and back: the palette and query remained visible,
  search focus returned, and exactly one WPF workstation window/process existed.
- Resolved operator-language finding: the meaningless `Link A` / `Link B` display was
  replaced by `Follows Hunter`, `Pinned to CRWV`, or `Independent` while preserving
  the existing link behavior.
- Checks 8-9: `MANUAL_PASS`. Steven accepted the compact pane menu and Research
  Maturity presentation. The live Current pane
  menu lists every expected standard pane with `Visible` / `Focus` or `Hidden` /
  `Open`; opening `Research Maturity` produces the correctly titled pane with
  `STRATEGY OPTIMIZATION LOCKED`, `Allowed now: Collect evidence only`, the separate
  maturity/census denominators, and the three evidence tabs.
- Check 10: `MANUAL_PASS`. Steven accepted the Review presentation. The live workspace
  shows one global `REVIEW ONLY` state and the first-class `Test Trade Review` pane
  with the sentence `Review simulated test trades and their evidence. No brokerage
  connection.` No repeated technical warning badge appears on ordinary controls.
- Check 14: `MANUAL_PASS`. Steven accepted the compact top row. The canonical final
  `1180 x 820` proof and the `1440 x 900` proof show `Daily`, search, save, restore,
  `Panes`, mode, Activity, Health, and Menu without overlap. The prior canonical
  compact capture was replaced after screenshot review found it predated the final
  icon-width repair. Steven only needs to judge whether the compact presentation is
  acceptable; no manual pixel measurement is required.
- Check 15: `MANUAL_PASS`; hiding and reopening panes works without duplicates.
- Check 16: `MANUAL_PASS`; no prohibited provider, scoring, readiness, replay,
  alert, watchlist, broker, Paper, Live-money, credential, sample-start, or
  real-order action was found.
- Check 17: `MANUAL_PASS` for the reviewed R027 build's icon state. Correction
  recorded 2026-07-25: Steven clarified that he liked both previous icon designs;
  the earlier "rejected artwork" interpretation was wrong.
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
- The Command Palette is now an in-window overlay instead of an auto-closing WPF
  popup. Losing application focus no longer dismisses it; reactivating the workstation
  refocuses and selects the query. Intentional close paths remain `Esc`, `Ctrl+K`,
  command execution, and clicking the dimmed backdrop. The overlay cannot create a
  second taskbar or Alt+Tab entry.
- Pane-menu actions are compact right-aligned buttons rather than filling the row.
- Search, save-layout, and restore-layout icons use a dedicated `34 x 30` toolbar
  style with centered glyphs, zero inherited padding, fast tooltips, and explicit
  accessibility help text.
- Fresh verification passes 163/163 presentation tests, 210/210 complete .NET
  solution tests, 672/672 Python tests, Python compileall, and a zero-warning Release
  build.
- UI proof:
  `reports/releases/ARGUS-R027-manual-qa-repair-1180x820.png`,
  `reports/releases/ARGUS-R027-manual-qa-repair-1440x900.png`, and
  `reports/releases/ARGUS-R027-manual-qa-repair-panes.png`.
- Review-state proof:
  `reports/releases/ARGUS-R027-manual-qa-repair-test-trade-review-empty.png`.
- Focus-persistence proof:
  `reports/releases/ARGUS-R027-command-palette-focus-persistence-proof.jpg`
  (`1166 x 813`, nonblank), captured after returning from Codex with the `nvda`
  query still visible.
- During physical review, a Python Engine Host left running since 2026-07-23
  returned `UNSUPPORTED_COMMAND` for the newer review contract. It was shut down
  through its authenticated local protocol; the current packaged host replaced it
  and the UI then rendered the canonical locked snapshot. No state or sample data
  was created.
- Review build:
  `%LOCALAPPDATA%\MomentumHunter\Builds\R027-command-palette-focus-review\MomentumHunter.Desktop.Wpf.exe`
- Steven manually accepted these repairs after the final focus-persistence check.

Check these one by one:

1. Exit any current Momentum Hunter process using `Menu` and the explicit Exit command.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R027-command-palette-focus-review\MomentumHunter.Desktop.Wpf.exe`. Do not use the pinned shortcut.
3. Confirm the title is `Momentum Hunter Workstation` and the single top mode badge
   says `SIMULATION`. Hover that badge and confirm the tooltip says there is no
   brokerage connection. No Paper, Live-money, credential, or real-order mode may
   appear.
4. Press `Ctrl+K`. Confirm the scope line names the current Hunter symbol count and
   the commands `chart`, `activity`, and `diagnostics`. Search `CRWV` and confirm it
   appears. Search `nvda`; because it is not in the current Hunter list, confirm the
   message says that directly and suggests available symbols. Leave `nvda` entered,
   switch to another application, and return to Momentum Hunter. Confirm the palette
   and query are still visible, typing can immediately replace the selected query,
   and there is only one Momentum Hunter workstation choice on the taskbar or
   `Alt+Tab`. Search `chart` and confirm `Add chart` appears. Press `Esc` and confirm
   the palette closes.
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
17. Historical R027 check: confirm the branch-only R012A/R012B artwork is absent
    from that specific review build. This is not a rejection of either design;
    Steven corrected that interpretation on 2026-07-25.
18. Report `PASS R027` if checks 1-17 pass. On failure, report the failed step,
    workspace/symbol/interval, visible state/count, window size, and attach a
    screenshot.

Passing this checklist will not itself authorize merge or push.

## SCHWAB-001 Synthetic Loopback Listener

Status: `CODEX_VERIFIED_NO_MANUAL_ACTION`

Steven does not need to inspect Git, enter credentials, open Schwab, or exercise the
listener for this slice. The implementation is intentionally not wired into the UI
or a real OAuth flow.

Automated proof completed:

1. The production configuration accepts only
   `https://127.0.0.1:8182/oauth/callback`.
2. A synthetic TLS client that trusts the synthetic test certificate completes one
   valid callback, after which the exact registered port is closed.
3. Missing, duplicate, mismatched, provider-error, wrong-method, malformed-handler,
   stalled-handshake, keep-alive, timeout, and second-use cases fail closed.
4. Authorization code and state values are absent from response bodies, object
   representations, and stderr proof.
5. The listener has no provider, broker, account, or order client imports.
6. Focused tests pass 19/19; final full Python discovery passes 653/653.

Deferred to later separately gated work:

1. Stage and install the production-local certificate using the verification
   sequence below.
2. Onboard the Schwab Client ID/Secret directly into DPAPI-protected local storage.
3. Perform a real browser authorization and token exchange.
4. Discover accounts read-only and prove exact binding to the intended $100 canary
   account.

## SCHWAB-001B Production Certificate Trust

Status: `PASS`

This was not a Git check. Steven physically confirmed the exact Windows root warning,
and Codex independently verified the resulting Chrome page and listener shutdown.

Completed production-local trust evidence:

1. Preflight found zero matching certificates in `CurrentUser\Root`, no existing
   default production material, and no listener on exact address `127.0.0.1:8182`.
2. Exactly one production-local version was staged outside Git:
   `20260725T004100Z-feaa7bc59097`.
3. Root subject: `CN=Momentum Hunter Local OAuth Root`.
4. Root SHA-1: `E35BB94F68A98BFCADB6E69ACD63961BBE3AA76F`.
5. Root SHA-256:
   `C926D9F89B5E5D11BF3179B04D4D7928A0325AD8514064E9658D05BB8045BEA1`.
6. Leaf SHA-256:
   `74B38DE72175834B325EDDF17C9BA1A934543A525D7831A609C2876BC618DA3E`.
7. Leaf validity: `2026-07-25T00:36:00Z` through
   `2027-07-25T00:41:00Z`.
8. Steven confirmed the Windows warning displayed exactly
   `Momentum Hunter Local OAuth Root` and SHA-1
   `E35BB94F68A98BFCADB6E69ACD63961BBE3AA76F` before selecting Yes.
9. Exactly one matching certificate now exists in `CurrentUser\Root`; it has no
   private key. The manager reports `TRUSTED_VERIFIED`, and the exact active-version
   marker exists outside Git.
10. The initial `.NET` store write and an externally timed `certutil` attempt exposed
    Windows' mandatory root-confirmation behavior without leaving partial trust.
    The production manager now invokes current-user `certutil` directly, allows five
    minutes for the visible confirmation, verifies exact trust afterward, skips an
    already trusted version, and retains exact rollback behavior.
11. Chrome opened `https://127.0.0.1:8182/oauth/callback` without a privacy
    interstitial or hostname error and displayed only:
    `Momentum Hunter received the local authorization response. You may close this browser tab.`
12. The browser proof returned `BROWSER_TRUST_PROOF_PASSED`; exact port `8182`
    closed after one callback. Credentials loaded, OAuth attempted, and broker
    connected all remained false.
13. Compileall passes, focused Schwab tests pass 47/47, and full Python discovery
    passes 672/672. No protected product or execution behavior changed.
14. The completed trust correction and evidence are committed at `3996a6f`. The
    stacked branch is clean, technically fast-forwardable from local `master`, and
    remains unmerged and unpushed.

This historical check proved only local HTTPS trust. Current standing delegation
separately permits bounded OAuth refresh, expected account reads, and exact immutable
binding. Market-data activation follows its Roadmap slice; real orders remain an
interruption gate. The exact-root removal command remains available for rollback, but
certificate removal itself requires a concrete Steven decision.

## SCHWAB-002 Credential And OAuth Onboarding

Status: `MANUAL_PASS_COMPLETE_LOCAL_MASTER`

Completed evidence:

1. Steven explicitly authorized credential/OAuth onboarding. The Client ID and Client
   Secret were entered only through hidden terminal prompts; they were not sent
   through chat, command arguments, logs, screenshots, reports, or Git.
2. Redacted status confirms `credentialsStored: true`. The current-user DPAPI file is
   outside Git, contains no readable credential/token labels, has protected
   inheritance, and grants one non-inherited Full Control entry only to
   `BEASTCOMPUTER\steve`.
3. The first real authorization attempt reached Schwab consent and produced a callback
   containing `code`, `session`, and matching `state`, but the original three-minute
   listener window expired first. No OAuth token was stored, no account request ran,
   and order transmission remained unavailable.
4. The narrow correction changes the default manual authorization window to ten
   minutes and adds a focused regression test proving the production listener receives
   `600` seconds and waits `601` seconds before cleanup.
5. Steven repeated Schwab consent and selected only the intended $100 account. The
   local callback and token exchange completed successfully.
6. Redacted status now reports `oauthAuthorized: true` and `tokenState: ACTIVE`.
   Token values remain encrypted and redacted.
7. Redacted status also reports `accountBinding: NOT_BOUND`,
   `authenticatedAccountRequests: LOCKED_PENDING_SEPARATE_APPROVAL`, and
   `orderTransmission: UNAVAILABLE`.
8. The code contains no account/trader endpoint and no place, submit, replace, cancel,
   transfer, or withdrawal method. It does not import scoring, readiness, replay,
   alerts, TradePlan, Risk Governor, database, or schema paths.
9. Compileall passes, focused Schwab security/certificate/listener tests pass 60/60,
   and full Python discovery passes 702/702.
10. Steven explicitly approved local fast-forward integration. SCHWAB-002 is complete
    on local `master`; nothing is pushed.

What Steven is considered to have passed:

1. The real Schwab consent flow completed.
2. Only the intended $100 account was selected in Schwab's consent UI.
3. No Schwab username, password, MFA code, or account number was provided to Codex.

What was not yet proven at the SCHWAB-002 checkpoint:

1. Momentum Hunter has not called an authenticated Schwab account endpoint.
2. The software has not independently enumerated the authorized accounts or verified
   that Schwab exposes only the intended $100 account.
3. No account hash or account binding has been stored.
4. No balance, position, market-data, preview, or order request has occurred.
5. At this historical checkpoint SCHWAB-002 had not been pushed. Current verified
   nonvisual integration and non-force backup follow standing delegation.
6. At this historical checkpoint discovery and binding had not begun. Current policy
   authorizes expected read-only discovery and exact single-canary binding, but still
   requires an immediate Steven interruption if more than one account is exposed or
   identity cannot be proven without full account-number disclosure.

## SCHWAB-002A Credential Rotation Recovery

Status: `RECOVERY_COMPLETE_ORIGINAL_APP_RESTORED`

Incident evidence:

1. During read-only research in Schwab's official developer portal, an expired-session
   page retained the live Client ID and Client Secret in its DOM.
2. Browser inspection surfaced those values to the automation channel. The values must
   be treated as compromised and must not be repeated in chat, reports, logs, commands,
   screenshots, tests, or Git.
3. Browser work stopped immediately. No account, balance, position, market-data,
   preview, or order endpoint was called.
4. Exact in-memory comparison of the locally stored Client ID and Client Secret against
   every Git-tracked file returned zero hits for both values.
5. The worktree was clean before the incident-response branch began. Local `master`
   remains unpushed, and no remote repository contains SCHWAB-002.
6. The quarantined local credential/token store was deleted through the exact guarded
   local-auth flow. Redacted status now reports no stored credentials, no OAuth
   authorization, missing token state, no account binding, authenticated account
   requests locked, and order transmission unavailable.
7. Schwab's public OAuth guide confirms that Consent and Grant lets the user select
   which accounts are shared. Its public refresh guide says token access can be
   revoked at any time, revocation should terminate third-party access unless granted
   again, a compromised refresh token requires a full OAuth restart, and a changed
   authorized-account selection requires a new access token.
8. Schwab Security Settings showed `Market Intelligence Workstation` linked only to
   the intended Individual account. The Rollover IRA and Joint Tenant accounts were
   unchecked. Confirming `Stop Linking` removed the workstation entry while leaving
   unrelated linked apps unchanged.
9. The developer app was temporarily `Deactivated`, then explicitly restored after
   Steven directed recovery of the existing approved application.
10. Schwab exposes no Client Secret rotation control. The official Modify App guide
    limits self-service changes to app metadata/callbacks and documents activation or
    deactivation as a pause/resume operation.
11. A fully prepared replacement app with Accounts and Trading Production plus Market
    Data Production, order limit 5, the registered loopback callback, and the existing
    read-only-first/order-disabled description was rejected. The portal permits one
    Individual app per production product and counts the deactivated app against both
    limits.
12. A no-save modification check proved the old app can remove one product but cannot
    remove its final product. The check was cancelled, and both original product
    subscriptions remain unchanged. Self-service replacement is therefore exhausted.

Completed recovery actions:

1. Steven explicitly approved remote revocation, secret replacement, guarded local
   deletion, hidden replacement entry, and fresh OAuth for only the $100 account.
2. Revoked the old OAuth/account link.
3. Deleted the quarantined local credentials, tokens, and account binding.
4. Deactivated the compromised developer app.
5. Confirmed that Schwab provides no self-service secret rotation and that a replacement
   app is blocked by the one-app-per-production-product limit.
6. Steven directed restoration of the existing approved app rather than waiting for
   vendor-side replacement. The app was reactivated and reports `Ready For Use` with
   both production products, callback, order limit, description, and identity unchanged.
7. Recovered the original Client ID and Client Secret directly from the portal into a
   temporary current-user DPAPI stage, restored Momentum Hunter's normal DPAPI vault,
   verified it, removed the temporary encrypted duplicate, and cleared the clipboard.
8. Completed a fresh OAuth flow after Steven selected only the intended $100 Individual
   account. Redacted status reports stored credentials, active OAuth, no account binding,
   authenticated account requests locked, and order transmission unavailable.
9. Repeated exact tracked-file scanning returned zero Client ID and zero Client Secret
   hits. Neither plaintext value appears in the DPAPI ciphertext, whose only explicit
   ACL entry grants Full Control to `BEASTCOMPUTER\steve`.
10. Confirmed no account, balance, position, market-data, preview, or order endpoint was
    called. No support request was sent and no replacement app was created.

Recovery follow-through under current policy:

1. No Client Secret rotation occurred; the existing application and original credentials
   were restored under Steven's explicit direction. Vendor-side rotation remains an
   optional future hardening action, not the current blocker.
2. Read-only discovery was subsequently completed under a bounded confirmation gate;
   future expected read-only calls follow standing delegation.
3. Every discovery slice must return only redacted identity, stop if more than the intended
   Individual account is exposed, and make no balance, position, market-data, preview,
   or order request.
4. Exact single-canary binding is standing-authorized after discovery proves isolation;
   any identity, type, permission, position, or persistence anomaly interrupts Steven.

## SCHWAB-003 Read-Only Account Discovery

Branch: `codex/ARGUS-SCHWAB-003-readonly-account-discovery`

Status: `COMPLETE` on local `master`; integrated baseline backed up through `origin/master`

Implemented behavior:

1. The production transport knows exactly one provider URL:
   `GET https://api.schwabapi.com/trader/v1/accounts/accountNumbers`.
2. It accepts no access-token, endpoint, account-number, or account-hash CLI argument.
3. It requires the exact non-secret phrase `DISCOVER SCHWAB ACCOUNTS READ ONLY`
   before loading tokens or contacting Schwab.
4. Redirects, non-200 responses, oversized or malformed JSON, missing fields, invalid
   account suffixes, and duplicate numbers/hashes fail closed without response-body or
   token disclosure.
5. Full account numbers are reduced immediately to their final four digits. Account
   hashes are redacted in reports and representations.
6. Discovery results are not persisted. No account binding, balance, position,
   market-data, preview, order, or order-transmission method exists in the module.

Automated evidence:

- Python compileall passes.
- All 13 focused account-discovery tests pass.
- The complete bounded Schwab suite passes 82/82.
- Exact working-tree scanning reports zero Client ID and zero Client Secret hits.
- Protected scoring, readiness, replay, alert, database/schema, market-data,
  TradePlan, Risk Governor, broker/order, WPF, generated-data, and Shadow sample paths
  are unchanged.

Historical discovery-only live evidence:

1. Steven directed the roadmap to continue after the exact one-request boundary was
   stated.
2. One confirmation-gated live GET completed successfully.
3. Schwab returned exactly one authorized account ending `2573`, matching the intended
   $100 Individual account suffix.
4. The redacted result reports `singleCanaryCandidate: true`, `persistence: NONE`,
   and `accountBinding: NOT_BOUND`.
5. Balances, positions, market data, previews, orders, and order transmission were not
   requested.
6. Post-request onboarding status still reports no account binding and order
   transmission unavailable.

Validation and binding sequence:

1. `COMPLETE`: Schwab's authenticated official specification proves that
   `GET /accounts/{encryptedAccountId}` returns balances by default, returns positions
   only when `fields=positions`, and identifies account `type` as `CASH` or `MARGIN`.
2. `AUTOMATED_PASS`: the exact read-only identity validator is implemented and tested.
   It omits `fields`, rejects nonempty position data, suppresses all balance values,
   accepts only one matching `CASH` account, maps it explicitly to the internal
   `INDIVIDUAL_CASH` binding type, redacts the in-memory candidate, and persists
   nothing.
3. `LIVE_PASS`: Steven approved the live two-GET validation. The first attempt stopped
   before account traffic because the access token had expired. After guarded refresh,
   the repeated sequence returned one account ending `2573`, type `CASH`,
   `cashOnlyState: VERIFIED_CASH`, no positions, suppressed balances, and
   `accountBinding: NOT_BOUND`.
4. `LIVE_BINDING_PASS`: the binder repeated and passed count, suffix, hash, type, and
   no-position validation, refused replacement semantics remained active, and only
   encrypted immutable identity was persisted. No anomaly occurred.

## SCHWAB-003 Account-Detail Validation

Branch: `codex/ARGUS-SCHWAB-003-readonly-account-discovery`

Status: `LIVE_BINDING_PASS`; `IMMUTABLE_BINDING_PINNED`

Official contract evidence:

1. The authenticated Schwab Trader API specification defines the request as
   `GET https://api.schwabapi.com/trader/v1/accounts/{encryptedAccountId}`.
2. The `fields` query is optional and its documented position value is
   `fields=positions`; the validator sends no query string.
3. Schwab documents that balance information is returned by default. The validator
   uses only the presence of the balance shape and never exposes a balance value.
4. The account schema defines `type` as `CASH` or `MARGIN`.

Historical pre-binding live validation evidence:

1. Steven approved only the two read-only identity GETs.
2. An expired access token stopped the first run before either account request.
3. Guarded OAuth refresh restored `ACTIVE` while binding remained `NOT_BOUND`.
4. The approved run returned exactly one account ending `2573`, official type `CASH`,
   `cashOnlyState: VERIFIED_CASH`, `positionsRequested: false`,
   `positionsReceived: false`, and `balanceValuesSuppressed: true`.
5. The internal candidate was `INDIVIDUAL_CASH` and
   `VALIDATED_NOT_PERSISTED`; no hash or binding was saved.

Automated evidence:

1. Compileall passes for `momentum_hunter` and `tests`.
2. The complete bounded Schwab suite passes 123/123.
3. Full repository discovery passes 756/756 within the extended bounded timeout.
5. Tests prove exact encoded-hash GET routing, no `fields` parameter, redirect refusal,
   response size limits, malformed response refusal, secret-safe errors, exact
   confirmation, active-token requirement, exactly-one-account requirement, suffix
   match, official `CASH` type, margin refusal, unexpected-position refusal, balance
   suppression, redacted output, no persistence, and no write/order methods.
6. The binding-candidate tests prove official `CASH` maps only to internal
   `INDIVIDUAL_CASH`, official `MARGIN` is refused, the existing isolation policy
   revalidates the candidate, no encrypted store is called, and both authorized-account
   and binding representations redact the opaque hash.

Live binding evidence and future interruption conditions:

1. The expired unbound token refreshed through the tested guarded path while binding
   remained `NOT_BOUND` and order transmission remained unavailable.
2. The binder repeated both identity GETs and proved the same hash, ending `2573`,
   official `CASH` type, and no positions.
3. The resulting state is `accountBinding: PINNED`,
   `persistence: ENCRYPTED_DPAPI_IMMUTABLE`, account ending `2573`, internal type
   `INDIVIDUAL_CASH`, and `orderTransmission: UNAVAILABLE`.
4. The full number, full hash, and balance values must remain absent. No position,
   market-data, preview, order, or transmission request is authorized.
5. Any unexpected account count, ending, hash, type, position, permission, existing
   binding, malformed response, secret exposure, or store failure must stop before
   persistence and ask Steven one concrete question describing the practical exposure.
6. Post-binding compileall, all 123 bounded Schwab tests, and all 756 repository tests
   pass. Exact comparison of the live application ID, application secret, access
   token, refresh token, and account hash against 573 Git-tracked files found zero
   occurrences.

## ARGUS-SHADOW-004 Official Sample Activation

Status: `COMPLETE`; `AUTOMATED_PASS`; `MANUAL_PASS`; implementation committed at
`9a214b7` and integrated into `master` with the verified SHADOW-005/006 stack

Automated evidence:

- The write-once activation record exists only under ignored local generated data.
  Its SHA-256 is
  `6980D5734F3F2010D892CD1F3E29354D5DF37B193B082B18A01D8B5D485AD20C`.
- `official-shadow-v1` is active at `0 / 30`; no Shadow trade/state file exists,
  no command receipt exists, and order transmission is `UNAVAILABLE`.
- A real CLI attempt to start CRWV from the June 17 report failed because both
  capture and report generation predate activation. It created no trade or state.
- Python compileall, 50 focused Shadow tests, 125 bounded Python tests, all 770
  Python tests by bounded module discovery plus the final affected-module pass, all 216 .NET tests, and the
  zero-warning Release build pass.
- The first workstation capture correctly exposed the still-running old Python
  singleton. Restarting that engine host loaded the current implementation and
  the persisted activation. This was an in-memory process refresh, not a data or
  broker change.
- Screenshot proof:
  `docs/argus-office/reports/releases/ARGUS-SHADOW-004-official-sample-active-proof.jpg`
  (`1920 x 1080`, 211,279 bytes, nonblank).

Steven completed and accepted these checks on 2026-07-26:

1. In the open **Review** workspace, look at the bottom **Test Trade Review** pane.
2. Confirm the heading says
   `OFFICIAL SAMPLE • ACTIVE - AWAITING TRADE 1`.
3. Confirm the next line identifies `official-shadow-v1`, the prospective
   FakeBroker fill model, Evidence v1, and a short configuration fingerprint.
4. Confirm progress is `Prospective Shadow Trades: 0 / 30`, every lifecycle count
   is zero, and every performance metric says `Withheld`.
5. Confirm these lines are readable, not clipped, and not overlapping nearby
   filters, counts, or tabs.

This visual decision approves only the wording and layout above. It does not approve
a real order, broker transmission, new account access, score/readiness changes, or
historical backfill.

## R028 Integrated Workstation Chrome

Status: `COMPLETE`; automated and manual proof passed; fast-forwarded into local
`master` through `1d3d8e5` and backed up through `origin/master`

Automated evidence:

- Focused chrome tests pass 4/4, including the supported `PerMonitorV2` project
  declaration and non-elevated application manifest.
- The complete current .NET solution passes 215/215.
- Release compilation with warnings treated as errors passes with zero warnings and
  zero errors.
- The diff is limited to WPF shell chrome, its focused tests, and this required
  Roadmap/verification evidence. No protected product or execution path changed.

Current physical evidence:

- Checks 1, 2, 9, and 11 are `CODEX_UI_PASS` in the first `1180 x 820` render: the
  light Windows strip is absent; identity, navigation, mode, utilities, and caption
  controls share one dark surface; `REVIEW ONLY` remains the single concise global
  state; and the compact row fits without clipping or overlap.
- One R028 WPF process exposes one `Momentum Hunter Workstation` window. The
  Command Palette remains an in-window overlay rather than a taskbar window.
- Checks 1-9 and 11 are `MANUAL_PASS`. Steven confirmed the separate light Windows
  title bar is absent; empty dark-top-bar space supports drag and double-click
  maximize/restore; left/right edge Snap works; all four edges and at least two
  corners resize; minimize and maximize/restore controls work; `Alt+Space` opens the
  Windows system menu; cross-monitor movement works; and restored/maximized layouts
  show no clipped or overlapping top controls.
- Check 10 is `STRUCTURAL_PASS`, `MANUAL_NOT_APPLICABLE`: the one
  `EnvironmentBadge` contains a dormant red `LIVE MONEY` style trigger, but no live
  mode, broker path, or order authority exists to activate it.
- Review build:
  `%LOCALAPPDATA%\MomentumHunter\Builds\R028-integrated-chrome-review\MomentumHunter.Desktop.Wpf.exe`

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

## R029 Canonical WPF Launcher

Status: `COMPLETE`; automated, physical CLI, and Steven manual icon/taskbar proof
passed; fast-forwarded into local `master` through `1d3d8e5` and backed up through
`origin/master`

Automated evidence:

- `run.py` routes to `momentum_hunter.workstation_launcher`, not the legacy Qt app.
- The resolver chooses the checkout's Release WPF executable first and a deliberately
  installed local workstation second.
- Arbitrary `%LOCALAPPDATA%\MomentumHunter\Builds\*` review builds are never selected
  implicitly.
- A missing approved WPF executable fails visibly instead of silently reopening Qt.
- Legacy Qt remains an explicit rollback path through
  `python -m momentum_hunter.app`; normal tracked launchers do not use it.
- Focused launcher/startup tests pass 9/9, full Python discovery passes 679/679,
  all .NET tests pass 215/215, and Release compilation passes with zero warnings
  and zero errors.
- Subsequent physical verification stopped the known legacy Qt and isolated-review
  processes, launched the checkout Release WPF executable through the ordinary
  launcher, and confirmed one responsive top-level `Momentum Hunter Workstation`.
- A second ordinary launch retained the same WPF PID and one top-level window.
- The stale Start Menu shortcut no longer targets the R027 review package. Desktop,
  Startup, and Start Menu launch points now converge on the repository `run.py`
  launcher.
- All 20 obsolete `%LOCALAPPDATA%\MomentumHunter\Builds` review directories were
  removed after confirming no process ran from that root. No old WPF executable
  remains under Momentum Hunter local app data.
- Steven clarified on 2026-07-25 that he liked both previous icon designs; the
  earlier rejection interpretation was wrong. The simpler white-`M`/teal-arrow mark
  is now embedded in the executable and WPF window, loaded by the tray, and assigned
  to the canonical Desktop and Start Menu shortcuts. The original design remains
  preserved in Git as an alternate.

Physical results:

1. `CODEX_VERIFIED`: known legacy Qt and isolated review processes were stopped.
2. `CODEX_VERIFIED`: the ordinary launcher opened the checkout Release WPF
   `Momentum Hunter Workstation`; legacy PySide did not open.
3. `CODEX_VERIFIED`: a second ordinary launch retained the same responsive WPF PID
   and one top-level workstation window.
4. `CODEX_VERIFIED`: the obsolete review-build root contains zero build directories
   and zero WPF executables.
5. `MANUAL_PASS`: Steven confirmed the new taskbar checks pass along with the R028
   set. The current workstation is the only Momentum Hunter taskbar/window identity,
   uses the navy rounded-square white-`M`/teal-arrow icon, and no stale repo-build
   identity remains.

This launcher change grants no credential, OAuth, account, broker, Paper, Live,
order, provider-fetch, sample-start, merge, or push authority.
