# Current State

Date reconciled: 2026-07-13

## Canonical Baseline

- Local `master` HEAD: `1180315 Add daily OHLC source for breakout research`.
- `master` matches `origin/master` (`0 ahead / 0 behind`).
- All named local branch tips were checked on 2026-07-13 and are reachable from an `origin/*` branch.
- The worktree was clean before this documentation reconciliation branch was created.

## What Is In Local Master

- Guided Daily Workflow first bridge and Argus Office governance foundation.
- Gateway / Argus Machine Python UI extraction.
- Argus Machine simulation foundation: TradePlan, Risk Governor, ledger, FakeBroker, Simulation Lab, Machine Log, Execution Auditor, and hardening tests.
- Technical Breakout Research Engine v1 and its research-only daily OHLC source.

## Current Active Branches

| Branch | HEAD | Status | Meaning |
| --- | --- | --- | --- |
| `codex/ARGUS-R004-momentum-hunter-wpf-shell-spike` | `fb024a1` | `STARTED`, pushed, clean | WPF workstation feasibility spike. It is three commits ahead of `master`, uses mock/local engine data, and can fast-forward merge after review. |
| `codex/technical-confluence-wave-1-primitives` | `9678c5c` | `STARTED`, pushed | Research-only Wave 1 confluence primitives awaiting review and merge decision. |
| `codex/technical-indicator-registry-confluence-roadmap-v1` | `2af99da` | `STARTED`, pushed | Indicator registry/confluence roadmap awaiting review; not canonical behavior. |
| `codex/daily-ohlc-coverage-expansion-v1` | `2f1e03d` | `NEEDS_REVIEW`, pushed | Separate daily OHLC coverage expansion; not in `master`. |

## Simulation Safety Boundary

- Paper and live trading remain locked.
- No PaperBroker, LiveBroker, broker credentials, API keys, provider SDK, or real order path exists.
- A016 broker research is permitted only as docs/research work; it does not authorize A017/A018 code.
- Any paper or live work needs a new Goal Charter and explicit Steven approval.

## Architecture Boundary

- Python remains the canonical engine for scanning, scoring, evidence, replay, storage, readiness, trade planning, and risk governance.
- Canonical Argus Machine paths remain `momentum_hunter/autonomy/*`, `momentum_hunter/ui/autonomy_gateway.py`, and `momentum_hunter/ui/trade_plan_ladder.py`.
- The R004 WPF shell is a feasibility spike only. It is not a production Python bridge or a frontend-replacement decision.

## Next Decisions

1. Review/merge or hold the R004 WPF workstation feasibility spike.
2. Review/merge or hold the Wave 1 confluence primitives.
3. Select the next research lane: confluence validation or A016 broker research.

## Branch History Notes

- `codex/ARGUS-A006-A015-argus-machine-simulation` is cloud-backed but superseded by the clean-room-derived simulation foundation in `master`.
- `codex/ARGUS-A004-A005-tradeplan-risk-governor` is superseded and not a source for new work.
- See `docs/argus-office/BRANCH_LEDGER.md` and `docs/argus-office/CANONICAL_CODE_PATHS.md` for canonical-path and branch detail.

## Protected Areas

Do not change core scoring, trade readiness, replay identity, historical capture selection, database schema/migrations, broker/order execution, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior without explicit approval.
