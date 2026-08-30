# Goal Charter: ARGUS-CANONICAL-LEDGER-RECONCILIATION-001

## Goal And Admission

Restore the accepted Current-Edge Research Ledger on a Steven-review candidate
branch, forward from the authorized corrected canonical history, while
preserving that correction and excluding every unrelated byte. This charter
authorizes no `master` mutation, merge, or Prospective Observer implementation.

Admission is exact:

```text
TASK_BRANCH = codex/argus-canonical-ledger-reconciliation-001
CURRENT_CANONICAL_BASE = 99b95f530513343702e70077f970c43b5524c613
CURRENT_CANONICAL_TREE = 0c412c063d078505ed367c45f34954faf25e22a3
```

Before Builder edits and at closeout, Git Steward must prove the clean task
branch and local/origin/direct-remote `master` remain at exact `99b95f5`.
Accepted Ledger history remains reachable at `251ac0512cc6a9338d122b48294ac33db58d5ee5`,
but its artifacts are absent from the pre-reconciliation HEAD tree. History
presence and HEAD-tree presence must remain separate facts.

## Phase A GO And Movement Classification

Read-only Phase A is complete and accepted as GO:

```text
ACCEPTED_LEDGER_BYTES_IDENTIFIABLE = TRUE
CURRENT_CANONICAL_STATE_IDENTIFIABLE = TRUE
CORRECTION_SCOPE_IDENTIFIABLE = TRUE
LEDGER_COLLATERAL_REMOVAL_IDENTIFIABLE = TRUE
UNRELATED_CONTENT_CAN_BE_EXCLUDED = TRUE
RESTORATION_CAN_BE_FORWARD_ONLY = TRUE
PRODUCTION_BEHAVIOR_CHANGE_REQUIRED = FALSE
```

Preserve this exact classification without blame or guessed attribution:

```text
CANONICAL_MOVEMENT_CAUSE = AUTHORIZED_DIRECTIVE_EXECUTED_OUT_OF_ORDER
INITIATING_PROCESS = UNKNOWN
AUTONOMOUS_UNEXPLAINED_MUTATION = FALSE
AUTONOMOUS_CANONICAL_MUTATION = FALSE
AUTONOMOUS = FALSE
```

If any Phase A truth or classification becomes false or ambiguous, stop.

## Exact Authorized Artifact Surface

Builder may add exactly these six accepted Git-blob byte sequences:

| Path | Accepted SHA-256 | Git blob |
|---|---|---|
| `momentum_hunter/current_edge_research_ledger.py` | `A0FD9228BB1CB47C3251D641809787AFE29DB7417C806D1724D7F5D327282CE4` | `9e4a5df2170b59cee0efc57927bb4463f797d2d4` |
| `tests/test_current_edge_research_ledger.py` | `34C94F082423E61A6EC70EBA882C690D3520CDC15A8AE13FAD90CDC216D2D3CA` | `f9770b5c7cccac1c4f4fcf0eb6989c5510477cd6` |
| `docs/argus-office/goal-charters/ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001.md` | `BAC99C28409C2585CDB3FB0D1814C71D7A97598B29B3DE417C08DF99C4E76E43` | `1f0b426d6e5f990e75a712f3f0764fa18e435c4a` |
| `docs/argus-office/reports/architecture/ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001-reuse-inventory.md` | `336659412B043F31D0DE8889698A1156F087F615B077474E32F75E29A15FAF7F` | `8c2da4b1da26293a256abd061c731c24f76ccb3d` |
| `docs/argus-office/reports/architecture/ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001.md` | `6FD61A182FA144638A061A0A0861FA494579130B548B34EC37438B848BAD7368` | `78c36027e40220fe1d44a16749da37d705afaf38` |
| `docs/argus-office/reports/architecture/ARGUS-CURRENT-EDGE-RESEARCH-LEDGER-001-SECOND-EYE.md` | `41967CBB6DBA0D559A3201214F17625E3118A1DA6D6888EC5BAF9A5CFE3AF425` | `eadbc8794662966312a23ad730a69f4005294909` |

