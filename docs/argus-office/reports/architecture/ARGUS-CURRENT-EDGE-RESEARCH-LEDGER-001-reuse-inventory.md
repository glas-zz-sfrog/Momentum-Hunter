# ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001 Reuse Inventory

**As of:** 2026-08-29

**Role:** Code Mapper / Data Integrity Reviewer

**Branch:** `codex/argus-current-edge-research-ledger-001`

**Canonical base:** `848d20a6bd5a49e9bb8e179eaa374109756801b0`
**Scope:** Pre-implementation repository inventory for the ten identity, governance, persistence, root-isolation, and validation concerns required by directive section 4. This artifact changes no application code, test code, configuration, database, runtime, provider, broker, scheduler, service, GUI, Paper, or Shadow behavior.

## Executive verdict

`BLOCKED_IDENTITY_COLLISION = FALSE`

The repository already has authoritative, non-conflicting owners for the
identities the Current-Edge Ledger must observe:

- `ARGUS-STAT-DATA-001` owns the prospective `opportunity_id` and the canonical
  market-path, broker-execution, and data-quality outcome attachments.
- `ARGUS-RESEARCH-GOV-001` owns experiment, sample, dataset, feature, partition,
  variant, holdout, result, and research-authority semantics.
- The producing production/research artifact owns its strategy profile,
  configuration fingerprint, source-evidence fingerprint, repository Git
  identity, and runtime identity.
- The Current-Edge Ledger may own only its canonical prediction packet, reveal
  association, immutable file receipt, and their domain-separated identities.

The minimal implementation is therefore an isolated freeze/reveal manifest,
not a second opportunity denominator, experiment registry, strategy registry,
runtime registry, outcome engine, or evidence store. Existing owner identities
must be carried as opaque exact references and validated for shape and internal
consistency; the ledger must not reinterpret or regenerate them.

### Canonical/Roadmap precondition observation

Current Git evidence places local `master`, `origin/master`, the accepted
Strategy Science branch, and this task's base at exact commit `848d20a`. The
Roadmap `Now > Parallel Authorized Research`, the current Task Log entry, and the
Strategy Science Branch Ledger entry still describe that packet as branch-only,
pending merge, with canonical at `8b81bcd` and no push or merge. The canonical
content itself is the exact accepted packet, so this is not
`BLOCKED_CANONICAL_DRIFT`; it is stale authoritative status metadata.

`BUILDER_START = HELD_PENDING_ROADMAP_GIT_RECONCILIATION`

Git Steward and Release Scribe must reconcile that routine nonvisual status
before implementation begins. This inventory may be reviewed and retained
because it changes no code and does not rely on the stale lifecycle label.

## Classification standard

- `REUSE_EXACTLY`: use the existing semantic identity or governance contract
  unchanged.
- `REFERENCE_EXISTING_OWNER`: freeze an exact owner-issued identity/reference;
  do not calculate a competing identity in the ledger.
- `EXTEND_MINIMALLY`: reuse a proven pattern while adding only the ledger-owned
  contract needed by this directive.
- `MISSING`: no suitable implementation or bounded extension point exists.

## Ten-item directive inventory

