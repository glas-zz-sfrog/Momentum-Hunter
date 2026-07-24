# Branch Ledger

Date reconciled: 2026-07-24

## Current Truth

Local `master` at `164e32e` remains the canonical merged product baseline. It contains the Python automation/simulation foundation, R004-R012 workstation foundation, and ARGUS-SHADOW-001/002/003. Local `master` is ten commits ahead of `origin/master` at `69feedf`; R027 has not changed master and nothing was pushed.

Git evidence at reconciliation time:

- Steven approved the local fast-forward of `codex/ARGUS-SHADOW-002-wpf-shadow-review`.
- Local `master` contains ARGUS-SHADOW-001 through `bb962be` and ARGUS-SHADOW-002 implementation `7fee390` plus governance closeout.
- Steven approved the local fast-forward of `codex/ARGUS-SHADOW-003-sample-readiness-gate`; local `master` contains implementation `9002df0`, verification `bb7aec6`, and this merge-state closeout.
- Remote `master` remains at `69feedf46c6e2c94499d4256b63b355f1619bf14`.
- ARGUS-SHADOW-001's matching feature branch is remotely backed up at `bb962be`; ARGUS-SHADOW-002 is not pushed.
- `codex/ARGUS-A016T-schwab-paper-api-response` records Schwab's live-only, no-paperMoney, no-sandbox answer on a separate unmerged branch. A017 is blocked by vendor capability.
- `codex/ARGUS-R026-wpf-phase12-clean-room-integration` consolidates R013-R025 on a separate unmerged review branch and is not part of ARGUS-SHADOW-001.
- Steven authorized `codex/ARGUS-R027-integrate-r026-with-shadow-baseline` to reconcile current master `164e32e` with R026 `838ed22` without rewriting either parent; combined automated verification now passes and the branch awaits Steven's manual check.
- `safety/ARGUS-R027-before-r026-integration` preserves pre-integration master `164e32e`.
- `codex/ARGUS-TEST-001-unattended-qt-discovery` remains preserved at `03ab813`; its two test files are identical to R026 `838ed22` and are included in R027 through the R026 parent.
- R013-R025 remain individually preserved and are source/audit branches for R026/R027, not separate merge candidates.
- `codex/ARGUS-R011-wpf-chart-candle-integration` starts from `a17eff8`; its implementation and proof are merged into `master`, and commit `268f3f8` is remotely backed up through `origin/master`.
- `codex/ARGUS-R012-wpf-chart-readability` is merged and remotely backed up through `69feedf`.
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
| `54c58a8` | Map Shadow Trading lifecycle wiring | Yes |
| `5d11f02` | Build prospective Shadow Trading validation | Yes |
| `7fee390` | Add WPF Shadow Trading review surface | Yes |
| `9002df0` | Add Shadow sample readiness gate | Yes |
| `a263311` | R026 integrated Phase 12 implementation through Research Maturity | No; R026/R027 branch history only |
| `838ed22` | Harden unattended Qt test discovery on R026 | No; R026/R027 branch history only |

## Branch Classifications

