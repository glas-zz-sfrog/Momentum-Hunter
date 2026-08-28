# ARGUS-STAT-DATA-002C Goal Charter

## Objective

Repair the confirmed provider-contact accounting defect, prove Schwab quote and
history readiness before consuming another prospective observation window, and
run one final natural 30-minute STAT-DATA canary only after those gates pass.

## Authorized Scope

- Derive provider-contact truth from the hash-verified exported runtime
  inventory and distinguish attempted paths from physically preserved provider
  responses.
- Report Finviz and Schwab contact independently without treating Schwab
  failures as successful market-data retrieval.
- Add a bounded, read-only, disposable Schwab SPY quote/history preflight using
  the existing approved market-data authentication and provider paths.
- Preserve sanitized preflight evidence and require a current passing proof
  before prospective activation/provider runtime launch.
- Replay the immutable 002B packet through the repaired reporter, rehearse
  packaging, run Hard Chew, and schedule one clean next-session canary when
  same-day time is insufficient.

## Prohibited Changes

Do not change prospective population definitions, denominator semantics,
Continuous discovery/readiness/composition/TradePlan behavior, Schwab provider
or authentication semantics, Paper, Shadow, broker, account values, positions,
orders, execution authority, services, installed runtime, or canonical
production.

## Acceptance

1. The preserved 002B packet replays as provider contact `YES`, Finviz contact
   `YES`, and successful Schwab market-data contact `NO`.
2. Attempt-only and absent-provider cases remain contact `NO`.
3. Provider identities come from verified exported files or explicit preserved
   successful Schwab counters, not an obsolete guessed directory.
4. A sanitized Schwab preflight proves active authorization, one current SPY
   quote with valid clock evidence, and one bounded SPY history response in
   disposable stores without account-value, position, Paper, Shadow, or order
   access.
5. A failed preflight creates no activation and consumes no canary clock.
6. Focused tests, package rehearsal, full discovery, compile, scans, and
   protected-boundary review pass before another live canary.
7. Every terminal live result produces a sanitized verified second-eye ZIP and
   stops for independent review.

## Stop Gate

No merge or deployment is authorized. After the terminal live packet, stop for
independent second-eye review.
