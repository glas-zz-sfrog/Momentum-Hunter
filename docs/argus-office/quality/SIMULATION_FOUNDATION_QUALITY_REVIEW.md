# Simulation Foundation Quality Review

Date: 2026-07-01
Branch: `codex/ARGUS-QUALITY-001-simulation-foundation-review`

## Summary

The Argus Machine simulation foundation is useful and buildable, but it should be treated as a simulation foundation, not a paper-trading foundation. It is ready to support A016 broker research because A016 is docs-only. It needs targeted hardening before A017 PaperBrokerAdapter skeleton or A018 first paper pilot.

## Module Classifications

| Module | Classification | Rationale |
| --- | --- | --- |
| `momentum_hunter/ui/autonomy_gateway.py` | `KEEP_WITH_HARDENING` | Real console behavior, but too much direct `window.argus_*` mutation and mixed UI/orchestration/audit rendering. |
| `momentum_hunter/ui/trade_plan_ladder.py` | `KEEP` | Small, extracted PySide component with a narrow render API. |
| `momentum_hunter/autonomy/view_models.py` | `KEEP_WITH_HARDENING` | Good view-model layer; needs stale/corrupt/fallback source handling. |
| `momentum_hunter/autonomy/risk_governor.py` | `KEEP_WITH_HARDENING` | Clear gates; needs explicit policy for `Needs review` simulation allowance. |
| `momentum_hunter/autonomy/broker.py` | `KEEP_WITH_HARDENING` | Honest FakeBroker; future adapter safety contracts need to be stricter. |
| `momentum_hunter/autonomy/ledger.py` | `KEEP_WITH_HARDENING` | Useful event shape; lacks pre-append validation and persistence semantics. |
| `momentum_hunter/autonomy/simulation.py` | `REFACTOR_BEFORE_DEPENDENCY` | Accepts any `BrokerAdapter` and calls `submit_order`; must guard FakeBroker-only behavior before paper work. |
| `momentum_hunter/autonomy/auditor.py` | `KEEP_WITH_HARDENING` | Catches important missing/invalid evidence; not yet a chronological hard gate. |
| `momentum_hunter/trade_planning.py` | `KEEP` | Canonical TradePlan source model remains appropriate. |
| `momentum_hunter/app.py` | `KEEP_WITH_HARDENING` | Gateway integration is narrow, but the file remains a major extraction risk. |

## Quality Risks

1. Simulation engine has no pre-call adapter safety guard.
2. Auditor validates evidence after the fact rather than preventing unsafe adapter calls.
3. Ledger accepts incomplete order-like events and relies on auditor detection later.
4. UI gateway is growing into a stateful orchestration module.
5. Current-candidate fallback TradePlans are planning scaffolds and should not be treated as paper-quality setups.

## Hardening Priorities

1. Add negative tests proving simulation refuses non-FakeBroker and transmit-capable adapters.
2. Add a FakeBroker-only guard inside `SimulationLabEngine`.
3. Strengthen auditor chronology and preview-before-submit rules.
4. Add ledger validation for order-like events or constrain engine writes.
5. Extract cockpit rendering/state helpers out of `autonomy_gateway.py`.
