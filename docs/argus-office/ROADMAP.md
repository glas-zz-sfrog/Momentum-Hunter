# Momentum Hunter Roadmap

## Authority

This is the single authoritative view of current product position, active work, and next work. Update its `Now` section from Git evidence before a task is reported complete, merged, or blocked.

Supporting records have narrower roles:

- `BRANCH_LEDGER.md` is the detailed Git and branch-evidence record.
- `VERIFICATION_QUEUE.md` is the exact deferred Steven-check list; it does not replace Roadmap state or authorize merges.
- `TASK_LOG.md` and `CHANGELOG_ARGUS.md` are append-only history.
- Historical architecture notes and release reports remain evidence of their original decisions; they do not override this Roadmap.

## Delegated Authority And Interruption Policy

Steven delegates routine nonvisual execution to Codex. Do the work, prove it, integrate it, and back it up without asking Steven to approve an expected result.

Standing authorization includes bounded nonvisual implementation, tests, documentation, read-only external calls, OAuth refresh, expected single-account validation and encrypted immutable binding, deterministic evidence collection, exact confirmation phrases after preconditions pass, task branches, commits, clean fast-forward merges, and non-force pushes.

Steven remains the decision-maker for:

- GUI, layout, interaction, icon, and other visual acceptance.
- Unexpected brokerage state: account count other than one, ending other than `2573`, type other than `CASH`, changed hash, unexpected positions or trading permissions, broader authorization scope, or any condition that could expose another account to reads or future trades.
- Real order transmission, replacement, or cancellation; unattended-live enablement; money movement; destructive data deletion; database migration; credential revocation/rotation/deletion; provider-app deactivation/deletion; paid services; or ambiguous protected-domain semantics.
- Unsafe Git operations: reset, rebase, branch deletion, force-push, non-fast-forward merge, or remote-divergence resolution.

When an anomaly occurs, stop before the consequential action and ask Steven one concrete question that explains the observed state and practical exposure. A software confirmation phrase is an internal interlock, not a recurring CEO approval request.

## Now

Last reconciled: 2026-07-28 for the parallel R035/R036/R037 candle-input and explicit-preview chain while the SHADOW-016 one-time armed-opening baseline remains frozen on synchronized `master` at `1af5b31`. The last completed operational run remains the one-time SHADOW-014 proof-only opening at `4c35181`. The 8:35 AM CT Windows task ran once, exited `0` on attempt 1 of 4, required no retry, and completed its independent outcome update successfully. The task was no longer running at inspection time, had no next run, and its live action exactly matched the exported definition. The action references `official-shadow-v1-selector-proof-bundle-4c35181`, omits `-ArmShadowSelector`, and therefore remained `PROOF_ONLY_UNARMED`.

The opening produced one immutable `shadow` capture, its bound trade-planning report, a live Schwab candidate+SPY/IWM quote proof, and a finalized 12/12 selector proof bundle. Capture, report, and scheduled-task SHA-256 identities match the frozen binding evidence. At finalization, all 12 prerequisite proofs passed semantic and hash verification; the quote ages were `0.571`, `0.370`, and `0.425` seconds, and the independent HTTPS Date clock proof passed with `0.932` seconds absolute skew and `1.235` seconds measurement uncertainty against the five-second gate. A later arm-check correctly rejects that same proof as older than five minutes; this is the intended fail-closed freshness behavior and does not invalidate its persisted proof-only finalization.

The selector arm, frozen selection policy, decision-cycle store, Shadow trade state, report handoff, and Trade 1 are all deterministically absent. `sample-status` remains `ACTIVATED`, `SELECTOR_NOT_ARMED`, automatic collection disabled, transmission unavailable, and `0 / 30`. The semantic handoff is intentionally `NOT_CREATED` in proof-only mode. The Engine Host remained healthy and continued its normal five-minute monitoring cadence; the opening log explicitly records `UNARMED_OPENING_PROOF_ONLY`, so the task did not invoke a selector cycle.

The immutable Schwab binding still decrypts locally as the sole approved ending `2573`, type `INDIVIDUAL_CASH`, with the account hash withheld. The opening quote proof included no account data, requested no positions, balances, or orders, and exposed no transmission capability. No brokerage anomaly was observed. Task Scheduler operational-history logging was disabled, so the audit relies on the scheduler's final result plus the runner's timestamped attempt, outcome, and status logs.

The sanitized completion audit is preserved outside the repository under `ArgusReviewBundles`. Local and remote `master` were synchronized at proof baseline `4c35181`; this reconciliation changes governance only. The one-use inspection heartbeat is retired after the completed audit.

