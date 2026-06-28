# ARGUS-A000 Autonomous Platform Foundation

## Executive Summary
ARGUS-A000 establishes the autonomous-side foundation for Momentum Hunter / Argus without changing application code. The target product shape is a two-door gateway: Steven Desk for human-guided momentum operations, and Argus Machine for autonomous planning, simulation, paper trading, broker awareness, and future gated execution. This packet defines the machine console, safety modes, Top 5 Trade Plan Candidates, Trade Plan Ladder, Risk Governor, Broker Adapter path, Execution Ledger, autonomous agent roles, and the first follow-up task sequence.

## Two-Door Gateway Concept
Momentum Hunter should eventually open to two large choices:
- Steven Desk: the current human-guided dashboard path.
- Argus Machine: the autonomous planning and supervision path.

The gateway must make the boundary obvious. Steven Desk keeps the present operator workflow. Argus Machine opens a controlled machine room where plans can be generated, simulated, audited, and eventually routed through strict broker gates.

## Steven Desk Definition
Steven Desk is the human-led operations surface. Steven reviews candidates, checklist state, watchlist readiness, and trade context, then decides what to do. Existing scoring, readiness, replay, alert, and dashboard behavior remain protected.

## Argus Machine Definition
Argus Machine is the autonomous-side surface. It observes available market/candidate data, proposes structured TradePlans, ranks candidate setups, runs simulations, tracks risk gates, and records auditable machine activity. It must never imply a live order is approved unless a future Steven-approved live execution task explicitly implements that state.

## Simulation Lab Mode
Simulation Lab is the first machine mode. It uses historical or captured data to evaluate TradePlans without broker connectivity. Output is analysis-only and must be labeled as simulated.

## Paper Trading Mode
Paper Trading uses a paper broker or isolated fake broker path to test order lifecycle behavior without real capital. All paper actions require TradePlan linkage, Risk Governor status, and ledger recording.

## Live Trading Locked Mode
Live Trading starts locked. It may be visible as a future mode, but controls must remain disabled until Steven explicitly approves a separate live-trading implementation task.

## Machine Status Bar
The status bar should show current mode, data freshness, broker connection class, Risk Governor status, execution lock state, and last machine event. In early builds it may use placeholders, but labels must clearly say placeholder, simulated, paper, read-only, preview, or live-locked.

## Candidate Queue
The Candidate Queue is the broader ordered set of machine-observed setups. It can later feed the Top 5 area. The queue should show ticker, setup label, source, data freshness, and whether a candidate can produce a TradePlan.

## Top 5 Trade Plan Candidates
The console must include a visible Top 5 Trade Plan Candidates area. It should show the five highest-priority candidate trade plans, with ticker, setup label, status, and risk/gate state when available. Each ticker must be clickable and should populate the Trade Plan Ladder for that candidate. Labels should use terms like Top 5 Setups, Top 5 Trade Plan Candidates, or Top 5 Machine Plans. Avoid "Strongest Trades" until Risk Governor and paper outcomes prove that wording.

## Selected Candidate Workbench
The workbench is the context area for the selected ticker. It should show setup evidence, source data state, plan generation state, manual notes, and any warnings that prevent a plan from becoming actionable.

## Trade Plan Ladder
The Trade Plan Ladder is the structured plan panel for the selected candidate. It must include ticker, setup type, entry trigger, entry/limit price, invalidation or hard stop, Target 1, Target 2, Target 3, trailing stop rule, position size, max dollar risk, risk/reward, manual override state, and Risk Governor status. Machine-filled values should be labeled as machine-generated. Steven edits should mark the field as a manual override and require Risk Governor re-check.

## Risk Governor Panel
The Risk Governor panel explains whether a TradePlan is blocked, needs review, simulation-only, paper-eligible, preview-only, or approved by the currently allowed mode. It owns gate definitions and safety review, not order placement.

## Order Console
The Order Console is locked by default. Early versions may show disabled preview controls, but must not route broker orders. Future versions can progress from preview to confirmed execution only through separate approved tasks.

## Machine Log
The Machine Log records notable autonomy events: candidate ranked, plan generated, plan edited, risk gate run, broker state read, paper order simulated, paper order submitted, order preview generated, and execution blocked.

