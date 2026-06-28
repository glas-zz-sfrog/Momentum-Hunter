# Autonomy Safety Policy

## Prime Rule
Argus Machine may plan, simulate, and explain before it can execute. Live execution stays locked until Steven explicitly approves a separate live execution task.

## Protected Areas
Do not change core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior without explicit approval.

## Broker Safety
- No live order placement in foundation or skeleton tasks.
- No secrets in source control.
- Paper and live labels must be visually explicit.
- Read-only live mode must not include order methods.
- Live preview must not transmit orders.
- Confirmed live execution requires Steven approval, Risk Governor pass, TradePlan linkage, and Execution Ledger writes.

## UI Safety
- Do not call candidates "approved trades" unless they are approved in the current mode.
- Do not use "Strongest Trades" until paper outcomes and Risk Governor evidence support it.
- Show disabled/locked states honestly.
- Explain the next required action when a plan is blocked.

## Audit Safety
Execution Auditor must be able to trace every order-like action to a TradePlan, risk gate result, mode, approval state, adapter, and timestamp.
