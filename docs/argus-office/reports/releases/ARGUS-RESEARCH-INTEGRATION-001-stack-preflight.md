# ARGUS-RESEARCH-INTEGRATION-001 Research Stack Preflight

## Classification

`INTEGRATION_PREFLIGHT_COMPLETE_PENDING_AUGUST_17_EVIDENCE`

This is an isolated integration rehearsal. It is not canonical, installed,
scheduled, activated, or authorized to influence production decisions.

## Frozen Lane

- Canonical checkout:
  `C:\Users\steve\OneDrive\Documents\Investing`
- Canonical and `origin/master` before-image:
  `ea056155182351be70bb03d23841aca55c6118ae`
- Preflight worktree:
  `C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-RESEARCH-INTEGRATION-001`
- Installed manifest SHA-256 before-image:
  `8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`
- Service before-image: `Running / Automatic`
- August 17 before-image: opening, Paper, successor Pass 1, and successor
  Pass 2 all `PENDING` at exact expected Git head `ea056155`.

## Dependency Graph

```text
ea056155 canonical base
|-- SPECIALIST-CONTRACT-001
|   |-- STAT-DATA-001
|   |-- REGIME-002
|   |-- EXEC-QUALITY-001
|   |-- EVENT-SHOCK-001
|   |-- TECH-STRUCTURE-002
|   `-- EXIT-RESEARCH-001
|-- RESEARCH-DATA-001
|   `-- RESEARCH-DATA-002
`-- RESEARCH-GOV-001
```

RESEARCH-GOV-001 has static naming references to future research identities,
but no import dependency on the specialist or data branches. STAT-DATA-001
depends only on the common specialist contract; it does not import the
individual specialist implementations.

## Source Branches

| Task | Authoritative head | Parent | Remote backup |
| --- | --- | --- | --- |
| SPECIALIST-CONTRACT-001 | `e65cb702dfd0c2515c8c37bae6fd377315c71f83` | implementation `802f2d1`, then verification closeout | Equal |
| RESEARCH-DATA-001 | `d03301cec3d2f675ca03f32a2c8c8e5e4adc9726` | `ea056155` | Equal |
| RESEARCH-DATA-002 | `12e6a05d0f1f2e860edb522c7a9247c3a39fbdf6` | DATA-001 `d03301c` | Equal |
| RESEARCH-GOV-001 | `0f61e4898063f9a8b7949d227880bee03384542e` | `ea056155` | Equal |
| STAT-DATA-001 | `cd95490661b54c73af162c8b9f651039006ad0c6` | specialist `e65cb70` | Equal |
| REGIME-002 | `99a25f84219377e9988e8284aa15a944e3936784` | specialist `e65cb70` | Equal |
| EXEC-QUALITY-001 | `1b105e71d99d45a8ed8099ae4001bd9c6ba2242f` | specialist `e65cb70` | Equal |
| EVENT-SHOCK-001 | `fe8ca09556fe8ea3dd81949e59ac26d8e3d86da4` | specialist `e65cb70` | Equal |
| TECH-STRUCTURE-002 | `1b47b4ad4cac7f5b944b0662e5c2269ffa8829a6` | specialist `e65cb70` | Equal |
| EXIT-RESEARCH-001 | `c8fcc15395e5ac3b76c16fc6ac28b6a0c7da2899` | specialist `e65cb70` | Equal |

All source worktrees were clean. Every composed implementation module is
byte-identical to its authoritative branch object.

## Rehearsed Order

1. Common specialist contract and its verification closeout.
2. Research data inventory.
3. Research security identity and price-basis contract.
4. Research experiment governance.
5. Prospective opportunity denominator.
6. Regime exhaustion specialist.
7. Execution-quality specialist.
8. Event-shock specialist.
9. Technical-structure specialist.
10. Exit-intelligence specialist.

This order applies each parent once and only the unique child commit from each
stacked branch.

## Conflict Matrix

No source, test, package, schema, config, scheduler, service, broker, WPF, or
runtime conflict was found.

| Applied branch | Dry-merge conflicts |
| --- | --- |
| RESEARCH-DATA-001 | `BRANCH_LEDGER`, `RISK_REGISTER`, `ROADMAP`, `TASK_LOG` |
| RESEARCH-DATA-002 | `BRANCH_LEDGER`, `RISK_REGISTER`, `TASK_LOG` |
| RESEARCH-GOV-001 | all five shared governance ledgers |
| STAT-DATA-001 | all five shared governance ledgers |
| REGIME-002 | `BRANCH_LEDGER`, `RISK_REGISTER`, `ROADMAP`, `TASK_LOG` |
| EXEC-QUALITY-001 | all five shared governance ledgers |
| EVENT-SHOCK-001 | all five shared governance ledgers |
| TECH-STRUCTURE-002 | all five shared governance ledgers |
| EXIT-RESEARCH-001 | all five shared governance ledgers |

The five shared ledgers are `BRANCH_LEDGER.md`, `CHANGELOG_ARGUS.md`,
`RISK_REGISTER.md`, `ROADMAP.md`, and `TASK_LOG.md`. The overlap is caused by
independent branches prepending current-state entries to the same files.

The dry merge also exposed branch-local reuse of `R-083`, `R-086`, and
`R-087`. The combined preflight assigns unique IDs `R-086` through `R-095`.
This is governance reconciliation only; no implementation behavior changed.

## Combined Behavior

- The common opinion contract remains the only shared specialist dependency.
- No production module imports any new research module.
- No arbiter, vote counter, universal score, or authority combiner exists.
- Abstention/failure remains distinct from neutral opinion.
- Specialist outputs retain `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`.
- Research data remains identity/basis/survivorship limited.
- STAT-DATA-001 remains inactive and lacks producer wiring.
- RESEARCH-GOV-001 remains an offline contract with no active registry.
- Every individual specialist remains offline, unpersisted, and unactivated.

## Verification

- Compileall: PASS.
- Combined focused stack: PASS, 367 tests.
- First full discovery: 2,380 tests, two environment-only failures because the
  new isolated worktree did not contain its expected `.venv` junction.
- Worktree environment correction: added an ignored junction from the
  preflight worktree `.venv` to the canonical virtual environment; no tracked
  file changed.
- Exact affected regression rerun: PASS, 45 tests.
- Final full discovery rerun: PASS, 2,380 tests.
- Source fidelity: PASS; all ten implementation modules are byte-identical to
  their authoritative source branches.
- Existing-runtime importer scan: PASS, zero hits.
- Network/broker import scan: PASS, zero hits.
- Submit/cancel/replace/network call-site scan: PASS, zero hits.
- Conflict-marker scan: PASS, zero hits.
- Risk-ID uniqueness: PASS, zero duplicates after combined reconciliation.
- Secret scan: PASS. Fourteen conservative matches were inspected; thirteen
  are 40/64-character commit or fingerprint fixtures and one is a test class
  identifier. No credential-shaped value is present.
- Protected-path review: PASS. Changed top-level areas are only
  `docs/argus-office`, top-level offline `momentum_hunter` modules, and tests;
  no package, schema, config, service, scheduler, WPF, broker adapter, or
  existing production module changed.
- Canonical nonmutation: PASS at final closeout; canonical Git, installed
  manifest hash, service state, and all four August 17 receipts match the
  frozen before-image.

## Remaining Gates

- Preserve and adjudicate the August 17 opening, Paper, and both SETUP-002
  receipts before canonical integration.
- Reconcile this branch against the then-current canonical head and rerun Hard
  Chew; do not assume `ea056155` remains the integration base.
- Implement STAT-DATA-002 producer wiring separately before denominator
  activation.
- Give each specialist a separately authorized producer, persistence model,
  prospective sample, calibration plan, and authority study before any runtime
  use.
- Resolve the research-data security identity, corporate-action basis, and
  survivorship gaps before broad historical claims.

## Recommendation

After August 17 evidence is terminal, use this rehearsal as the source of one
deliberate parent-first integration pass. Do not merge the ten original
branches independently and do not activate any research component as part of
that integration.
