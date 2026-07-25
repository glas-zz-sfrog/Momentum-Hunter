# Momentum Hunter Roadmap

## Authority

This is the single authoritative view of current product position, active work, and next work. Update its `Now` section from Git evidence before a task is reported complete, merged, or blocked.

Supporting records have narrower roles:

- `BRANCH_LEDGER.md` is the detailed Git and branch-evidence record.
- `VERIFICATION_QUEUE.md` is the exact deferred Steven-check list; it does not replace Roadmap state or authorize merges.
- `TASK_LOG.md` and `CHANGELOG_ARGUS.md` are append-only history.
- Historical architecture notes and release reports remain evidence of their original decisions; they do not override this Roadmap.

## Now

Last reconciled: 2026-07-25 after R029 canonical WPF launcher implementation on `codex/ARGUS-R029-canonical-wpf-launcher`, stacked from R028 commit `0e7a6ce` and local `master` `5f156eb`. R027 and SCHWAB-001 remain complete on local `master`; remote `master` remains at `69feedf`, 37 commits behind local, and nothing was pushed. R028 is committed but branch-only pending Steven's deferred window drag/Snap/resize/control/cross-monitor checks and merge approval. R029 corrects the remaining Phase 12 launcher conflict: tracked normal launch paths still entered legacy PySide through `run.py` even though WPF is canonical. Normal launch now resolves only to the checkout's Release WPF executable or a deliberately installed local WPF copy, never an arbitrary review build; missing WPF fails visibly, and legacy Qt remains available only through explicit `python -m momentum_hunter.app`. Focused launcher/startup tests pass 9/9, full Python discovery passes 679/679, all .NET tests pass 214/214, and Release builds with zero warnings and zero errors. No running application was stopped, opened, or focused during R029 verification. No scoring, readiness, replay, alert, database, market-data, broker, order, OAuth, credential, generated-data, or sample state changed. Only `CRWV` has stored minute candles; the future actual-data cutover purge gate remains mandatory. The official evidence sample has not started; `SAMPLE START LOCKED` remains canonical.

| Item | Current truth |
| --- | --- |
| Canonical product baseline | Local `master` contains the Phase 10 foundation, R011-R027 WPF workstation work, ARGUS-SHADOW-001/002/003, the reconciled Shadow/WPF integration, and the credential-free SCHWAB-001 loopback/certificate foundation. Remote `master` remains at `69feedf`. |
| Active product decision | The Windows-first WPF workstation is the accepted operator surface and Python remains the canonical trading and evidence engine. Schwab Trader API is the authenticated read-only and separately supervised-live target. Schwab Support confirmed there is no automated Trader API paperMoney path or retail sandbox; thinkorswim paperMoney is manual Shadow reconciliation only. |
| Integrated implementation | Phases 8, 9, and 10, R011-R027, and ARGUS-SHADOW-001/002/003 are `COMPLETE` on local `master`. SCHWAB-001's listener, certificate lifecycle, browser-proof tooling, installer correction, and physical trust proof are also integrated locally. R028 and R029 remain branch-only. Phase 11 remains `ACTIVE` because the official Shadow sample is locked and broker/OAuth/account gates are not started. A017's automated Schwab paper API path remains `BLOCKED_VENDOR_CAPABILITY`. |
| Git sequencing | `origin/master` remains at `69feedf`; local `master` is 37 commits ahead. R028 is committed at `0e7a6ce` on its branch; R029 is its one permitted stacked successor. Neither branch is merged or pushed. Source/audit branches remain local and unpushed. |
| Merge-base evidence | Pre-merge local `master` `164e32e` was an ancestor of the accepted stacked branch, and the integration used `git merge --ff-only`; no merge commit was created. |
| R004 status | `COMPLETE`: workstation-shell feasibility is integrated into `origin/master`. |
| R005 status | `COMPLETE`: close-to-tray, lifecycle controls, single-instance activation, and physical Windows tray QA are integrated into `origin/master`. |
| Immediate next action | Preserve the verified R029 branch and stop branch growth at the one-successor limit. When Steven is available, verify the deferred R028 window interactions and the R029 normal-launch routing in one short session. Merge and push remain separate decisions. No successor may imply credential, OAuth, account, broker, Paper, Live-money, order, sample-start, merge, or push authority. |
| Remote backup action | Remote `master` remains at `69feedf`; local `master` is 37 commits ahead after the approved local integration. Nothing from R013-R027, SCHWAB-001, or their acceptance evidence has been pushed. A remote backup still requires Steven's separate explicit push approval. |
| Broker and execution state | FakeBroker remains the only automated execution boundary. Schwab `Trader API - Individual` access is approved, and production app `Market Intelligence Workstation` is `Ready For Use` with `Accounts and Trading Production`, `Market Data Production`, callback `https://127.0.0.1:8182/oauth/callback`, and an order-request throttle of `5` per account per minute. SCHWAB-001 adds a credential-free, provider-free, one-use HTTPS receiver plus local root/leaf generation, AES-encrypted PKCS8 leaf keys, DPAPI-protected key-password storage, exact SAN/chain/ACL proof, explicit install/remove trust confirmations, and a synthetic browser trust proof. Production-local version `20260725T004100Z-feaa7bc59097` is trusted only in `CurrentUser\Root` and is browser-verified; its exact-root removal path remains available. The Client ID and Client Secret exist in Schwab but have not been revealed, copied, or stored locally. No OAuth token, account hash, authenticated request, production endpoint client, paper/live broker path, or transmitting method exists. The registered products preserve future order capability, but Paper and Live remain software-locked. |

