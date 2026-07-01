# ARGUS-QUALITY-001 - Simulation Foundation Quality Review

Date: 2026-07-01
Branch: `codex/ARGUS-QUALITY-001-simulation-foundation-review`
Review target: local `master` at `6893dba Reconcile Argus branch ledger and canonical paths`

## 1. Executive Verdict

Verdict: `READY_FOR_A016_WITH_CAUTIONS`, and `HARDEN_BEFORE_A017/A018`.

The Argus Machine simulation foundation is a real simulation foundation, not just labels. It has structured `TradePlan` view models, a Risk Governor, a ledger, a FakeBroker adapter, a simulation engine, an auditor, UI panels, and focused tests proving important behavior. It is solid enough to support A016 broker research because A016 is docs/research only and must not add broker code or credentials. It is not solid enough to build paper broker code on directly without hardening first. The main hardening issues are that `SimulationLabEngine` accepts any `BrokerAdapter` and calls `submit_order` without first enforcing FakeBroker-only metadata, the auditor is meaningful but not yet a hard chronological gate, and `autonomy_gateway.py` is already accumulating too much widget wiring, runtime state mutation, ledger recording, cockpit rendering, and audit display behavior.

## 2. Current Local Master State

- Current branch before audit branch creation: `master`.
- Audit branch: `codex/ARGUS-QUALITY-001-simulation-foundation-review`.
- Local `master` contains `664381d Add clean-room simulation proof`: yes.
- Local `master` contains `6893dba Reconcile Argus branch ledger and canonical paths`: yes.
- Local `master` status vs `origin/master`: ahead 76, behind 0.
- Worktree before report edits: clean.
- Push policy followed so far: `master` not pushed.

## 3. What Was Inspected

Product files inspected:

| File | Lines | Notes |
| --- | ---: | --- |
| `momentum_hunter/ui/autonomy_gateway.py` | 754 | Main Argus Machine UI wiring and simulation cockpit rendering. |
| `momentum_hunter/ui/trade_plan_ladder.py` | 44 | Extracted ladder widget. |
| `momentum_hunter/autonomy/view_models.py` | 324 | Top 5 candidate and ladder view models. |
| `momentum_hunter/autonomy/risk_governor.py` | 121 | Simulation gate result and risk gates. |
| `momentum_hunter/autonomy/broker.py` | 241 | Broker interface and FakeBroker implementation. |
| `momentum_hunter/autonomy/ledger.py` | 122 | In-memory execution ledger and machine log rendering. |
| `momentum_hunter/autonomy/simulation.py` | 118 | Simulation engine and order request builder. |
| `momentum_hunter/autonomy/auditor.py` | 94 | Execution ledger and simulation-chain auditor. |
| `momentum_hunter/trade_planning.py` | 1848 | Canonical TradePlan source model and report generation. |
| `momentum_hunter/app.py` | 7311 | Application integration point for the gateway. |

Test files inspected:

| File | Tests | Notes |
| --- | ---: | --- |
| `tests/test_trade_planning.py` | 13 | TradePlan and market-tape behavior. |
| `tests/test_argus_autonomy.py` | 19 | Autonomy model, FakeBroker, simulation, and auditor tests. |
| `tests/test_trade_plan_ladder.py` | 2 | Ladder widget render and clear behavior. |
| `tests/test_autonomy_gateway.py` | 9 | Gateway and Argus Machine UI behavior. |

Also inspected directly imported dependencies needed to understand behavior: `momentum_hunter/models.py`, `momentum_hunter/time_utils.py`, and `momentum_hunter/monitor_targets.py` import surfaces through code search and dependency mapping.

## 4. Architecture Quality Scorecard