| # | Required concern | Classification | Exact repository/test evidence | Ownership and non-duplication decision |
|---:|---|---|---|---|
| 1 | Code/repository identity | `REFERENCE_EXISTING_OWNER` | `momentum_hunter/opening_runtime_identity.py:883-893` obtains and validates a full Git HEAD and records worktree status. `momentum_hunter/research_governance.py:574-623,1521-1531` requires an experiment's full 40-character `code_git_identity`; `tests/test_research_governance.py:468-490` rejects code-identity drift. The canonical accepted packet/base/branch all resolve to `848d20a6bd5a49e9bb8e179eaa374109756801b0`. | Freeze the exact full Git SHA supplied by the existing Git/runtime evidence owner and record its owner/scope. Do not invent a second repository digest or let the ledger infer historical code identity from its own current process. A dirty/uncommitted source state cannot masquerade as the recorded commit. |
| 2 | Strategy identity | `REFERENCE_EXISTING_OWNER` | `momentum_hunter/trade_planning.py:80-116` owns the current composite profile and its content-derived configuration fingerprint; `:2618-2634` writes those identities into the produced report. `momentum_hunter/scoring.py:539-550` owns scoring-profile selection, while `tests/test_evidence_integrity.py:320-337` proves the report exports the exact composite profile and fingerprint. | Carry the exact strategy/profile/version identity emitted by the observed source artifact, plus its source artifact ID/fingerprint. The ledger must not establish a universal strategy registry, rename a profile, or treat a display label alone as a content identity. A synthetic strategy uses an explicitly synthetic, ledger-fixture-scoped owner identity and cannot be presented as production Argus. |
| 3 | Configuration identity | `REFERENCE_EXISTING_OWNER` | `momentum_hunter/trade_planning.py:83-116` canonicalizes and fingerprints the composite configuration. `momentum_hunter/continuous_production.py:239-242` exposes the canonical Continuous deployment configuration fingerprint. `momentum_hunter/opening_runtime_identity.py:306-350,741-770` fingerprints classified opening configuration and binds it into the approved runtime identity. `tests/test_opening_runtime_identity.py:213-245` proves configuration changes alter identity and unclassified configuration fails closed. | Freeze the exact configuration fingerprint supplied by the producing domain. Do not recompute a cross-domain "Argus configuration" or merge opening, Continuous, scoring, and research configuration semantics. The reference must name its owner/profile so two scoped fingerprints cannot be mistaken for the same thing. |
| 4 | Runtime identity | `REFERENCE_EXISTING_OWNER` | `momentum_hunter/opening_runtime_identity.py:104-129` defines the exact runtime/configuration/environment/release identity result; `:741-879` composes runtime surface, configuration, environment, and promotion-policy identity; `:896-953` binds the approved runtime to source Git and no-order authority. `tests/test_opening_runtime_identity.py:148-245` proves intended boundary sensitivity, and `:289-305` rejects a dirty runtime worktree. Continuous separately binds its runtime and configuration identity in `momentum_hunter/continuous_runtime.py:275-288,3147-3147` and `momentum_hunter/continuous_production.py:205-242`. | Preserve an exact owner-scoped runtime reference when the observed artifact has one. Opening and Continuous identities are distinct trust boundaries, not conflicting candidates for a new global ID. The ledger must neither recompute nor approve a runtime; it records the owner-issued value. Synthetic/offline input must be explicitly identified as synthetic rather than borrowing an approved production runtime fingerprint. |
| 5 | Evidence fingerprinting | `EXTEND_MINIMALLY` | `momentum_hunter/storage.py:133-138,156-184` hashes immutable source bytes and records the hash with capture provenance. `momentum_hunter/opportunity_denominator.py:603-632` validates cutoff-safe evidence references, fingerprints the evidence set, and binds it into opportunity identity. `momentum_hunter/research_governance.py:2294-2347` validates domain fingerprints and defines deterministic canonical JSON plus SHA-256. Focused tamper tests pass in `tests/test_raw_capture_integrity.py:128-187`, `tests/test_opportunity_denominator.py:556-561,618-635`, and `tests/test_research_governance.py:920-947`. | Preserve every source owner's evidence ID and fingerprint as opaque data. Add only domain-separated canonical fingerprints for `FrozenPredictionPacketV1` and `RevealPacketV1`, plus receipt identity, exact-byte stored SHA-256, and domain-separated stored-byte fingerprint bindings. Existing modules differ legitimately in namespace, newline, case, and envelope conventions, so copying one fingerprint into another domain would be a semantic collision; an explicit ledger canonicalization/version avoids that collision. |
| 6 | Immutable/write-once artifact behavior | `EXTEND_MINIMALLY` | `momentum_hunter/research_governance.py:1948-2003` is caller-rooted, deterministic, byte-idempotent, conflict-rejecting, fsync-backed, and link-created without last-write-wins behavior. `momentum_hunter/opportunity_denominator.py:1113-1165,1239-1294` provides separate immutable base/opportunity/outcome attachments with exact-reference enforcement and conflict rejection. `tests/test_research_governance.py:877-918` and `tests/test_opportunity_denominator.py:563-616` prove duplicate idempotency, conflicting-write rejection, restart, and base-before-attachment behavior. | Reuse these persistence semantics, not either domain's record identity. Add only two new write-once collections (`predictions`, `reveals`) and receipt collections under the ledger root. Prediction and reveal bytes remain separate. No overwrite/update/delete API and no database are justified. |
| 7 | Opportunity/candidate identity | `REUSE_EXACTLY` | The accepted architecture explicitly selects STAT-DATA ownership in `docs/argus-office/reports/architecture/ARGUS-STRATEGY-SCIENCE-LAB-001.md:203-212,431-440,1360-1369`. `momentum_hunter/opportunity_denominator.py:207-266,560-650` constructs the authoritative `opportunity_id` from cycle, origin, cutoff, candidate/setup/TradePlan references, and exact evidence. The Roadmap section `ARGUS-STAT-DATA-001 - Prospective Opportunity Denominator` records this owner as canonical, integrated, research-only, and inactive. `tests/test_opportunity_denominator.py:250-260` rejects duplicate identity and ticker-as-security identity. `momentum_hunter/candidate_lifecycle.py:926-947` remains the authoritative upstream candidate/setup identity for its narrower lifecycle. | A ledger prediction for an opportunity must carry the exact STAT-DATA `opportunity_id` and opportunity fingerprint. Existing market-path or broker outcome IDs/fingerprints are reveal references, not copied outcomes. The candidate-lifecycle opportunity ID may appear only in the existing STAT-DATA `candidate_id`/origin lineage; it is not promoted to a competing ledger opportunity ID. The deterministic `TEST1` fixture should obtain its opportunity identity from a synthetic STAT-DATA record. |
| 8 | Research-governance semantics | `REUSE_EXACTLY` | `momentum_hunter/research_governance.py:23-44,170-307` owns the research-only authority, timing, sample/dataset, feature, metric, benchmark, partition, holdout, search, and experiment contracts. `:574-654` constructs a preregistered experiment with exact code/policy/data identities and `RESEARCH_ONLY` / `EXECUTION_AUTHORITY_NONE`; `:1521-1598` fails closed on drift or incomplete governance. `tests/test_research_governance.py:468-490,673-690,843-867` proves identity drift, hidden-variant deletion, and false-health/no-authority controls. | The packet may reference an existing experiment/sample/policy fingerprint but must not register, amend, select, promote, or health-label an experiment. Reuse `RESEARCH_ONLY` and `EXECUTION_AUTHORITY_NONE` exactly. The directive's `PRODUCTION_DECISION_AUTHORITY = NONE` is an additional packet authority marker, not an experiment-registry rewrite. |
| 9 | Caller-defined storage roots | `EXTEND_MINIMALLY` | `momentum_hunter/research_governance.py:1948-1955` requires an absolute caller path and places deterministic collections beneath `experiment-registry-v1`; `tests/test_research_governance.py:958-960` rejects a relative root. `momentum_hunter/candle_persistence_contract.py:161-180,233-251` proves explicit-root containment and atomic temporary writes; `tests/test_candle_persistence_contract.py:190-228` exercises outside-root and failed-replace behavior. `momentum_hunter/opening_runtime_identity.py:1205-1227` rejects invalid filenames and reparse points for its own store. | Require a caller-supplied absolute path, resolve it once, add a fixed ledger directory, derive every child path from validated hash/token material, re-check containment immediately before reads/writes, and reject symlink/reparse escapes. Do not use `MomentumHunterData`, repository-relative defaults, environment variables, a production database, or a machine-global default. Existing root patterns are reusable, but none alone proves every directive root-escape condition. |
| 10 | Tamper/restart validation patterns | `EXTEND_MINIMALLY` | `momentum_hunter/research_governance.py:2004-2057` scans the whole registry on load, rejects partial files and unexpected paths, strictly parses duplicate keys/fields, revalidates each record, and compares canonical bytes. `momentum_hunter/opening_runtime_identity.py:1420-1489` validates record fingerprints and the complete predecessor receipt chain. `tests/test_research_governance.py:920-960` proves tampered, malformed, duplicate-key, partial-write, and restarted-load failures; `tests/test_opening_runtime_identity.py:327-344` proves release/pointer/receipt tampering fails closed. | On construction or first read after restart, validate every prediction packet, reveal packet, receipt, path, canonical byte sequence, hash binding, and cross-reference before returning any record or permitting another write. Add ledger-specific proof that reveal never changes prediction bytes/fingerprint and that a corrupt prediction, reveal, receipt, or partial artifact prevents silent continuation. The cited Opening predecessor-chain pattern remains reference evidence, not a ledger V1 requirement. Do **not** copy STAT-DATA's behavior of ignoring a stray temp file (`tests/test_opportunity_denominator.py:637-646`), because this directive requires interrupted artifacts to fail closed. |