### Status Legend

- `NOT_STARTED`: no implementation has begun.
- `ACTIVE`: work is underway on the named branch.
- `IMPLEMENTED_PENDING_MERGE`: work is committed and verified on a branch, but Steven has not approved its local merge.
- `COMPLETE`: work is merged into local `master` and verified.
- `BLOCKED`: a stated gate or CEO decision prevents work from starting.
- `BLOCKED_VENDOR_CAPABILITY`: the required broker capability does not exist; implementation cannot proceed by configuration alone.
- `DEFERRED`: valid future work, intentionally not the current priority.

### Roadmap Governance

Status: `COMPLETE`

- The authoritative Roadmap is integrated into `master`; `CURRENT_STATE.md` remains deleted.
- This file is the single live state view; branch history and canonical paths are recorded in their supporting governance files.

## Roadmap

### Phase 0 - Office Scaffold

Status: `COMPLETE`

- Establish agent roles, operating rules, templates, branch policy, and protected-area rules.
- Keep governance separate from product runtime behavior.

### Phase 1 - Read-Only Mapping

Status: `COMPLETE`

- Map critical routes, data flows, scoring surfaces, replay surfaces, alerts, storage, and operator workflows.
- Use maps and audits to identify small, protected implementation slices.

### Phase 2 - Scoped Improvements

Status: `COMPLETE`

- Turn approved findings into bounded Builder tasks with focused tests and protected-path review.
- Preserve scoring, readiness, replay, storage, and execution behavior unless a separate task explicitly approves a change.

### Phase 3 - Release Discipline

Status: `COMPLETE`

- Maintain task, branch, decision, quality, and release evidence.
- Require Steven approval for local merge and explicit approval for push.

### Phase 4 - Automation And Simulation Foundation

Status: `COMPLETE` on `origin/master`

- Use neutral product terminology: Automation, Simulation, Machine Room, Risk Governor, Execution Ledger, Trade Plan, and operator review.
- Keep `Argus` as the Codex builder and office persona, not a product-screen or product-flow name.
- Retain the existing Python simulation foundation: TradePlan, Risk Governor, FakeBroker-only simulation, Execution Ledger, and Execution Auditor.
- Keep every paper and live execution boundary locked.