| Area | Score | Evidence | Assessment |
| --- | --- | --- | --- |
| UI/autonomy separation | B- | `autonomy_gateway.py` imports autonomy primitives at lines 22-29, while `trade_plan_ladder.py` only imports view models at line 5. | The separation is real, but the gateway still owns too much orchestration and state mutation. |
| `autonomy_gateway.py` size risk | C+ | 754 lines; largest functions include `build_argus_order_console_panel` at lines 349-424, `render_argus_auditor_gate` at lines 663-721, and `build_argus_machine_console_page` at lines 126-183. | It is not mini-`app.py` yet, but it is moving that direction. |
| View model separation | B | `Top5CandidatePlan` and `LadderRow` are dataclasses at `view_models.py` lines 22-47; ladder rows are built without PySide at lines 249-268. | Good boundary. Needs stale-source and ranking hardening. |
| TradePlan source authority | A- | `view_models.py` imports `TradePlan` and `TradePlanRow` from `trade_planning.py` at lines 10-17; no duplicate execution model is used. | Canonical source path is clear. |
| Risk Governor responsibility | B | `evaluate_trade_plan` builds gates at `risk_governor.py` lines 42-78. | Clear for simulation, but `Needs review` still allows simulation because `allows_simulation` only blocks `Blocked` gates at lines 37-39. |
| Ledger responsibility | B- | `ExecutionLedger.record` writes structured events at `ledger.py` lines 64-99. | Good event shape; weak validation and no persistence boundary yet. |
| FakeBroker responsibility | B | `FakeBrokerAdapter.metadata` says `order_transmit_allowed=False` and `credential_status="not required"` at `broker.py` lines 117-125. | Honest fake adapter. Needs stronger guard before future adapters exist. |
| Simulation engine responsibility | C+ | `SimulationLabEngine.run_candidate` records risk, previews, then calls `self.adapter.submit_order` at `simulation.py` lines 24-100. | It orchestrates the whole flow but must enforce adapter safety before future paper/live code exists. |
| Auditor responsibility | B- | Auditor validates order-like events at `auditor.py` lines 29-66 and chain presence at lines 69-94. | Meaningful but not yet a strict chronological advancement gate. |
| A016 support | B | A016 is docs-only research. No broker code or credentials are needed. | Ready with cautions. Do not start A017 code from this without hardening. |

## 5. Code Quality Scorecard

| Module | Classification | Evidence | Why |
| --- | --- | --- | --- |
| `momentum_hunter/ui/autonomy_gateway.py` | `KEEP_WITH_HARDENING` | Directly mutates `window.argus_*` state in `ensure_argus_machine_runtime` lines 186-196, selection lines 507-551, and rendering lines 603-721. | Good UI foundation, but too much state/orchestration for future broker work. |
| `momentum_hunter/ui/trade_plan_ladder.py` | `KEEP` | Small 44-line widget; delegates row creation to `ladder_rows_for_candidate` at lines 33-44. | Clean extracted component with a narrow API. |
| `momentum_hunter/autonomy/view_models.py` | `KEEP_WITH_HARDENING` | Builds report plans at lines 70-148 and current candidate plans at lines 151-196; ranking key at lines 199-200. | Good DTO layer, but report parse failures silently return empty and current-candidate fallback uses scaffolded trade rows. |
| `momentum_hunter/autonomy/risk_governor.py` | `KEEP_WITH_HARDENING` | Required gates at lines 52-60; `allows_simulation` at lines 37-39. | Clear gate language. Needs explicit policy for whether `Needs review` should allow simulation. |
| `momentum_hunter/autonomy/broker.py` | `KEEP_WITH_HARDENING` | Broker interface lines 64-96; FakeBroker lines 99-241; metadata lines 117-125. | Strong fake broker boundary today; future real adapter work needs interface contracts and tests before reuse. |
| `momentum_hunter/autonomy/ledger.py` | `KEEP_WITH_HARDENING` | Event fields lines 10-26; record method lines 64-99. | Useful audit shape; should validate required fields and define persistence semantics before A018. |
| `momentum_hunter/autonomy/simulation.py` | `REFACTOR_BEFORE_DEPENDENCY` | Engine accepts any `BrokerAdapter` at lines 19-22 and calls `self.adapter.submit_order` at line 78. | Current use is FakeBroker-only, but this must be guarded before any paper adapter exists. |
| `momentum_hunter/autonomy/auditor.py` | `KEEP_WITH_HARDENING` | Required event fields lines 46-65; chain check lines 69-86; paper gate lines 89-94. | Good first gate. Needs chronology, preview requirement, and stricter action/event consistency. |
| `momentum_hunter/trade_planning.py` | `KEEP` | `TradePlan` and `TradePlanRow` dataclasses at lines 136-184; report rows sorted at lines 252 and ranked at lines 477-508. | Canonical planning model is broad but already test-protected. |
| `momentum_hunter/app.py` | `KEEP_WITH_HARDENING` | Gateway import at line 215; app stack integration at lines 367-372; open machine console at lines 409-413. | Integration is narrow, but the 7311-line class remains a modernization risk. |

## 6. Test Quality Scorecard

