# ARGUS-SHADOW-003 - Sample Readiness Gate

## Branch And Status

- Branch: `codex/ARGUS-SHADOW-003-sample-readiness-gate`
- Implementation commit: `9002df0`
- Classification: `IMPLEMENTED_PENDING_MERGE`
- Local `master`: `fe3326d`, seven commits ahead of `origin/master` at `69feedf`
- Push: none
- Merge: none
- Official sample: not started

## Scope

Shadow-003 prepares the existing prospective FakeBroker evidence path for a future
official sample. It adds an immutable active sample definition, freezes that definition
on every newly created Shadow Trade and nontransmitting ticket, audits the complete
definition, excludes evidence that does not match it exactly, and exposes the locked
state read-only in WPF.

The default definition is `engineering-preflight-v1` with official authorization
false. Opening the review does not create a state file, trade, ledger event, broker
request, or sample record.

## Runtime Behavior

- `momentum_hunter/shadow_trading.py`
  - Adds deterministic sample, strategy/configuration, fill-model, and evidence-schema
    metadata.
  - Fingerprints canonical strategy and execution-policy inputs with SHA-256.
  - Persists metadata with each new trade and ticket across atomic JSON restart.
  - Preserves legacy records without writing or backfilling them.
  - Excludes unauthorized, unversioned, malformed, obsolete, tampered, or active-
    definition-mismatched records.
  - Fails same-version/configuration conflicts in the readiness audit.
  - Includes the exact definition in command idempotency fingerprints and risk ledger
    evidence.
  - Routes both raw and review aggregate metrics through the same eligibility gate.
  - Returns `BLOCKED`, `PASS`, or `IN_PROGRESS` readiness with explicit findings.
  - Adds no sample-start command. A passing result is pure and has no side effect.
- WPF contracts and presentation
  - Strictly validate sample version syntax, lowercase SHA-256 fingerprints, fill-model
    identity, evidence-schema version, authorization, counted-trade definition
    equality, and start-gate consistency.
  - Display `SAMPLE START LOCKED`, the exact preflight definition, and the blocking
    reason in the existing read-only Shadow Review.
  - Add no button, command, broker client, credential, Paper control, Live control, or
    transmitting method.

## Tests

- Python compileall: pass.
- Bounded Python safety suite: 112/112 pass.
- .NET solution: 100/100 pass.
  - Presentation: 55
  - Layout: 5
  - Integration: 40
- Release build: pass with 0 warnings and 0 errors.
- Broader bounded Python modules: 90/92 pass.
  - `tests.test_technical_breakouts`: 15/15 pass in 73.474 seconds.
  - `tests.test_entry_plans`: unchanged legacy Qt module exceeded 120 seconds.
  - `tests.test_gui_states`: unchanged legacy Qt module exceeded 120 seconds.
- `git diff --check`: pass.

Focused tests prove deterministic and policy-sensitive fingerprints, persisted metadata
and restart, source non-mutation, default lock, authorized engineering pass without
state creation, legacy byte preservation, tamper rejection, malformed-state failure,
same-version policy conflict, exact-version counting, unauthorized metric withholding,
invalid-version rejection, and the absence of any start method.

## UI Proof

- Path:
  `docs/argus-office/reports/releases/ARGUS-SHADOW-003-sample-readiness-gate-overview-proof.png`
- Dimensions: 1880 x 1040
- Size: 180,913 bytes
- SHA-256:
  `010C4BA35DDC83C583FC0893A219DEFD4C72C45AB25F9D8B175140FB6B06C6EB`
- Pixel sanity: 34 unique colors in a 40-pixel sampling grid; nonblank.
- Capture method: temporary offscreen WPF harness outside the repository; no mouse,
  keyboard, desktop capture, provider fetch, or source-state write.

Visible proof includes `REVIEW - Read Only`, `FAKEBROKER - NONTRANSMITTING`, `SAMPLE
START LOCKED`, the preflight sample/fill/evidence/config identity, `0 / 30`, withheld
aggregate metrics, excluded synthetic preflight records, frozen evidence/plan state,
and no start or order action.

## Protected Areas

No production scoring, trade readiness, replay identity, historical capture selection,
database schema/migration, alert threshold, TradePlan calculation, Risk Governor
semantics, FakeBroker fill/exit behavior, P&L/R/MFE/MAE calculation, provider fetch,
Schwab network/account/OAuth/credential behavior, Paper/Live control, or transmitting
behavior changed.

The only runtime eligibility change is fail-closed evidence classification for the new
official sample definition. Existing/unversioned records remain readable and preserved
but cannot count toward the new sample.

## Risks And Limits

- Shadow-003 is local branch work and is not remotely backed up.
- The two legacy Qt test modules retain their pre-existing timeout problem.
- Strategy/configuration integrity depends on deliberately versioning the frozen
  strategy contract when a material rule changes; the audit prevents silent mismatch
  against the active policy but cannot infer product intent.
- The proof uses synthetic preflight rows and does not prove official sample outcomes.
- An engineering `PASS` does not start collection, prove profitability, authorize
  broker access, or permit transmission.

## Steven Check

1. Confirm the proof says `SAMPLE START LOCKED`.
2. Confirm the exact preflight sample, fill model, evidence schema, and configuration
   identity are visible.
3. Confirm progress is `0 / 30` and every metric is withheld.
4. Confirm synthetic preflight rows are excluded.
5. Confirm the surface is read-only and FakeBroker-only.
6. Confirm there is no sample-start, broker, Paper, Live, credential, or order action.

Report `PASS SHADOW-003 UI PROOF` or the failed step. Passing the check does not itself
authorize a merge or official sample start.

## Recommendation

Review `9002df0` and the proof, then make a separate local fast-forward decision.
After integration, retain the default lock until Steven separately authorizes the exact
official sample definition. Do not begin trade 1 or a stacked Shadow branch before
those decisions.
