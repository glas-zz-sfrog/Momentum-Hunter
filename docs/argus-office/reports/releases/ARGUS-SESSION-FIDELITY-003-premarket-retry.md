# ARGUS-SESSION-FIDELITY-003 Premarket Retry

## Result

Implemented a prospective, Alpaca-only retry for the three SESSION-FIDELITY-001
premarket observations whose Alpaca child failed safely. The original evidence
is preserved; this task creates a new program identity and new output paths.

## Frozen Matrix

| Checkpoint | Central time | Scope |
| --- | --- | --- |
| A | 2026-08-12 03:05 | Alpaca SPY/QQQ/NVDA, five minutes |
| B | 2026-08-12 05:55 | Alpaca SPY/QQQ/NVDA, five minutes |
| C | 2026-08-12 06:05 | Alpaca SPY/QQQ/NVDA, five minutes |

Each task has one bounded one-minute scheduler retry, no late start, a
12-minute execution limit, and CurrentUser DPAPI compatibility. Steven must
remain logged in; the desktop may be locked.

## Failure Hardening

- Frozen dependencies load as one origin-verified module set.
- Installer and runtime both verify clean commits and exact file hashes.
- Evidence is write-once, fingerprinted, sanitized, and outside Git.
- A scheduler retry after a successful write returns `DUPLICATE_VERIFIED`
  without loading the provider or making another request.
- Tampered, conflicting, wrong-task, wrong-checkpoint, wrong-symbol, unsafe, or
  late evidence fails closed.

## Safety Boundary

No account values, positions, previews, orders, Paper order lifecycle, Shadow,
service, Engine Host, production persistence, strategy authority, execution
authority, or live endpoint is reachable from this task. Order transmission is
`UNAVAILABLE`.

## Verification

- Compileall: pass.
- Focused: 15/15 pass.
- Adjacent market-data boundary: 67/67 pass.
- Full Python discovery: 1,329/1,329 pass in 217.967 seconds.
- Final hash, secret, protected-path, and task-definition proof occurs before
  installation.

## Classification

`IMPLEMENTED_PENDING_FROZEN_INSTALL`
