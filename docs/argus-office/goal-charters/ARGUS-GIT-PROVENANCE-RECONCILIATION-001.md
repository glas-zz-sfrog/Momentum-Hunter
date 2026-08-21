# ARGUS-GIT-PROVENANCE-RECONCILIATION-001

## Goal Statement

Replace the ambiguous long-running-experiment nonmutation model with an exact,
auditable provenance contract that separates campaign integrity from authorized
external production changes without rewriting historical evidence.

## User Pain / Operator Outcome

A 12-24 hour experiment must not become scientifically ambiguous merely because
separately authorized production work advances Git, manifests, or services.
Steven must be able to tell exactly what the experiment ran, what production ran,
what changed, who authorized it, and whether the experiment remained isolated.

## In Scope

- Exact ancestry and deployed-product reconciliation for the August 20 overnight campaign.
- A chronological authorized production-change ledger for that campaign window.
- Explicit `CAMPAIGN_NONMUTATION` and `GLOBAL_PRODUCTION_NONMUTATION` claims.
- A reusable, standalone provenance validator/finalizer for future campaigns.
- Shared mutable resource declaration and post-change isolation revalidation.
- Governance correction that preserves the original overnight failure.

## Out Of Scope

- Reclassifying, regenerating, editing, or rehashing the original overnight evidence.
- Adjudicating the overnight provider observations.
- Trading strategy, discovery, Schwab, Alpaca, Paper, writer, runtime, cadence, UI, or execution changes.
- Service restart/reinstall, deployment, manifest/scheduler change, credential refresh, or provider/broker call.

## Protected Areas

The original overnight evidence, production manifests, service definitions,
scheduler, shared credential stores, and installed runtime are read-only. Stop if
canonical Git diverges, installed product differs from current governance by
non-governance code unexpectedly, a historical evidence file changes, or the
reconciliation would require production mutation.

## Acceptance Criteria

- Local `master` equals `origin/master` and the canonical worktree is clean.
- Full-SHA ancestry is proven for `e1ea386`, `e69426b3`, `dca0671b`, `a754226`, and the overnight branch head.
- Installed product versus governance-only HEAD is proven with product-tree comparisons.
- The authorized Schwab lifecycle transition is timestamped with old/new Git, config, manifest, service, and executable identities.
- Shared mutable campaign resources and any historical provenance gaps are explicit.
- The future contract accepts a revalidated external change while keeping global nonmutation false, and rejects broken isolation, tampering, malformed identity, or an undeclared shared resource.
- The original overnight `PRODUCTION_NONMUTATION = FAILED` evidence remains byte-for-byte unchanged.

## Evidence Required

- Git ancestry/remote-containment output and exact tree identities.
- Read-only installed manifest, executable, service, and scheduler hashes.
- Historical campaign state/module hashes and deployment rollback/canary hashes.
- Focused validator tests, compile check, diff check, secret scan, and protected-path review.
- Before/after fingerprints for services, scheduler, manifests, and all overnight evidence files.

## Evidence Depth / Hard Chew Requirements

- Compile the standalone provenance tool.
- Test valid no-change, valid authorized-change, broken isolation, chain mismatch,
  tampering, undeclared resource, and write-once behavior.
- Run bounded adjacent governance/tool tests when available.
- Review every changed path to prove runtime/product semantics are untouched.
- Recompute production and historical-evidence fingerprints after verification.
- Commit and push only the feature branch; do not merge or begin provider-evidence reconciliation.

## Smallest Safe Implementation Slice

Add a standalone provenance contract/verifier, one historical reconciliation
report, and the required current-governance records. Do not import the verifier
from any Momentum Hunter runtime module.

## Open CEO Decisions

- None. A later, separate task must decide the overnight provider-evidence validity.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove the requested outcome.
- [x] Evidence required is strong enough to verify completion.