## Execution Ledger
The Execution Ledger is the durable audit trail for simulated, paper, preview, and future live execution activity. Every future order-like action must reference a TradePlan, risk gate result, mode, approval state, and timestamp.

## Broker Adapter Abstraction
Broker integration must sit behind a Broker Adapter abstraction. The console should know the adapter class and mode, not direct broker details. Broker adapters progress from fake to paper to read-only live to preview to confirmed execution.

## FakeBrokerAdapter Phase
FakeBrokerAdapter is the first adapter phase. It supports simulated order lifecycle behavior without external broker connectivity, secrets, or real capital.

## Paper Broker Phase
The paper broker phase connects to a broker paper environment only after separate approval. It must use paper credentials, paper labels, isolated ledgers, and explicit mode status.

## Read-Only Live Broker Phase
Read-only live broker mode can observe account and position state but cannot place, modify, or cancel orders. It exists to validate account awareness and risk context before any live order preview.

## Live Order Preview Phase
Live order preview may prepare a broker-compatible order payload without transmitting it. It must show exactly what would be sent and require explicit Steven confirmation before any future send behavior is implemented.

## Confirmed Live Execution Phase
Confirmed live execution is a future locked phase. It requires explicit Steven approval, fresh Risk Governor pass, TradePlan linkage, approval state, execution ledger write, and broker adapter safety checks.

## Supervised Automation Phase
Supervised automation can eventually monitor candidates, refresh TradePlans, and propose order previews. It should remain supervised until separate CEO approval allows narrower autonomous actions.

## Safety Gates Required Before Any Broker Execution
Before any broker execution path exists, Argus must have:
- Explicit Steven approval for the live execution task.
- Broker adapter abstraction and mode lock.
- TradePlan object with required fields.
- Risk Governor result attached to the TradePlan.
- Execution Ledger writes before and after order-like actions.
- UI language that distinguishes simulated, paper, read-only, preview, and live.
- Tests for gate failures and disabled execution states.
- No secrets committed to the repo.
- Kill switch or mode lock visible to Steven.

## First 20 Autonomous Tasks
| ID | Task | Branch | Scope |
| --- | --- | --- | --- |
| ARGUS-A001 | Gateway and Machine Console Product Spec Review | codex/ARGUS-A001-gateway-machine-console-spec-review | Docs only |
| ARGUS-A002 | Build Gateway Shell | codex/ARGUS-A002-build-gateway-shell | App code and focused UI tests |
| ARGUS-A003 | Build Argus Machine Console Skeleton | codex/ARGUS-A003-machine-console-skeleton | App code and focused UI tests |
| ARGUS-A004 | TradePlan Object Spec and Model | codex/ARGUS-A004-tradeplan-object-model | Docs, model code, tests |
| ARGUS-A005 | Risk Governor Spec and First Gate Engine | codex/ARGUS-A005-risk-governor-first-gates | Docs, simulation-only gate code, tests |
| ARGUS-A006 | FakeBrokerAdapter Spec and Stub | codex/ARGUS-A006-fake-broker-adapter-stub | Docs, fake adapter code, tests |
| ARGUS-A007 | Execution Ledger Schema Design | codex/ARGUS-A007-execution-ledger-schema-design | Docs only unless schema approved |
| ARGUS-A008 | Simulation Lab Prototype | codex/ARGUS-A008-simulation-lab-prototype | App code, no broker |
| ARGUS-A009 | Top 5 Candidate Ranking Data Contract | codex/ARGUS-A009-top5-candidate-contract | Docs, view model tests |
| ARGUS-A010 | Manual Override and Recheck Flow | codex/ARGUS-A010-manual-override-recheck-flow | App code, Risk Governor tests |
| ARGUS-A011 | Machine Log Display | codex/ARGUS-A011-machine-log-display | App code, UI tests |
| ARGUS-A012 | Paper Trading Adapter Plan | codex/ARGUS-A012-paper-trading-adapter-plan | Docs only |
| ARGUS-A013 | Paper Trading Adapter Skeleton | codex/ARGUS-A013-paper-trading-adapter-skeleton | Code, tests, no live credentials |
| ARGUS-A014 | Read-Only Broker Awareness Plan | codex/ARGUS-A014-readonly-broker-awareness-plan | Docs only |
| ARGUS-A015 | Read-Only Broker Adapter Skeleton | codex/ARGUS-A015-readonly-broker-adapter-skeleton | Code, tests, no order methods |
| ARGUS-A016 | Live Order Preview Spec | codex/ARGUS-A016-live-order-preview-spec | Docs only |
| ARGUS-A017 | Live Order Preview Skeleton | codex/ARGUS-A017-live-order-preview-skeleton | Code, tests, no transmit |
| ARGUS-A018 | Execution Audit Review | codex/ARGUS-A018-execution-audit-review | Review docs/tests |
| ARGUS-A019 | Autonomous Mode Lock QA | codex/ARGUS-A019-autonomy-mode-lock-qa | QA tests and report |
| ARGUS-A020 | CEO Live Execution Readiness Review | codex/ARGUS-A020-live-execution-readiness-review | Docs only |