SHADOW-015 closes the three remaining synthetic negative controls with one executable, nonmutating drill. Structured Engine Host failure is blocked before handoff creation, clock skew plus uncertainty above five seconds is blocked, and a still-running opening remains `IN_PROGRESS` without retiring its observer. The production-local run passed `3 / 3`; its ignored JSON and Markdown evidence have SHA-256 `42291D42534F1228CBBCD9F6C22252B2913EE0CBC54F54B01AE93A9FA38A2FC3` and `17A20D69F0EC117A829E1EE8B207F681AB9BA72AF4D22AC27AFDFF063A726D88`. The full protected Shadow directory stayed unchanged with only activation SHA-256 `6980D5734F3F2010D892CD1F3E29354D5DF37B193B082B18A01D8B5D485AD20C`; arm, policy, cycle, state, handoff, and trade remain absent. Compileall, 6 focused tests, 127 adjacent Shadow/Engine Host tests, all 50 bounded backend/evidence/storage modules, and all 914 Python tests pass.

SHADOW-016 closes the scheduler-shape gap before the first armed FakeBroker-only opening. An armed task is now rejected unless it is explicitly Shadow-only, enabled, future-dated, one-time, and scheduled at exactly 8:35 AM local Central time. The one-time task cannot start late when missed, receives zero Task Scheduler retries, and retains only the existing runner-owned initial attempt plus three finite infrastructure retries. A nonmutating plan mode proves the exact task action before registration; the default installer still plans three daily unarmed tasks and leaves Shadow disabled. PowerShell parsing, 3 focused scheduling tests, 130 affected Shadow/Engine Host tests, all 917 Python tests, and all 216 .NET tests pass. The final scheduling closeout binds the 2026-07-29 task to the synchronized commit containing this statement; after integration and backup, a fresh 11-artifact static bundle is prepared from that final head before the task is installed.

R035 is `IMPLEMENTED_PENDING_MERGE` on `codex/ARGUS-R035-candle-input-reconcile-1af5b31`. It adds a bounded, exact-host, GET-only Schwab price-history source; inactive candidate candle staging bound to the persisted monitor-target report; hash-verified read-only `1m`, deterministic `5m`, and `Daily` preview contracts; a read-only legacy cutover inventory; and a one-command preflight that still performs no deletion, SQLite mutation, chart activation, scoring/readiness change, or broker/order action. Self-review hardened the file boundary so the source report and arbitrary existing files cannot be overwritten, refresh is limited to already valid inactive staging artifacts, provider-time concurrent changes fail before staging, and inventory receipts are write-once. Python compileall, 56 focused tests, all 173 Schwab tests, all 973 Python tests, all 216 .NET tests, and a zero-warning Release build pass. Actual cutover remains separately gated and no generated stage/report is tracked.

R036 is `IMPLEMENTED_PENDING_MERGE` and remotely backed up on `codex/ARGUS-R036-staged-candle-preview-host-7cbc2cb`, stacked directly on the verified R035 tip; implementation/hardening closes at `05008f3`. It adds one idempotent `get_staged_schwab_chart_preview` Engine Host command that reads only the default inactive stage and its matching manifest through `StagedSchwabChartService`. The host normalizes the request, returns only the exact bounded chart wire contract, rejects extra account/token fields, malformed candles, invalid chronology/geometry/state counts, unsafe flags, and unverified evidence with sanitized failures. It performs no provider fetch, account read, file write, chart activation, collection cycle, WPF change, or broker/order action. Self-review repaired the valid one-candle `INSUFFICIENT DATA` display boundary. Python compileall, 61 focused host/stage tests, all 980 Python tests, all 216 .NET tests, and a zero-warning Release build pass. No generated artifact is tracked and no Steven visual check is required because no UI consumes the command yet.

R037 is `IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE` on `codex/ARGUS-R037-wpf-staged-candle-preview-02f6423`, stacked directly on the verified R036 tip. The chart still starts on `Stored`; a compact session-only `Staged preview` segment explicitly requests R036 and never persists or activates the preview. The .NET bridge independently requires the exact 13-field top-level wire contract, exact lineage/candle fields, explicit-offset clocks, bounded text and candle counts, ordered OHLCV, state/count consistency, preview-only/inactive flags, exact inactive Schwab lineage, and unavailable order transmission. Expanded account/token-shaped payloads and malformed evidence fail closed. Preview failure remains visibly unavailable with no stored, mock, cross-symbol, or cross-timeframe fallback, and switching back to `Stored` is explicit and reversible. Twenty-one focused .NET tests, all 224 .NET tests, Python compileall, 61 host/stage tests, all 980 Python tests, and a warnings-as-errors Release build pass. Fresh offscreen proof at `1440 x 900` and `1120 x 650` shows both modes without overlap; Steven's exact seven-step visual acceptance remains pending before integration.