## Collision audit

### Opportunity identity

There are two visible opportunity-shaped hashes, but they are not peer owners:

- `candidate-opportunity-v1` in `candidate_lifecycle.py` identifies one candidate
  lifecycle by symbol, market session, and originating evidence family.
- `opportunity-identity-v1` in `opportunity_denominator.py` identifies one
  complete-denominator research opportunity and may carry the upstream candidate
  identity, setup, TradePlan, origin, cutoff, and evidence lineage.

The accepted Strategy Science architecture selects the second as the Current-Edge
ledger reference. Treating the first as a replacement would be a collision;
retaining it only as upstream lineage is not.

### Runtime and configuration identity

Opening Runtime and Continuous each own a deliberately scoped runtime/configuration
identity. They are not interchangeable and neither is a global Argus identity.
The ledger must store `owner_scope + owner_identity + fingerprint` and validate
the exact reference. It must not hash both into a new authoritative runtime ID.

### Fingerprint algorithms

Canonical JSON/hash helpers are repeated in domain modules, with domain-specific
envelopes and encodings. Those fingerprints do not collide because their owners
and namespaces differ. V1 must freeze one ledger-specific canonicalization and
version for ledger-owned packet/receipt bytes while leaving all referenced hashes
unchanged.

## Minimum ownership seam for V1