## Push/Merge Policy For Autonomous Work
Master must not be pushed by agents. Autonomous feature branches may be pushed only when the task explicitly allows it, changed files are inside approved paths, acceptance criteria pass, and the worktree is clean. No PR is created unless Steven asks. No merge happens unless Steven explicitly approves.

## First 5 Follow-Up Tasks In Detail

### ARGUS-A001 - Gateway and Machine Console Product Spec Review
Goal ID: ARGUS-A001.
Goal name: Gateway and Machine Console Product Spec Review.
CEO intent: Review and refine this foundation into a CEO-approved product direction.
Branch name: `codex/ARGUS-A001-gateway-machine-console-spec-review`.
Allowed file areas: `docs/argus-office/**` and `.codex/**` if agent metadata needs clarification.
Protected areas: all app code, tests, package files, database/schema files, generated data, broker/order execution, runtime behavior.
Agents required: Goal Steward, Git Steward, UI Operator Designer, Risk Governor Agent, Execution Architect, Release Scribe.
Implementation allowed: no.
Tests required: no automated tests; run `git diff --check` and changed-path verification.
Commit policy: one docs/config commit if acceptance criteria pass.
Push policy: no push unless Steven explicitly approves.
Merge policy: no merge unless Steven explicitly approves.
Acceptance criteria: CEO questions are resolved or logged; gateway language is approved; Machine Console panel list is approved; Top 5 and ladder language does not imply live approval; broker roadmap remains safety-gated.
Stop conditions: product direction is ambiguous, Steven requests live execution scope, or protected areas would need edits.

### ARGUS-A002 - Build Gateway Shell
Goal ID: ARGUS-A002.
Goal name: Build Gateway Shell.
CEO intent: Momentum Hunter opens to two large buttons: Steven Desk and Argus Machine.
Branch name: `codex/ARGUS-A002-build-gateway-shell`.
Allowed file areas: app UI files needed for navigation, focused tests, and docs/release notes.
Protected areas: scoring logic, readiness logic, replay identity, historical capture selection, database/schema, broker/order execution, alert thresholds, secrets, production configs, runtime behavior outside the gateway.
Agents required: Goal Steward, Git Steward, Code Mapper, UI Operator Designer, Builder, QA Regression, Release Scribe.
Implementation allowed: yes.
Tests required: focused UI/navigation tests proving Steven Desk opens the current dashboard and Argus Machine opens a placeholder console.
Commit policy: one scoped commit after tests pass.
Push policy: no push unless Steven explicitly approves.
Merge policy: no merge unless Steven explicitly approves.
Acceptance criteria: startup shows two clear choices; Steven Desk preserves current dashboard path; Argus Machine opens placeholder Machine Console; no broker/scoring/readiness behavior changes.
Stop conditions: current app entrypoint is ambiguous, gateway requires protected behavior changes, or tests cannot prove existing dashboard access remains intact.

