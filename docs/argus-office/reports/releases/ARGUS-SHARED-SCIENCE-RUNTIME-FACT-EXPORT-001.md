# ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001

## Disposition

`IMPLEMENTED_PENDING_INDEPENDENT_SECOND_EYE`

This is a candidate-only shared-contract implementation. It is not integrated into canonical, installed in production, registered as a service, registered with a scheduler, or activated for autonomous capture.

## Authority and admission

- Workstream: `CROSS_LANE_INTEGRATION_STEWARD`
- Source design: `ARGUS-SCIENCE-ALWAYS-ON-RECORDER-CONTRACT-001`
- Accepted architecture: `OPTION_C_ONE_WAY_VERSIONED_RUNTIME_FACT_EXPORT_CONSUMED_READ_ONLY_BY_SCIENCE_CUSTODY`
- Admitted canonical: `986407467ae8de27df1bc228d843a8701014ac06`
- Candidate branch: `codex/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001`
- Full-suite executable identity: recorded in the sealed Hard Chew summary and second-eye manifest
- Design packet root: `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-SCIENCE\ARGUS-SCIENCE-ALWAYS-ON-RECORDER-CONTRACT-001-20260831-213529-9638763-CT`
- Design checksum-sidecar SHA-256: `f40207a300b0d5ea91992e4e7f03491e3de031714a8928d01118a8a9b9ec4434`
- Design inventory: 13 files including the checksum sidecar; all 12 substantive artifacts verified against it.
- Preserved baseline root: `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\LANE-SCIENCE\ARGUS-SCIENCE-DESCRIPTIVE-BASELINE-001-20260831-205641-7160835-CT`
- Baseline checksum-sidecar SHA-256: `8a75e0dc8521c3e970f4063860c50e01f8618be7788e0cbff6e368514bc6fd52`

The exact committed candidate HEAD and final candidate tree are recorded in the sealed second-eye manifest. The report itself intentionally does not embed its own recursively determined commit identity.

## Implemented boundary

The implementation provides one dormant, import-side-effect-free, producer-owned, versioned append-only research export. Future Science custody can read verified records, but it receives no callback or command path into runtime behavior.

Seven schema-v1 record families are implemented:

1. discovery cycle
2. candidate observation
3. decision event
4. market snapshot
5. reference plan
6. provider-health event
7. outcome observation

All 14 `MVP_REQUIRED` contract capabilities are represented at the export boundary:

1. durable session partition and custody envelope
2. complete discovery denominator
3. owner-preserving identity graph
4. immutable material decision state
5. contemporaneous market and score snapshot
6. natural catalyst identity pass-through with explicit absence
7. contemporaneous TradePlan/reference-level pass-through without synthesis
8. pre-outcome eligibility commitment
9. canonical outcome series and horizon linkage
10. provider, readiness, and gap evidence
11. anti-hindsight canonical hashing and linkage
12. restart, idempotency, and conflict safety
13. coverage, manifest, checksum, and retention closeout
14. one-way versioned producer export and no-authority boundary

The contract uses canonical UTF-8 JSONL with LF endings, sorted keys, explicit semantic absence, no nulls, and no floating-point/NaN ambiguity. Identities are owner-wrapped and durable; no lifecycle join uses symbol alone. Decision and outcome records preserve their distinct authoritative time roles, and outcome facts bind to the exact frozen decision, eligibility, and source-path identities and hashes.

Restart recovery resumes from immutable last-safe checkpoints. Same semantic identity plus identical canonical bytes is idempotent. Same identity plus conflicting bytes persists conflict evidence and fails closed. Partial tails are detectable and recoverable without rewriting frozen facts.

The bounded fixture retained every discovery cycle and candidate row, including zero-result, rejected, qualified, blocked, and provider-gap states. Outcome eligibility is frozen prospectively for `+5`, `+15`, `+30`, `+60`, and regular-session-close horizons; session-close truncation is explicit. No autonomous outcome scheduler is implemented or activated.

## Files

- `momentum_hunter/research_fact_export.py`
- `tests/test_research_fact_export.py`
- `tools/verify_research_fact_export.py`
- `tools/run_shared_science_runtime_fact_export_hard_chew.py`
- `tools/package_shared_science_runtime_fact_export.py`
- `docs/argus-office/reports/releases/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001.md`

No existing application source, GUI, Science recorder, Opening Engine runtime, strategy, execution, service, scheduler, authentication, configuration, package, or database file was modified.

## Verification

Sealed Hard Chew evidence:

`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\INTEGRATION\ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001-9864074-PASS6`

- Approved environment gate: PASS (`Python 3.12.6`, `bs4 4.12.3`, `requests 2.32.3`, `PySide6 6.7.3`)
- Compile/import: PASS
- Focused acceptance tests: PASS, 25/25
- Adjacent owner regressions: PASS, 118/118
- Full Python discovery: PASS, 2,905 tests, 2 expected skips
- Full .NET suite: PASS, 259/259
- Git diff check: PASS
- Forbidden-import scan: PASS
- Secret/credential scan: PASS
- Design packet verification: PASS
- Preserved baseline verification: PASS
- Offline preserved-evidence rehearsal: PASS
- Production checkout clean/synchronized and unchanged: PASS
- Foreign Opening Engine worktree clean and unchanged at `e47e2e85ea00867a4b2ee0fd58583363302de91e`: PASS

Expected Python skips:

1. `tests.test_gui_states.GuiStateTests.test_research_lab_open_returns_control_before_slow_report_finishes` — the exact admitted canonical independently fails this untouched GUI timing assertion in the approved environment; GUI repair is out of scope.
2. `test_opening_runtime_identity.OpeningRuntimeIdentityTests.test_reparse_runtime_component_is_rejected_when_supported` — existing Windows symlink-privilege skip (`WinError 1314`).

The offline rehearsal used the verified preserved baseline without provider contact and wrote only to the isolated rehearsal root:

`C:\Users\steve\AppData\Local\Temp\MomentumHunter-INTEGRATION-ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001-rehearsal-007`

It exercised 25 discovery cycles, 1,415 observations, 99 unique symbols, explicit evidence gaps, restart, deterministic replay/readback, and source-sidecar nonmutation.

## Protected-boundary review

- Science-to-runtime control path: `NONE`
- Current-Edge dependency: `NONE`
- Trading semantics changed: `FALSE`
- Engine readiness defect repaired: `FALSE`
- GUI contract change required: `NO`
- Live provider contact: `NO`
- Provider authentication changed: `FALSE`
- Account or position authority used: `NO`
- Paper or Shadow authority used: `NO`
- Order or execution authority used: `NO`
- Autonomous capture activated: `FALSE`
- Service registered or changed: `FALSE`
- Scheduler registered or changed: `FALSE`
- Production installed: `FALSE`
- Canonical mutated: `FALSE`

## Review and rollback

Independent second-eye review remains mandatory because the candidate adds executable shared/runtime contract semantics. The review must reproduce the focused tests from the sealed artifact and validate the manifest, executable blob hashes, evidence logs, no-authority proof, protected-path inventory, storage measurements, and detached checksum without trusting this report.

Rollback before integration is simply to reject the candidate branch and package; canonical and production require no restoration because neither was changed. If a later separately authorized integration occurs, rollback must use a new reviewed canonical action rather than rewriting or deleting this frozen candidate lineage.

`READY_FOR_STEVEN_MERGE_REVIEW = NO` until independent second-eye acceptance is returned.
