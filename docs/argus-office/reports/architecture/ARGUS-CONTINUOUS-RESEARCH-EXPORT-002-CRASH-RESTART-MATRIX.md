# ARGUS-CONTINUOUS-RESEARCH-EXPORT-002 Crash And Restart Matrix

The proof uses isolated publication roots and synthetic exceptions at every
meaningful boundary. Recovery always derives truth from canonical published
bytes and never from filesystem timestamps or report prose.

| Boundary | Required recovered truth |
| --- | --- |
| Before START commit | No public object; a later real START is sequence 1. |
| START raw bytes staged | START is not visible before recovery; recovery publishes it once. |
| START public before checkpoint | One START; no duplicate and checkpoint reconstructs. |
| Clean restart after START | START remains immutable and idempotent. |
| Ordinary event raw bytes staged | Partial event is not public; recovery publishes exact bytes once. |
| Ordinary event public before checkpoint | Published event reconstructs stream head exactly. |
| Between sequential events | Next sequence and previous raw-envelope SHA resume exactly. |
| Before FINAL | No FINAL appears. |
| FINAL raw bytes staged | FINAL is not visible early; recovery verifies and publishes once. |
| FINAL public before terminal checkpoint | FINAL remains unique, last, and terminal after restart. |
| Clean no-crash path | START, events, and FINAL verify through the same scanner. |

The matrix also corrupts sequence and previous-hash state, introduces malformed
staging, attempts conflicting identity reuse, and verifies that all cases fail
closed. Incomplete terminal truth survives close/restart as
`INCOMPLETE_NO_FINAL`. No partial staged object is returned by `published()` or
stored under the public namespace.

```text
RESTART_CRASH_MATRIX = PASS
PARTIAL_SOURCE_NEVER_ADMITTED = PASS
PREVIOUS_RAW_ENVELOPE_CHAIN_PROVEN = YES
```

Machine evidence is `evidence/proof/crash-restart-matrix.json` and
`evidence/proof/hash-chain-proof.json` in the second-eye package.