The post-freeze integration graph is now explicitly audited. R035, R036, and R037 form one linear chain. SHADOW-017 is a parallel sibling from `1af5b31`; neither it nor R036 contains the other. A read-only merge-tree check finds no overlapping runtime or test path and only four expected governance conflicts: `CHANGELOG_ARGUS.md`, `ROADMAP.md`, `TASK_LOG.md`, and `VERIFICATION_QUEUE.md`. After the operational audit releases `master`, fast-forward R035 and R036 first. Then replay SHADOW-017's six focused commits onto that released baseline on a new reconciliation branch, regenerate the four governance files from observed truth, rerun the combined proof, and fast-forward only the verified result. If SHADOW-017 lands before R037 is visually accepted, replay R037 implementation commit `c5f287a` onto the then-current baseline after acceptance rather than directly merging the old sibling branch. Do not rebase, reset, or create a non-fast-forward merge.

SHADOW-007 status truthfulness is integrated and backed up from `79e75b2` through this closeout. The read-only `sample-status` command now scopes its legacy `PASS` to sample activation only and separately reports `NOT_ARMED`, `automaticCollectionEnabled: false`, `canCollectOfficialTrade: false`, `ACTIVATED_SELECTOR_NOT_ARMED`, and the regular-market quote-proof/bundle gate. The change creates no state and leaves the activation hash and `0 / 30` sample unchanged. Twenty-seven focused tests, 123 adjacent Shadow/Engine Host tests, all 844 Python tests, and all 216 .NET tests pass.

SHADOW-008 proof-bundle assembly is integrated and backed up at `fdcf898`. Quote-proof schema v2 distinguishes `LIVE_SCHWAB_TRADER_API`, `INJECTED_SOURCE`, and unspecified sources; only the normal CLI-created Schwab transport path is marked production. The nontransmitting assembler creates 11 atomic static proof artifacts on synchronized canonical `master` and never calls `selector-arm`, writes policy, creates a cycle or trade, or exposes an order endpoint. SHADOW-009 supersedes the earlier caller-supplied candidate input with report-derived identity and expands the runtime/test evidence, so the retained SHADOW-008 production bundle is stale by design and cannot pass current canonical verification.

| Item | Current truth |
| --- | --- |
| Canonical baseline | Local and remote `master` are synchronized at `1af5b31` with the WPF workstation through R029, Python engine contracts, Shadow-001 through Shadow-016, and SCHWAB-001/002/002A/003 read-only safeguards. The completed proof-only opening remains bound to `4c35181`; the scheduled armed opening remains bound only to the frozen final SHADOW-016 head. |
| Active branch | `codex/ARGUS-R037-wpf-staged-candle-preview-02f6423` is the visual successor stacked on the verified R036 backend and R035 input chain. `codex/ARGUS-SHADOW-016-017-reconcile-1af5b31` separately preserves verified post-opening evidence work; none of these branches moves the frozen scheduled checkout before the operational audit. |
| Shadow sample | `ACTIVATED`; `SELECTOR_NOT_ARMED`; `0 / 30` completed; no selection-policy file, Shadow state, or trade exists; order transmission is `UNAVAILABLE`. |
| Active decision | Use deterministic automatic selection, not operator-selected official trades. The proof-only opening, all three negative controls, and the one-time scheduler guards pass. The 2026-07-29 ceremony may arm only from its newly prepared final-head bundle with a fresh in-window quote/clock proof. Handoff completion remains semantic, clock validity remains a pre-arm/per-decision gate, and thirty trades is an engineering gate rather than proof of edge or live authorization. |
| Blocked by | No unresolved implementation or synthetic-proof gate. The first armed FakeBroker-only collection is operationally time-gated until 2026-07-29 at 8:35 AM CT and must fail closed on any stale proof, Git mismatch, brokerage anomaly, or protected-state change. R035 is merge-deferred only to preserve that frozen checkout; product development is not blocked. |
| Scheduled operational proof | `SCHEDULED_PENDING_RUN`; the prior 2026-07-28 proof-only task passed, SHADOW-015 passed `3 / 3`, and the replacement task is one-time at 2026-07-29 8:35 AM CT with an explicit arm switch and no scheduler recurrence or restart. |
| Immediate operational work | Preserve the final-head static bundle and exact installed-task definition, then inspect the one-time 2026-07-29 opening after its finite runner completes. Do not launch it early, retry a terminal failure, reuse expired proof, synthesize/backfill Trade 1, or bypass fresh quote/clock validation. Keep the verified R035, R036, R037, and SHADOW-017 feature branches backed up. After the audit releases `master`, fast-forward R035 and R036 in ancestry order, reconcile the parallel SHADOW-017 commits onto that released baseline, and integrate the combined nonvisual result only after full proof. R037 additionally waits for Steven's exact visual acceptance and must be replayed onto the then-current baseline if SHADOW-017 lands first. |
| Broker state | Schwab OAuth is active after exact sole-account revalidation; the immutable `2573` `INDIVIDUAL_CASH` binding remains read-only. No preview or transmitting method exists. The previously surfaced, unrotated Client Secret is an explicit blocker for future transmitting code. |
| Steven action | R037 has one queued visual check before merge; it can wait until Steven is available and does not block the operational audit or unrelated nonvisual work. Any brokerage anomaly or real-order proposal remains an interruption gate. |
| Data caveat | Legacy/current persisted bid/ask rows with only monitor-cycle timestamps remain unavailable rather than presumed fresh. The candidate-bound Schwab opening proof passed, but it is point-in-time evidence and expires after five minutes rather than becoming reusable market data. Only `CRWV` has active stored minute candles. R035 can stage and audit actual Schwab candles but cannot activate them; actual-data cutover remains a destructive-operation interruption gate. The frozen early-close table covers 2026-2028 and fails closed beyond it. |

