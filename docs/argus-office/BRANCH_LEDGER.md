# Branch Ledger

Date reconciled: 2026-07-23

## Current Truth

Local `master` is the canonical merged product baseline for Momentum Hunter. It contains the Python automation and simulation foundation, Technical Breakout Research Engine v1, daily OHLC source support, the R004 WPF workstation shell, R005 tray/lifecycle work, the independent Python Engine Host, Phase 9 read-only workstation integration, Phase 10 persisted TradePlan/Risk Governor/FakeBroker simulation integration, R011 WPF chart candles, and R012 chart readability through `69feedf Add WPF chart readability`. Local and remote `master` are synchronized.

Git evidence at reconciliation time:

- Current task branch: `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit`.
- Local and remote `master` are synchronized at `69feedf46c6e2c94499d4256b63b355f1619bf14`.
- ARGUS-SHADOW-001 starts from `69feedf`; its audit `54c58a8` and implementation `5d11f02` are pushed only to the feature branch and are not merged.
- `codex/ARGUS-A016T-schwab-paper-api-response` records Schwab's live-only, no-paperMoney, no-sandbox answer on a separate unmerged branch. A017 is blocked by vendor capability.
- `codex/ARGUS-R026-wpf-phase12-clean-room-integration` consolidates R013-R025 on a separate unmerged review branch and is not part of ARGUS-SHADOW-001.
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
| `54c58a8` | Map Shadow Trading lifecycle wiring | No; feature branch only |
| `5d11f02` | Build prospective Shadow Trading validation | No; feature branch only |

## Branch Classifications

| Branch | HEAD | Pushed? | Merged to local `master`? | Classification | Purpose | Next action |
| --- | --- | --- | --- | --- | --- | --- |
| `master` | `69feedf` | Yes; synchronized with `origin/master` | Yes | `ACTIVE` | Canonical merged Python engine, WPF operator surface, independent host, read-only evidence, FakeBroker-only Phase 10 simulation, R011 chart candles, and R012 readability. | Review ARGUS-SHADOW-001 and R026 separately; keep Paper/Live locked. |
| `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit` | `5d11f02` plus governance closeout | Yes; feature branch only | No | `IMPLEMENTED_PENDING_MERGE` | Prospective frozen-evidence Shadow Trading, quote-driven FakeBroker lifecycle/outcomes, durable audit/metrics, manual paperMoney ticket, and network-free Schwab read-only preparation. | Preserve remote branch; Steven reviews evidence before any local fast-forward. |
| `codex/ARGUS-R026-wpf-phase12-clean-room-integration` | `838ed22` | No | No | `NEEDS_REVIEW` | Consolidated R013-R025 WPF implementation and unattended Qt test hardening. | Complete its separate operator checklist; do not combine its merge decision with Shadow Trading. |
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
