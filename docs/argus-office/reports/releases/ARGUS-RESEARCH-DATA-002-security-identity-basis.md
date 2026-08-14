# ARGUS-RESEARCH-DATA-002 Release Report

## Classification

`IMPLEMENTED_PENDING_MERGE`

## Scope

Added a standalone provider-neutral research identity and price-basis engine,
synthetic contract tests, and an actual compatibility report derived from the
preserved DATA-001 inventory. No provider was contacted or selected, and no
historical evidence was repaired or rewritten.

## Implemented Contracts

- Durable security identity with point-in-time symbol aliases and explicit
  active, delisted, acquired, renamed, inactive, and unknown states.
- Verified forward split, reverse split, and symbol-change actions with
  source/action fingerprints; unsupported action semantics remain blocked.
- Raw-provider, split-adjusted, total-return-adjusted, and unknown price bases.
- Immutable raw-to-adjusted OHLCV lineage with independent deterministic
  reconciliation.
- Survivorship status and fail-closed research admission outcomes.
- Specialist compatibility for `CORPORATE_ACTION` and
  `DATA_BASIS_UNCERTAIN` without a hard feature-branch dependency.

## Dataset Result

All five DATA-001 sources lack stable security IDs, historical aliases,
delisted coverage, point-in-time membership, event-level corporate-action
lineage, and verified price-basis semantics. Point-in-time capability remains
`INSUFFICIENT`, survivorship status is `UNCONTROLLED`, and corporate-action-
sensitive research must abstain. Report fingerprint:
`3C763CFF90D9CFEF1C5B75B55E2ABBB5D0E759883519317DE1ACBD199EFAD8BC`.

## Proven Gaps

- Durable security identity and alias history.
- Verified corporate-action event chain.
- Explicit price-basis verification and transformation lineage.
- Point-in-time universe membership including inactive and delisted names.

Another provider was not procured or selected. The report records where a
provider might eventually be required, while preserving existing Schwab and
prospective collection as the first path to test.

## Verification

- Python compileall: pass.
- Focused identity/action/basis tests: 24 pass.
- Focused plus adjacent candle/evidence/DATA-001 regressions: 155 pass.
- Full Python discovery: 2,050 pass in 268.520 seconds.
- `git diff --check`: pass.
- Secret scan: pass; no credential-shaped value exists in task code, tests, or
  generated compatibility evidence.
- Capability scan: pass; the module has no network, provider, account, broker,
  order, service, scheduler, Engine Host, UI, scoring, Paper, Shadow, or
  execution import/call. Matches in tests are denylist assertions.
- Protected-path review: pass; changes are limited to one isolated research
  module, its tests, hash-addressed research reports, and governance files.
- Hard Chew self-review tightened canonical price-bar rebuilding, mandatory
  serialized schema/fingerprint evidence, point-in-time symbol-change chain
  reconciliation, aligned technical-series comparison, and invalid UTF-8
  rejection before the final full-suite pass.
- Source nonmutation: pass; DATA-001 inventory SHA-256 remains
  `61F2F0726B95AE9266D7CFCDE91FB1B24556A4D11700C746B0C337B7D5729886`.
- Canonical nonmutation: pass; canonical `master` and `origin/master` remain
  synchronized at `ea056155`, and the installed automation manifest remains
  `8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`.

## Safety

The engine has no provider, network, account, broker, order, service,
scheduler, Engine Host, WPF, scoring, readiness, selection, Paper, Shadow, or
execution capability. Raw inputs are immutable, outputs are explicit
write-once files, and every unsupported or unverifiable condition fails
closed.

## Recommendation

Integrate this foundation deliberately after feature-branch proof, then build
`ARGUS-STAT-DATA-001` so prospective research preserves the complete
opportunity denominator. Do not begin broad statistical modeling until both
identity/basis admission and denominator evidence are available.