### Status Legend

- `NOT_STARTED`: no implementation has begun.
- `ACTIVE`: work is underway on the named branch.
- `IMPLEMENTED_PENDING_MERGE`: work is committed and verified on a branch but has not yet been integrated. Proven nonvisual work may integrate automatically; visual work waits for Steven's manual acceptance.
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

- Turn scoped findings into bounded Builder tasks with focused tests and protected-path review.
- Preserve scoring, readiness, replay, storage, and execution behavior unless the current task explicitly authorizes a bounded change; interrupt Steven only if scope or semantics must expand.

### Phase 3 - Release Discipline

Status: `COMPLETE`

- Maintain task, branch, decision, quality, and release evidence.
- Require Steven visual acceptance for GUI work. Integrate and non-force-push proven nonvisual work automatically when Git and secret checks are clean.

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

Status: `ACTIVE`; SHADOW-001 through SHADOW-013 and the Schwab read-only foundations are `COMPLETE` on `master`; the official sample is `ACTIVATED`, `SELECTOR_NOT_ARMED`, `OPENING_CEREMONY_UNPROVEN`, and `0 / 30`; A017 is `BLOCKED_VENDOR_CAPABILITY`; every real-order gate remains closed

#### 11A - Shadow Trading Evidence Program

- ARGUS-SHADOW-001 is integrated into local `master` at `bb962be`. It connects frozen current evidence to canonical TradePlan and Risk Governor decisions, conservative quote-driven FakeBroker orders/positions/exits, durable ledger/audit/outcomes, executable P&L/R/MFE/MAE, sample-gated metrics, and a nontransmitting manual paperMoney ticket.
- ARGUS-SHADOW-002 is integrated into local `master` after Steven's explicit fast-forward approval. It adds a read-only WPF review surface over canonical Shadow/FakeBroker evidence; it creates no execution authority and cannot edit completed trades, plans, or risk decisions.
- ARGUS-SHADOW-003 is integrated into local `master` after Steven's explicit fast-forward approval. Implementation `9002df0` freezes sample version, strategy/configuration fingerprint, fill-model version, evidence-schema version, and explicit sample authorization on new records; preserves legacy records without backfill; excludes unauthorized, obsolete, malformed, or mismatched records; gates every aggregate metric path; and exposes a read-only `SAMPLE START LOCKED` audit in WPF.
- Python owns the prospective sample lifecycle and durable evidence. WPF is a bounded review surface only. FakeBroker remains the only automated execution boundary, and every Shadow decision must be prospective.
- Shadow-002 proof visibly shows: `X / 30` eligible completed trades; active, unfilled, rejected, excluded, and invalid states; evidence and plan locks; decision and evidence timestamps; ideal versus estimated executable results; spread/slippage/fill explanation; P&L, R, MFE, MAE, duration, and exit reason; linked Chart, frozen Trade Plan, Why, and History/Activity drill-down; and minimum-sample gating.
- The official sample may start only after Shadow-001 is in the active baseline, Shadow-002 is accepted and integrated, evidence snapshots/TradePlans/Risk decisions are immutable, stable IDs connect candidate/evidence/plan/risk/command/ledger/outcome, duplicate commands and restart duplicates fail closed, P&L/MFE/MAE are reproducible, fill/spread/slippage assumptions are documented and locked, market-session/time-zone behavior is verified, and data-quality eligibility is deterministic.
- Every counted Shadow Trade must record a `SampleVersion`, strategy/configuration fingerprint, fill-model version, and evidence-schema version. Shadow-003 makes these requirements canonical on local `master`; their engineering `PASS` state has no command or side effect that begins sample collection.
- ARGUS-SHADOW-004 adds a CLI-only, write-once activation record for `official-shadow-v1`. It creates no trade, report, ticket, provider request, broker call, or order. Production services load the record automatically; a direct in-memory authorization flag without persisted evidence fails closed.
- The official sample activated at `2026-07-25T18:18:58.477916-05:00` and remains empty at `0 / 30`. Report generation and source capture must both be offset-aware, at or after activation, ordered correctly, and no later than the decision. The June 17 CRWV report was deliberately rejected and left no Shadow state file.
- The activation file is local generated state under ignored `MomentumHunterData`; it is not tracked or pushed. Its immutable SHA-256 is `6980D5734F3F2010D892CD1F3E29354D5DF37B193B082B18A01D8B5D485AD20C`.
- ARGUS-SHADOW-005 makes each successful scheduled capture produce the canonical CSV/JSON/Markdown TradePlan report exactly once. It validates source path, timestamp, session, prospective ordering, and candidate count; refuses partial output sets; verifies the raw capture hash did not change; and can recover the missing derived report on a duplicate scheduled run without rescanning.
- The Finviz scan now reads its required candidate fields from one custom screener response. Quote/news requests remain read-only and bounded separately, preventing the old per-symbol full retry schedule from overrunning the 30-minute Windows task limit.
- Steven approved deterministic automatic selection and rejected operator selection for the official sample. SHADOW-006 implements canonical rank/score/identity ordering and preserves the complete ordered assessment with every rejection reason; Risk Governor remains an eligibility gate rather than a ranker.
- The blanket 30-minute freshness proposal is rejected. The accepted initial matrix is: current selection quote no older than 30 seconds, source capture no older than 10 minutes, report no older than 5 minutes, and report-to-selection delay no longer than 60 seconds. Daily OHLC and catalyst age use separate rules. Missing, future-dated, timezone-ambiguous, or contradictory clocks skip the cycle.
- A production audit found that Active Monitor refreshes report-level `generated_at` even when copied candidate bid/ask values were not fetched again. The observation schema now keeps monitor-cycle time separate from provider quote time/source. Shadow selection, fills, and counterfactuals consume only independently identified provider quote time/source; legacy or current rows without them fail closed as quote unavailable. Alert-cycle timing and alert thresholds are unchanged.
- The canonical baseline includes a read-only Schwab Market Data quote source at the exact `/marketdata/v1/quotes` endpoint. It requests candidates and SPY/IWM once per cycle, uses the oldest provider `bidTime`, `askTime`, and `quoteTime` as executable time, refreshes expired OAuth only through the immutable sole-`2573`-CASH read-only account revalidation path, and records only requested symbol-matched finite evidence. The quote transport has no account endpoint; no order endpoint or transmitting method exists. Live weekend proof parsed the provider response and rejected it as stale, closed, and extended-hours; one canonical in-market 30-second proof remains before arming.
- `docs/argus-office/autonomy/SHADOW_SAMPLE_CONSTITUTION.md` is now `IMPLEMENTED_CANONICAL_NOT_AUTHORIZING`. Runtime and tests implement its ranking, warning severity, freshness, quote boundary, duplicate/portfolio, session, denominator, benchmark, diversity, and hash rules. It still grants no authority to arm or begin Trade 1.
- The compile-time construction switch is replaced by a write-once selector-arm record. Arming requires the exact internal phrase and the complete named set of structured proof artifacts, each bound to the current activation, sample, constitution, runtime build, verification time, and hash-verified evidence. `selector-arm-check` runs that verifier without mutation; `selector-arm` uses the same verifier before creating policy or arm state. Partial proof creates neither policy nor arm state; later source or proof changes invalidate the arm.
- Every armed in-window five-minute Engine Host attempt is a denominator record; restart gaps become `SYSTEM_DOWNTIME`. Reports, stale/data-quality blocks, selections, unfilled/cancelled orders, completions, and failures are counted separately.
- Eligible-candidate, deterministic-random, SPY, and IWM observations are preserved without creating trades. Completed-trade cycles finalize comparable returns at the selected trade exit; open/no-trade cycles remain explicitly mark-to-latest.
- The 30-trade gate releases descriptive metrics only. At least 10 distinct trading sessions are required for broader strategy review, and concentration is reported without altering selection.
- Trade 1 cannot occur from a feature branch or an unbacked local build. SHADOW-004/005 and the hardened selector must be committed, fast-forwarded into canonical `master`, and non-force backed up before the selector can become armed.
- SHADOW-008 provides the production proof-bundle ceremony. Static preparation is atomic and write-once, requires clean synchronized `master`, verifies the accepted SHADOW-004 UI evidence and every named static gate, and creates 11 artifacts without arming. Finalization accepts only schema-v2 live Schwab CLI evidence for the exact candidate plus SPY/IWM, revalidates every hash and context, adds the twelfth artifact, and remains nonmutating. The final arm is still a separate command.
- SHADOW-009 removes caller-selected quote-proof identity: finalization derives the highest canonical-ranked symbol from the newest fresh report, validates its provider/schema/clocks, validates source-capture path/time/session/count/symbol identity, and preserves report/capture/quote bytes plus a hash-bound binding artifact.
- SHADOW-009 adds one distinct immutable `shadow` capture at 9:35 AM ET per XNYS market-open day, followed immediately by the existing Engine Host cycle. The handoff is report-hash-idempotent, retries a complete duplicate report only when its write-once host receipt is missing, and does not rescan, transmit, arm, or create an official trade by itself.
- SHADOW-010 automates the already-authorized nontransmitting arm ceremony before that handoff. It proves canonical Git/static evidence before contacting Schwab, derives the three-symbol quote request from the canonical report, accepts only normal live Schwab quote provenance, finalizes and re-verifies all 12 artifacts, and supplies the existing exact arm confirmation only after the verifier passes. Any failure stops before the selector cycle; an already valid arm is nonmutating and skips market-data work.
- SHADOW-011 fixes proof-clock ordering discovered during the pre-open audit. The quote proof records request start before guarded OAuth/provider work, evaluates freshness after the response, rejects backward or timezone-naive evaluation clocks, and records actual request duration. This changes no freshness threshold and weakens no future-data rejection.
- SHADOW-012's scheduler-native restart design is superseded by SHADOW-013's runner-owned bounded retry classifier. One initial attempt plus three retries occur only for recognized provider/network/host infrastructure failures; terminal policy or evidence failures stop after one attempt.
- SHADOW-013 makes receipt completeness semantic, requires verified host/capture/report/cycle identities, preserves incomplete receipts, adds pre-arm and per-decision clock-skew proof, freezes configuration/task identity, and separates outcome-update status from opening success.
- The default SHADOW-013 scheduled action is proof-only and unarmed. The installer leaves the Shadow task disabled unless explicitly enabled, and the runner omits selector/Engine Host invocation unless the separately explicit arm switch is present. The 8:50 heartbeat is finite, tri-state, and inspection-only.
- Once a sample version starts, it permits no historical backfill, deletion of losers, selective exclusions, scoring/readiness/risk changes, entry/stop/target changes, spread/slippage/fill-model changes, or silent recomputation.
- If a material defect invalidates evidence, preserve the affected sample, close its version, document and fix the defect, and begin a new version. Never rewrite the affected sample into a cleaner result.
- FakeBroker evidence must model and record bid/ask spread, slippage, unfilled and delayed limit fills, supported partial fills, gaps through stops, halted/unavailable states, stale/missing quote rejection, session eligibility, buying power, position concurrency, daily-loss limits, restart recovery, and ambiguous states. Track both ideal setup and estimated executable results; estimated executable result is the primary evidence metric.
- Report evidence checkpoints at 5, 10, 20, and 30 completed eligible trades. Interim reports evaluate mechanics and evidence quality and must not tune the strategy to the developing sample.
- Thirty completed eligible trades is an initial engineering gate, not proof of a durable edge, a profitability claim, or permission to transmit any broker order.

