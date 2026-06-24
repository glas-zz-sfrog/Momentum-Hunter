# Pre-1B Control Document Status

Date: 2026-06-23

Source control document: `C:\Users\steve\Downloads\Momentum_Hunter_UI_Test_Log_Pre_1B.xlsx`

Purpose: close the remaining Pre-1B control-document findings before continuing the larger Operator Dashboard Redesign. This status document records what was fixed, what was verified, and what remains intentionally deferred.

## Status Summary

| ID | Area | Priority | Current status | Evidence |
| --- | --- | --- | --- | --- |
| MH-BUG-004 | Research crash | P0 | Fixed for Pre-1B | Research Lab now opens lightweight overview panels first; heavy panels load on demand; panel failures are caught and shown as recoverable UI messages. Targeted smoke: `RESEARCH_ACTIONS_SMOKE_OK research=1.07s readiness=1.06s`. |
| MH-QA-010 | Research smoke gap | P1 | Fixed for Pre-1B | Both Research actions were smoke-tested with bounded offscreen Qt probes: Open Research Lab and Open Readiness Gate. No full Qt unittest module was used. |
| MH-UI-001 | Scanner semantics | P1 | Fixed for Pre-1B | UI now shows `Basic Momentum` and `Heavy Volume Momentum`; scanner tooltip/criteria text explains Heavy Volume emphasizes higher absolute liquidity and larger market cap while using a lower relative-volume threshold. |
| MH-UI-002 | Watchlist plan meaning | P1 | Fixed for Pre-1B | Watchlist Center now labels the column `Trade Plan`, shows progress such as `Incomplete 0/4`, and exposes missing-field text separately. |
| MH-UI-003 | Watchlist plan action | P1 | Fixed for Pre-1B | Watchlist Center rows now include an `Edit Plan` / `View Plan` action that jumps to the candidate entry-plan editor. |
| MH-UI-005 | Evidence usability | P1 | Fixed for Pre-1B | Evidence Console now uses progressive disclosure: `Monitor + Health`, `Execution Ready`, `Alerts + Outcomes`, and `Performance` tabs, with a top next-action guidance strip. Full visual/layout redesign remains Phase 2 / 1B layout work. |
| MH-OPP-006 | Timeline density | P1 | Fixed for Pre-1B | Candidate Timeline now has `Signal`, `Outcome`, and `Audit` presets plus a selected-row detail panel separating capture-time signal facts, later annotations, and warnings. |
| MH-DATA-008 | Timeline Rel Vol 0.0 | P1 | Fixed for Pre-1B | Legacy-zero and missing relative volume are displayed as `N/A` with system warnings instead of trusted `0.0`; analytics can distinguish unavailable values. |
| MH-DATA-009 | Repeated timeline captures | P1 | Fixed for Pre-1B | Timeline rows preserve timestamped captures but warn on repeated signal fingerprints so analytics can avoid overweighting exact repeats. |
| MH-RES-007 | Top-score fixed-hold event study | P1 | Deferred to 1B+ | Added to `docs/FUTURE_IDEAS.md`. It remains gated until relative-volume validity and duplicate-signal handling are trustworthy. |
| MH-DEFER-011 | Health retest | P3 | Deferred | Workbook explicitly marked Health as deferred. No Pre-1B code change required. |
| MH-POS-012 | Dashboard guardrail | Guardrail | Preserved | Existing dashboard hierarchy, session context, and stale/fresh warning behavior were not intentionally removed. |
| MH-POS-013 | Timeline guardrail | Guardrail | Preserved | Timeline audit depth remains available through the `Audit` preset while compact views reduce default density. |

## Verification Commands Run

All commands were run with the UI/Qt testing safety rule: no broad Qt unittest modules, bytecode disabled for Python validation commands, isolated probes, bounded command timeouts, and process checks after risky commands.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_provider_errors
```

Result:

```text
Ran 5 tests in 0.082s
OK
```

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_replay tests.test_outcome_maturity
```

Result:

```text
Ran 15 tests in 0.646s
OK
```

Targeted UI probes:

```text
RESEARCH_ACTIONS_SMOKE_OK research=1.07s readiness=1.06s
PRE1B_CONTROL_UI_PROBE_OK
RESEARCH_LAZY_SMOKE_OK summary=0.01s dialog=0.07s status=Research Lab initial panels loaded in 0.02 seconds.
```

Process checks after risky commands:

```text
No leftover python.exe or pythonw.exe processes were present.
```

## Remaining Work After Pre-1B

These are not blockers for the Pre-1B control document, but they should remain on the roadmap:

- Full Evidence Console redesign beyond the current tab grouping and next-action strip.
- Full Operator Dashboard layout Phase 2.
- Top-score fixed-hold event study after enough clean observations exist.
- Health page retest after future Health work lands.
- A dedicated Qt test-runner helper that enforces timeouts and kills only the spawned test process on hang.