| Test file | Classification | What it proves | What it does not prove |
| --- | --- | --- | --- |
| `tests/test_trade_planning.py` | `KEEP` | 13 tests prove TradePlan generation, warning states, export, tape parsing, spread blocking, event-mode report behavior. | Does not prove autonomy-specific paper/live boundaries. |
| `tests/test_argus_autonomy.py` | `KEEP_WITH_HARDENING` | 19 tests prove Top 5 view models, missing stop/risk blocks, live mode block, manual override block, ledger serialization, FakeBroker lifecycle/rejection, simulation pass/reject, paper advancement gate, and auditor negative cases. | Does not prove SimulationLabEngine refuses non-Fake adapters before calling `submit_order`; does not prove chronology or preview-before-submit is required. |
| `tests/test_trade_plan_ladder.py` | `KEEP_WITH_HARDENING` | 2 tests prove the widget renders structured TradePlan rows and clears state. | Mostly label/state tests; does not test missing fields or visual fit. |
| `tests/test_autonomy_gateway.py` | `KEEP_WITH_HARDENING` | 9 tests prove gateway routing, safe shell language, Top 5 row creation, candidate click, disabled paper/live buttons, simulation button updates, auditor warn/pass states, and empty state. | Some assertions are label brittle; does not prove disabled buttons have no connected command path beyond `isEnabled=False`; no screenshot sanity proof in this audit. |

Negative-test counts by theme from test names:

| Theme | Count |
| --- | ---: |
| Missing/incomplete plan | 10 |
| Risk/live/paper lock | 5 |
| Ledger/audit | 11 |
| Fake broker lifecycle | 3 |
| UI empty/locked states | 7 |
| Manual override | 1 |

## 7. Safety Boundary Scorecard

| Boundary | Result | Evidence | Assessment |
| --- | --- | --- | --- |
| 1. No live trading path exists. | PASS | No autonomy `LiveBroker` implementation. UI creates disabled `Live Order Locked` button at `autonomy_gateway.py` lines 370-381. | Current simulation foundation has no live path. |
| 2. No paper broker path exists yet. | PASS | UI creates disabled `Paper Order Locked` button at line 370; no `PaperBroker` implementation in autonomy. | Paper is display-locked only. |
| 3. No credentials/API keys are used. | PASS | FakeBroker metadata says `credential_status="not required"` at `broker.py` line 123; narrow scan found no autonomy credential values. | Good for current foundation. |
| 4. No external broker/network calls exist. | PASS | Narrow autonomy/UI scan found no `requests`, `urllib`, `http`, or `socket` in implementation. | Broad repo has existing market-data HTTP, but not broker/autonomy execution. |
| 5. FakeBroker cannot be confused with a real broker. | PARTIAL | Labels say FakeBroker only at `autonomy_gateway.py` lines 350-357 and metadata line 119. Engine still accepts `BrokerAdapter` and calls `submit_order` at `simulation.py` lines 20 and 78. | Clear today, but needs an adapter guard before paper adapters exist. |
| 6. TradePlan/candidate objects cannot submit orders directly. | PASS | `Top5CandidatePlan` is a dataclass at `view_models.py` lines 28-47; order request is built only in `simulation.py` lines 103-118. | Good separation. |
| 7. Risk Governor is required before simulation. | PARTIAL | Engine records and checks `candidate.risk_result` at `simulation.py` lines 24-49. It does not recompute risk or reject synthetic stale `risk_result` objects. | Good for UI path, weaker as an engine contract. |
| 8. Ledger records enough evidence to audit machine actions. | PARTIAL | Ledger fields include mode, ticker, plan, risk, adapter, approval, action, result, actor/source at `ledger.py` lines 10-26. | Field shape is useful; validation is post-hoc and no persistence boundary exists. |
| 9. Execution Auditor detects missing/invalid evidence. | PARTIAL | Auditor checks required fields and mode/adapter/approval at `auditor.py` lines 44-66 and chain presence at lines 69-86. | It catches important errors but not chronology, preview-before-submit, or event_type/requested_action consistency. |
| 10. Paper/live controls locked visually and logically. | PASS | Buttons disabled and marked locked at `autonomy_gateway.py` lines 370-381; test asserts disabled state at `tests/test_autonomy_gateway.py` lines 107-119. | Current UI lock is strong. |
| 11. Top 5 candidates do not imply approved live trades. | PASS | Label says not approved trades at `autonomy_gateway.py` lines 228-230 and refresh label at lines 461-463; test asserts no approved-live language at `tests/test_autonomy_gateway.py` lines 78-87. | Good operator language. |
| 12. Demo/placeholder state is labeled clearly. | PARTIAL | Empty state is explicit at `autonomy_gateway.py` lines 480-485; current-candidate fallback creates scaffolded TradePlans from candidates at `view_models.py` lines 151-168. | No fake demo rows remain, but scaffolded candidate data should be labeled more explicitly before paper work. |

