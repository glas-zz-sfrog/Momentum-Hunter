# ARGUS-DATA-001B Evidence Authority Enforcement

## Classification

`IMPLEMENTED_PENDING_INTEGRATION_AFTER_2026-08-04_CAPTURE`

## Defect

DATA-001 truthfully labeled unresolved catalyst and research-only price evidence,
but it intentionally preserved the legacy composite and rank. Monday's four
unresolved catalysts could therefore remain influential after their authority
was blocked, and the selector did not consume the new integrity record.

## Repair

- Added `trade-planning-composite-v2-evidence-authority` with a canonical
  configuration and SHA-256 fingerprint.
- Blocked catalyst confidence contributes zero; blocked clusters cannot create
  risk-on bonuses or catalyst-derived outperformance claims.
- Current research-only price evidence forces
  `DO_NOT_TRADE_UNTRUSTED_EVIDENCE` unless a more specific do-not-trade state
  already applies.
- Shadow selection rejects missing/legacy profile metadata, configuration or
  fingerprint contradictions, unsupported integrity schema, research-only
  price/plan authority, unresolved catalyst authority, and inconsistent
  catalyst contribution records.
- Historical artifacts remain immutable. The new rule is prospective and
  carries a new profile/fingerprint rather than silently rewriting old scores.

## Monday Prospective Comparison

| Symbol | Stored score / rank | Prospective score / rank | Catalyst authority |
| --- | --- | --- | --- |
| MSFT | 83 / 1 | 78 / 2 | BLOCKED; zero contribution |
| GOOGL | 81 / 2 | 80 / 1 | BLOCKED; zero contribution |
| CMCSA | 80 / 3 | 76 / 3 | BLOCKED; explicit DIS mention preserved |
| AMZN | 79 / 4 | 75 / 4 | BLOCKED; zero contribution |

The stored Monday report SHA-256 remains
`7E905BBA2392BD91803978DA73128C75399AEF37442C583870C13523CD0D6E99`.

## Proof

- Python compileall: pass.
- Focused evidence/planning/selection tests: 70/70.
- Adjacent Shadow/lifecycle/host/autonomy/workstation tests: 191/191.
- Candidate-story isolation after detecting overlapping full-suite runners: 8/8.
- Clean full Python discovery: 1,066/1,066 in 190.229 seconds.
- Negative tests prove unresolved catalyst, research-only price, legacy profile,
  tampered configuration, and contradictory catalyst contribution cannot create
  an eligible Shadow candidate or trade.
- Source nonmutation tests remain green.

## Protected Behavior

This patch deliberately changes prospective composite catalyst authority,
TradePlan execution eligibility, and selector fail-closed semantics within the
authorized DATA-001B scope. It does not change RVOL, entry/stop/target formulas,
position sizing, Risk Governor calculation, FakeBroker lifecycle, accounts,
credentials, provider networking, broker/order behavior, transmission, UI,
database/schema, service, scheduler, raw captures, or generated evidence.

## Operational Freeze

Canonical `master` and `origin/master` remain clean at `2aa4ef3`. The installed
service is Running/Automatic, and `opening-capture-20260804` remains `PENDING`
for 08:35 Central with latest start 08:40 and expected Git head `2aa4ef3`.
DATA-001 and DATA-001B must integrate in order only after that terminal capture
is preserved, followed by a deliberate remaining-job repin and fresh service
identity proof. Shadow remains unarmed at `0 / 30`; order transmission remains
`UNAVAILABLE`.