#### 11B - Schwab Read-Only And Canary Preparation

- A016 selected Schwab/thinkorswim continuity. Schwab Support confirmed that Trader API cannot access paperMoney and has no retail sandbox, so A017 is `BLOCKED_VENDOR_CAPABILITY`.
- FakeBroker is the only automated boundary. thinkorswim paperMoney is manual ticket and fill-model reconciliation only; no interim Alpaca path is approved.
- SCHWAB-001/002/002A/003, live `CASH` validation, immutable binding, and bound-refresh safety are integrated. The production app, loopback callback, certificate trust, OAuth, DPAPI vault, and sole `2573` `INDIVIDUAL_CASH` binding are active and read-only.
- Account discovery and validation fail closed on any unexpected account count, suffix, type, hash, position, or permission. Sensitive account and balance values remain suppressed.
- The Client Secret was surfaced to the browser-automation channel during portal research. No credential or token was found in Git, but no rotation occurred. Read-only use continues under the recorded risk; transmitting code is blocked until Schwab supplies rotation, replacement, or explicit vendor remediation.
- The first future real-money gate is a broker-plumbing canary using a boring, liquid, preapproved instrument. A strategy-driven canary is separate and later. Pre-canary, canary-active, and post-canary position invariants must be implemented first.
- Detailed chronology, certificate identifiers, test counts, containment evidence, and remaining gates are preserved in `reports/security/SCHWAB-READONLY-ONBOARDING-AND-CREDENTIAL-INCIDENT.md`.
- No task may ask for a Schwab username, password, or MFA; place credentials/tokens/account hashes in Git or chat; automate thinkorswim; or transmit, replace, or cancel a real broker order without the applicable Steven decision.