| Branch | HEAD | Pushed? | Merged to local `master`? | Classification | Purpose | Next action |
| --- | --- | --- | --- | --- | --- | --- |
| `master` | `164e32e` | No; `origin/master` remains at `69feedf` | Yes | `ACTIVE` | Canonical Python engine, WPF operator surface, Shadow lifecycle/review, and versioned sample-readiness gate. | Remain unchanged until R027 completes and Steven separately approves integration. |
| `codex/ARGUS-R027-integrate-r026-with-shadow-baseline` | Two-parent integration of `164e32e` plus `838ed22` | No | No | `ACTIVE`; `IMPLEMENTED_PENDING_MERGE` product state | Preserves current Shadow lifecycle/review/sample lock while adding the R013-R025 read-only WPF stack and exact R026 test hardening. | Steven runs the R027 checklist, then separately approves or rejects local master integration. |
| `safety/ARGUS-R027-before-r026-integration` | `164e32e` | No | Points to current master | `DO_NOT_USE` | Safety pointer for the pre-R027 canonical baseline. | Preserve until R027 is resolved and reviewed. |
| `codex/ARGUS-TEST-001-unattended-qt-discovery` | `03ab813` | No | No | `SUPERSEDED` | Independent copy of the same two Qt test fixes carried by R026 `838ed22`; R027 full discovery passes 641/641. | Preserve as audit evidence; do not merge separately. |
| `codex/ARGUS-SHADOW-003-sample-readiness-gate` | `9002df0`, `bb7aec6`, plus this merge-state closeout | No | Yes | `MERGED_TO_LOCAL_MASTER` | Immutable sample/config/fill/evidence metadata, fail-closed eligibility and readiness audit, gated metrics, and read-only locked WPF proof. | Preserve locally as audit history. Merge approval did not authorize official trade 1 or a push. |
| `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit` | `bb962be` | Yes; feature branch only | Yes | `MERGED_TO_LOCAL_MASTER` | Prospective frozen-evidence Shadow Trading, quote-driven FakeBroker lifecycle/outcomes, durable audit/metrics, manual paperMoney ticket, and network-free Schwab read-only preparation. | Preserve as remotely backed-up audit history. |
| `codex/ARGUS-SHADOW-002-wpf-shadow-review` | `fe3326d` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Read-only WPF Shadow review, strict identity-chain audit, filters, linked review panes, and minimum-sample metric gating. | Preserve locally; next work starts from local `master`, not this branch. |
| `codex/ARGUS-R026-wpf-phase12-clean-room-integration` | `838ed22` | No | No | `SUPERSEDED` | Consolidated R013-R025 WPF implementation and unattended Qt test hardening; source parent for the verified R027 integration. | Preserve as immutable audit history; review R027 instead of merging R026 directly. |
| `codex/ARGUS-R025-wpf-research-maturity-evidence` | `5f0d36c` | No | No | `SUPERSEDED` | Read-only research-maturity/evidence-census projection with fail-closed strategy locks. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R024-wpf-candidate-story-evidence` | `37a0778` | No | No | `SUPERSEDED` | Linked read-only Candidate Story projection over canonical persisted evidence. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R023-wpf-daily-workflow-evidence` | `22eac54` | No | No | `SUPERSEDED` | Read-only Daily Workflow guidance and evidence pane. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R022-wpf-saved-watchlist-evidence` | `8fd9b72` | No | No | `SUPERSEDED` | Read-only persisted saved-watchlist projection. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R021-wpf-technical-research-evidence` | `756fbd2` | No | No | `SUPERSEDED` | Read-only technical-breakout event and study projection. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R020-wpf-alert-outcome-evidence` | `1475c41` | No | No | `SUPERSEDED` | Read-only persisted alert/outcome evidence. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R019-wpf-activity-events` | `9cb3f8b` | No | No | `SUPERSEDED` | Full read-only activity event disclosure. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R018-wpf-monitoring-status` | `1137a02` | No | No | `SUPERSEDED` | Read-only monitoring lifecycle disclosure. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R017-wpf-replay-context` | `b642aa9` | No | No | `SUPERSEDED` | Exact read-only replay identity disclosure. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R016-wpf-health-diagnostics` | `89952aa` | No | No | `SUPERSEDED` | Read-only component health diagnostics. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R015-wpf-candidate-evidence` | `a9f27c7` | No | No | `SUPERSEDED` | Persisted candidate Why/Research evidence disclosure. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R014-wpf-command-palette` | `86c54c4` | No | No | `SUPERSEDED` | Symbol quick-open and real pane actions with visible failure states. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R013-wpf-chart-inspection` | `29dd27d` | No | No | `SUPERSEDED` | Nearest-candle hover inspection with UTC/OHLCV detail. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-A016T-schwab-paper-api-response` | `1bc90a8` | No | No | `NEEDS_REVIEW` | Preserves Schwab Support's live-only, no-paperMoney, no-sandbox response and broker decision consequences. | Keep A017 blocked; preserve as branch evidence. |
| `codex/ARGUS-R012-wpf-chart-readability` | `69feedf` | Commit backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Deterministic WPF chart price/time axes and latest stored-bar OHLCV details with no engine or provider change. | Historical integration branch. |
| `codex/ARGUS-R011-wpf-chart-candle-integration` | `268f3f8` | No branch ref; commit is backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Versioned read-only local chart snapshots and WPF candle/wick/volume rendering with explicit stale/unavailable behavior. | Historical integration branch; begin R012 from `master`. |
| `codex/ARGUS-A016S-schwab-paper-api-verification` | `c979866` | No | No | `SUPERSEDED` | Schwab paper API evidence gate and verified support request. | Preserve as sent-request history; A016T records the answer. |
| `codex/ARGUS-A016-broker-research-matrix` | `90259e4` | No | No | `SUPERSEDED` | Broker matrix plus Steven's original Schwab/thinkorswim continuity decision. | Preserve as research history; A016T records the vendor constraint. |
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
