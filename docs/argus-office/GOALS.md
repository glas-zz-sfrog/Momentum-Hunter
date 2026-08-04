# Argus Goals

This file records durable product and operating goals that should survive individual task branches.

## Market Awareness: Operate Continuously, Decide On Material Events

Status: `ACTIVE`; architecture and task contracts implemented pending merge

Goal:

- Make Momentum Hunter continuously aware of watched candidates, market and
  sector regime, macro events, catalyst changes, and setup evolution throughout
  the eligible session rather than treating the 08:35 Central opening capture
  as the whole trading day.

Operator Pain:

- A momentum move can form, fail, pull back, reclaim, or become exhausted in
  minutes. A morning snapshot alone cannot tell Steven what the market is doing
  now, and independent provider connections would create inconsistent or stale
  truth across charts, monitoring, and position marking.

Acceptance Direction:

- Retain 08:35 as an immutable bootstrap and unattended reliability proof.
- Use one Python-owned Schwab Streamer session and central subscription manager.
- Separate periodic broad discovery from bounded continuous monitoring.
- Reevaluate on material candle, catalyst, regime, event, stale, and lifecycle
  transitions rather than every quote.
- Persist legal candidate states, evidence fingerprints, and duplicate/noise
  controls.
- Keep breakout, pullback, and reclaim as distinct setup identities with
  immutable versioned TradePlans and a fresh Risk Governor decision.
- Keep sequential-breakout detection research-only until prospective evidence
  supports any stronger authority.
- Begin a new official Shadow sample only after continuous semantics are frozen;
  never rewrite v1, v2, or v3.
- Keep WPF and Codex downstream of versioned Python evidence and keep FakeBroker
  as the only automated execution boundary.

## Shadow: Observe An Active FakeBroker Position Honestly

Status: `ACTIVE`; implementation, automated proof, WPF visual acceptance,
canonical integration, backup, proof repair, v3 activation, and operational
closeout pass. The scheduled live twelfth-proof ceremony remains.

Goal:

- Show a prospective official Shadow working order or active position near real
  time without adding broker authority or fabricating executable performance.

Success:

- Python marks long positions from bid and short positions from ask.
- A separate five-second active loop runs only for an official working
  FakeBroker order or position; the five-minute candidate cycle is unchanged.
- Quotes older than the frozen ten-second limit preserve the last reliable mark
  but suppress live P&L, exits, and green/red state.
- WPF consumes a cached versioned snapshot, refreshes once per second, and does
  not calculate official results or call a provider.
- Open states use WORKING/AHEAD/BEHIND/FLAT/STALE/HALTED/EXIT_PENDING; only
  completed records use WINNER/LOSER/FLAT_EXIT.
- v1 and activated-empty v2 remain immutable. Prospective v3 is activated-empty
  at `0 / 30` after visual acceptance, integration, and backup; collection may
  begin only after corrected final-head proof and arming pass.
- Aggregate claims remain withheld below the sample gate, and FakeBroker
  remains the only automated execution boundary.

## Daily Workflow: Make The Next Light Click

Status: Active

Goal: Momentum Hunter's Daily Workflow should make the operator's next required action obvious, including the dependency that must be satisfied to make the next light click.

Operator Pain: Steven should not have to infer sequence, blockers, readiness meaning, stale-data risk, or watchlist prerequisites from scattered buttons and audit tables.

Current Evidence:
- ARGUS-0003 produced the guided Daily Workflow design report.
- ARGUS-0004 added the first guided modal stepper bridge.
- ARGUS-0006 identified follow-up quality issues around stale data, no-candidates, no-watchlist, incomplete plans, readiness diagnostic states, and button/state mismatch.

Acceptance Direction:
- Trust blockers dominate normal workflow actions.
- Capture missing, stale data, no candidates, unreviewed candidates, no watchlist, incomplete plans, and readiness gates use distinct language.
- The UI shows one next required action and explains why it is next.
- Existing scoring, readiness, replay, alert, storage, and runtime semantics stay protected unless the current task or Roadmap defines an exact bounded change with Hard Chew proof; semantic expansion interrupts Steven.

## Governance: Goal Charter Before Builder

Status: Active

Goal: Future Builder tasks should start from an explicit Goal Charter so implementation, tests, and acceptance evidence all point at the same desired outcome.

Acceptance Direction:
- Task prompts or office docs identify goal, operator pain, scope, non-goals, protected areas, acceptance criteria, and evidence required.
- Goal Steward verifies the charter before Builder implementation begins.
- Completion reports map verification back to the charter instead of redefining success around what was easiest to implement.

## Automation And Simulation: Keep Complexity Behind Progressive Disclosure

Status: Active

