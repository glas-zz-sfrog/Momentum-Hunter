# ARGUS-SCHWAB-CONTINUOUS-AUTH-LIFECYCLE-001

## Goal Statement

Make Schwab read-only market-data authentication recover unattended from ordinary access-token expiry across multiple Momentum Hunter processes, while preserving exact failure classifications and zero financial authority.

## User Pain / Operator Outcome

An expired access token must cost one bounded refresh, not the rest of the trading day. A failed read must remain an explicit system failure, and a later prospective cycle must recover without a reboot or session restart.

## In Scope

- Cross-process single-flight ownership for the shared encrypted Schwab OAuth state.
- Atomic reread, refresh, persistence, and stale-state adoption.
- Market-data-only refresh for Continuous Runtime with no account endpoint.
- One bounded retry after HTTP 401, distinct HTTP 403 and interactive-reauth classifications.
- Sanitized auth-health metrics and readiness failure evidence.
- Focused, multiprocess, restart, continuous-recovery, and full-suite proof.
- Exact verified canonical deployment and a new live read-only canary when market time permits.

## Out Of Scope

- Account, balance, position, transaction-history, preview, or order endpoints.
- Strategy, Finviz qualification, universe, composition, TradePlan, Risk Governor, Paper, Shadow, writer payload, poison handling, or cadence changes.
- Continuous Paper or live execution activation.

## Protected Areas

Schwab credentials, production authentication state, and Continuous Runtime behavior are touched only for the exact lifecycle repair authorized by Steven's directive. Stop for an undecryptable/missing store, account-scope anomaly, secret exposure, provider behavior requiring broader authority, unsafe Git state, or any order-capable path. If the refresh credential is rejected, stop automatic repair at `SCHWAB_INTERACTIVE_REAUTH_REQUIRED` and use the existing browser OAuth flow without exposing credentials.

## Acceptance Criteria

- Exactly one process owns refresh; all waiters reread and adopt the resulting state.
- Refresh state is never overwritten by a stale process and is persisted atomically.
- Continuous market-data refresh makes no account or order request.
- Expiry and one HTTP 401 recover once; a second 401 fails closed; 403 remains distinct.
- Auth failure is preserved and later same-day readiness can succeed.
- Installed service context proves quote, minute/history, canonical parse, and readiness consumption.
- Full Hard Chew and a terminal live canary pass before governance claims success.

## Evidence Required

- Sanitized starting identity/store/service evidence and immutable failed-canary bundle.
- Deterministic two-process contention, stale-reread, persistence-failure, restart, 401/403, reauth, and no-secret tests.
- One-run full Python suite, compileall, diff check, secret/capability/protected-path scans.
- Before/after deployment hashes and terminal canary metrics.

## Evidence Depth / Hard Chew Requirements

- Compile all Python sources.
- Run focused Schwab OAuth, market-data, candle, backfill, readiness, and continuous recovery tests.
- Run the complete Python test suite in one invocation.
- Review every auth/runtime diff for account/order capability and diagnostic leakage.
- Preserve failures; fix narrowly; repeat affected and broad proof.
- Update the authoritative Roadmap only from observed branch, merge, deployment, and canary facts.

## Smallest Safe Implementation Slice

Introduce one path-derived cross-process refresh coordinator shared by all Schwab token writers; add a pure OAuth read-only refresh consumer for Continuous market data; expose sanitized lifecycle counters; retain existing account-bound workflows outside Continuous.

## Open CEO Decisions

- None unless interactive OAuth is actually required or an account/authority anomaly appears.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove the requested outcome.
- [x] Evidence required is strong enough to verify completion.
