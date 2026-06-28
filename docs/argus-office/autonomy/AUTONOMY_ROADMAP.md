# Autonomy Roadmap

## Purpose
This roadmap stages Argus Machine from a safe visible shell to simulation, paper trading, read-only broker awareness, live order preview, and future confirmed execution. The roadmap is intentionally safety-gated and does not authorize live broker behavior.

## Stages
1. Foundation docs and agent roles.
2. Gateway shell with Steven Desk and Argus Machine.
3. Machine Console skeleton with locked panels.
4. TradePlan object/model.
5. Risk Governor first gate engine.
6. FakeBrokerAdapter and Simulation Lab.
7. Top 5 Trade Plan Candidates data contract.
8. Paper broker planning and adapter skeleton.
9. Read-only live broker awareness.
10. Live order preview.
11. Confirmed live execution, only after explicit Steven approval.
12. Supervised automation, only after execution audit readiness.

## Mode Progression
Simulation comes first, then paper, then read-only live, then live preview, then confirmed live execution. Each mode must preserve clear labels, mode locks, Risk Governor status, and Execution Ledger auditability.

## First Five Tasks
| ID | Branch | Purpose |
| --- | --- | --- |
| ARGUS-A001 | `codex/ARGUS-A001-gateway-machine-console-spec-review` | Docs-only CEO review of gateway and console direction. |
| ARGUS-A002 | `codex/ARGUS-A002-build-gateway-shell` | Build two-button gateway shell. |
| ARGUS-A003 | `codex/ARGUS-A003-machine-console-skeleton` | Build placeholder Machine Console panels. |
| ARGUS-A004 | `codex/ARGUS-A004-tradeplan-object-model` | Specify and implement TradePlan object/model. |
| ARGUS-A005 | `codex/ARGUS-A005-risk-governor-first-gates` | Add simulation/display-only Risk Governor gates. |

## Non-Goals
- No live broker order placement in the foundation packet.
- No scoring changes.
- No readiness semantic changes.
- No database/schema changes unless a future task explicitly approves them.
- No secrets or broker credentials in the repository.
