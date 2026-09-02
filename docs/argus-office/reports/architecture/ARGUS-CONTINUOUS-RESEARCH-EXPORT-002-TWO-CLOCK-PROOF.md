# ARGUS-CONTINUOUS-RESEARCH-EXPORT-002 Two-Clock Proof

The offline proof publishes one fixed Producer START, discovery, and V2 decision
exactly once. It then submits the exact same raw byte sequence to two isolated
canonical Science custody roots.

| Clock | Value |
| --- | --- |
| T0 Producer discovery known/emitted | `2026-09-02T13:31:00Z` |
| T0 Producer decision cutoff | `2026-09-02T13:32:00Z` |
| T0 Producer decision time/emitted | `2026-09-02T13:32:01Z` |
| T1 Science receipt | `2026-09-02T14:00:00Z` |
| T2 Science receipt | `2026-09-02T14:00:01Z` |

Proven invariants:

- Producer START/discovery/decision raw bytes are identical at T1 and T2.
- Producer discovery and decision envelope SHA-256 values are identical.
- The decision has no `outcome_eligibility_commitment_sha256` or `science_*`
  field.
- Science custody accepts the exact exporter bytes directly at both clocks.
- Science observation receipt hashes differ because custody receipt identity is
  clock-bound.
- Science eligibility hashes differ under the accepted Science-owned receipt
  semantics.
- Both custody roots verify all hashes.

Therefore:

```text
PRODUCER_REQUIRES_FUTURE_SCIENCE_HASH = NO
CIRCULAR_DEPENDENCY_REMOVED = PASS
PRODUCER_RAW_BYTES_T1 = PRODUCER_RAW_BYTES_T2
SCIENCE_RECEIPT_HASH_T1 != SCIENCE_RECEIPT_HASH_T2
```

Machine evidence is `evidence/proof/two-clock-proof.json` in the second-eye
package.
