# ARGUS-SCHWAB-AFTER-HOURS-001 Readiness

Status: `IMPLEMENTED_PENDING_TUESDAY_PROOF`

## Implemented

- A fixed-date after-hours guard accepts only 4:00-8:00 PM Eastern on Tuesday,
  August 11, 2026.
- The existing guarded Schwab candle observer is reused for SPY, QQQ, and NVDA
  with extended hours enabled and no production persistence.
- Quote age, candle age, complete OHLCV, Streamer completion, price-history
  completion, comparable minutes, OHLC agreement, and read-only safety are
  adjudicated separately.
- Volume-only stream/history differences are preserved as
  `PROVEN_WITH_LIMITATIONS`; stale, missing, or OHLC-conflicting evidence is
  `DATA_INSUFFICIENT`.
- Proof files are write-once, fingerprinted, sanitized, and stored outside the
  repository.
- Runner preflight pins clean Git identity and the exact module SHA-256.

## Scheduled Tasks

- `Momentum Hunter Schwab After Hours Open Proof 20260811` at 15:05 Central.
- `Momentum Hunter Schwab After Hours Late Proof 20260811` at 18:35 Central.

Both tasks are Ready, wake-enabled, limited to the current interactive user,
configured with two bounded retries, and export their task XML to
`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles`.

## Verification Before Scheduling

- New focused tests: 10 pass.
- Affected Schwab quote/candle/overnight boundary: 100 pass.
- Full Python discovery: 1,332 pass.
- PowerShell parser and plan-only runner/installer: pass.
- Central time zone, NIST synchronization, Schwab HTTPS reachability, no AC
  sleep/hibernate, enabled wake timers, and Running/Automatic automation
  service: confirmed.
- No existing Tuesday proof output was present at installation.

## Residual Risk

The tasks use current-user DPAPI and therefore require Steven's Windows session
to remain logged in. A locked desktop is acceptable. A logout, power-off,
credential revocation, provider outage, or Schwab entitlement change can still
produce a fail-safe result. The early and late runs are independent so one
valid disappointing result cannot be overwritten by the other.