Canonical SHA-256 is over Git blob bytes. Line-ending conversion grants no byte
change. Any drift is `BLOCKED_ACCEPTED_LEDGER_BYTE_DRIFT`.

Only three current shared governance files may receive minimal semantic edits:

- `docs/argus-office/ROADMAP.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/BRANCH_LEDGER.md`

Never copy their historical `251ac051` bytes over current governance. Preserve
the authorized correction and chronology, anomaly/unknown-actor disclosure,
accepted Strategy Science and Ledger history, temporary Ledger absence,
candidate restoration, suspended Observer, production freeze, branch-integrity
governance, and current cross-subproject state. Historical states stay labeled.
This reconciliation Goal Charter is the sole additional tracked process-
governance artifact required for task framing. Builder remains limited to the
six exact artifacts, and Release Scribe remains limited to the three shared
governance files; no other tracked path is authorized by this charter.

## Forward-Only Boundary

Required history is `99b95f5 -> new reconciliation commits`. Materialize only
the six verified blobs plus semantic governance edits. Do not:

- restore the entire `251ac051` tree or any historical tree;
- revert `99b95f5` or restore/copy historical governance wholesale;
- reset, cherry-pick, rebase, merge, squash, force-push, delete branches, or
  rewrite history;
- checkout/restore a whole historical tree;
- clean correction/quarantine/history references; or
- push or merge anything to `master`.

The candidate diff against `99b95f5` must contain only the six exact artifacts
and three semantic governance paths, and prove:

`UNAUTHORIZED_CONTENT_REINTRODUCED = FALSE`

No GUI, Observer, provider, broker, runtime, scheduler, scoring, ranking,
TradePlan, risk, execution, Paper, Shadow, configuration, database, abandoned
experiment, or unrelated cross-subproject content may return.

## Authority And Observer Suspension

Restored Ledger authority remains exact:

```text
RESEARCH_ONLY = TRUE
PRODUCTION_DECISION_AUTHORITY = NONE
EXECUTION_AUTHORITY = NONE
PROVIDER_ACCESS = NONE
BROKER_ACCESS = NONE
SCHEDULING = NONE
PRODUCTION_INFLUENCE = NONE
```

`ARGUS-DIRECTIVE-CURRENT-EDGE-PROSPECTIVE-OBSERVER-001` is suspended, not
rejected: `SUSPENDED_PENDING_CANONICAL_LEDGER_RECONCILIATION` and
`PROSPECTIVE_OBSERVER_IMPLEMENTED = FALSE`. Do not create, restore, amend,
resume, or test Observer implementation. Its old base `251ac051` cannot be
reused; Steven must later reissue it against the new canonical head.

## Roles And Required Fresh Proof

- Goal Steward owns only this charter.
- Git Steward proves admission, ancestry, refs, diff scope, and refuses every
  forbidden Git operation.
- Builder owns only the six exact additions; Release Scribe owns only semantic
  governance reconciliation and the report packet.
- Independent second eye compares Git blobs/trees directly.
- Steven retains the merge/canonical decision.

After final bytes, run and report as newly executed:

1. Ledger focused suite `48/48 PASS` and H01-H18 `18/18 PASS`.
2. All fourteen accepted Ledger terminal truths.
3. Bounded owner regressions, expected baseline `207 / OK / one expected skip`,
   but report the truthful fresh result and never relabel stale evidence.
4. Compile/clean-import and deterministic normal versus optimized (`-O`) proof.
5. Exact P1/O1 packet, receipt, fingerprint, and stored-byte identities.
6. Tamper/truncation/partial/restart/hardlink/traversal/reparse/root,
   duplicate-idempotency, and immutable-conflict checks.
7. Six-artifact SHA/blob, branch/tree/ancestry, changed-path, protected-path,
   capability/import, secret, conflict, whitespace, Markdown/link, and
   `git diff --check` checks.

Expected protected status is `NO CHANGE` for strategy/scoring, ranking,
TradePlan, risk/sizing, execution/orders/accounts, brokerage/providers,
Paper/Shadow, GUI, runtime/services/schedulers, live configuration/secrets,
database/schema, and local/remote `master`; Observer is `NOT IMPLEMENTED`.
Unexpected change is `BLOCKED_PROTECTED_PATH_DRIFT`.