### Phase 5 - C# WPF Operator-Surface Feasibility

Status: `COMPLETE / DIRECTION ACCEPTED`

- Preserve Python as the canonical engine for research, scoring, readiness, replay, storage, trade planning, risk, and simulation.
- R004 proved the Windows-first WPF workstation shell: docked and floating panes, linked contexts, persistent layouts, recovery behavior, and simulation-only safety language.
- R005 proved close-to-tray behavior, single-instance activation, lifecycle controls, restricted tray commands, and physical Windows tray behavior.
- WPF is the accepted planned operator surface, subject to continued phase-gated validation; it is not a Python-engine rewrite or broker integration.
- Keep Hide, Pause Monitoring, and Exit as separate lifecycle operations. Tray or layout state must never store execution authorization, credentials, API keys, broker permissions, or order-routing permissions.

### Phase 6 - Python Simulation Foundation And Evidence Research

Status: `COMPLETE` on `origin/master`

- `momentum_hunter/autonomy/*`, `trade_planning.py`, and the current Python UI modules remain the canonical implementation on `master`.
- The clean-room simulation foundation and hardening tests are merged on `master`.
- Technical Breakout Research Engine v1 and its daily OHLC source are merged on `master`; they remain research-only and do not alter production scoring or execution behavior.
- The older standalone execution-model branch and earlier simulation branch are superseded; see `BRANCH_LEDGER.md`.

### Phase 7 - WPF Workstation And Background Lifecycle

Status: `COMPLETE`

- R004 and R005 are integrated into `origin/master` at `e14105493061ec133ecd273aaac21d8e33ead5cf`.
- R004 supplied the workstation shell: docked, tabbed, floating, resizable panes; linked chart contexts; saved layouts; SQLite recovery; and simulation-only safety language.
- R005 originally supplied close-to-tray behavior, explicit exit, session-ending behavior, single-instance signaling, restricted tray commands, and an in-process background-collection lifecycle. Physical Windows QA passed.
- Under the original R005 boundary, collection continued only while the hidden WPF process remained alive.
- Phase 8 superseded that hosting limitation. The independent Python Engine Host is now canonical, and a WPF close or crash does not inherently stop it.
- Explicit Exit remains the deliberate joint-shutdown path for the workstation and its managed Python host.

### Phase 8 - Headless Python Engine Through Versioned Contracts

Status: `COMPLETE` on local and remote `master` through `a886c90`

- The approved Goal Charter creates versioned, provider-neutral host identity, health, collection, capability, command, and structured-error contracts.
- `momentum_hunter/engine_host.py` owns the independent loopback-only Python Engine Host. WPF discovers an existing host or launches one, reconnects by host identity, and deliberately shuts it down only on explicit Exit.
- The host has an atomic single-host lease, per-command idempotency, non-overlapping cycle guard, and a guard against the existing active-monitor runner starting a second collection loop.
- The host core owns snapshot, pause, resume, one collection cycle, and graceful shutdown. Phase 9 adds one versioned persisted-evidence snapshot capability; TradePlan, Risk Governor, chart data, simulation, broker, Paper, and Live remain outside the boundary.
- Focused Python process proof and .NET integration proof passed. The implementation fast-forwarded into local `master` and was later backed up through the approved R011 master push. See `reports/releases/ARGUS-R008-python-engine-contract-host.md`.

### Phase 9 - Read-Only Discovery, Research, Health, And Replay Integration

Status: `COMPLETE` on local and remote `master` through `a886c90`

- Connect WPF panes to the Phase 8 read-only boundary for candidates, evidence, research context, health, and replay.
- Preserve source lineage, stale-data language, and read-only replay identity.
- Use the independent engine lifecycle rather than a workstation-owned collection loop.
- The first slice exposes persisted report/status snapshots only and explicitly disables mock TradePlan, chart, risk, and simulation fallback until Phase 10.
- Focused Python tests, focused C# presentation/integration tests, a C#-to-Python host proof, broader nearby Python regression, the full .NET suite, and full Python discovery passed before the Steven-approved local fast-forward.

