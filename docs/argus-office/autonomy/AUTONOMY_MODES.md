# Autonomy Modes

## Mode Table
| Mode | Purpose | Broker Access | Order Ability | Required Label |
| --- | --- | --- | --- | --- |
| Planning | Draft plans and candidate ranking. | None | None | Planning only |
| Simulation Lab | Test plans against fake or historical state. | None or fake only | Simulated only | Simulated |
| Paper Trading | Exercise order lifecycle with paper capital. | Paper only | Paper only | Paper |
| Read-Only Live | Observe live account context. | Read-only | None | Read-only |
| Live Preview | Build order payloads for review. | Live metadata allowed | No transmit | Preview only |
| Confirmed Live | Send approved orders. | Live | Confirmed send only | Live confirmed |
| Supervised Automation | Controlled autonomous monitoring/actions. | Future approved scope only | Future gated scope only | Supervised |

## Locked Defaults
Planning and Simulation Lab are the only early modes. Paper, read-only live, preview, confirmed live, and supervised automation require separate Goal Charters and Steven approval.

## Mode Invariants
- A mode must be visible to Steven.
- The Broker Adapter must match the mode.
- Risk Governor status must be visible before order-like actions.
- Execution Ledger entries must include mode and approval state.
- UI labels must not blur simulated, paper, preview, and live behavior.
