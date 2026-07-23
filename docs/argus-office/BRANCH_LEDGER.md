# Branch Ledger

Date reconciled: 2026-07-23

## Current Truth

Local `master` is the canonical merged product baseline for Momentum Hunter. It contains the Python automation and simulation foundation, Technical Breakout Research Engine v1, daily OHLC source support, the R004 WPF workstation shell, R005 tray/lifecycle work, the independent Python Engine Host, Phase 9 read-only workstation integration, Phase 10 persisted TradePlan/Risk Governor/FakeBroker simulation integration, R011 read-only WPF chart candles, and R012 chart readability through `69feedf Add WPF chart readability`. Steven explicitly approved the R012 fast-forward and master push; local and remote `master` are synchronized at `69feedf`.

Git evidence at reconciliation time:

- Local and remote `master` are synchronized at `69feedf46c6e2c94499d4256b63b355f1619bf14`.
- Steven approved R012, and the task branch fast-forwarded locally with no merge commit before the approved master push.
- `codex/ARGUS-R012A-momentum-hunter-app-icon` starts from synchronized `master` at `69feedf`; its original icon integration is preserved but its artwork is superseded by R012B after Steven's visual-quality rejection.
- `codex/ARGUS-R012B-momentum-hunter-icon-redesign` builds from R012A and is automatically verified at `37e92c4`, but Steven rejected its white-`M`/teal-arrow artwork. Preserve its integration mechanics only; do not merge the branch.
- `codex/ARGUS-R013-wpf-chart-inspection` is separately verified through `29dd27d`, unpushed, and unmerged.
- `codex/ARGUS-R014-wpf-command-palette` is automatically verified at `8ca111b`, unpushed, and unmerged.
- `codex/ARGUS-REVIEW-R012B-R014-combined-ui` integrates the three preserved branches for one operator review build; combined compile/tests/proof pass through `271d0ca`, but the included R012B artwork is rejected. It is unpushed, unmerged, and not a merge candidate.
- `codex/ARGUS-R015-wpf-candidate-evidence` starts from synchronized `master` at `69feedf`; selected-candidate Why/Research evidence, tests, proof, and a versioned review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R016-wpf-health-diagnostics` starts from synchronized `master` at `69feedf`; read-only health projection, tests, two-viewport proof, and a versioned review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R017-wpf-replay-context` starts from synchronized `master` at `69feedf`; read-only replay identity projection, tests, two-viewport proof, and a versioned review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R018-wpf-monitoring-status` starts from synchronized `master` at `69feedf`; read-only background-monitoring projection, lifecycle tests, degraded-state proof, and a versioned review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R019-wpf-activity-events` starts from synchronized `master` at `69feedf`; read-only activity-event projection, insertion/order tests, two-viewport proof, and a versioned review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R020-wpf-alert-outcome-evidence` starts from synchronized `master` at `69feedf`; schema-v2 read-only alert/outcome mapping, source-integrity tests, two-viewport proof, and a versioned review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R021-wpf-technical-research-evidence` starts from synchronized `master` at `69feedf`; a separate read-only host command, source-validated technical-event/outcome projection, source-integrity proof, two-viewport proof, and a versioned review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R022-wpf-saved-watchlist-evidence` starts from synchronized `master` at `69feedf`; a separate read-only host command, source-ordered latest saved-watchlist projection, source-integrity proof, two-viewport proof, and a versioned review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R023-wpf-daily-workflow-evidence` starts from synchronized `master` at `69feedf`; unchanged extracted Python guidance, a separate read-only host command, strict WPF Daily Workflow projection, 8,666-file source-integrity proof, two-viewport proof, and an isolated review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R024-wpf-candidate-story-evidence` starts from synchronized `master` at `69feedf`; a separate read-only host command, canonical trusted Candidate Story projection, strict WPF mapping, 76-file source-integrity proof, two-viewport proof, and an isolated review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R025-wpf-research-maturity-evidence` starts from synchronized `master` at `69feedf`; a separate read-only host command, strict persisted maturity/census projection, fail-closed strategy-lock validation, source-integrity proof, two-viewport proof, and an isolated review build pass on branch HEAD. It is unpushed and unmerged.
- `codex/ARGUS-R026-wpf-phase12-clean-room-integration` starts from synchronized `master` at `69feedf` and cleanly integrates the R013 through R025 implementations as 13 commits through `a263311`. Python compileall, 115 bounded Python tests, 194 .NET tests, zero-warning Release build, all packaged host commands, 8,982-file source-integrity proof, and a six-frame WPF proof pass. It excludes rejected icon artwork and remains unpushed and unmerged.
- `codex/ARGUS-A016S-schwab-paper-api-verification` is branch-only through `c979866`; its official support request is sent, but no A017 implementation gate has opened.
- `codex/ARGUS-R011-wpf-chart-candle-integration` starts from `a17eff8`; its implementation and proof are merged into `master`, and commit `268f3f8` is remotely backed up through `origin/master`.
- `codex/ARGUS-R012-wpf-chart-readability` is merged and backed up through `origin/master` at `69feedf`.
- R004 and R005 are integrated through the `d3a98d9` and `e141054` history; their historical feature branches remain preserved but are not active work bases.