### New ledger-owned identities

Only these identities are new:

1. `prediction_packet_id` and `prediction_packet_fingerprint`, domain-separated
   from and containing the exact owner-issued opportunity, cutoff, experiment,
   code, strategy, configuration, runtime, evidence, and prediction state.
2. `prediction_receipt_id`, binding the exact prediction path, complete stored
   bytes SHA-256, domain-separated stored-byte fingerprint, packet fingerprint,
   and terminal write result.
3. `reveal_packet_id` and `reveal_packet_fingerprint`, binding exactly one frozen
   prediction plus the reveal cutoff, outcome-evidence references, existing
   canonical outcome-attachment references when applicable, and unresolved or
   explicit result state.
4. `reveal_receipt_id`, binding the exact reveal path, complete stored bytes
   SHA-256, domain-separated stored-byte fingerprint, packet fingerprint, and
   terminal write result.

None of these changes `opportunity_id`, candidate/setup/TradePlan identity,
experiment/sample identity, source-evidence fingerprint, market-path outcome ID,
broker outcome ID, Git identity, strategy/configuration identity, or runtime
identity.

### Proposed module/test/docs seam

The bounded implementation should add or update only:

- `momentum_hunter/current_edge_research_ledger.py`: standard-library-friendly,
  research-only packet/receipt contracts, canonical serializers, validators,
  and a caller-rooted filesystem store. It may reference existing research-only
  identities but must have no provider, production writer, candidate/scoring,
  TradePlan, risk, Paper, Shadow, broker/order, scheduler, service, database, or
  GUI capability.
- `tests/test_current_edge_research_ledger.py`: the deterministic `TEST1`
  observe/freeze/restart/reveal proof; all eighteen hostile cases; no-authority,
  import-boundary, root-escape, nonmutation, and rollback checks; all artifacts
  below disposable absolute temporary roots.
- `docs/argus-office/reports/releases/ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001.md`:
  the 28-item evidence-backed completion packet.
- Existing task-owned governance records only: the Goal Charter, Roadmap, Task
  Log, and Branch Ledger. No new architecture service, database document,
  configuration file, generated data directory, or installation artifact is
  needed.

The new module should consume identity references rather than import executable
production paths. Test fixtures may call research-only STAT-DATA builders to
obtain a genuine synthetic `opportunity_id`; the ledger itself needs only strict,
owner-scoped reference validation.

## Protected paths not to touch

The following are authoritative references or forbidden production areas, not
implementation targets for this directive:

- Identity/governance owners:
  `momentum_hunter/opportunity_denominator.py`,
  `momentum_hunter/candidate_lifecycle.py`,
  `momentum_hunter/research_governance.py`,
  `momentum_hunter/opening_runtime_identity.py`,
  `momentum_hunter/continuous_runtime.py`,
  `momentum_hunter/continuous_production.py`,
  `momentum_hunter/trade_planning.py`,
  `momentum_hunter/scoring.py`, and `config/scoring_profiles.json`.
