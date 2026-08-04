# ARGUS-DATA-001B Goal Charter - Evidence Authority Enforcement

## Goal

Prospectively prevent unresolved catalyst evidence and research-only prices from
influencing execution eligibility while preserving every historical opening
artifact exactly as captured.

## Operator Outcome

Steven can trust that a candidate cannot become Shadow-eligible merely because
questionable evidence remains visible in a research report. Unsupported
catalysts contribute no score or scenario bonus, and current research-only
prices keep the plan explicitly execution-ineligible.

## Scope

- Introduce a versioned, hash-addressed composite configuration.
- Use only supported catalyst confidence in the composite score.
- Remove unresolved catalyst clusters and text from scenario bonuses and
  outperformance claims.
- Add explicit price and catalyst authority blockers to prospective TradePlans.
- Require the automatic Shadow selector to validate report-level configuration
  and candidate-level evidence authority before eligibility.
- Add focused negative tests for unresolved catalyst, research-only price,
  legacy profile, tampered configuration, and contradictory contribution data.

## Non-Goals

- Do not rewrite Monday's report, raw capture, score breakdown, or TradePlan.
- Do not integrate DATA-001 or DATA-001B before Tuesday's pinned capture.
- Do not change RVOL, entry/stop/target formulas, position sizing, Risk Governor,
  FakeBroker lifecycle, account binding, broker behavior, or UI.
- Do not create an execution-eligible provider path in this task.
- Do not arm Shadow or enable order transmission.

## Acceptance Criteria

- [x] `UNRESOLVED` / `BLOCKED` catalyst evidence contributes zero catalyst points.
- [x] Blocked catalyst clusters cannot create ranking bonuses or SMH claims.
- [x] Research-only price evidence forces an explicit plan blocker.
- [x] Selector evaluation rejects non-authority-enforced and contradictory reports.
- [x] Negative selector cases create no Shadow trade.
- [x] Monday's stored report hash and contents remain unchanged.
- [x] Compileall, focused, adjacent, full discovery, diff, capability, protected-path,
  and secret checks pass before commit.
- [x] Canonical `master`, installed service, and Tuesday manifest remain unchanged.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused authority tests: 70/70 pass.
- Adjacent Shadow, planning, host, autonomy, and workstation tests: 191/191 pass.
- Interference-isolated candidate-story suite: 8/8 pass.
- Full Python discovery: 1,066/1,066 pass in 190.229 seconds.
- Monday prospective comparison: MSFT 83/rank 1 becomes 78/rank 2; GOOGL
  81/rank 2 becomes 80/rank 1; CMCSA 80 remains rank 3 at 76; AMZN 79 remains
  rank 4 at 75. All four catalyst contributions become zero.
- Original Monday report SHA-256 remains
  `7E905BBA2392BD91803978DA73128C75399AEF37442C583870C13523CD0D6E99`.

## Status

`IMPLEMENTED_PENDING_INTEGRATION_AFTER_2026-08-04_CAPTURE` on
`codex/ARGUS-DATA-001B-evidence-authority-enforcement`. Tuesday remains pinned
to clean canonical `2aa4ef3`; no runtime installation or repin is authorized
before its evidence is terminal and preserved.

## Goal Steward Review

The implementation matches the CEO-advisor rule: unresolved catalyst evidence
may remain visible for research, but it may not add authority or enable
selection. The task closes the trust gap left intentionally open by DATA-001
without changing unrelated strategy semantics.