The Roadmap is the current-status authority. This ledger records branch evidence and classification only.

## Known Commit Containment

| Commit | Meaning | Local `master` contains? |
| --- | --- | --- |
| `ed94997` | Guard Daily Checklist quick actions | Yes |
| `c749e05` | Add guided Daily Workflow stepper | Yes |
| `18f3bf6` | Add Git Steward agent | Yes |
| `b8ecc92` | Add Goal Steward charter system | Yes |
| `4c004a1` | Add subagent artifact-first work contracts | Yes |
| `e04dffa` | Add autonomous platform foundation | Yes |
| `3365dea` | Add Hard Chew Protocol governance | Yes |
| `9ece892` | Add gateway and Argus Machine console skeleton | Yes |
| `e82b63e` | Add app.py responsibility map and extraction targets | Yes |
| `0ac66e0` | Extract Gateway and Argus Machine UI module | Yes |
| `664381d` | Add clean-room simulation proof | Yes |
| `4d63655` | Add technical breakout research engine | Yes |
| `1180315` | Add daily OHLC source for breakout research | Yes |
| `d3a98d9` | Integrate authoritative roadmap with R004 workstation shell | Yes |
| `e141054` | Preserve floating layout on explicit exit | Yes |
| `30c0e0b` | Reconcile roadmap after R004 and R005 integration | Yes |
| `6f853ba` | Harden Python host unavailable state | Yes |
| `a886c90` | Add read-only workstation integration | Yes |
| `180d69f` | Integrate WPF simulation workspace | Yes |
| `14fe317` | Fix simulation workspace plan mapping | Yes |
| `893a6da` | Clarify unavailable TradePlan state | Yes |
| `7efd48d` | Reconcile Phase 10 follow-up state | Yes |
| `a17eff8` | Record Phase 10 local integration | Yes |
| `268f3f8` | Add read-only WPF chart candles | Yes |
| `69feedf` | Add WPF chart readability | Yes |
| `a263311` | R026 integrated Phase 12 implementation through Research Maturity | No; R026 branch-only |
| `6f4c26e` | Add Momentum Hunter application icon | No; branch-only |
| `4c1c1ab` | Add WPF nearest-candle inspection | No; branch-only |
| `8ca111b` | Add WPF command palette quick actions | No; branch-only |
| `271d0ca` | Add combined Phase 12 UI review proof | No; review branch only |

## Branch Classifications