- Production evidence/configuration/data:
  `MomentumHunterData/**`, installed runtime/release/channel/service state,
  production configuration, capture manifests, SQLite files, schema, and
  migrations.
- Trading/runtime behavior: candidate generation, scoring, ranking, TradePlan,
  readiness, risk, sizing, entry/exit, Paper, Shadow, provider/Schwab/Alpaca,
  broker/account/order, scheduler, service, automation, Engine Host, and GUI/WPF
  modules or configuration.
- Historical/replay authority: replay identity rules, historical-capture
  selection, research-data basis/security identity, and existing immutable
  artifacts.

Tests may read/import existing research contracts and construct synthetic values;
they must not mutate these files or any production root.

## Verification performed for this inventory

Focused read-only verification:

```text
.\.venv\Scripts\python.exe -m unittest -q \
  tests.test_research_governance \
  tests.test_opportunity_denominator \
  tests.test_candidate_lifecycle \
  tests.test_opening_runtime_identity \
  tests.test_opening_runtime_identity_v2 \
  tests.test_storage \
  tests.test_candle_persistence_contract \
  tests.test_sequential_breakout_research \
  tests.test_sequential_breakout_outcomes

Ran 207 tests in 134.017s
OK (skipped=1)
```

The one skip is an existing platform-conditioned test. This inventory creates no
behavioral claim beyond the mapped owners and patterns.

Scoped documentation checks also pass: the inventory contains exactly ten rows,
all four classification labels are constrained to the directive vocabulary,
all 17 evidence-path references exist, all parsed cited line ranges are within
their files, the accepted base commit resolves, and the file contains zero tabs
or trailing-whitespace lines. The three paths in the proposed implementation
seam do not yet exist by design and were not counted as evidence links.

## Agent report

- **Branch:** `codex/argus-current-edge-research-ledger-001` from clean,
  synchronized canonical `848d20a6bd5a49e9bb8e179eaa374109756801b0`.
- **Scope:** The directive's ten-item pre-implementation reuse inventory and
  authoritative-identity collision review only.
- **Files changed:**
  `docs/argus-office/reports/architecture/ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001-reuse-inventory.md` only.
- **Tests or checks run:** 207 focused tests passed with one existing
  platform-conditioned skip. The ten-row/classification check, 17-path evidence
  link check, citation-range check, accepted-base check, and tab/trailing-
  whitespace checks passed. The scoped diff contains only this role-owned file;
  the concurrently created Goal Charter is owned by another authorized role.
- **Evidence for changed behavior:** Documentation-only artifact; runtime behavior
  did not change. Evidence is the exact code/test/architecture/Roadmap ownership
  mapping above.
- **Protected areas reviewed:** Identity, scoring, TradePlan, replay, historical
  selection, research governance, database/schema, provider, broker/order,
  runtime/configuration, Paper, Shadow, scheduler/service, and GUI. No protected
  semantic or file was changed.
- **Push/merge status:** No commit, push, merge, install, activation, provider
  call, or production write was performed by this role.
- **Risks:** The new ledger canonicalization, receipt identity and exact-byte binding, full root-security
  checks, cross-record chronology, and restart scan remain implementation work.
  A naive reuse of STAT-DATA's ignored-temp behavior or of a domain-specific hash
  without an explicit ledger namespace would fail this directive. Roadmap, Task
  Log, and Branch Ledger integration status is stale relative to current Git and
  must be reconciled before Builder work.
- **Manual QA:** Not applicable; documentation-only and nonvisual.
- **Open questions:** None requiring Steven input for reuse ownership. Routine
  canonical-status reconciliation remains with Git Steward and Release Scribe.
  The Builder must preserve the exact seam and stop if implementation reveals an
  owner mismatch not observable in this read-only inventory.
- **Recommendation:** First reconcile the Roadmap/Task Log/Branch Ledger with
  current canonical Git. Then proceed with the one isolated module, one focused
  test module, and completion report described above. Reuse STAT-DATA opportunity
  and outcome references, RESEARCH-GOV semantics, and owner-issued code/strategy/
  configuration/runtime/evidence identities. Do not activate a prospective
  observer or add a production import/write path.
