# Goal Charter: ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001B

## User-Visible Goal

The research-only Continuous runtime must compose natural TradePlan/no-plan
evidence from a fresh, chronology-valid decision packet and commit lifecycle,
setup, breakout, and Producer state as one accepted composition outcome.

## Operator Pain

The first provider-backed Producer-001A canary discovered and prepared real
symbols but emitted zero completed-bar events and zero compositions. Its failed
evidence also showed that readiness could freeze its cutoff before provider
acquisition completed and that natural setup preview work could mutate
authoritative ledgers before Producer evaluation succeeded.

## Scope

- Freeze one decision cutoff only after bounded provider acquisition completes.
- Bind every decision-authoritative input to an explicit `knownAt` not later
  than that cutoff.
- Stage natural lifecycle, setup, sequential-breakout, and Producer records away
  from authoritative state until the complete composition chain validates.
- Roll back an interrupted or failed multi-file publication deterministically.
- Keep pre-discovery bars available as historical context without recording
  them as new prospective material events.
- Preserve exact composition failure diagnostics and evidence chronology.
- Correct forensic accounting to distinguish attempts, successful backfills,
  runtime completed-bar events, and composition results.
- Prove restart after failed composition has no phantom state and one later
  successful composition commits exactly once.
- Repeat the real-provider research-only canary under a new immutable evidence
  identity, package a sanitized self-contained ZIP, and stop for second-eye
  adjudication.

## Non-Goals

- No change to discovery policy, setup vocabulary, scoring, opening capture,
  Paper, Shadow, account, position, broker, order, WPF, or live execution.
- No acceptance, repair, deletion, replacement, or reclassification of the
  failed Producer-001A canary or its second-eye ZIP.
- No arbitrary wall-clock slack and no retrospective trade creation.
- No merge or production deployment before the new canary and second-eye gate.

## Protected Areas

- Continuous readiness, event dispatch, composition, and checkpoint semantics.
- Candidate lifecycle, sequential setup, predecessor, and TradePlan identity.
- Canonical candle chronology and prospective/historical classification.
- Forensic evidence accounting and immutable canary packaging.

## Acceptance Criteria

1. A ready result exposes the final decision cutoff and every input `knownAt`;
   all values are no later than the cutoff.
2. Provider evidence received after the original runtime tick remains eligible
   under the final post-acquisition cutoff without adding guessed slack.
3. Any evaluation failure leaves authoritative lifecycle, breakout, Producer,
   setup, and plan state byte-identical.
4. An interrupted staged publication is rolled back before restart state is
   trusted.
5. Bars preceding the prospective floor can inform bounded history but cannot
   appear as new `PROSPECTIVE` events.
6. Failure evidence preserves exception class, diagnostic code, message,
   symbol, request cutoff, and each input `knownAt`.
7. Runtime/checkpoint event counts and backfill-ledger success counts reconcile
   independently from attempt counts.
8. Restart after a failed composition recovers no phantom state; a later valid
   composition commits once and replay remains idempotent.
9. Focused, adjacent, full Python, compile, protected-path, secret, and
   canonical/runtime nonmutation verification passes.
10. A new provider-backed canary is preserved under a new identity, its
    sanitized self-contained ZIP verifies from extraction, and work stops for
    independent second-eye adjudication.

## Required Evidence

- Mutation/failure-injection tests for cutoff chronology, staged composition,
  rollback, prospective-floor classification, restart, and exact failure data.
- Focused Continuous producer/runtime/natural-setup and forensic-accounting
  suites plus broader and full discovery results.
- Canonical, installed-runtime, service, scheduler, Paper/Shadow/order, and old
  failed-canary nonmutation hashes before and after work.
- New immutable canary root, manifest, sanitized ZIP hash, extracted focused
  rerun, and explicit second-eye stop classification.

## Completion Rule

Branch implementation may be classified `IMPLEMENTED_PENDING_MERGE` only after
Hard Chew passes. Natural-path acceptance remains pending until the new
provider-backed canary passes and the separately preserved packet survives
second-eye adjudication. The prior failed canary and ZIP remain immutable.
