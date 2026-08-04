# ARGUS-ROADMAP-002 - Continuous Intraday Market Awareness

## Classification

`CONTINUOUS_INTRADAY_ROADMAP_READY`

Branch status: `IMPLEMENTED_PENDING_MERGE` on
`codex/ARGUS-ROADMAP-002-continuous-intraday-awareness`.

## Executive Outcome

Momentum Hunter's next program is no longer organized as if the 08:35 Central
capture were the entire trading day. The capture remains a proven unattended
bootstrap and immutable evidence checkpoint. Continuous bounded monitoring,
periodic discovery, event-driven reevaluation, market/sector regime, macro
events, catalysts, setup progression, immutable TradePlans, Risk Governor,
FakeBroker lifecycle, and active marking now have one architecture and one
dependency chain.

The immediate task is R031B, not DATA-002 and not production candle persistence.
R031B must observe actual Schwab Streamer behavior, compare it with price
history, and leave every unsupported assumption unverified. R031C then
reconciles the older candle branch onto current canonical history before R032
creates the sole provider session and canonical candle collector.

## Current Baseline

- Canonical `master` and `origin/master` were synchronized at task base
  `0bd8a18`.
- Tuesday's unattended opening capture is preserved and DATA-001/001B are
  integrated.
- DATA-001 `488cbca` and DATA-001B `fe8c929` are canonical.
- SHADOW-024 is canonical through `cd43852`.
- R031 initial contract `a39086c` is included and superseded as branch closeout
  identity by `b96f745`.
- Provisional R032A and R031 observer work is preserved through `35c59ee`,
  `3272476`, and `d6d7217` on a separate clean pushed branch.
- R031A is the existing 3-15 minute, dry-run-by-default observer with an
  explicit live switch and pinned `websocket-client==1.9.0`; no replacement
  observer is planned.
- Official Shadow v3 is activated-empty, unarmed, and `0 / 30`; order
  transmission is `UNAVAILABLE`.

## Architecture Delivered

- Current-versus-target gap analysis.
- Continuous runtime component diagram.
- Central Schwab Streamer ownership diagram.
- Subscription priorities and failure rules.
- Discovery-versus-monitoring boundary.
- Candidate lifecycle and transition principles.
- Opportunity/setup/plan/decision identity.
- Event-trigger matrix.
- Data-cadence matrix.
- Immutable plan-version contract.
- Market-regime contract.
- Macro-event contract.
- Intraday catalyst contract.
- Sequential-breakout research contract.
- Staleness and recovery principles.

## Central Streamer Decision

Exactly one canonical Python process owns the Schwab Streamer session and
subscription manager. It revalidates the sole approved account invariant during
the future authorized bootstrap, then exposes market events through persisted
evidence and versioned Engine Host snapshots. WPF, charts, candidate monitoring,
regime, active marking, and Codex never open independent Streamer sessions.

Subscription priority is safety first: active FakeBroker orders/positions,
market controls, selected/near-trigger candidates, watched candidates, then
display/research. Provider capacity remains unknown until actual evidence proves
it; no numeric limit was invented.

## Candidate And Plan Decisions

The lifecycle distinguishes discovery, watching, impulse, breakout formation,
confirmation, pullback, reclaim, eligibility, missed entry, exhaustion, failure,
invalidation, cooldown, and stale evidence. Transitions are event-driven and
persist previous/next state plus evidence identity.

TradePlans are immutable. Breakout, pullback, and reclaim are distinct setup
identities. A missed breakout cannot be edited into a reclaim, and every
material plan revision requires a new Risk Governor result.

## R031B Gate

The R031B contract requires SPY, IWM, and one deterministic Hunter candidate;
every same-minute update; provider/receipt clocks; OHLCV change history;
acknowledgements; disconnect/reconnect evidence where safely exercised; and
price-history comparison. It adjudicates each behavior as verified, disproven,
partially verified, or unverified.

It performs no production persistence, account/position/order request, Engine
Host decision, service change, WPF change, selector action, FakeBroker action,
or Shadow mutation.

## Prioritized Runtime Sequence

1. R031B live candle proof and adjudication.
2. R031C current-baseline candle branch reconciliation.
3. R032 central Streamer manager and candle collector.
4. R033 Engine Host and WPF live charts.
5. MONITOR-001 candidate lifecycle and event coordinator.
6. DATA-002 time-normalized RVOL.
7. REGIME-001 rolling market/sector regime.
8. EVENT-001 macro-event policy.
9. CATALYST-002 intraday catalyst refresh.
10. BREAKOUT-001 sequential research capture.
11. BREAKOUT-002 prospective event study.
12. PLAN-002 immutable intraday plan versions.
13. SHADOW-025 new prospective continuous-intraday sample.

UI-STREAMLINE-001 may proceed in parallel only against canonical or synthetic
view models and still requires Steven visual acceptance.

## Files Changed

