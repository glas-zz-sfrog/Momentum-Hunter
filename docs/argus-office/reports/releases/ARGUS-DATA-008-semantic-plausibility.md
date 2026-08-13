# ARGUS-DATA-008 - Semantic Plausibility Gate

## Status

- Branch: `codex/ARGUS-DATA-008-semantic-plausibility`
- Base: synchronized canonical `a9821ed`
- Classification: `IMPLEMENTED_PENDING_INTEGRATION_AFTER_AUGUST_14_EVIDENCE`
- Canonical/runtime integration: none

## Implementation

- Added a pure deterministic semantic evaluator with versioned policy,
  structured issues, scanner-rejection accounting, and SHA-256 fingerprints.
- Finviz now evaluates parsed economic rows before filtering or scoring and
  fails closed on impossible/out-of-bounds relationships, unexplained row loss,
  duplicate symbols, or suspicious repeated values.
- A legitimate zero-candidate result remains valid when scanner criteria explain
  every rejection; rejection counts are emitted in the provider diagnostic log.
- Optional contextual checks reject stale, future, wrong-session, non-Schwab,
  severely disagreeing price evidence and explicitly comparable volume
  contradictions. They never substitute the authoritative value into Finviz.
- Optional verified-baseline input detects extreme cross-run distribution shifts.
- Semantic failures are nonretryable deterministic capture failures and preserve
  a compact structured diagnostic payload in the failure record/log.

## Verification

- Python compileall: pass.
- Focused semantic/provider/capture tests: 71/71 pass.
- Bounded provider, capture, workflow, scoring, storage, and TradePlan regression:
  105/105 pass.
- Initial full discovery identified two worktree-environment failures because a
  local `.venv` was absent; both exact tests passed after adding an ignored
  junction to the canonical dependency environment.
- Final corrected full Python discovery: 1,944/1,944 pass in 239.048 seconds.
- No provider, account, broker, service, scheduler, Engine Host, WPF, production
  data, or credential call occurred.

## Remaining Work

- After August 14 evidence is terminal, reconcile and integrate only if the
  feature branch remains ancestry-compatible and all safety checks still pass.
- Wire contextual Schwab/candle comparisons only when the opening/continuous
  pipeline can supply exact authoritative source, receipt, timestamp, session,
  and field-comparability evidence.
- Do not treat the broad sanity bounds as strategy thresholds or tune them from
  remembered winners.