### Phase 10 - Trade Planning, Risk, And Simulation Integration

Status: `COMPLETE` on local and remote `master` through `a17eff8`

- The versioned Python host exposes a persisted-plan simulation workspace snapshot and a symbol-scoped FakeBroker-only simulation command.
- WPF consumes the canonical persisted TradePlan, Risk Governor, Execution Ledger, and Execution Auditor evidence rather than a mock fallback. R011 adds chart evidence separately and does not alter these planning or simulation contracts.
- A Risk Governor block prevents the simulation call and states that no evidence changed. A permitted simulation records risk, preview, FakeBroker outcome, and audit evidence in the in-memory host ledger.
- Follow-up commits `14fe317` and `893a6da` remove the Top-5-only plan mapping mismatch and the empty Risk Governor badge: all valid persisted candidate plans are exposed, and a missing plan explicitly shows `Plan unavailable` with simulation unavailable rather than a blank colored state.
- Steven accepted the manual visual proof and approved the local merge with real chart candles still explicitly deferred. Release compilation passed; focused Python simulation/autonomy tests passed 29 tests, and the full .NET workstation solution passed 71 tests immediately before merge. Full Python discovery was previously bounded at 120 seconds and did not complete; retain that test-harness timeout as a follow-up risk.

### Phase 11 - Shadow Evidence, Schwab Capability, And Pre-Execution Hardening

Status: `ACTIVE`; ARGUS-SHADOW-001/002/003, R027, and the credential-free SCHWAB-001 loopback/certificate foundation are `COMPLETE` on local `master`; the official sample is `NOT_STARTED`; Schwab A017 is `BLOCKED_VENDOR_CAPABILITY`; Schwab application registration is `COMPLETE`; production-local material is `TRUSTED_VERIFIED`; the physical browser proof is `PASS`; credential onboarding, real OAuth, account access, and broker/order paths remain separately gated and not started

#### 11A - Shadow Trading Evidence Program

- ARGUS-SHADOW-001 is integrated into local `master` at `bb962be`. It connects frozen current evidence to canonical TradePlan and Risk Governor decisions, conservative quote-driven FakeBroker orders/positions/exits, durable ledger/audit/outcomes, executable P&L/R/MFE/MAE, sample-gated metrics, and a nontransmitting manual paperMoney ticket.
- ARGUS-SHADOW-002 is integrated into local `master` after Steven's explicit fast-forward approval. It adds a read-only WPF review surface over canonical Shadow/FakeBroker evidence; it creates no execution authority and cannot edit completed trades, plans, or risk decisions.
- ARGUS-SHADOW-003 is integrated into local `master` after Steven's explicit fast-forward approval. Implementation `9002df0` freezes sample version, strategy/configuration fingerprint, fill-model version, evidence-schema version, and explicit sample authorization on new records; preserves legacy records without backfill; excludes unauthorized, obsolete, malformed, or mismatched records; gates every aggregate metric path; and exposes a read-only `SAMPLE START LOCKED` audit in WPF.
- Python owns the prospective sample lifecycle and durable evidence. WPF is a bounded review surface only. FakeBroker remains the only automated execution boundary, and every Shadow decision must be prospective.
- Shadow-002 proof visibly shows: `X / 30` eligible completed trades; active, unfilled, rejected, excluded, and invalid states; evidence and plan locks; decision and evidence timestamps; ideal versus estimated executable results; spread/slippage/fill explanation; P&L, R, MFE, MAE, duration, and exit reason; linked Chart, frozen Trade Plan, Why, and History/Activity drill-down; and minimum-sample gating.
- The official sample may start only after Shadow-001 is in the active baseline, Shadow-002 is accepted and integrated, evidence snapshots/TradePlans/Risk decisions are immutable, stable IDs connect candidate/evidence/plan/risk/command/ledger/outcome, duplicate commands and restart duplicates fail closed, P&L/MFE/MAE are reproducible, fill/spread/slippage assumptions are documented and locked, market-session/time-zone behavior is verified, and data-quality eligibility is deterministic.
- Every counted Shadow Trade must record a `SampleVersion`, strategy/configuration fingerprint, fill-model version, and evidence-schema version. Shadow-003 makes these requirements canonical on local `master`; their engineering `PASS` state has no command or side effect that begins sample collection.
- Once a sample version starts, it permits no historical backfill, deletion of losers, selective exclusions, scoring/readiness/risk changes, entry/stop/target changes, spread/slippage/fill-model changes, or silent recomputation.
- If a material defect invalidates evidence, preserve the affected sample, close its version, document and fix the defect, and begin a new version. Never rewrite the affected sample into a cleaner result.
- FakeBroker evidence must model and record bid/ask spread, slippage, unfilled and delayed limit fills, supported partial fills, gaps through stops, halted/unavailable states, stale/missing quote rejection, session eligibility, buying power, position concurrency, daily-loss limits, restart recovery, and ambiguous states. Track both ideal setup and estimated executable results; estimated executable result is the primary evidence metric.
- Report evidence checkpoints at 5, 10, 20, and 30 completed eligible trades. Interim reports evaluate mechanics and evidence quality and must not tune the strategy to the developing sample.
- Thirty completed eligible trades is an initial engineering gate, not proof of a durable edge, a profitability claim, or permission to transmit any broker order.