## Independent Review And Review Package

The second eye must prove exact `99b95f5`/tree start; preserved correction
ancestry; all six accepted hashes/blobs; forward-only restoration with no
forbidden Git operation; truthful semantic governance chronology; no unrelated
content; all fresh tests/truths; unchanged production authority/protected paths;
suspended/unimplemented Observer; and explained final branch chronology. Author
narrative alone is insufficient. Success is branch-only
`ACCEPTED_FOR_STEVEN_REVIEW`; any later byte change refreshes affected review.

The sanitized Steven bundle must include executive GO/NO-GO, exact commit graph
and movement classification, pre-reconciliation and accepted Ledger identities,
Phase A file matrix, six hash/blob proofs and restored artifacts, three semantic
governance diffs, fresh tests/fourteen truths/protected proof, second-eye report,
final candidate head/tree/parent/ancestry and push/merge state, manifest, and a
detached manifest/ZIP checksum sidecar using the accepted non-self-referential
pattern. It must distinguish Ledger history presence from HEAD-tree presence.

## Seventeen Terminal Acceptance Truths

Any false, ambiguous, or `NOT_PROVEN` safety-critical line blocks acceptance:

```text
CURRENT_CANONICAL_BASE = 99b95f530513343702e70077f970c43b5524c613
CURRENT_CANONICAL_TREE_VERIFIED = TRUE
LEDGER_HISTORY_PRESERVED = TRUE
LEDGER_PRESENT_IN_PRE_RECONCILIATION_HEAD_TREE = FALSE
LEDGER_ACCEPTED_BYTES_IDENTIFIED = TRUE
LEDGER_RESTORED_ON_CANDIDATE_BRANCH = TRUE
LEDGER_MODULE_BYTES_MATCH_PRIOR_ACCEPTANCE = TRUE
LEDGER_TEST_BYTES_MATCH_PRIOR_ACCEPTANCE = TRUE
AUTHORIZED_CORRECTION_HISTORY_PRESERVED = TRUE
UNAUTHORIZED_CONTENT_REINTRODUCED = FALSE
SHARED_GOVERNANCE_CHRONOLOGY_RECONCILED = TRUE
PROSPECTIVE_OBSERVER_IMPLEMENTED = FALSE
PRODUCTION_DECISION_AUTHORITY = NONE
EXECUTION_AUTHORITY = NONE
PRODUCTION_RUNTIME_MUTATION = NONE
HISTORY_REWRITE_USED = FALSE
CANONICAL_MASTER_MUTATED_BY_THIS_DIRECTIVE = FALSE
```

Closeout also repeats the Phase A seven truths and movement classification.

## Stop, Rollback, And Git Closeout

Stop `BLOCKED_NEEDS_STEVEN_REVIEW` for base/tree/branch drift; unexplained ref
mutation; changed/ambiguous Phase A truth; unidentified or changed accepted
bytes; inseparable correction/collateral content; unrelated resurrection;
destructive-history need; chronology-erasing governance; production/protected
change; Observer need; or failed test, integrity, review, manifest, or package
gate outside this narrow outcome. Never solve ambiguity by reverting correction,
restoring `251ac051` wholesale, copying old governance, or rewriting history.

Rollback is a normal reviewable forward change removing only candidate additions
and semantic governance delta. It cannot touch `master`, correction history,
preserved refs, production state, or unrelated data.

After all gates, Git Steward may create and ordinarily non-force push review
commits only on the task branch and read back that branch exactly. This charter
requires:

```text
MASTER_MUTATION = NO
MERGE = NO
FORCE_PUSH = NO
CANONICAL_INTEGRATION = NO
```

Successful status is
`IMPLEMENTED_PENDING_STEVEN_REVIEW / RESEARCH_ONLY`, not canonical `COMPLETE`.
Return the candidate branch and package to Steven. Do not resume Observer work.

## Goal Steward Decision

`BUILDER_GO = TRUE`, bounded strictly to the six exact additions and semantic
three-file reconciliation after Git Steward revalidates admission. All Phase A,
test, protected, second-eye, package, no-master, and no-merge gates remain
mandatory.
