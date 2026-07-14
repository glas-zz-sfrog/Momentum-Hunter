# Branch Ledger

Date reconciled: 2026-07-13

## Current Truth

Local `master` is the canonical integration branch at `1180315 Add daily OHLC source for breakout research`. It matches `origin/master` (`0 ahead / 0 behind`) and is cloud-backed.

At this reconciliation, every named local branch tip is reachable from an `origin/*` ref. The safety branch `safety/ARGUS-cloud-backup-before-push` points to the current R004 workstation spike tip (`fb024a1`).

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
| `f4dda36` | Add simulation foundation hardening tests | Yes |
| `4d63655` | Add technical breakout research engine | Yes |
| `1180315` | Add daily OHLC source for breakout research | Yes |

## Branch Classifications

| Branch | HEAD | Pushed? | Merged to local `master`? | Classification | Purpose | Next action |
| --- | --- | --- | --- | --- | --- | --- |
| `master` | `1180315` | Yes; matches `origin/master` | Yes | `ACTIVE` | Canonical integration branch. | Create new task branches from this baseline. |
| `codex/ARGUS-R004-momentum-hunter-wpf-shell-spike` | `fb024a1` | Yes | No | `ACTIVE` | WPF workstation feasibility spike. | Review, then either fast-forward merge or retain as spike. |
| `codex/technical-confluence-wave-1-primitives` | `9678c5c` | Yes | No | `NEEDS_REVIEW` | Research-only Wave 1 confluence primitives. | Review test/safety evidence before merge decision. |
| `codex/technical-indicator-registry-confluence-roadmap-v1` | `2af99da` | Yes | No | `NEEDS_REVIEW` | Indicator registry and confluence roadmap. | Review as research framing; do not treat as canonical behavior. |
| `codex/daily-ohlc-coverage-expansion-v1` | `2f1e03d` | Yes | No | `NEEDS_REVIEW` | Daily OHLC coverage expansion. | Review data source and report behavior before merge decision. |
| `codex/ARGUS-A006-A015-clean-room-verification` | `664381d` | Content pushed via `master` | Yes | `MERGED_TO_LOCAL_MASTER` | Clean-room simulation verification branch. | Historical audit branch only. |
| `codex/ARGUS-A006-A015-argus-machine-simulation` | `91da577` | Yes | No by commit identity; content superseded | `SUPERSEDED` | Original simulation foundation workstream. | Do not use for new feature work. |
| `codex/ARGUS-A004-A005-tradeplan-risk-governor` | `8a90e18` | Yes | No | `SUPERSEDED` | Older standalone `momentum_hunter/execution/*` experiment. | Do not merge; use only as historical reference if needed. |
| `codex/ARGUS-A002-A003-gateway-machine-console-skeleton` | `52474fe` | Yes | No | `SUPERSEDED` | Earlier Gateway skeleton. | Do not use for new work. |
| `codex/ARGUS-A002A-gateway-machine-console-hardening` | `9ece892` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Hardened Gateway skeleton. | Historical only. |
| `codex/ARGUS-R002-extract-gateway-machine-ui` | `0ac66e0` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Gateway UI extraction. | Historical only. |
| `codex/ARGUS-R001-app-py-responsibility-map` | `e82b63e` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | `app.py` responsibility map. | Historical only. |
| `codex/ARGUS-R000-rewrite-refactor-decision-spike` | `b27013b` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Rewrite/refactor decision spike. | Historical only. |
| `codex/ARGUS-FI-001-future-ideas-autonomy-ui` | `008ac9a` | Yes | No | `PUSHED_FEATURE_BRANCH` | Future-ideas parking lot. | Review before any salvage. |
| `codex/subagent-work-contracts` | `4c004a1` | Content pushed via `master` | Yes | `MERGED_TO_LOCAL_MASTER` | Artifact-first subagent work contracts. | Historical only. |

## Do Not Use For New Work

Do not start new implementation from these branches:

- `codex/ARGUS-A006-A015-argus-machine-simulation`
- `codex/ARGUS-A004-A005-tradeplan-risk-governor`
- `codex/ARGUS-A002-A003-gateway-machine-console-skeleton`

Use a fresh task branch from `master` unless a named review branch is under active evaluation.