#### Standing Authorization And Branch Discipline

- Standing-authorized nonvisual work includes bounded Shadow implementation/repair, evidence collection, 5/10/20/30 reports, manual paperMoney reconciliation artifacts, authenticated read-only Schwab calls, OAuth refresh, exact canary binding when one `2573` CASH account revalidates, broker-preview research that official documentation proves nontransmitting, tests, reports, Roadmap updates, commits, clean fast-forward merges, and non-force pushes.
- Steven checkpoints apply to GUI/visual acceptance and the anomaly/consequence list in this Roadmap. Real broker transmission, destructive data/schema operations, credential or provider-app revocation, paid services, and protected semantic expansion remain interruption gates.
- Keep one active implementation branch and at most one stacked successor. Begin new work from the integrated local baseline. The official Shadow sample may begin automatically after every frozen prerequisite passes; any failed or ambiguous prerequisite interrupts Steven.
- R027 must preserve both validated parents: current Shadow `master` and R026. R026 and TEST-001 become source/audit branches after combined verification; do not rebase or rewrite either history merely for linearity.

### Phase 12 - Incremental Capability Migration And Qt Retirement

Status: `ACTIVE`; R011-R029 plus Shadow-001/002/003 are `COMPLETE` on local `master`; R035 and R036 are `IMPLEMENTED_PENDING_MERGE`; visual successor R037 is `IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE`; remaining Qt retirement stays incremental

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
- Real candle-data cutover has a mandatory destructive-operation interruption gate. The active legacy artifact is `MomentumHunterData/data/opportunity-minute-bars.json`, SHA-256 `DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69`; its current SQLite mirror contains 710 `CRWV` rows tied to that exact path and hash. Immediately before activating an actual candle source, stop and tell Steven the exact deletion targets and effect before removing the legacy JSON or rebuilding mirrored rows. Cutover cannot pass until the old hash is absent from every active candle store, none of the old 710 rows can be queried or rendered, source lineage names the actual provider and fresh timestamp, and regression/UI proof shows no mixed legacy/live candles. Do not delete the legacy data early or treat an archive/backup as an active chart source.
- R035 prepares that future decision without performing it. The canonical reconciliation branch reads Schwab price history through one bounded market-data GET, selects at most 25 symbols from an immutable persisted monitor-target report, stages `1m` and `Daily` bars only under inactive artifacts, maps verified staged data to read-only chart snapshots, and inventories the exact legacy file/SQLite identities using SQLite read-only/query-only mode.
- R035's cutover preflight is evidence, not activation: it binds fresh staged hashes to the source target set and inventory receipt while preserving every source hash. Existing unrelated files, monitor-target sources, active candle filenames, database filenames, changed-during-fetch targets, and prior receipts fail closed. No production chart, WPF contract, database row, score, alert, readiness rule, TradePlan, Shadow sample, account binding, or broker/order path changes.
- R035 passed Python compileall, 56 focused candle tests, 173 Schwab regressions, all 973 Python tests, all 216 .NET tests, a zero-warning Release build, protected-path review, source-hash proof, and secret-risk review. No UI changed, so no Steven visual check is required. Integrate only after the scheduled SHADOW-016 checkout is released.
- R036 exposes the verified inactive stage through one narrow Engine Host command without making it the active chart source. Its exact allowlisted wire payload carries only symbol, interval, state, observation/as-of text, bounded summaries, inactive/nontransmitting flags, source lineage, and at most 180 validated candles. Extra fields, invalid state/count combinations, malformed chronology/geometry, unsafe flags, or unverified staged evidence fail closed.
- R036 passed Python compileall, 61 focused Engine Host/stage tests, all 980 Python tests, all 216 .NET tests, a zero-warning Release build, protected-path review, and secret scan. No WPF consumer or visual change is included, so no Steven action is required. After the operational freeze, integrate R035 first and then R036 by clean fast-forward ancestry. The historical WPF staged-preview commit remains deferred for a separately reviewed visual task, and actual candle cutover remains the destructive-operation interruption gate.
- R037 reconciles that historical WPF idea without inheriting its contaminated branch, stale governance, or screenshots. `Stored` remains the startup/default active chart source. `Staged preview` is a visibly selected, session-only display request across chart panes; a fresh workstation returns to `Stored`.
- R037 independently validates the R036 payload in .NET and rejects expanded account/token fields, noncanonical summaries, timezone-ambiguous timestamps, malformed OHLCV, wrong identity/source/safety flags, unordered candles, and state/count mismatches. Failure shows only staged unavailability and never falls back to stored or mock candles. Switching either direction invokes no provider, account, file, collection, broker, or order path.
- R037 passed 21 focused .NET tests, all 224 .NET tests, Python compileall, 61 focused host/stage tests, all 980 Python tests, a warnings-as-errors Release build, protected-path/secret review, unchanged production hashes, and fresh normal/minimum offscreen UI proof. The exact manual checklist is in `VERIFICATION_QUEUE.md`; do not merge R037 until Steven accepts it. Actual candle activation and legacy-data deletion remain separate and unapproved.
- R028 integrated-workstation chrome is `COMPLETE` on local `master`. The implementation removes the separate light Windows strip and makes app identity, workspace navigation, the single global mode state, and system controls one continuous dark surface through WPF `WindowChrome`. It uses the native caption and resize contract rather than a borderless imitation, routes caption buttons through `SystemCommands`, provides an explicit `Alt+Space` menu path, declares `PerMonitorV2` through the supported project property, and keeps a single dormant red badge treatment for any future separately approved real-money label. Focused tests pass 4/4, all current .NET tests pass 215/215, and the zero-warning Release build passes. Steven manually passed the dark title surface, drag, double-click maximize/restore, left/right Snap, four-edge/two-corner resize, minimize/maximize controls, `Alt+Space`, cross-monitor movement, and restored/maximized no-clipping checks. This visual shell task grants no broker, live-mode, credential, or execution authority.
- R029 canonical WPF launcher and icon are `COMPLETE` and backed up through `origin/master`. `run.py`, the tracked batch/VBS path, the startup script generated by `momentum_hunter.startup`, and the PowerShell helper converge on a resolver that launches only the checkout Release WPF executable or a deliberately installed local workstation. Unmerged review builds are not auto-selected; missing WPF fails visibly; direct legacy Qt startup requires `python -m momentum_hunter.app`. Focused launcher tests pass 9/9, full Python discovery passes 679/679, all .NET tests pass 215/215, and Release compilation passes with zero warnings/errors. Physical verification opened the checkout Release WPF executable, retained one responsive process on a second launch, redirected the stale R027 Start Menu entry, removed all 20 obsolete local review packages, and passed the current icon/tooltip/single-window checks. Git Steward fast-forwarded the verified stack into local `master` through `1d3d8e5`; Steven separately approved the later remote backup.
- Migrate individual proven workflows to the WPF shell only after their Python contracts and operator proof are complete.
- Retire corresponding Qt screens incrementally, with acceptance evidence and rollback paths. Do not perform a broad rewrite.

