# ARGUS-THINKORSWIM-OVERNIGHT-RTD-001

## Goal

Determine whether the officially supported thinkorswim `tos.rtd` COM/Excel
interface exposes current market-only data during the true 20:00-04:00 Eastern
overnight session.

## Boundary

- Use desktop Excel as the official RTD client.
- Observe fixed `SPY`, `QQQ`, `NVDA`, `AAPL`, and `MU` market fields only.
- Do not scrape the UI, reverse engineer thinkorswim, inspect private network
  protocols, automate login, or persist account/position/order data.
- Do not trade, modify Momentum Hunter, change provider roles, restart services,
  modify manifests/scheduler, or write production evidence.
- Preserve the post-04:00 Phase A observation separately from tonight's actual
  true-overnight checkpoints.
- Do not describe Phase A as an exact 04:00 boundary capture; implementation
  began after 04:00 Eastern, so it can prove only post-boundary RTD operation.

## Acceptance

The task remains incomplete until the eight fixed checkpoints through 04:05 ET
are terminal and independently verified. Presence alone is insufficient; each
field requires update/change evidence. Local observation time must never be
presented as provider time.
