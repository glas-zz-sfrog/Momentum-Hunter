# Branch Ledger

Date reconciled: 2026-07-16

## Current Truth

`master` and `origin/master` are the canonical merged product baseline for Momentum Hunter. They contain the Python automation and simulation foundation, Technical Breakout Research Engine v1, daily OHLC source support, the R004 WPF workstation shell, R005 tray/lifecycle work, and the State-004 governance reconciliation through `30c0e0b Reconcile roadmap after R004 and R005 integration`.

Git evidence at reconciliation time:

- `git status --short --branch` on `master`: clean.
- `git rev-list --left-right --count origin/master...master`: `0 0`.
- `master` and `origin/master` both resolve to `30c0e0b4e3c3b80ec946681015f3b6f0a7dd729b`.
- The verified `master` and remote governance tree is `388b410727aefe9f65bd94bac8fa589e408ea787`.
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

## Branch Classifications

| Branch | HEAD | Pushed? | Merged to local `master`? | Classification | Purpose | Next action |
| --- | --- | --- | --- | --- | --- | --- |
| `master` | `30c0e0b` | Yes | Yes | `ACTIVE` | Canonical merged Python engine and accepted WPF operator-surface baseline. | Steven review is required before fast-forwarding Phase 8. |
| `codex/ARGUS-R008-python-engine-contract-host` | Phase-close tip (this record) | Yes | No | `IMPLEMENTED_PENDING_MERGE` | Independent local Python Engine Host, versioned WPF lifecycle bridge, duplicate guards, and process-level proof. | Review for an explicit fast-forward merge decision; do not add Phase 9 to this branch without recording a stacked-branch decision. |
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
