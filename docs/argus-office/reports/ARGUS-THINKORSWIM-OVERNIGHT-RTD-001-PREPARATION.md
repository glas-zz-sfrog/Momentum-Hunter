# ARGUS-THINKORSWIM-OVERNIGHT-RTD-001 Preparation

## Classification

`IMPLEMENTED_PENDING_PHASE_A_AND_TRUE_OVERNIGHT_EVIDENCE`

## Frozen Scope

- Official desktop Excel `tos.rtd` path only.
- Fixed symbols: SPY, QQQ, NVDA, AAPL, MU.
- Fixed documented market fields only; 75 total RTD cells.
- Phase A: 20 minutes after 04:00 Eastern, without claiming the exact boundary.
- Phase B: eight exact checkpoints from 19:55 through 04:05 Eastern.

## Verification Before Physical Launch

- PowerShell parser: 0 errors across runner and UAC launcher.
- Dry validation: 5 symbols, 15 fields, 75 cells, 0 account fields,
  0 order fields, 0 Excel/TOS contact.
- Focused and provenance tests: 20 passed.
- Python compileall: passed.
- Git diff check: passed.
- Secret-shape scan of executable configuration and launcher sources: passed.
- Canonical checkout: clean and synchronized at task start.

## Protected Boundaries

No Momentum Hunter product module, service, scheduler, manifest, OAuth state,
provider role, production evidence, account, position, Paper, Shadow, or order
path is changed. The evidence root is separate and write-once per checkpoint.

## Pending Evidence

The official RTD route has not yet been physically invoked by this source.
One elevated Excel launch is required because thinkorswim is installed for all
users. The true-overnight capability classification cannot be made before the
04:05 Eastern checkpoint completes.
