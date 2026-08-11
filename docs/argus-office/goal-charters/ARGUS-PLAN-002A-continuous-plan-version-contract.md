# ARGUS-PLAN-002A Goal Charter

## Goal

Build the authorized synthetic precursor to PLAN-002: a deterministic,
immutable contract that binds an existing DATA-004 IntradayPlan to the exact
continuous candidate and context evidence used to create it, without wiring or
activating production plan generation.

## Operator Value

Ensure Steven can later see why a continuous setup produced a particular plan,
which evidence version was used, what superseded it, and whether risk and
allocation were rerun, without allowing a missed breakout, research signal, or
manual override to rewrite history.

## Scope

- Bind opportunity, setup, plan, regime, event, catalyst, RVOL, source-clock,
  policy, predecessor, risk-reference, and allocation-reference identities.
- Keep plan versions and their explicit-path ledger append-only and tamper
  evident.
- Make exact repeats deterministic and idempotent.
- Require new plan/risk/allocation identities for material manual overrides.
- Add synthetic fixtures only; do not select a production persistence path.

## Exclusions

- No candidate discovery, score, readiness, ranking, or setup generation.
- No Risk Governor or allocation invocation.
- No provider, account, broker, order, credential, service, scheduler, Engine
  Host, Shadow, WPF, or production-store wiring.
- No merge or install before Tuesday's terminal opening/Paper evidence.
- No claim that PLAN-002 production authority or SHADOW-025 is complete.

## Acceptance

- Research-only setup evidence cannot become ready for risk review.
- Stale regime, blocking event context, nonauthoritative catalyst, blocked RVOL,
  and inconsistent identities fail closed.
- Material successors preserve predecessor identity and cannot branch history.
- Manual override requires a new plan, risk decision, and allocation decision.
- Decision validation re-derives every required plan, risk, allocation, and
  quantity blocker from persisted authority facts.
- Successor plans and manual-override decisions cannot move backward in time.
- Only the prospective-evidence authority profile may reach risk review.
- Live decision modes are rejected structurally.
- Compileall, 24 focused tests, 191 adjacent tests, and all 1,643 Python tests
  pass.
- Protected-path, secret, import/capability, whitespace, and canonical
  nonmutation reviews pass.
- Branch-local Roadmap says `IMPLEMENTED_PENDING_MERGE`.