| Branch | HEAD | Pushed? | Merged to local `master`? | Classification | Purpose | Next action |
| --- | --- | --- | --- | --- | --- | --- |
| `master` | `69feedf` | Yes; synchronized with `origin/master` after Steven's explicit approval | Yes | `ACTIVE` | Canonical merged Python engine, WPF operator surface, independent host, read-only evidence, FakeBroker-only Phase 10 simulation, R011 chart candles, and R012 chart readability. | Review R026 as the sole current Phase 12 merge candidate, choose R012C artwork separately, and keep broker work blocked at A017 pending Schwab evidence. |
| `codex/ARGUS-R026-wpf-phase12-clean-room-integration` | `a263311` plus this governance/proof closeout | No | No | `NEEDS_REVIEW` | Clean integration of R013-R025 runtime/test/proof work with reconciled contracts and layout schema, rejected icon excluded, complete automated proof, and one isolated operator build. | Steven performs the consolidated R026 checklist, then explicitly approves or rejects local fast-forward merge and push. |
| `codex/ARGUS-R025-wpf-research-maturity-evidence` | `5f0d36c` | No | No | `SUPERSEDED` | Separate read-only host and WPF projection of persisted research-maturity and evidence-census reports with distinct denominators, strategy-lock validation, evidence gates, census counts, questions, and no collection or action path. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R024-wpf-candidate-story-evidence` | `37a0778` | No | No | `SUPERSEDED` | Separate read-only host and linked WPF Candidate Story projection of canonical trusted replay rows and existing story classification, preserving chronology, source facts, later annotations, and explicit partial/unavailable states without actions or source mutation. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R023-wpf-daily-workflow-evidence` | `22eac54` | No | No | `SUPERSEDED` | Extracts the existing Daily Workflow guidance without behavior changes and projects exact persisted source/context/counts/readiness/next-action/five-step evidence into a read-only WPF pane with no action controls. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R022-wpf-saved-watchlist-evidence` | `8fd9b72` | No | No | `SUPERSEDED` | Separate read-only host and WPF Watchlist-pane projection of the newest persisted saved-watchlist artifact, preserving source order, stored values, truthful source states, and no mutation or actions. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R021-wpf-technical-research-evidence` | `756fbd2` | No | No | `SUPERSEDED` | Separate read-only host and WPF Research-pane projection of stored technical-breakout events and outcome studies, with truthful source states, bounded detail, no mutation, and no production-signal integration. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R020-wpf-alert-outcome-evidence` | `1475c41` | No | No | `SUPERSEDED` | Schema-v2 read-only projection of persisted opportunity-alert states and stored outcomes into the Review workspace without recalculation or mutation. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R019-wpf-activity-events` | `9cb3f8b` | No | No | `SUPERSEDED` | Read-only WPF disclosure of existing Activity event UTC time, category, scope, health state, and message without changing event production, order, or persistence. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R018-wpf-monitoring-status` | `1137a02` | No | No | `SUPERSEDED` | Read-only WPF projection of monitoring lifecycle state, summary/detail, symbol/cycle counts, UTC completion time, and explicit no-automation boundary. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R017-wpf-replay-context` | `b642aa9` | No | No | `SUPERSEDED` | Read-only WPF projection of exact replay ID, source state, symbol, interval, UTC as-of time, summary, and explicit no-mutation boundary. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R016-wpf-health-diagnostics` | `89952aa` | No | No | `SUPERSEDED` | Read-only WPF Diagnostics projection of aggregate and per-component engine health state, summaries, UTC checks, unavailable states, and a usable scrollable pane. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R015-wpf-candidate-evidence` | `a9f27c7` | No | No | `SUPERSEDED` | Persisted selected-candidate catalyst, readiness, liquidity, quality, lineage, and opportunity-note disclosure in WPF Why/Research tabs with explicit unavailable states and pinned-plan consistency. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R012B-momentum-hunter-icon-redesign` | `37e92c4` plus governance reconciliation | No | No | `DO_NOT_USE` | Reusable generator and icon wiring wrapped around white-`M`/teal-arrow artwork that failed Steven's visual review. | Do not merge; reuse only the integration mechanics on a clean R012C artwork branch. |
| `codex/ARGUS-R012A-momentum-hunter-app-icon` | `9a15f7b` | No | No | `SUPERSEDED` | Established executable/window/tray/shortcut icon integration, but the original target/candlestick artwork failed Steven's visual-quality review. | Do not merge; reuse the proven wiring only through a clean R012C replacement. |
| `codex/ARGUS-R013-wpf-chart-inspection` | `29dd27d` | No | No | `SUPERSEDED` | Nearest-candle crosshair inspection with exact UTC/OHLCV details and primary/secondary chart parity. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-R014-wpf-command-palette` | `86c54c4` | No | No | `SUPERSEDED` | Symbol quick-open, partial candidate filtering, real palette actions, visible failure states, and responsive toolbar controls. | Preserve as an R026 source/audit branch; do not merge individually while R026 is under review. |
| `codex/ARGUS-REVIEW-R012B-R014-combined-ui` | `271d0ca` plus governance reconciliation | No | No | `DO_NOT_USE` | Noncanonical integration of R012B, R013, and R014 whose automated proof passed but whose included icon failed visual review. | Do not merge as a unit; review R013 and R014 separately and replace the icon on R012C. |
| `codex/ARGUS-R012-wpf-chart-readability` | `69feedf` | Commit backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Deterministic WPF chart price/time axes and latest stored-bar OHLCV details with no engine or provider change. | Historical integration branch; retain the deferred physical checklist in `VERIFICATION_QUEUE.md`. |
| `codex/ARGUS-R011-wpf-chart-candle-integration` | `268f3f8` | No branch ref; commit is backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Versioned read-only local chart snapshots and WPF candle/wick/volume rendering with explicit stale/unavailable behavior. | Historical integration branch; begin R012 from `master`. |
| `codex/ARGUS-A016S-schwab-paper-api-verification` | `c979866` | No | No | `ACTIVE` | Schwab paper API evidence gate and verified support request. | Await and preserve official response; do not begin A017. |
| `codex/ARGUS-A016-broker-research-matrix` | `90259e4` | No | No | `NEEDS_REVIEW` | Broker matrix plus Steven's Schwab/thinkorswim continuity decision. | Preserve under A016S; review before any local merge. |
| `codex/ARGUS-R010-tradeplan-risk-simulation-integration` | `7efd48d` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Persisted TradePlan and Risk Governor evidence, FakeBroker-only simulation, ledger/auditor results, and explicit unavailable-plan handling in WPF. | Historical integration branch; start Phase 11 from local `master`. |
| `codex/ARGUS-R009-readonly-workstation-integration` | `a886c90` (stacked from `6f853ba`) | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Read-only persisted Python candidates, evidence, health, source lineage, and Replay context in WPF; mock planning/chart/simulation fallback disabled. | Historical integration branch; Phase 10 must branch from local master. |
| `codex/ARGUS-R008-python-engine-contract-host` | `6f853ba` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Independent local Python Engine Host, versioned WPF lifecycle bridge, duplicate guards, and process-level proof. | Historical integration branch; Phase 10 must branch from local master. |
| `codex/ARGUS-R004-momentum-hunter-wpf-shell-spike` | `5bbd0c7` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Windows-first WPF workstation-shell feasibility spike. | Historical branch; do not continue feature work here. |
| `codex/technical-confluence-wave-1-primitives` | `9678c5` | Yes | No | `NEEDS_REVIEW` | Research-only technical confluence primitives. | Review separately; it is not the current workstation-shell priority. |
| `codex/technical-indicator-registry-confluence-roadmap-v1` | `2af99da` | Yes | No | `NEEDS_REVIEW` | Indicator registry and confluence planning artifacts. | Keep as research planning; do not treat it as production behavior. |
| `codex/ARGUS-STATE-002-roadmap-reconciliation` | `ccfb7a0` | Yes | No | `SUPERSEDED` | Earlier roadmap reconciliation attempt. | Do not merge; replaced by the authoritative Roadmap reconciliation. |
| `codex/ARGUS-STATE-003-authoritative-roadmap` | `48d3ab4` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Established the authoritative Roadmap that was integrated through R004/R005 history. | Historical governance branch. |
| `codex/ARGUS-INTEGRATE-roadmap-r004` | `d3a98d9` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Integrated the authoritative Roadmap with R004 workstation history. | Superseded as an active work base by `master`. |
| `codex/ARGUS-R005-background-tray-lifecycle` | `e141054` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Close-to-tray, lifecycle controls, single-instance signaling, and R005 physical QA fixes. | Historical branch; Phase 8 must start from a new branch. |
| `codex/ARGUS-A006-A015-clean-room-verification` | `664381d` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Clean-room cherry-pick verification branch for simulation foundation; source of local fast-forward merge. | Keep as audit branch; do not continue feature work here. |
| `codex/ARGUS-A006-A015-argus-machine-simulation` | `91da577` | No | No by commit identity; content superseded by clean-room cherry-picks on `master` | `SUPERSEDED` | Original simulation foundation workstream. | Do not use for future work; use `master` or a new task branch. |
| `codex/ARGUS-A004-A005-tradeplan-risk-governor` | `8a90e18` | Yes | No | `SUPERSEDED` | Older standalone `momentum_hunter/execution/*` TradePlan/RiskGovernor experiment. | Do not merge as-is; see salvage note below. |
| `codex/ARGUS-A002-A003-gateway-machine-console-skeleton` | `52474fe` | Yes | No | `SUPERSEDED` | Earlier Gateway / Argus Machine skeleton branch. | Do not use; replaced by `codex/ARGUS-A002A...`, R002 extraction, and current `master`. |
| `codex/ARGUS-A002A-gateway-machine-console-hardening` | `9ece892` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Hardened Gateway / Argus Machine skeleton. | Historical branch only. |
| `codex/ARGUS-R002-extract-gateway-machine-ui` | `0ac66e0` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Extracted Gateway / Argus Machine UI into `momentum_hunter/ui/autonomy_gateway.py`. | Historical branch only. |
| `codex/ARGUS-R001-app-py-responsibility-map` | `e82b63e` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | `app.py` responsibility map and extraction targets. | Historical branch only. |
| `codex/ARGUS-R000-rewrite-refactor-decision-spike` | `b27013b` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Rewrite/refactor decision spike. | Historical branch only. |
| `codex/ARGUS-FI-001-future-ideas-autonomy-ui` | `008ac9a` | Yes | No | `PUSHED_FEATURE_BRANCH` | Future ideas parking lot for autonomy/UI. | Needs Steven/ChatGPT review before cherry-pick or merge; not canonical. |
| `codex/subagent-work-contracts` | `4c004a1` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Artifact-first subagent work contracts. | Historical branch only. |
| `codex/ARGUS-A000A-hard-chew-protocol` | `3365dea` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Hard Chew Protocol governance. | Historical branch only. |
| `codex/ARGUS-A000-autonomous-platform-foundation` | `e04dffa` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Autonomous platform foundation docs. | Historical branch only. |
| `codex/ARGUS-0005A-goal-steward-verify` | `b8ecc92` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Goal Steward and Goal Charter system. | Historical branch only. |
| `codex/ARGUS-0005-git-steward-agent` | `18f3bf6` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Git Steward agent and branch safety rules. | Historical branch only. |
| `codex/ARGUS-0004-guided-daily-workflow-stepper` | `c749e05` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Guided Daily Workflow stepper bridge. | Historical branch only. |
| `codex/ARGUS-0003-guided-daily-workflow-design` | `eee0ab3` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Guided Daily Workflow design report. | Historical branch only. |
| `codex/ARGUS-0002-daily-checklist-visibility` | `ed94997` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Daily Checklist visibility and quick-action guards. | Historical branch only. |
| `codex/ARGUS-0000-office-scaffold` | `319244b` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Argus Office scaffold and discovery report. | Historical branch only. |

