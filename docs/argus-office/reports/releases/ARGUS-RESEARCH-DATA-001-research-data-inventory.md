# ARGUS-RESEARCH-DATA-001 Release Report

## Classification

`IMPLEMENTED_PENDING_MERGE`

## Scope

Added a standalone, read-only inventory engine and deterministic reports for
Momentum Hunter's current historical and prospective research evidence. The
task does not add data collection, select a provider, or change runtime
authority.

## Inventory Result

- Canonical Schwab minute history: 38,286 bars, 7 symbols, 17 session dates.
- Canonical Schwab Daily history: 1,764 bars, 7 symbols, 252 bars per symbol.
- Research-only adjusted Daily history: 79,298 rows, 263 symbols; 248 symbols
  have at least 200 bars and 15 are sparse.
- Candidate history: 1,256 rows across 290 symbols; opening artifacts do not
  preserve a complete raw/rejected denominator.
- SETUP-002: activated prospectively but empty, with first eligibility on
  August 17, 2026.
- Inventory fingerprint:
  `5D414FDC41BA78DBC07328653EA491847377D0C5690904F96E4067C6CB2BA735`.

## Capability Result

Daily technical-pattern research and rank/setup-conditioned outcomes are
`PARTIAL`. Intraday analogs, true premarket structure, failed breakouts,
continuation/pullback/reclaim statistics, regime conditioning, event studies,
time-of-day effects, and historical analog modeling are `INSUFFICIENT`.

The principal blockers are narrow canonical breadth/depth, incomplete
extended-session classification, missing durable security identity and symbol
continuity, missing corporate-action transformation lineage, incomplete
prospective opportunity denominators, and insufficient event attribution.

## Universe Integrity

All inspected histories are ticker-keyed. No inspected dataset preserves a
durable security identifier, ticker effective dates, delisted-security
coverage, point-in-time universe membership, or a complete corporate-action
event chain. The 263-symbol Daily cache is therefore research-only and cannot
be treated as a survivor-safe canonical universe.

## Provider Decision

No new provider was selected or recommended. Existing Schwab backfill and
prospective evidence collection must first be measured against the explicit
gap exit conditions. Any later provider proposal must name the exact fields,
depth, authority, denied authority, cost, and exit condition it addresses.

## Verification

- Python compileall: pass.
- Focused inventory tests: 13 pass.
- Adjacent data/candle/research regression tests: 188 pass.
- Full Python discovery: 2,026 pass in 271.412 seconds.
- Two initial full-discovery failures were isolated-worktree bootstrap failures:
  two PowerShell tests required `<worktree>/.venv`. A temporary ignored junction
  to the canonical virtual environment made both modules pass 35/35 and the
  complete suite pass 2,026/2,026; the junction was then removed.
- `git diff --check`: pass.
- Protected-path review: pass; only the new read-only module, its tests,
  hash-addressed reports, and governance files changed.
- Capability scan: pass; no network/provider/broker/service import or call is
  present. The sole `submit_order` match is a negative test assertion.
- Secret scan: pass; matches are historical governance labels such as OAuth or
  credentials, with no credential-shaped value in task code or evidence.

## Safety

The module imports no provider, network, account, position, broker, order,
service, scheduler, Engine Host, WPF, scoring, readiness, or execution path.
It reads explicit source paths and writes only explicit write-once report
outputs. Source evidence is never normalized or repaired in place.

## Recommendation

Close the security-identity and corporate-action basis gap before broad Daily
pattern claims, and begin the prospective opportunity-denominator work before
rank/setup statistics. Do not procure another provider until an exact gap
survives those two bounded tasks.
