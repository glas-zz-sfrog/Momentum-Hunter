# ARGUS-POST-20260814 Integration Reconciliation

## Classification

`READY_FOR_FAST_FORWARD_AND_EXACT_HEAD_REPIN`

## Operational Gate

The August 14 evidence is terminal and preserved. The 05:55 Schwab boundary
checkpoint was useful with explicit candle limitations; the 06:05 checkpoint
was high fidelity for SPY, QQQ, and NVDA quotes, candles, and volume. The 07:00
capture received/parsed 20/20 rows and truthfully qualified zero. The 08:35
opening received/parsed 20/20 rows, qualified SNDK and NU, and completed 5/5
opening bars plus seven baseline sessions for both.

The dependent Canary Alpaca Paper cycle reached candidate strategy logic and
terminated `NO_TRADE`. It found the expected Paper-only account, zero prior
positions/orders, created no order, and performed no Shadow or live action.
SNDK was below its entry trigger; NU was a missed/reclaim setup with inadequate
execution reward/risk.

## SNDK Reconciliation

SNDK's completed-Daily setup invalidation was `$1,331.58`; its DATA-004
opening-range stop was `$1,565.00`; its entry trigger was `$1,696.37`. These are
intentionally distinct concepts. The old selector compared Daily invalidation
to the intraday stop for exact equality and therefore produced a false
contradiction. The repair now:

- validates Daily invalidation against completed-Daily support;
- validates the TradePlan stop against DATA-004 intraday evidence;
- accepts a tighter long stop above Daily invalidation; and
- rejects a stop that permits loss below Daily invalidation.

The defect did not alter August 14 because SNDK never reached its entry.

## Integrated Scope

- SETUP-001 premarket/fresh-setup retrospective research case study.
- SETUP-002 dormant prospective successor observer with empty denominator.
- PAPER-005 actual-fill, post-fill-risk, protection-quantity, and recovery
  reconciliation.
- DATA-008 intrinsic provider semantic plausibility before filtering/scoring.
- SESSION-FIDELITY-008 premarket provider-scope correction and proof tools.
- AFTER-CLOSE-001 GET-only contract/serialization diagnostic.
- AFTER-CLOSE-002 offline preserved-regular-session replay diagnostic.
- Phase 13R specialist-intelligence research roadmap.

## Safety Boundaries

- SETUP-002 is not installed, scheduled, or activated.
- After-close/replay tools do not submit, cancel, or replace orders.
- Schwab fidelity tooling is read-only and bounded to SPY/QQQ/NVDA.
- DATA-008 does not substitute or average providers and does not change score
  weights.
- PAPER-005 remains exact-host Alpaca Paper only; it adds no live endpoint.
- No credential, account identity, raw market evidence, production candle
  store, WPF file, database schema, or live-order capability changed.

## Verification

- Python compileall: `PASS`.
- High-risk combined suite: `181 PASS`.
- Corrected adjacent automation/broker/allocation suite: `222 PASS`.
- Full Python discovery: `2,004 PASS` in 268.222 seconds.
- Worktree-only virtual-environment junction was required for the installer's
  default-path test; it is ignored and not part of Git.
- No .NET/WPF file changed, so .NET testing was not required.

## Deployment Sequence

1. Complete static protected-path, secret, capability, and whitespace checks.
2. Commit and back up this feature branch.
3. Fast-forward canonical `master` and push non-force.
4. Install the exact final canonical identity and repin the remaining 20
   opening/Paper jobs once.
5. Verify service health, exact manifest identity, future pending jobs, zero
   enabled Shadow jobs, and transmission unavailable.
6. Prove and activate SETUP-002 separately before prospective collection.