#### 11B - Schwab Read-Only And Canary Preparation

- A016 produced the broker matrix, and Steven selected Schwab/thinkorswim continuity for the eventual read-only and supervised-live direction. An interim Alpaca implementation is not approved.
- Schwab Trader API Support confirmed there is no automated Trader API paperMoney path and no retail sandbox. A017 is therefore `BLOCKED_VENDOR_CAPABILITY`, not awaiting an answer.
- FakeBroker remains the only automated boundary. thinkorswim paperMoney is limited to manual Shadow ticket entry and reconciliation; do not automate thinkorswim or represent the $100 live canary account as paper.
- Schwab `Trader API - Individual` access is approved. Production app `Market Intelligence Workstation` was created on 2026-07-24 and Schwab reports it as `Ready For Use`.
- The registered app includes `Accounts and Trading Production` and `Market Data Production`, preserving eventual account-data, market-data, and supervised order capability. Its order-request throttle is `5` per account per minute. Registration is not permission for Momentum Hunter to transmit an order.
- Schwab registered `https://127.0.0.1:8182/oauth/callback`. This is an intentional loopback callback: after Steven authorizes in the browser, the browser redirects to the listener on the same computer; Schwab does not initiate a public inbound connection to Steven's network.
- SCHWAB-001 implements a one-use TLS 1.2-or-newer HTTPS receiver whose production defaults permit only `127.0.0.1:8182/oauth/callback`. It requires an explicit certificate/key pair, validates the exact path and Host header, compares a high-entropy state value, rejects missing/duplicate/mismatched/error callbacks and unsupported methods, applies bounded connection and authorization timeouts, suppresses request logging and Python server-version disclosure, and closes after success, terminal rejection, malformed handling, manual close, or timeout.
- Synthetic proof opens the exact registered address, completes a callback through a client that explicitly trusts the synthetic certificate, and confirms the port is closed before and after. It also proves duplicate use is refused, wrong paths do not consume the valid callback, keep-alive cannot delay closure, a stalled TLS handshake cannot hold the listener open, callback objects redact code/state from `repr`, response bodies do not echo code/state, and the listener imports no provider, broker, account, or order client. Focused tests pass 19/19; final compileall and full Python discovery pass 653/653.
- The Windows certificate lifecycle generates a five-year local root and a one-year server leaf limited to SANs `127.0.0.1` and `localhost`; never persists the root private key; writes only an AES-256-encrypted PKCS8 leaf key; stores its random password in current-user DPAPI; verifies exact certificate hashes, validity, hostname, chain, TLS handshake, and current-user-only explicit ACLs; versions material; refuses untrusted material by default; and requires exact confirmation phrases for install/remove. The production installer uses Windows `certutil -user -f -addstore Root`, waits up to five minutes for the mandatory visible Windows root warning, verifies the exact thumbprint afterward, skips reinstall when already trusted, and attempts exact-thumbprint rollback after a failed new install. Passwords never enter the trust-install command.
- Production-local certificate version `20260725T004100Z-feaa7bc59097` is active at the default Local AppData path outside Git. Root SHA-1 is `E35BB94F68A98BFCADB6E69ACD63961BBE3AA76F`, root SHA-256 is `C926D9F89B5E5D11BF3179B04D4D7928A0325AD8514064E9658D05BB8045BEA1`, and leaf SHA-256 is `74B38DE72175834B325EDDF17C9BA1A934543A525D7831A609C2876BC618DA3E`. Its leaf is valid from `2026-07-25T00:36:00Z` through `2027-07-25T00:41:00Z`. Exactly one matching root exists in `CurrentUser\Root`, has no private key, and the encrypted key, DPAPI secret, ACL, chain, hostname, and local TLS checks return `TRUSTED_VERIFIED`.
- Steven confirmed the Windows warning displayed the exact root name and full SHA-1 before clicking Yes. Chrome then opened the synthetic callback without a privacy interstitial and displayed only `Momentum Hunter received the local authorization response. You may close this browser tab.` The callback output returned `BROWSER_TRUST_PROOF_PASSED`; port `8182` closed after one request; credentials, OAuth, and broker flags remained false. Compileall passes, focused Schwab tests pass 47/47, and full Python discovery passes 672/672. No dependency, package, database, scoring, readiness, alert, trade-planning, broker, order, WPF, or generated-data path changed.
- Local HTTPS trust is ready, but a real OAuth attempt is not authorized by this pass. The listener is not wired to credential onboarding, an authorization URL, token exchange, token storage, account discovery, or WPF. Those remain separate checkpoints. The Schwab app remains modifiable if official runtime behavior requires a callback correction.
- Schwab has issued a Client ID and Client Secret, but neither has been revealed, copied, or stored locally. When credential onboarding is separately authorized, credentials must move directly from Schwab into Windows DPAPI-protected current-user storage and must never appear in Git, chat, command history, screenshots, logs, reports, or generated data.
- No OAuth token, account hash, authenticated request, production network client, or transmitting method exists. The $100 canary account is not connected or bound.
- Existing Schwab preparation code remains network-free and nontransmitting. OAuth/account access, exact canary-account binding, authenticated reads, preview, and order transmission remain separate checkpoints.
- No task may ask for a Schwab username, password, or MFA; store a Client ID/Secret in Git or chat; automate thinkorswim; or transmit Paper or Live orders without the applicable explicit checkpoint.