### ARGUS-A003 - Build Argus Machine Console Skeleton
Goal ID: ARGUS-A003.
Goal name: Build Argus Machine Console Skeleton.
CEO intent: Add the first visible machine room with placeholder panels.
Branch name: `codex/ARGUS-A003-machine-console-skeleton`.
Allowed file areas: app UI/view-model files for placeholder console, focused UI tests, docs/release notes.
Protected areas: broker/order execution, scoring/readiness semantics, database/schema, replay identity, secrets, production configs, runtime behavior outside the console shell.
Agents required: Goal Steward, Git Steward, UI Operator Designer, Execution Architect, Risk Governor Agent, Builder, QA Regression, Release Scribe.
Implementation allowed: yes.
Tests required: UI tests proving all required panels render and disabled/placeholder states are explicit.
Commit policy: one scoped commit after tests pass.
Push policy: no push unless Steven explicitly approves.
Merge policy: no merge unless Steven explicitly approves.
Acceptance criteria: Machine Status Bar, Top 5 Trade Plan Candidates, Selected Candidate Workbench, Trade Plan Ladder, Risk Governor, Order Console, and Machine Log render; live order controls are disabled or absent; no live data is required.
Stop conditions: skeleton work drifts into real broker integration, scoring changes, or hidden runtime behavior.

### ARGUS-A004 - TradePlan Object Spec and Model
Goal ID: ARGUS-A004.
Goal name: TradePlan Object Spec and Model.
CEO intent: Establish the structured plan object that every machine action will reference.
Branch name: `codex/ARGUS-A004-tradeplan-object-model`.
Allowed file areas: docs/specs, app model/module files for TradePlan if approved by mapping, focused unit tests.
Protected areas: broker/order execution, database/schema unless separately approved, scoring semantics, alert thresholds, secrets, production configs.
Agents required: Goal Steward, Git Steward, Code Mapper, Execution Architect, Risk Governor Agent, Builder, QA Regression, Release Scribe.
Implementation allowed: yes.
Tests required: unit tests for required fields, manual override flagging, status defaults, and serialization if implemented.
Commit policy: one scoped commit after tests pass.
Push policy: no push unless Steven explicitly approves.
Merge policy: no merge unless Steven explicitly approves.
Acceptance criteria: TradePlan includes ticker, setup type, entry trigger, entry/limit, stop, targets, trailing rule, size, max risk, risk/reward, manual override state, Risk Governor status, mode, approval state, and audit identifiers; no broker send behavior exists.
Stop conditions: schema/database changes appear necessary without approval, live broker semantics are requested, or required fields cannot be represented cleanly.

### ARGUS-A005 - Risk Governor Spec and First Gate Engine
Goal ID: ARGUS-A005.
Goal name: Risk Governor Spec and First Gate Engine.
CEO intent: Add the first safety gate layer over TradePlan while remaining simulation/display-only.
Branch name: `codex/ARGUS-A005-risk-governor-first-gates`.
Allowed file areas: docs/specs, simulation-only gate code, focused unit/UI tests, release notes.
Protected areas: live broker execution, alert thresholds, production configs, secrets, database/schema unless approved, scoring semantics unless explicitly approved.
Agents required: Goal Steward, Git Steward, Risk Governor Agent, Execution Architect, Security Reviewer, Builder, QA Regression, Release Scribe.
Implementation allowed: yes.
Tests required: gate-pass/gate-fail unit tests and UI tests proving blocked states cannot appear as approved live trades.
Commit policy: one scoped commit after tests pass.
Push policy: no push unless Steven explicitly approves.
Merge policy: no merge unless Steven explicitly approves.
Acceptance criteria: Risk Governor evaluates required TradePlan fields, max dollar risk presence, manual override recheck requirement, mode compatibility, and approval state; output is display-only/simulation-only; no broker methods are called.
Stop conditions: implementation requires live broker calls, persistent schema changes without approval, or unclear maximum-risk rules.

## Questions For Steven
- Should the first gateway replace startup immediately or appear behind a temporary command/menu path?
- Should Argus Machine initially show placeholder data, current dashboard candidates, or only a locked empty state?
- What account/risk assumptions should the first Risk Governor use for simulation-only checks?
- Which broker or trading platform should drive the paper/read-only roadmap first?
- What language should the UI use for plans that are interesting but not approved?

## Recommended CEO Decision
Approve ARGUS-A001 as the next docs-only review so Steven and ChatGPT can lock the product language before Builder opens the app shell in ARGUS-A002.
