# ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001 Hard Chew

## Candidate

- Base canonical: `04f6f8382e03906cbd174711a1d4df2d43a5cab4`
- Implementation head: `ee95d21cce986f48177364c69857ade1052a74c0`
- Branch: `codex/ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001`
- Contract action: `NEW_VERSION_REQUIRED`

## Required behavior

| Gate | Result |
|---|---|
| Frozen V1 circular blocker reproduction preserved | PASS |
| Exact T0/T1 two-clock proof | PASS |
| Producer seals without future Science hash | PASS |
| Producer content hash stable across Science receipt times | PASS |
| Science custody receipt hash separate | PASS |
| Science eligibility hash separate | PASS |
| Science receipt before producer known-at/seal rejected | PASS |
| Wrong producer hash in eligibility rejected | PASS |
| Wrong observation custody receipt in eligibility rejected | PASS |
| Producer Science-future-field injection rejected | PASS |
| Outcome/future-market input during initial eligibility rejected | PASS |
| Later outcome exact-link replay | PASS |
| V1/V2 parser separation | PASS |
| Legacy V1 bytes and embedded eligibility preserved | PASS |
| V2 crash/restart at source, payload, and receipt phases | PASS |
| Duplicate replay/idempotency | PASS |

The exact proof JSON is `two-clock-contract-proof.json`, SHA-256
`93226896C8753FA66F98BA4DE133B06C9AFA5AACAF6D6B29D5D9A93DCBEE0835`.
It is Git-bound to the implementation head and records identical producer
Decision/discovery hashes at Science clocks one second apart, distinct Science
receipt and eligibility hashes, three disjoint hash domains, successful later
outcome replay, and every required negative rejection.

## Automated verification

| Verification | Result | Evidence SHA-256 |
|---|---|---|
| Approved environment descriptor | PASS; fingerprint `791197DEDD392BD3D5FA0D6FB051F395562E336ABF995FC9FBD633FAC28760C8` | `D89E5E4649EEA3F25F03C431BA3FDBCFB69CCE16B0F05391FAB0405A190E1534` |
| Full focused Science custody suite | 61/61 PASS | `6496480E4956EB97FDB331DE26117E477D1FBDAF0CFE7CDB7B7DE40EE4703B68` |
| Continuous/denominator compatibility | 162/162 PASS | `B37ADB1C81EDD08440B9580C7288AECB88CBAE5B29E7E8B991C0AC2B4781A223` |
| Full approved Python discovery | 2,941/2,941 PASS; one expected privilege skip | `0CB417CFDF4DADCB0D5FE2D09AA98F45CE1F33E7EB907D16D7C456FFEB71B7BA` |
| `compileall -q momentum_hunter tests` | PASS | command evidence in package instructions/report |
| `git diff --check` | PASS after documentation EOF normalization | final frozen-head package verification |
| Context-aware secret scan | PASS | no secret-like value found |
| Capability scan | PASS | no new provider/network/service/scheduler/execution capability |
| Owned/protected path scan | PASS | exact Science/shared-contract surface only |
| Relevant .NET contract exposure | NOT APPLICABLE | no matching DTO/schema surface under `src/` or `tests-dotnet/` |

The expected skip is
`test_reparse_runtime_component_is_rejected_when_supported`: Windows symlink
creation was unavailable with WinError 1314. This is the same privilege-bound
skip class accepted by prior canonical Hard Chew runs.

## Protected-domain review

No Continuous module, GUI/`src/` path, Opening Engine path, provider client,
authentication, service, scheduler, installed runtime, discovery/scoring/
readiness/TradePlan/risk behavior, Paper, Shadow, broker, account, position, or
order path changed. No provider contact, deployment, activation, or production
test execution occurred.

The blocked `ARGUS-CONTINUOUS-RESEARCH-EXPORT-001` branch and its two reports
remain immutable at `a06d4aecd67578cefe783b035ec1ea425090eef2`; its mechanical
proof remains SHA-256
`A68C6FED0EB56D3C371B4196A42CDD78EDD474B5053EC32788AD77C48837F0B0`.

## Classification

`FULL_HARD_CHEW = PASS`

This remains `IMPLEMENTED_PENDING_SECOND_EYE`. It is not merged, deployed, or
activated, and it grants no authority to restart the producer exporter or
Science reader.