## 8. Module-By-Module Classification

See the Code Quality Scorecard above. The most important dependency warning is:

`momentum_hunter/autonomy/simulation.py` is `REFACTOR_BEFORE_DEPENDENCY`. It is acceptable as a first FakeBroker-only simulation engine. It should not become the base paper/live execution orchestrator until it refuses non-Fake adapters in simulation mode, validates adapter metadata before preview/submit, and separates risk evaluation, request creation, broker call, and ledger write phases.

## 9. Test-File-By-Test-File Classification

See the Test Quality Scorecard above. The most important test warning is:

`tests/test_argus_autonomy.py` has strong negative coverage for the auditor and risk gates, but it does not yet prove that the simulation engine cannot call a non-Fake adapter. That missing test matters because `SimulationLabEngine.__init__` accepts any `BrokerAdapter` at `simulation.py` lines 19-22.

## 10. Top 10 Quality Concerns

1. `SimulationLabEngine` accepts any `BrokerAdapter` and calls `submit_order` without pre-call FakeBroker enforcement (`simulation.py` lines 19-22 and 78).
2. Auditor validation is post-hoc. It can fail bad evidence after the engine already called an adapter (`auditor.py` lines 29-94).
3. `audit_simulation_chain` does not require preview before fake submit, only a final submit/block outcome (`auditor.py` lines 81-84).
4. `audit_simulation_chain` does not validate event chronology, so an order event before a risk event could still satisfy the action set.
5. `ExecutionLedger.record` accepts empty required fields and relies on later audit to find them (`ledger.py` lines 64-99).
6. `autonomy_gateway.py` directly mutates many `window.argus_*` attributes and mixes UI construction, orchestration, ledger writes, and audit display (`autonomy_gateway.py` lines 186-196, 507-551, 603-721).
7. Risk Governor `Needs review` gates still allow simulation because `allows_simulation` only checks blocked gates (`risk_governor.py` lines 37-39 and 61-68).
8. Report parsing in `build_candidate_plans_from_report` silently returns empty on IO/JSON failures (`view_models.py` lines 70-74), which could hide stale/broken report sources from the operator.
9. Current-candidate fallback builds TradePlans from `bars=[]`, `market_tape=None`, and `UNKNOWN_RVOL` (`view_models.py` lines 151-168); this is okay for simulation scaffolding but needs stronger labeling before paper work.
10. UI tests prove many labels and state changes but do not include screenshot proof or visual regression checks for the dense cockpit layout.

## 11. Top 10 Things That Are Solid

1. The gateway integration in `app.py` is narrow: import at line 215 and stack wiring at lines 367-372.
2. The Trade Plan Ladder is a real extracted widget with a small render API (`trade_plan_ladder.py` lines 8-44).
3. `Top5CandidatePlan` carries structured TradePlan and Risk Governor data rather than placeholder dictionaries (`view_models.py` lines 28-47).
4. Top 5 labels explicitly say candidates are not approved trades (`autonomy_gateway.py` lines 228-230 and 461-463).
5. Risk Governor checks stop, max risk, risk/reward, manual override, broker mode, and approval (`risk_governor.py` lines 52-60).
6. FakeBroker metadata explicitly blocks transmit and requires no credentials (`broker.py` lines 117-125).
7. FakeBroker supports preview, fill, partial fill, rejection, cancel, positions, and order status without network calls (`broker.py` lines 133-182).
8. Ledger events include mode, ticker, TradePlan ID, risk result ID, adapter, approval state, action, result, actor, and source (`ledger.py` lines 10-26).
9. Auditor catches missing required fields, wrong mode, wrong adapter, wrong approval state, duplicate order-like IDs, and missing chain evidence (`auditor.py` lines 29-86; tests in `tests/test_argus_autonomy.py` lines 229-320).
10. Focused tests passed: 43 tests across trade planning, autonomy, ladder, and gateway.

## 12. Missing Tests / Weak Tests

High-value missing tests:

