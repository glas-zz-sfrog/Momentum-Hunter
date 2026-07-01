# Current State

## Phase
ARGUS-QUALITY-001 simulation foundation quality review after local merge of the Argus Machine simulation foundation.

## Branch
Current canonical local branch: `master`

Local `master` HEAD: `6893dba Reconcile Argus branch ledger and canonical paths`

Local `master` status vs `origin/master`: ahead 76, not pushed.

## State Summary
Local `master` now contains the Argus Machine simulation foundation. The simulation foundation was finalized through `codex/ARGUS-A006-A015-clean-room-verification` and fast-forward merged into local `master`.

ARGUS-QUALITY-001 reviewed the current simulation foundation and classified it as ready for A016 broker research with cautions, but not ready for A017/A018 paper broker dependency without hardening.

Canonical Argus Machine implementation paths are:

- Gateway / Argus Machine UI: `momentum_hunter/ui/autonomy_gateway.py`
- Trade Plan Ladder UI: `momentum_hunter/ui/trade_plan_ladder.py`
- TradePlan source model: `momentum_hunter/trade_planning.py`
- Autonomy primitives: `momentum_hunter/autonomy/*`

Paper and live trading remain locked. No paper broker, live broker, broker credentials, API keys, or real order path exists on local `master`.

Quality review artifacts:

- `docs/argus-office/reports/quality/ARGUS-QUALITY-001-simulation-foundation-review.md`
- `docs/argus-office/quality/SIMULATION_FOUNDATION_QUALITY_REVIEW.md`
- `docs/argus-office/quality/SIMULATION_FOUNDATION_HARDENING_PLAN.md`
- `docs/argus-office/quality/TEST_QUALITY_REVIEW.md`
- `docs/argus-office/quality/A016_READINESS_DECISION.md`

## Active Rule
Steven remains final merge and push approver. Do not push `master` until Steven explicitly approves. Future implementation should start from a fresh task branch off local `master`.

## Branch Truth
The original `codex/ARGUS-A006-A015-argus-machine-simulation` branch is superseded by the clean-room cherry-picked history on `master`. It should not be used for future work.

The older `codex/ARGUS-A004-A005-tradeplan-risk-governor` branch is also superseded. It contains an unmerged `momentum_hunter/execution/*` model path that is not canonical.

See:

- `docs/argus-office/BRANCH_LEDGER.md`
- `docs/argus-office/CANONICAL_CODE_PATHS.md`

## Active Artifact Note
`argus_review_bundle_current.zip` may exist as an untracked review artifact in the repo root. It is not source code and should not be committed unless a future task explicitly requests artifact tracking.

## Review Bundle Quality Note
Future review bundles should:

- fix manifest variable substitution before delivery,
- include imported dependencies such as `momentum_hunter/trade_planning.py`, `momentum_hunter/models.py`, `momentum_hunter/time_utils.py`, and `momentum_hunter/monitor_targets.py`,
- remain curated and exclude secrets, credentials, `.env` files, virtualenvs, generated market data, and raw data folders.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Next work should either harden the simulation foundation through `ARGUS-QUALITY-002` / `ARGUS-A013B` / `ARGUS-A015B`, or proceed with `ARGUS-A016` as docs-only broker research with no code, credentials, API keys, dependencies, or paper/live wiring. Paper/live remain locked until a separate Steven-approved task explicitly changes that scope.