#### Standing Authorization And Branch Discipline

- After the current Shadow directive and Roadmap reconciliation, bounded Shadow pipeline implementation/repair, Shadow review improvements, gated evidence collection, 5/10/20/30 checkpoint reports, manual paperMoney reconciliation, credential-free Schwab contracts/fixtures, tests, reports, Roadmap updates, and sample-safe WPF migration are standing-authorized.
- Master merge/push, consequential Git integration, real OAuth/account access, Client credentials/tokens, authenticated Schwab requests, transmitting broker methods, protected-domain semantic changes, database migrations, and paid dependencies/data still require separate Steven approval.
- Keep one active implementation branch and at most one stacked successor. R027 and SCHWAB-001 are now integrated into local `master`; begin R028 from that exact local baseline on a new task branch. No official sample collection may begin until Steven separately authorizes the exact sample definition.
- R027 must preserve both validated parents: current Shadow `master` and R026. R026 and TEST-001 become source/audit branches after combined verification; do not rebase or rewrite either history merely for linearity.

### Phase 12 - Incremental Capability Migration And Qt Retirement

Status: `ACTIVE`; R011-R027 plus Shadow-001/002/003 are `COMPLETE` on local `master`; R028 and R029 are branch-only; remaining Qt retirement stays incremental

- R011 adds one versioned `get_chart_snapshot` host command backed only by stored `opportunity-minute-bars.json` and `daily-ohlc-bars.json` evidence.
- WPF renders `1m`, deterministically aggregated `5m`/`15m`, and `Daily` candles with bodies, wicks, and volume. Source lineage and `AVAILABLE`, `STALE`, `INSUFFICIENT_DATA`, or `UNAVAILABLE` state remain visible.
- Missing intraday evidence never falls back to daily or mock candles. No provider call, background fetch, or source-data write was added.
- Candidate, interval, linked-pane, and pinned-pane context are covered by tests. The full CLI-only WPF proof shows CRWV with 143 stored stale 5-minute candles, source/as-of text, simulation-only language, and paper/live locks.
- Steven approved R011; Git Steward fast-forwarded it into local `master` without a merge commit and backed it up to `origin/master` under separate explicit push approval.
- R012 adds deterministic nice price ticks, chronological UTC time ticks, and a latest stored-bar OHLCV strip without changing the chart contract or Python engine.
- R012 focused tests passed 14 tests, the complete .NET suite passed 88 tests, Release compilation passed with zero warnings, and the offscreen WPF proof shows readable axes/details while preserving source lineage, simulation-only language, and paper/live locks.
- R012 was accepted, fast-forwarded, and pushed with local and remote `master` synchronized at `69feedf`.
- R013 through R025 remain preserved on R026 and are fully integrated with the current Shadow baseline on local `master` through Steven-authorized R027.
- R027 preserves Shadow snapshot/start/advance commands, automatic post-collection observation, read-only Shadow Review, sample lock, and FakeBroker-only boundaries alongside technical research, saved watchlist, Daily Workflow, Candidate Story, Research Maturity, command palette, chart inspection, health, replay, monitoring, activity, and alert/outcome evidence.
- R027 passed Python compileall, full discovery at 672/672, 163 presentation tests, all 210 .NET tests, zero-warning Release compilation, no-live-capability and protected-path review, source-nonmutation checks, and fresh UI proof. Manual review passed the required `CRWV` / `5m` candle and hover cases and provisionally accepted the current Trade Plan evidence tabs pending broader market data. Repair commit `f84106a` and palette repair `cd09f1b` resolved clipped interval text, meaningless sync labels, no-op pane actions, unrecoverable pane removal, and focus-loss dismissal. Live Windows verification confirms the truthful palette miss, complete Current pane menu, Research Maturity opening, single global mode treatment, first-class `Test Trade Review`, final compact toolbar, and persistence of the palette/query across a Codex-to-workstation focus round-trip. The palette is inside the main window and creates no second taskbar or Alt+Tab window. Steven manually accepted the final visual check and explicitly authorized the local fast-forward merge.
- Real candle-data cutover has a mandatory legacy-data purge gate. The active legacy artifact is `MomentumHunterData/data/opportunity-minute-bars.json`, SHA-256 `DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69`; its current SQLite mirror contains 710 `CRWV` rows tied to that exact path and hash. Immediately before activating an actual candle source, a separately approved cutover task must stop chart readers, verify the exact deletion targets, remove the legacy JSON from the active data path, remove or rebuild the mirrored legacy rows without changing schema, clear process/chart caches, load only the new source, and restart readers. Cutover cannot pass until the old hash is absent from every active candle store, none of the old 710 rows can be queried or rendered, source lineage names the actual provider and fresh timestamp, and regression/UI proof shows no mixed legacy/live candles. Do not delete the legacy data early or treat an archive/backup as an active chart source.
- R028 integrated-workstation chrome is branch-only and `ACTIVE` on `codex/ARGUS-R028-integrated-workstation-chrome`, pending manual interaction QA and merge approval. The implementation removes the separate light Windows strip and makes app identity, workspace navigation, the single global mode state, and system controls one continuous dark surface through WPF `WindowChrome`. It uses the native caption and resize contract rather than a borderless imitation, routes caption buttons through `SystemCommands`, provides an explicit `Alt+Space` menu path, declares `PerMonitorV2` through the supported project property, and keeps a single dormant red badge treatment for any future separately approved real-money label. Focused tests pass 4/4, all .NET tests pass 214/214, and the zero-warning Release build passes. The initial `1180 x 820` render fits without clipping and exposes one workstation window; Steven deliberately deferred physical drag/Snap/resize/control/cross-monitor proof. This visual shell task grants no broker, live-mode, credential, or execution authority.
- R029 canonical WPF launcher is implemented and verified on the stacked branch `codex/ARGUS-R029-canonical-wpf-launcher`. `run.py`, the tracked batch/VBS path, the startup script generated by `momentum_hunter.startup`, and the PowerShell helper now converge on a resolver that launches only the checkout Release WPF executable or a deliberately installed local workstation. Unmerged review builds are not auto-selected; missing WPF fails visibly; direct legacy Qt startup requires `python -m momentum_hunter.app`. Focused tests pass 9/9, full Python discovery passes 679/679, all .NET tests pass 214/214, and Release compilation passes with zero warnings/errors. Existing running windows were deliberately untouched while Steven used the computer.
- Migrate individual proven workflows to the WPF shell only after their Python contracts and operator proof are complete.
- Retire corresponding Qt screens incrementally, with acceptance evidence and rollback paths. Do not perform a broad rewrite.