- Simulation engine refuses any adapter whose metadata is not `FakeBrokerAdapter`, not `Simulation Lab`, or has `order_transmit_allowed=True`.
- Simulation engine refuses to call adapter methods if risk evidence is missing, stale, wrong mode, or synthetic.
- Auditor fails a chain where `fake_order_submitted` exists without `simulated_order_previewed`.
- Auditor fails a chain where the final order event timestamp precedes the risk gate event.
- Auditor checks event_type/requested_action consistency for order-like events.
- Ledger record validation rejects empty required fields for order-like events, or the engine never records them.
- UI test proves paper/live locked buttons have no connected order path, not only disabled text.
- View model tests cover fewer-than-five, no candidates, corrupt report JSON, stale report metadata, and report fallback messaging.
- Ladder tests cover missing stop/risk fields and manual override display.
- Screenshot sanity proof for the dense simulation cockpit layout.

## 13. Refactor-Before-Dependency Recommendations

Before A017 PaperBrokerAdapter skeleton or A018 paper pilot:

1. Add a `SimulationAdapterGuard` or equivalent pre-call check in `SimulationLabEngine` that allows only `FakeBrokerAdapter`, `Simulation Lab`, `order_transmit_allowed=False`, and `credential_status="not required"` while in simulation mode.
2. Split `SimulationLabEngine.run_candidate` into risk evidence validation, request creation, broker preview/submit, and ledger write helpers.
3. Make the auditor the source of truth for advancement gates, including chronology, preview-before-submit, event_type/requested_action consistency, and exact adapter metadata.
4. Add ledger validation for required order-like fields before append, or constrain engine writes so invalid order-like events cannot be recorded.
5. Extract `autonomy_gateway.py` cockpit state rendering into smaller presenter functions or a view-state object so paper work does not pile onto direct `window` mutation.

## 14. A016 Readiness Decision

Decision: `READY_FOR_A016_WITH_CAUTIONS`.

A016 may proceed because it is broker research/API feasibility only. It must not implement broker code, add credentials, create API keys, install dependencies, or wire paper/live order behavior. The current simulation foundation gives enough vocabulary for a broker research matrix: adapter metadata, mode separation, credential status, transmit lock, order lifecycle, ledger evidence, and auditor expectations.

Cautions:

- Research must treat the current `BrokerAdapter` as a conceptual interface, not a production execution contract.
- Research must identify how each broker supports paper mode, credential scoping, preview, cancel, status, rate limits, and audit data, but no credential setup should occur.
- A016 should explicitly feed hardening requirements for A017/A018 rather than assuming the current simulation engine is safe to reuse unchanged.

## 15. A017/A018 Preconditions

Before A017 PaperBrokerAdapter skeleton:

- Simulation engine has a FakeBroker-only guard test.
- Broker adapter interface has documented capability/credential/transmit semantics.
- Paper adapter skeleton is non-transmitting and returns explicit not-configured blocks.
- Tests prove paper adapter cannot submit unless a future approved paper mode is configured.

Before A018 first paper order pilot:

- Execution Auditor is a hard gate, not display-only.
- Ledger persistence/export path is specified.
- Risk Governor recomputation or freshness validation exists at action time.
- Manual overrides require a re-check and are tested end-to-end.
- Paper credentials are stored outside repo and never logged.
- UI labels distinguish simulation, paper preview, paper submitted, read-only live, and live-locked.
- Steven has approved the exact broker, account, order type, and failure handling.

## 16. What Steven Should Trust

- The current Argus Machine simulation foundation is not merely placeholder text.
- The UI keeps paper/live controls visibly disabled.
- FakeBroker is local and credential-free.
- Top 5 candidates are labeled as planning candidates, not approved trades.
- The tests prove a meaningful chunk of risk, ledger, fake broker, auditor, and UI behavior.
- A016 docs-only broker research can safely proceed from this vocabulary.

## 17. What Steven Should Not Trust Yet

- Do not trust the simulation engine as a safe abstraction for future paper/live adapters.
- Do not trust the auditor as a complete advancement gate yet.
- Do not trust the ledger as persistent, immutable, or validated enough for real broker audit trails.
- Do not trust current-candidate fallback data as paper-trading quality evidence.
- Do not trust label-based UI tests as enough proof for paper trading controls.

## 18. Recommended Next 5 Tasks