- `docs/argus-office/ROADMAP.md`
- `docs/argus-office/GOALS.md`
- `docs/argus-office/DECISIONS.md`
- `docs/argus-office/RISK_REGISTER.md`
- `docs/argus-office/BRANCH_LEDGER.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`
- `docs/argus-office/goal-charters/ARGUS-ROADMAP-002-continuous-intraday-awareness.md`
- `docs/argus-office/architecture/CONTINUOUS_INTRADAY_MARKET_AWARENESS.md`
- `docs/argus-office/task-contracts/ARGUS-R031B-live-candle-proof-adjudication.md`
- `docs/argus-office/task-contracts/CONTINUOUS_INTRADAY_IMPLEMENTATION_SEQUENCE.md`
- `docs/argus-office/reports/releases/ARGUS-ROADMAP-002-continuous-intraday-awareness.md`

## Protected-Area Result

No application code, tests, package/dependency files, service, manifest,
scheduler, Engine Host, provider configuration, account binding, database,
generated evidence, raw capture, candle store, WPF, scoring, readiness,
TradePlan runtime, Risk Governor runtime, FakeBroker, Shadow state, or
broker/order behavior changed.

No real order path was added. No account or provider call occurred. Codex remains
outside every real-time decision path.

## Verification

- Git and branch ancestry reconciled from local evidence: pass.
- Markdown path/reference checks: pass.
- Contradiction and stale-status scan: pass after one narrow stale-history fix.
- `git diff --check`: pass.
- Protected-path review: pass; every changed path is under
  `docs/argus-office/`.
- Credential-shaped secret scan: pass with zero hits.
- Canonical worktree/head nonmutation: pass at `0bd8a18`, synchronized 0/0 with
  `origin/master`.
- Installed manifest nonmutation: pass; SHA-256 remains
  `938C996D36435131F37BAE61F790AFA81E00B8993906FED72009C4595AB2A1D5`.
- Application tests: not applicable because only governance documentation
  changed.

## Remaining Risks

- Schwab entitlement and actual Streamer behavior remain unproven until R031B.
- Subscription capacity and reconnect semantics are unknown.
- Numerical discovery, hysteresis, cooldown, event, and regime policies remain
  intentionally unfrozen.
- Continuous semantics require a new Shadow sample and cannot reuse v3.
- Canonical integration will require deliberate exact-head service-manifest
  repin while ordinary opening jobs remain pinned.

## CEO Answers

1. **Is Momentum Hunter still designed as a morning-only system?** No. The
   08:35 capture is the first immutable bootstrap event, not the final market
   opinion or sole decision window.
2. **What continuously observes candidates?** The future Python candidate
   monitor consumes events from the one central subscription manager and other
   versioned evidence sources, then persists legal lifecycle transitions.
3. **What discovers candidates later in the day?** A separate bounded broad
   discovery coordinator using approved screener, movement, volume, gap,
   catalyst, sector, and halt/resumption sources at an evidence-tested cadence.
4. **What triggers intraday reevaluation?** Material candidate-state, completed
   candle, breakout/failure, volume, catalyst, regime, macro-window, liquidity,
   stale/recovery, or lifecycle changes. An ordinary quote alone does not.
5. **What prevents noisy overtrading?** Stable opportunity/setup IDs,
   hysteresis, cooldowns, evidence-delta thresholds, event deduplication,
   non-overlapping cycles, and duplicate checks before plans and commands.
6. **How are market regime changes handled?** Versioned rolling states may
   trigger bounded reevaluation, caution/block new positions, or invalidate a
   prospective setup; they never rewrite history or silently add score.
7. **How are Fed and macro events handled?** A sourced calendar creates explicit
   pre-event, event-risk, and post-event observation windows. It does not predict
   releases or initiate trades.
8. **How are missed breakouts separated from reclaim plans?** They use distinct
   setup IDs and immutable plan versions. The missed/failed breakout remains in
   evidence; a reclaim requires new evidence and a new Risk Governor result.
9. **Why is there only one Schwab Streamer session?** Schwab permits one session
   per user, and a single owner prevents capacity competition and contradictory
   market truth.
10. **How are subscription priorities managed?** Active FakeBroker safety
    symbols are non-evictable, followed by market controls, selected/near-trigger
    candidates, watched candidates, and display/research references.
11. **Which Streamer behaviors remain unverified?** Formal finality, normal/worst
    close latency, consolidated-volume authority, capacity, halt/stale behavior,
    extended-hours consistency, split adjustment, corrections, and reconnect
    semantics until actually observed.
12. **When does continuous behavior require a new Shadow sample?** Before any
    continuous cadence, setup, volume, regime, replanning, or event-trigger
    semantics produce official evidence. SHADOW-025 owns the new prospective
    sample; v1/v2/v3 stay unchanged.

## Recommendation

Commit and back up this feature branch without changing canonical runtime. Run
R031B during the next suitable market window, then execute R031C before any
production candle collector or additional provider connection is built.
