# Broker Adapter Spec

## Goal
Broker integration must be isolated behind adapter classes so Argus can progress safely from fake behavior to paper trading, read-only live awareness, live preview, and future confirmed live execution.

## Adapter Phases
1. FakeBrokerAdapter: local simulated order lifecycle only.
2. PaperBrokerAdapter: paper account order lifecycle only.
3. ReadOnlyLiveBrokerAdapter: live account observation only.
4. LivePreviewBrokerAdapter: builds order payload previews without transmit.
5. ConfirmedLiveBrokerAdapter: future locked transmit path after Steven approval.

## Common Adapter Metadata
- Adapter name.
- Mode.
- Capabilities.
- Order transmit allowed: true or false.
- Credential source status without exposing secrets.
- Last health check.

## Hard Boundaries
- No live order placement in this foundation task.
- No secrets committed to repo.
- No adapter may expose a transmit method unless a future Goal Charter explicitly approves it.
- Read-only adapters must not place, modify, or cancel orders.

## Console Contract
The Machine Status Bar should show adapter name, mode, health, and whether order transmit is locked.
