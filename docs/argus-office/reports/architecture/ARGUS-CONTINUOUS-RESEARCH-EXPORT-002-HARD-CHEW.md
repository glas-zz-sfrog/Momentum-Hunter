# ARGUS-CONTINUOUS-RESEARCH-EXPORT-002 Hard Chew

## Scope

The task adds one dormant offline exporter module, one focused test module, two
evidence runners, one package builder, and task-unique architecture reports. It
does not edit canonical Science contract/custody semantics, existing Continuous
runtime or producer paths, shared governance, Opening/Observer, GUI, services,
schedulers, provider/authentication, strategy, TradePlan economics, Paper,
Shadow, broker/account/position/order code, execution authority, or generated
production evidence.

## Behavioral Proof

- Exact V2 parser acceptance and deterministic canonical bytes: PASS.
- Direct unchanged Science custody acceptance: PASS.
- Producer/Science authority separation and prohibited Science-field injection:
  PASS.
- Two-clock producer invariance with distinct Science custody/eligibility hashes:
  PASS.
- START-first and late-START rejection: PASS.
- Per-stream contiguous sequence and exact prior raw-envelope chain: PASS.
- Explicit dependency ordering without universal semantic-order invention: PASS.
- Truthful FINAL, frozen cutoff, immutable counts/heads, premature/incomplete
  no-FINAL behavior: PASS.
- Restart/crash matrix and public atomicity: PASS.
- Unresolved instrument identity without fabricated classification: PASS.
- Historical Class-B non-upgrade and absent retrofit surface: PASS.
- Outcome separation: existing `OutcomeAttachmentV1` remains separate and is
  not added to Producer T0 bytes.

## Test Gates

- `FOCUSED_EXPORTER_SUITE`: 31/31 PASS after final-head freeze.
- `SCIENCE_COMPATIBILITY_SUITE`: 96/96 PASS after final-head freeze.
- `CONTINUOUS_ADJACENT_SUITE`: 253/253 PASS.
- `FULL_APPROVED_PYTHON_DISCOVERY`: 2990/2990 PASS with one expected Windows
  platform skip after final-head freeze.
- Approved Python executable SHA-256:
  `3470F7919170D235D7E6079691462C4B217745EC67EE612E745730E46D98F238`.

## Freeze Gates

Compileall, full discovery, diff check, capability scan, context-aware secret
scan, protected-path review, clean frozen-head verification, final focused and
compatibility checks, deterministic packaging, fresh extraction,
manifest/checksum verification, and outer ZIP hashing all pass in the package
evidence. Builder merge authority remains `NO`.