Goal: Momentum Hunter should expose automation, simulation, evidence, risk, and future broker supervision through the accepted WPF workstation without forcing the operator to manage internal machinery.

Operator Pain: Steven needs a quiet, truthful workstation that reveals detail when needed without turning every action into a warning label or presenting candidates as approved trades.

Acceptance Direction:
- The operator experience uses neutral product terms: Automation, Simulation, Machine Room, Risk Governor, Execution Ledger, and Trade Plan.
- The WPF workstation is the canonical operator shell; Python remains the canonical trading and evidence engine.
- Primary workflows stay concise. TradePlan, Risk Governor, execution evidence, and diagnostics appear through progressive disclosure rather than a permanently dense cockpit.
- Global mode treatment communicates Simulation, supervised Live, or locked state without repeating safety labels on ordinary controls.
- TradePlan, Risk Governor, Broker Adapter, and Execution Ledger boundaries exist before any broker work.
- FakeBroker remains the only automated execution boundary until a later gate explicitly authorizes a transmitting adapter.
- Live execution remains locked until Steven explicitly approves the applicable supervised-canary or unattended-live Goal Charter.

## Evidence: Prove Edge Before Authority

Status: Active

Goal: Momentum Hunter must demonstrate prospective, reproducible, execution-adjusted evidence before strategy-driven real-money use.

Operator Pain: A technically reliable system can still create a flattering sample through stale inputs, correlated trades, optimistic fills, selective denominators, or market beta.

Acceptance Direction:
- Official Shadow selection is automatic, deterministic, versioned, and independent of operator discretion.
- The frozen sample constitution defines ordering, eligibility, freshness, deduplication, concurrency, cooldown, fill assumptions, session rules, data sources, benchmarks, and invalidation rules.
- Every expected decision cycle is accounted for, including skipped, blocked, unfilled, unavailable, and failed cycles.
- Results disclose market-session, regime, sector, catalyst, symbol, and time-of-day concentration.
- Counterfactual observations compare the selected candidate with other eligible candidates, a deterministic random eligible candidate, and relevant benchmarks without creating extra portfolio trades.
- The first 30 completed trades release descriptive metrics and prove pipeline/evidence integrity only. At least 10 distinct sessions are required before broader strategy review, and durable edge claims still require a larger, diverse prospective sample.
- Data-source or methodological changes create a new sample version; prior evidence is never silently recomputed.

## Execution: Constrain Every New Authority

Status: Active

Goal: Every progression from FakeBroker to read-only broker access, broker plumbing, supervised strategy execution, and unattended execution must reduce ambiguity rather than merely add capability.

Operator Pain: A low-dollar account limits financial loss but does not prevent wrong-account routing, ambiguous retries, stale state, credential misuse, or a malformed automation path.

Acceptance Direction:
- Read-only Schwab work remains bound to the sole approved `2573` `CASH` account and fails closed on any identity, account-count, position, permission, or credential anomaly.
- Broker plumbing is proven with a boring, liquid, preapproved instrument before any Momentum Hunter strategy can drive a real order.
- Pre-canary, canary-active, and post-canary position expectations are explicit and reconciled to the immutable ledger.
- Settled cash, order identity, submission ambiguity, partial fills, cancel races, restart reconciliation, and an out-of-process kill path are proven before strategy-driven execution.
- No transmitting code is enabled under the previously surfaced Schwab Client Secret until vendor remediation is documented.
- A supervised live canary and unattended live execution are separate gates; neither advances automatically.

## Architecture: Modernize Without A Premature Rewrite

Status: Active

Goal: Momentum Hunter should become easier to modernize and eventually frontend-replaceable without rewriting proven Python engine behavior.

Operator Pain: Steven sees a dated UI and a large `app.py`, but a full rewrite would risk scoring, readiness, replay, storage, and broker safety before the frontend/backend boundary is ready.

Current Evidence:
- ARGUS-R000 found `momentum_hunter/app.py` is 7,188 lines and mixes shell navigation, UI construction, workflow mapping, scanner orchestration, report rendering, formatting, and styling.
- Backend modules already exist for daily workflow, scoring, storage, replay, SQLite, trade planning, evidence, and UI view-state decisions.

Acceptance Direction:
- No full rewrite until the Python engine boundary is explicit.
- The Windows-first C#/.NET WPF workstation-shell feasibility path comes before more Qt modernization.
- Versioned Python contracts prove the engine boundary before product workflows move into the WPF shell.
- Existing Qt screens migrate or retire only in small, test-protected slices after the boundary is validated.
- Protected trading, replay, storage, scoring, readiness, and broker/order behavior remain untouched unless Steven approves a separate Goal Charter.