1. `ARGUS-QUALITY-002` - Add hard negative tests for simulation adapter guards, audit chronology, preview-before-submit, stale report source, and UI no-op/locked paths.
2. `ARGUS-A013B` - Harden SimulationLabEngine so simulation mode refuses any non-FakeBroker or transmit-capable adapter before any broker method call.
3. `ARGUS-A015B` - Harden Execution Auditor into a real paper-advancement gate with chronology, preview requirement, event consistency, and adapter metadata validation.
4. `ARGUS-A014B` - Extract Argus Machine cockpit state/rendering from `autonomy_gateway.py` into smaller presenters or view-state helpers.
5. `ARGUS-A016` - Create the broker research matrix as docs-only, with explicit no-code/no-credentials constraints and A017/A018 safety gates.

## Required Metrics

Top 10 largest functions/classes from inspected product files:

| Lines | File | Kind | Name | Location |
| ---: | --- | --- | --- | --- |
| 3977 | `momentum_hunter/app.py` | class | `MomentumHunterWindow` | 305-4281 |
| 464 | `momentum_hunter/app.py` | function | `_show_study_dialog` | 3818-4281 |
| 324 | `momentum_hunter/app.py` | function | `open_morning_review_workspace` | 2194-2517 |
| 210 | `momentum_hunter/app.py` | function | `_build_execution_ready_panel` | 777-986 |
| 198 | `momentum_hunter/app.py` | function | `_show_timeline_dialog` | 2661-2858 |
| 191 | `momentum_hunter/app.py` | function | `_refresh_execution_ready_panel` | 988-1178 |
| 182 | `momentum_hunter/app.py` | function | `build_historical_recurrence_panel` | 5897-6078 |
| 143 | `momentum_hunter/autonomy/broker.py` | class | `FakeBrokerAdapter` | 99-241 |
| 139 | `momentum_hunter/app.py` | function | `refresh_study_view` | 4111-4249 |
| 131 | `momentum_hunter/app.py` | function | `build_candidate_story_chart` | 5045-5175 |

Autonomy import relationships:

- `auditor.py` -> `ledger`, `risk_governor`
- `broker.py` -> `time_utils`
- `ledger.py` -> `time_utils`
- `risk_governor.py` -> `time_utils`, `trade_planning`
- `simulation.py` -> `broker`, `ledger`, `risk_governor`, `view_models`
- `view_models.py` -> `risk_governor`, `models`, `time_utils`, `trade_planning`
- `ui/autonomy_gateway.py` -> autonomy modules, `monitor_targets`, `ui/trade_plan_ladder`
- `ui/trade_plan_ladder.py` -> `view_models`

PySide dependencies:

- `momentum_hunter/ui/autonomy_gateway.py`
- `momentum_hunter/ui/trade_plan_ladder.py`

Non-UI autonomy modules do not import PySide.

## Commands Run

Compile:

```powershell
.\.venv\Scripts\python.exe -B -m compileall -q momentum_hunter tests
```

Result: PASS, no output.

Focused tests:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_trade_planning tests.test_argus_autonomy tests.test_trade_plan_ladder tests.test_autonomy_gateway -v
```

Result: PASS, 43 tests ran in 6.119 seconds.

Diff whitespace:

```powershell
git diff --check
```

Initial result before report edits: PASS, no output.

Status:

```powershell
git status --short --branch
```

Initial audit branch result: clean `## codex/ARGUS-QUALITY-001-simulation-foundation-review`.

Forbidden-pattern scan:

```powershell
rg -n -i "requests|urllib|http|socket|api_key|secret|token|password|credential|PaperBroker|LiveBroker|submit_live|submit_paper|place_order|send_order|alpaca|schwab|ibkr|tradestation" momentum_hunter tests
```

Meaning of broad hits:

- Existing market-data and provider modules use `requests`, `socket`, and HTTP URLs for scanner/market data work, not broker execution: examples include `momentum_hunter/market.py`, `momentum_hunter/outcomes.py`, `momentum_hunter/providers.py`, `momentum_hunter/trade_planning.py`, and related tests.
- Autonomy implementation hits are expected safety labels and metadata: `credential_status` in `broker.py`, `stale_tokens` in `risk_governor.py`, and locked paper/live UI button names in `autonomy_gateway.py`.
- Autonomy tests include expected negative/safety strings such as asserting no `requests`, no `urllib`, no `http`, and a fake invalid `LiveBrokerAdapter` evidence row.
- No autonomy implementation hit shows real broker credentials, paper broker code, live broker code, or external broker/network calls.
