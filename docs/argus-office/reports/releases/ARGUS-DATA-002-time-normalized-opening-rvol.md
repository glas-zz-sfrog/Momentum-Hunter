# ARGUS-DATA-002 Time-Normalized Opening RVOL

Status: `COMPLETE`

## Result

Prospective TradePlan and Active Monitor reports no longer treat partial-session
volume divided by a full-day average as execution-authoritative RVOL. The
authoritative value now comes from terminal canonical Schwab minute bars and
compares identical elapsed-session windows. Historical captures and reports
remain unchanged.

## Evidence Contract

- Schema 1 and profile `time-normalized-rvol-v1` record source, symbol, RVOL
  type, session date/minute, window timestamps, observed and expected volume,
  ratio, current bar counts, baseline policy, baseline dates, formula, and
  findings.
- Opening evidence at 08:35 Central uses completed 09:30-09:34 Eastern bars;
  the current minute and later minutes are excluded.
- Premarket and completed Daily evidence use the same elapsed-window rule.
- Five complete comparable prior sessions are required; twenty are targeted.
- Missing current bars, too few baselines, zero expected volume, invalid source,
  type or symbol mismatch, contradictory chronology, or tampering fails closed.
- The legacy ratio remains visible as `LEGACY_RVOL_RESEARCH_ONLY` and cannot
  grant readiness or selection authority.

## Runtime Boundaries

- The calculator reads the existing canonical candle store; it makes no network,
  provider, account, position, order, broker, or transmission call.
- Active Monitor reuses the evidence and cannot promote a row without it.
- Shadow independently revalidates schema, profile, source, symbol, formula,
  volumes, ratio, bar counts, baseline count and dates, chronology, and report
  agreement before a candidate can be eligible.
- Discovery score, composite score weights, alert thresholds, plan formulas,
  account allocation, FakeBroker lifecycle, UI, database schema, packages,
  credentials, raw captures, generated reports, and legacy candle data are
  unchanged.

## Verification

- Python compileall: pass.
- Focused TradePlanning, Active Monitor, evidence-integrity, RVOL, and selector
  suite: 92 passed before final self-review.
- Full Python discovery: 1,236 passed in approximately 18.9 minutes.
- Full .NET solution: 251 passed.
- Final cross-symbol evidence fix: compileall plus 58 RVOL/selector tests pass.
- `git diff --check`: pass.
- Secret/network/account/order capability review: no new capability or sensitive
  value.
- Source nonmutation and unchanged discovery/composite scores: proven by tests.

## Remaining Limits

- Authority is intentionally unavailable until the canonical store contains a
  complete current elapsed window and at least five comparable prior sessions.
- DATA-002 does not itself fetch or backfill candles; R032/R032B/R032C own that
  bounded collection and history-loading path.
- Official Shadow remains unarmed and blocked by DATA-003 through DATA-005.
- R034 legacy archive/deletion remains a separate Steven approval gate.

## Integration Closeout

- Feature commit `876eb2e` is pushed and fast-forwarded into canonical `master`.
- Local and remote `master` are synchronized and clean.
- The guarded Engine Host snapshot accepts the current runtime identity.
- All 25 future opening jobs are pending from Monday 2026-08-10 through
  2026-09-14 at the final synchronized closeout head.
- Zero Shadow jobs are enabled and order transmission remains `UNAVAILABLE`.