### Phase 13 - Broker Execution Validation Gate

Status: `BLOCKED_VENDOR_CAPABILITY`

- The future evidence ladder is: (1) FakeBroker prospective Shadow Trading; (2) manual thinkorswim paperMoney ticket/reconciliation; (3) Schwab contract emulator, complete on local `master`; (4) synthetic one-use HTTPS loopback callback, certificate lifecycle, and browser-proof tooling, complete on local `master`; (5) production-local certificate staging, exact CurrentUser trust installation, and browser-warning-free proof, `PASS`; (6) separately authorized credential onboarding and OAuth; (7) Schwab authenticated read-only integration; (8) exact single-canary-account isolation proof; (9) broker preview only if official documentation proves a nontransmitting endpoint; (10) a separately approved supervised live canary; (11) reconciliation, audit review, and token-revocation drill; and (12) repeated supervised canary cycles.
- Schwab Trader API cannot access paperMoney and has no retail sandbox. Manual thinkorswim paperMoney reconciliation is evidence collection, not an automated API execution path.
- No automatic transition into authenticated access, broker preview, or supervised live testing is authorized. Each applicable ladder step requires its own evidence and Steven checkpoint.

### Phase 14 - Unattended Live Execution

Status: `BLOCKED`

- Requires separate explicit Steven approval after repeated supervised-canary evidence, credential and account-isolation controls, reconciliation and independent audit review, token-revocation proof, and a dedicated unattended-live Goal Charter.
- No standing directive may auto-advance into Phase 14.

## Roadmap Update Protocol

At every substantive task closeout, the responsible agent must:

1. Reconcile the `Now` section against `git status --short --branch`, the active branch HEAD, and local `master` versus `origin/master`.
2. Move the affected roadmap phase to the correct status without calling branch-only work `COMPLETE`.
3. Record the concrete next action and any new block or decision gate.
4. Update `BRANCH_LEDGER.md` only when branch/merge/push state changes, and `TASK_LOG.md` or `CHANGELOG_ARGUS.md` as historical evidence requires.
5. Cite the resulting Roadmap transition in the final CEO report.

## Protected Areas

Do not change core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior without explicit approval.
