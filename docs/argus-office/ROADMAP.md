# Roadmap

Date reconciled: 2026-07-13

Status legend:

- `COMPLETED` means the work is in local `master`.
- `STARTED` means a branch exists but is not yet part of canonical `master`.
- `NOT STARTED` means no approved implementation exists.

## Phase 0 - Office Scaffold

Status: `COMPLETED`

- Agent roster, operating rules, branch safety, Goal Charter, and Hard Chew Protocol are established.
- Steven remains final merge and push approver.

## Phase 1 - Read-Only Mapping

Status: `COMPLETED` for the first mapping pass

- The rewrite/refactor decision spike and `app.py` responsibility map identify the protected Python engine and practical extraction targets.
- Future mapping remains available as focused work when a new boundary or risk needs evidence.

## Phase 2 - Scoped Improvements

Status: `ACTIVE`

- The first guided Daily Workflow bridge is complete.
- The durable Daily Workflow goal remains active: make the next required action and its blocker unmistakable.
- Follow-up clarity for stale data, no candidates, no watchlist, incomplete plans, and readiness diagnostics is not yet scheduled.

## Phase 3 - Release Discipline

Status: `ACTIVE`

- Releases use task branches, evidence-based verification, protected-path review, and local fast-forward merge only with Steven approval.
- Local `master` is now backed up to `origin/master`; future commits must be pushed deliberately after approval.

## Phase 4 - Argus Machine Simulation Foundation

Status: `COMPLETED` as a simulation-only foundation

- Local `master` contains the Gateway, TradePlan ladder, Top 5 candidate flow, Risk Governor, Execution Ledger, FakeBroker, Simulation Lab, Machine Log, and Execution Auditor foundation.
- Quality review and hardening tests are included in `master` through `f4dda36`.
- Canonical implementation paths are `momentum_hunter/autonomy/*`, `momentum_hunter/ui/autonomy_gateway.py`, and `momentum_hunter/ui/trade_plan_ladder.py`.
- The work is simulation-only. Paper and live execution remain locked.

## Phase 5 - Technical Research Engine

Status: `ACTIVE`

- `COMPLETED`: Technical Breakout Research Engine v1 is in `master` at `4d63655`.
- `COMPLETED`: research-only daily OHLC source work is in `master` at `1180315`.
- `STARTED`: technical indicator registry/confluence roadmap exists on `codex/technical-indicator-registry-confluence-roadmap-v1` at `2af99da` and needs review before merge.
- `STARTED`: Wave 1 confluence primitives exist on `codex/technical-confluence-wave-1-primitives` at `9678c5c` and need review before merge.
- Research stays read-only: no scoring, readiness, alert threshold, trade-planning, broker, or UI behavior changes are authorized by this phase.

## Phase 6 - Staged Architecture Modernization

Status: `STARTED`

- `COMPLETED`: Gateway / Argus Machine UI extraction is in `master` through `0ac66e0`.
- `STARTED`: `codex/ARGUS-R004-momentum-hunter-wpf-shell-spike` at `fb024a1` proves a dockable WPF workstation shell, independent chart contexts, and layout recovery.
- The R004 shell is a feasibility spike, not a replacement frontend: it uses mock/local engine data and has no production Python engine bridge.
- The R004 branch is cloud-backed, clean, and can fast-forward into local `master` after Steven approves merge readiness.
- Python remains the canonical engine for scanning, scoring, evidence, replay, storage, readiness, trade planning, and risk governance.

## Phase 7 - Broker Research Before Paper Code

Status: `NOT STARTED`

- A016 broker research may be docs/research-only. It must not add credentials, dependencies, adapters, or order routing.
- A017 PaperBrokerAdapter, A018 first paper pilot, A019 paper outcome review, and A020 read-only live adapter specification are not started.
- No paper broker, live broker, broker credential, API key, or real order path exists.
- A future paper-trading task needs a fresh Goal Charter, an explicit provider decision, and a safety review; it cannot be inferred from the simulation foundation.

## Current Decision Order

1. Review and decide whether to merge the R004 WPF workstation feasibility spike.
2. Review the unmerged Wave 1 technical-confluence primitives and decide whether they belong in `master`.
3. Choose whether the next research task is confluence validation or A016 broker research.
4. Keep paper/live behavior locked until a separately approved charter clears the required gates.

## Protected Areas

Do not change core scoring, trade readiness, replay identity, historical capture selection, database schema/migrations, broker/order execution, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior without explicit approval.
