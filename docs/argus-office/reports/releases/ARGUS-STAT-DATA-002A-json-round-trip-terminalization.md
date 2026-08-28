# ARGUS-STAT-DATA-002A JSON Round-Trip And Terminalization Repair

## Status

`LIVE_CANARY_FAILED / SECOND_EYE_REVIEW_REQUIRED / IMPLEMENTED_PENDING_MERGE / RESEARCH_ONLY`

## Branch

- Branch: `codex/ARGUS-STAT-DATA-002A`
- Base: `c01a393794b05165e1b33a4869f4b9703eed3a3c`
- Product repair: `83b952d4bed5ee0b062f21f8314289ce5e9d7335`
- Final implementation: `415a3e2e5432420bde2ffee9ada0a28c2e55c65f`
- Push: complete
- Merge/deployment: unauthorized and not performed

## Scope

The task repairs the confirmed JSON tuple/list round-trip mismatch and moves
all post-prepare canary gates inside truthful terminal accounting. It does not
change denominator populations, membership semantics, providers, strategy,
readiness, TradePlans, Paper, Shadow, broker, account, position, or orders.

## Files Changed

- `momentum_hunter/prospective_denominator.py`: canonical load-boundary
  normalization before strict validation.
- `tools/run_stat_data_002_canary.py`: terminal accounting, provider-contact
  evidence, exact-path rehearsal, and failure-aware packaging flow.
- Focused tests for persistence drift, early terminalization, empty-store
  accounting, summary failure, and failure packaging.
- Goal Charter, Roadmap, and this release report.

## Repair Evidence

- Exact ordered JSON population array reloads as the canonical tuple.
- Reordered, missing, extra, duplicate, malformed, and non-string populations
  fail closed.
- The original failed activation reloads without changing activation ID or
  fingerprint.
- Early activation, identity, market-data identity, market-window, provider
  start, runtime, verification, and summary failures preserve terminal facts.
- Provider-path attempt and observed provider contact are recorded separately.
- A prepared empty store reports explicit zero observations and members.

## Verification

- Focused final suite: `90/90 PASS`.
- First full approved-environment discovery: `2,851/2,851 PASS`, one expected
  Windows skip.
- Final settled-byte discovery: `2,852/2,852 PASS`, one expected Windows skip,
  elapsed `1,234.151s`.
- Approved environment fingerprint:
  `791197DEDD392BD3D5FA0D6FB051F395562E336ABF995FC9FBD633FAC28760C8`.
- Compileall, diff check, targeted secret scan, capability scan, and protected-
  path review: pass.
- Corrected offline exact-path rehearsal: pass, provider contact false, zero
  observations, preserved activation identity, package and extracted focused
  verification pass.
- Offline rehearsal ZIP SHA-256:
  `E29BEEA5CD8A67773AA4C7244C3AF374232D9F5CA84074BF94726A789A3F3610`.

## Live Canary

The single authorized live attempt created a new immutable activation and
entered the natural runtime path at `2026-08-28T12:17:42.917528-04:00`. It
failed before provider contact:

`RuntimeCheckpointError: Runtime checkpoint root must remain under the temporary directory.`

The wrapper supplied its durable OneDrive evidence root as the natural runtime
generation/checkpoint root. The canonical runtime rejected that boundary
before Finviz or Schwab evidence existed. This is a distinct canary integration
defect, not the repaired JSON round-trip defect.

- Provider path attempted: `true`.
- Provider contact observed: `false`.
- Natural prospective observations/members/outcomes: `0/0/0`.
- Terminal record: present and truthful.
- Verification: `FAIL`, correctly reflecting failed acceptance.
- Canary rerun: not performed.

The first package attempt encountered the disposable writer owner lock while
the runtime was exiting. Its partial stage was preserved under a failure name.
After the disposable process was confirmed absent, packaging of the unchanged
terminal evidence completed successfully; no provider or Product rerun was
performed.

## Mandatory Second-Eye Package

- ZIP: `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-STAT-DATA-002A-PROSPECTIVE-CANARY-20260828-415A3E2-SECOND-EYE.zip`
- SHA-256: `6ADE90F1B88B6EB20D1CD005FCCBD592AA08557376A103E9F8AEC39FFC5B96FC`
- Files: `237`
- Manifest entries: `236`
- Secret scan: `PASS`
- Manifest verification: `PASS`
- Pre-ZIP focused verification: `PASS`
- Extracted-ZIP focused verification: `PASS`

## Protected Areas

Population definitions and statistical semantics are unchanged. The live path
remained `RESEARCH_ONLY` with execution authority `NONE`, order capability
`UNAVAILABLE`, and no account values, positions, Paper, Shadow, broker, or order
request. Canonical Git, services, and installed manifests were not changed.

## Git And Installed State

- Canonical local/origin: `23ee162373654e1db91af4c19f75bbc7887e3174`, clean.
- Automation, Continuous Runtime, and Continuous Writer: Running/Automatic.
- Automation manifest:
  `AFC55EC289E46E02DF96C2FC0B4DD501DEEC763FC94B82DBB2065B25F942700B`.
- Continuous configuration:
  `EF1986A35000CA8EB425BCD7470BE0A9C4496007853F4AF20F779B565AF9D982`.
- Continuous deployment manifest:
  `FC2810BAA3730EDFB7679026A70F305992EC772A381E733819B54FFFD29B73EB`.

## Risks And Recommendation

The JSON and terminalization defects are repaired, but natural statistical
capture remains unaccepted because the canary/runtime checkpoint topology is
incompatible. Preserve both failed canaries and the new packet. Do not repair,
rerun, merge, deploy, or begin downstream work until independent second-eye
review returns a narrow decision.

## Terminal Classifications

```text
STAT_DATA_002A_IMPLEMENTED = YES
JSON_ROUND_TRIP_REPAIRED = YES
POPULATION_SEMANTICS_CHANGED = NO
PRESERVED_FAILED_ACTIVATION_RELOADS = YES
ACTIVATION_ID_PRESERVED = YES
ACTIVATION_FINGERPRINT_PRESERVED = YES
PRE_PROVIDER_TERMINALIZATION_REPAIRED = YES
EARLY_FAILURE_PRODUCES_TERMINAL_RECORD = YES
EARLY_FAILURE_PRODUCES_SECOND_EYE_PACKAGE = YES
FULL_HARD_CHEW = PASS
NEW_LIVE_CANARY_COMPLETED = YES
PROVIDER_CONTACT_OCCURRED = NO
NATURAL_PROSPECTIVE_MEMBERS = 0
SECOND_EYE_ZIP_REQUIRED = YES
SECOND_EYE_ZIP_CREATED = YES
READY_FOR_SECOND_EYE_REVIEW = YES
PAPER_OR_EXECUTION_AUTHORITY_USED = NO
MERGE_AUTHORIZED = NO
```

## Manual QA

None. This task has no visual surface.

## Open Questions

- What disposable `%TEMP%` runtime root and durable evidence export boundary
  should the canary use without altering the canonical runtime contract?
- Should the package wrapper explicitly wait for disposable writer shutdown
  before copying evidence, or exclude only proven ephemeral owner-lock state?