### Phase 13 - Broker Execution Validation Gate

Status: `BLOCKED_VENDOR_CAPABILITY`

- The future evidence ladder is: (1) FakeBroker prospective Shadow Trading; (2) manual thinkorswim paperMoney ticket/reconciliation; (3) Schwab contract emulator, complete on local `master`; (4) synthetic one-use HTTPS loopback callback, certificate lifecycle, and browser-proof tooling, complete on local `master`; (5) production-local certificate staging, exact CurrentUser trust installation, and browser-warning-free proof, `PASS`; (6) credential onboarding and OAuth, complete on local `master` in SCHWAB-002; (7) standing-authorized Schwab authenticated read-only account discovery; (8) exact single-canary-account isolation proof; (9) broker preview only if official documentation proves a nontransmitting endpoint; (10) a Steven-approved supervised live canary order; (11) reconciliation, audit review, and token-revocation drill; and (12) repeated supervised canary cycles.
- Schwab Trader API cannot access paperMoney and has no retail sandbox. Manual thinkorswim paperMoney reconciliation is evidence collection, not an automated API execution path.
- Authenticated reads and proven nontransmitting preview work may advance automatically when expected invariants hold. Real order transmission never auto-advances and requires a concrete Steven decision after the complete evidence chain is shown.

### Phase 14 - Unattended Live Execution

Status: `BLOCKED`

- Requires a separate explicit Steven decision after repeated supervised-canary evidence, credential and account-isolation controls, reconciliation and independent audit review, token-revocation proof, and a dedicated unattended-live Goal Charter.
- No standing directive may auto-advance into Phase 14.

## Roadmap Update Protocol

At every substantive task closeout, the responsible agent must:

1. Reconcile the `Now` section against `git status --short --branch`, the active branch HEAD, and local `master` versus `origin/master`.
2. Move the affected roadmap phase to the correct status without calling branch-only work `COMPLETE`.
3. Record the concrete next action and any new block or decision gate.
4. Update `BRANCH_LEDGER.md` only when branch/merge/push state changes, and `TASK_LOG.md` or `CHANGELOG_ARGUS.md` as historical evidence requires.
5. Cite the resulting Roadmap transition in the final CEO report.

## Protected Areas

Protected areas require exact task scope and Hard Chew proof. Do not ask again when the current task or Roadmap already authorizes the bounded change. Interrupt Steven before changing protected semantics, transmitting a real order, performing destructive data/schema work, exposing or revoking credentials, or expanding beyond the documented outcome.
