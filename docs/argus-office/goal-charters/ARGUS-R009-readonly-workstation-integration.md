# ARGUS-R009 - Read-Only Workstation Integration

## Goal Statement

Connect the WPF workstation to persisted Python candidates, evidence, health, source lineage, and Replay context through the independently hosted local Python engine, without exposing planning, simulation, broker, Paper, or Live behavior.

## User Pain / Operator Outcome

The workstation must stop presenting deterministic mock candidate context as though it were current evidence. Steven can inspect the latest persisted Python snapshot, see unavailable or stale source conditions honestly, and know that planning and simulation remain a later phase.

## In Scope

- Add a versioned read-only workspace snapshot command to the loopback-only Python Engine Host.
- Map existing persisted trade-planning reports, active-monitor status, and alert store data without recalculating score or readiness.
- Surface read-only candidates, activity, health, source lineage, and non-synthesized Replay context in WPF.
- Disable TradePlan, chart, risk, and simulation behavior while the WPF shell is populated by the Phase 9 read-only boundary.
- Add Python, C# mapper, presentation, and C#-to-Python host tests.

## Out Of Scope

- Any change to scoring, readiness, capture selection, Replay identity rules, alert semantics, providers, databases, trade planning, Risk Governor, FakeBroker simulation, Paper, Live, credentials, or order routing.
- A broker adapter, provider fetch, chart source, or screen redesign.

## Protected Areas

Core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, and runtime behavior remain protected. This task adds a read-only presentation boundary only.

## Acceptance Criteria

- The host exposes a versioned read-only snapshot capability over existing loopback transport.
- The snapshot reads persisted reports and status files only; it never writes files, fetches providers, or recalculates score/readiness.
- Missing or malformed source data is shown as unavailable without mock candidate fallback.
- WPF uses the real snapshot for candidates, evidence activity, health, source lineage, and Replay context.
- WPF states that planning, charts, risk, and simulation are deferred and does not call its mock trade-plan/simulation path in read-only mode.
- No broker, Paper, or Live capability is added.

## Evidence Required

- Python mapper tests prove raw score/readiness preservation, missing-data disclosure, and source-file non-mutation.
- Host tests prove the read-only command returns a payload without starting collection or exposing execution capability.
- C# mapper and presentation tests prove source labels, nullable missing numeric values, disabled mock fallback, and no primary action.
- C#-to-Python process proof reads an actual host payload through `PythonEngineHostConnection`.

## Evidence Depth / Hard Chew Requirements

- Run Python compileall and focused Python tests.
- Run a Release .NET build and focused presentation/integration tests.
- Run bounded broader Python and .NET test discovery with timeout handling.
- Review the final diff for protected paths, mock fallback, execution words/capabilities, and accidental generated data.
- Perform a second self-review of source, tests, and WPF-facing labels; fix any narrow defects and rerun verification.
- UI proof: no desktop-control session is available in this task context, so view-model and XAML bindings must be covered by automated tests and the limitation reported honestly.
- Commit only after acceptance criteria pass and update the Roadmap with branch, test, and merge evidence.

## Smallest Safe Implementation Slice

One read-only snapshot command that maps the latest persisted report/status data, plus a WPF adapter that disables mock planning/simulation whenever that command is active.

## Open CEO Decisions

- None for this implementation slice. Phase 10 remains the decision point for TradePlan, Risk Governor, chart source, and FakeBroker simulation integration.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove the requested outcome.
- [x] Evidence required is strong enough to verify completion.