## A004/A005 Supersession Finding

`codex/ARGUS-A004-A005-tradeplan-risk-governor` is superseded.

Evidence:

- It is listed by `git branch --no-merged master`.
- Its branch-only diff adds `momentum_hunter/execution/__init__.py`, `momentum_hunter/execution/trade_plan.py`, `momentum_hunter/execution/risk_governor.py`, `tests/test_trade_plan.py`, and `tests/test_risk_governor.py`.
- Current local `master` does not use `momentum_hunter/execution/*`.
- Current canonical implementation uses `momentum_hunter/trade_planning.py` for `TradePlan` / `TradePlanRow` and `momentum_hunter/autonomy/*` for Risk Governor, ledger, broker adapter, simulation engine, and auditor.

Salvage note:

- Do not merge A004/A005 as-is.
- The branch may be useful only as historical reference for isolated tests or naming ideas.
- Any salvage must be manually ported into the canonical `trade_planning.py` / `autonomy/*` architecture under a new task, with tests proving no duplicate model path is introduced.

## Do Not Use For New Work

Do not start new implementation from:

- `codex/ARGUS-A006-A015-argus-machine-simulation`
- `codex/ARGUS-A004-A005-tradeplan-risk-governor`
- `codex/ARGUS-A002-A003-gateway-machine-console-skeleton`

Use a fresh task branch from local `master` instead.
