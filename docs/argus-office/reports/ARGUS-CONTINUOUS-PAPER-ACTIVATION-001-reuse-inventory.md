# Continuous Paper Reuse Inventory

## Starting Identity

- Canonical base: `dca0671b7856c11b432304a544477246d2764faf`
- Installed continuous product: `e69426b3b7bd179cd62eba2e28a5d0553da47154`
- Starting research mode: `RESEARCH_ONLY`
- Starting Paper capability: `UNAVAILABLE`
- Starting live capability: `UNAVAILABLE`

## Component Classification

| Function | Canonical source | Classification | Notes |
| --- | --- | --- | --- |
| DATA-004 same-session plan | `intraday_trade_plan.py`, `trade_planning.py` | REUSABLE_AS_IS | Continuous composition already carries `IntradayPlanEvidence`. |
| Continuous composition | `continuous_composition.py`, `continuous_live_qualification.py` | REQUIRES_SMALL_EXTENSION | Full plan exists in composition state but only sparse plan identity reaches persisted runtime evidence. |
| Paper Risk Governor | `paper_risk_governor.py` | REQUIRES_ADAPTER | Existing evaluator is bound to opening-report rows; thresholds remain reusable. |
| DATA-005B allocation | `provider_neutral_allocation.py` | REUSABLE_AS_IS | Account/capability inputs remain provider-neutral. |
| Alpaca Paper adapter | `alpaca_paper_broker.py` | REUSABLE_AS_IS | Exact-host, Paper-only, idempotent order operations already exist. |
| A004 execution mechanics | `alpaca_paper_engineering.py` | REQUIRES_SMALL_EXTENSION | Reuse submission, actual-fill reconciliation, stop, flatten, and recovery for verified continuous admission. |
| PAPER-005 hardening | `alpaca_paper_engineering.py` | REUSABLE_AS_IS | Post-fill risk and exact protective quantity checks are canonical. |
| Lifecycle capability proof | `alpaca_paper_lifecycle.py` | REUSABLE_AS_IS | Existing capability registry remains the arm prerequisite. |
| Execution Ledger/evidence | `alpaca_paper_engineering.py` | REQUIRES_ADAPTER | Existing write-once records are reused under a new continuous sample identity. |
| Dedicated writer | `continuous_production.py`, `continuous_evidence_writer.py` | REQUIRES_SMALL_EXTENSION | Add a bounded plan-admission artifact; no Paper credentials enter writer/runtime. |
| Independent process host | `MomentumHunter.ContinuousServiceHost` | REQUIRES_SMALL_EXTENSION | Add a `paper` role that launches a separate Python supervisor. |
| Upstream lifecycle/setup producer | production `LiveCompositionSource` inputs | MISSING | Installed source supplies candles/RVOL but no lifecycle or successor setup evidence; zero plans are currently possible. |

## Architectural Decision

No second execution engine will be created. The new code is limited to an immutable continuous-plan admission contract, a continuous-specific risk adapter, and an independent supervisor that invokes the existing Alpaca Paper engineering lifecycle.
