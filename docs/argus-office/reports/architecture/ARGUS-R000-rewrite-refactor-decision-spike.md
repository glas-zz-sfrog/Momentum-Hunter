# ARGUS-R000 Rewrite / Refactor Decision Spike

## 1. Executive Recommendation
Do not rewrite Momentum Hunter now. Pursue a staged hybrid architecture: keep the Python engine, modernize the PySide6 shell with a real design system, and extract `momentum_hunter/app.py` into smaller UI modules and view-model/service boundaries. The north star is a Python core engine with replaceable frontends, but the first implementation path should be PySide6 modernization plus app.py extraction because it preserves proven trading behavior while removing the parts that make the interface feel dated.

## 2. Current Architecture Diagnosis
Evidence from the current codebase:
- `momentum_hunter/app.py` is 7,188 lines and contains the `MomentumHunterWindow` class starting at line 408.
- The same file builds the startup gateway at lines 499-553, the Argus Machine console at lines 611-882, the dashboard/watchlist/replay/capture pages at lines 970-1243, scanner orchestration at lines 2229-2293, Daily Workflow modal assembly at lines 2985-3073, Daily Workflow stepper/view logic at lines 4788-5308, report widgets at lines 6273-7498, and the global stylesheet at line 7558.
- Backend modules already exist for scanner models, storage, scoring, replay, SQLite, active monitoring, trade planning, daily workflow reports, evidence console view models, and freshness/view-state decisions.
- The repository has about 80 test files, including GUI coverage for gateway, Daily Workflow, dashboard states, and morning review.

Diagnosis: the engine is not the part demanding a rewrite. The strain is concentrated in an overloaded desktop shell and a thin design-system layer.

## Existing Module Boundary Inventory
The codebase already has useful extraction targets outside `app.py`:
- Scanner/provider/model boundary: `models.py`, `providers.py`, `scoring.py`, and scanner presets are separate from the GUI.
- Evidence/reporting boundary: active monitor, alert outcome, evidence health, evidence console view model, opportunity research, outcome maturity, and report-index modules exist outside the shell.
- Replay boundary: `replay.py` owns replay view-model construction and is called by UI builders.
- SQLite/data storage boundary: SQLite store, query, validation, migration, report, analytics, and maintenance modules exist as dedicated files.
- UI helper boundary: `momentum_hunter/ui/data_view_state.py` already contains freshness and view-state display decisions.
- Trade planning boundary: `trade_planning.py` contains planning dataclasses/report generation for the current trade-planning pipeline.
- Execution/autonomy boundary: on this local-master branch, there is not yet a tracked `momentum_hunter/execution` package; autonomy and broker/risk concepts are currently represented by Argus Office specs and the display-only Argus Machine shell.
- Test boundary: about 80 `tests/test_*.py` files exist, including GUI tests for gateway, Daily Workflow, and dashboard state.

## 3. What Is Actually Wrong With The UI
The UI feels dated because:
- Layouts are mostly hand-built PySide6 widgets in one large file, so page composition is dense and rigid.
- The visual language is mostly one global QSS block plus per-widget object names; there is no first-class component library for cards, pills, banners, gated buttons, or trading-mode states.
- Complex workflows such as Daily Workflow and Argus Machine are embedded as local widget builders instead of reusable cockpit components.
- Tables dominate the experience even when Steven needs sequence, priority, mode, and trust state.
- The gateway and Argus Machine shell have the right product split, but the page still inherits older desktop visual patterns.

This is fixable inside PySide6 before considering a frontend rewrite.

## 4. What Is Actually Wrong With The Code Structure
`app.py` mixes responsibilities:
- UI shell and navigation.
- Page/widget construction.
- Workflow state translation.
- Provider/scanner orchestration.
- Persistence calls.
- Report discovery and CSV/JSON reads.
- HTML formatting for details and replay.
- Chart/table widget construction.
- Global styling.
- Gateway and autonomous console placeholder logic.

The problem is not that Python is wrong. The problem is that presentation, orchestration, formatting, and view-model logic are too tightly located in one file.

## 5. Whether A Full Rewrite Is Justified Now
No. A full rewrite is not justified now.

Reasons:
- Core engine behavior is already spread across tested Python modules.
- Protected areas include scoring, readiness, replay, storage, broker/order behavior, and runtime semantics; a rewrite would put all of those at risk.
- PySide6 can support a much more modern app if the design system and component boundaries are improved.
- A rewrite would slow the autonomy roadmap while creating duplicate UI and engine integration risk.

## 6. Whether A Major Refactor Is Justified Now
Yes, but only as a staged, test-protected refactor. The correct refactor is not "rewrite app.py in one move." It is a sequence of small extractions that make the UI safer to modernize and later replace.

## 7. Frontend Option Comparison

| Option | Pros | Cons | Decision |
| --- | --- | --- | --- |
| PySide6 modernized | Lowest risk, keeps current app, can improve visual quality quickly, preserves tests and packaging. | Still desktop-widget based; high polish requires discipline. | Recommended first path. |
| PySide6 + MVVM/module extraction | Best near-term architecture move; turns app.py into shell plus pages/components/view models. | Requires careful incremental work and GUI regression tests. | Required bridge. |
| C# WinUI 3 | Strong native Windows feel and modern controls. | High rewrite cost; Python engine boundary required first; Windows-only. | Revisit later after backend boundary exists. |
| C# Avalonia | Cross-platform .NET desktop and more modern UI than current shell. | Still a rewrite; Python interop/API boundary needed. | Possible later frontend candidate. |
| Tauri/web frontend | Best dashboard polish and web-style component velocity. | Requires backend/API separation and web security/packaging choices. | Strong north-star option after service boundary. |
| Hybrid backend/API model | Lets Python engine stay authoritative while frontends become replaceable. | Requires interface design and DTO discipline. | Recommended north star. |

## 8. Recommended Architecture North Star
Use a staged hybrid architecture:
- Python core engine remains authoritative for scanning, scoring, evidence, replay, storage, readiness, trade planning, and risk governance.
- PySide6 becomes a modular desktop frontend in the near term.
- A narrow application-service boundary exposes stable DTOs for future frontends.
- A later WinUI/Avalonia/Tauri UI can consume the same engine boundary without rewriting market logic.

## 9. What Should Remain Python
Keep these in Python:
- Scanner/provider orchestration.
- Candidate/scoring logic.
- Evidence and readiness reports.
- Replay identity and timeline logic.
- SQLite/storage/migration code.
- Daily Workflow report generation.
- Trade planning and future Risk Governor logic.
- Broker adapter and execution audit services when explicitly approved later.

## 10. What Could Later Become C#/Web/Frontend
Potential future frontend-only surfaces:
- Startup gateway.
- Steven Desk dashboard shell.
- Argus Machine console.
- Trade Plan Ladder presentation.
- Risk Governor status visualization.
- Watchlist Center UI.
- Daily Workflow cockpit.
- Report browser/charts.
- Machine Log and Execution Console presentation.

## 11. What Should Be Extracted From App.py First
Extract lowest-risk UI/page boundaries first:
1. Gateway and Argus Machine console builders.
2. Daily Workflow guided-panel builder and step state mapping.
3. Design-system/style tokens currently embedded in `STYLESHEET` and helper stylesheets.
4. Report panel builders and HTML formatters.
5. Scanner and data-loading orchestration into application services.

## 12. First 10 Safe Extraction Seams
1. Gateway page builders and navigation callbacks.
2. Argus Machine placeholder candidate constants and console panels.
3. Daily Workflow guided panel builder.
4. Daily Workflow step/next-action pure logic.
5. Daily Workflow table builders.
6. Global stylesheet and color/state helper functions.
7. Report panel builders for historical/catalyst/outcome/recommendation reports.
8. Replay HTML/detail formatters.
9. Execution-ready CSV/JSON loader helpers.
10. Watchlist Center table population and entry-plan opening glue.

## 13. First 5 Executable Refactor Tasks
1. ARGUS-R001 - App.py Responsibility Map and Extraction Targets.
2. ARGUS-R002 - Extract Gateway / Argus Machine UI into Dedicated Module.
3. ARGUS-R003 - Extract Daily Workflow UI Builder from App.py.
4. ARGUS-R004 - Create Momentum Hunter Design System / Theme Layer.
5. ARGUS-R005 - Define Backend Engine Boundary for Future Frontend Rewrite.

Detailed task contracts are in `docs/argus-office/architecture/REFRACTOR_ROADMAP.md`.

## 14. First 5 Frontend Modernization Tasks
1. Define design tokens for background, surface, accent, danger, warning, success, locked, simulation, paper, and live states.
2. Build reusable PySide6 components for status pills, mode banners, command cards, risk-gate rows, and locked action buttons.
3. Apply the component layer first to Gateway and Argus Machine because they are isolated from scoring/runtime behavior.
4. Modernize Daily Workflow into a cockpit-like first-class dashboard/modal without changing workflow facts.
5. Add screenshot proof standards for UI work: nonblank image, expected panels visible, and desktop/mobile or window-size sanity where applicable.

## 15. First 5 Autonomous-Side Architecture Tasks
1. Map Top 5 placeholder candidates into real `TradePlan` DTOs without broker behavior.
2. Feed Risk Governor output into the Argus Machine display as read-only status.
3. Define Execution Ledger DTOs and append-only audit semantics before paper trading.
4. Define Broker Adapter interface states but keep adapters unimplemented/locked.
5. Define Machine Log event schema for planning, simulation, paper, blocked, and approval-needed events.

## 16. What Not To Touch Yet
Do not touch:
- Scoring formulas or score weights.
- Readiness semantics.
- Replay identity.
- Historical capture selection.
- SQLite schema/migrations.
- Broker/order execution behavior.
- Alert threshold semantics.
- Secrets/API keys/env config.
- Live/paper order routing.
- Production runtime behavior.

## 17. Risks Of Rewriting Now
- Regression in scoring, readiness, replay, or storage behavior.
- Loss of trust in existing tests because both app and frontend would move at once.
- Long period with two half-working apps.
- Delayed Argus Machine progress.
- Premature frontend choice before the backend boundary is stable.

## 18. Risks Of Not Rewriting
- `app.py` keeps growing and becomes harder to review.
- UI modernization remains inconsistent if there is no design system.
- Future frontend replacement gets harder if service boundaries are not extracted.
- Steven continues to feel the product is less polished than its engine deserves.

## 19. Recommended CEO Decision
Steven should approve a staged modernization program, not a full rewrite. The decision should be:
- Keep Python as the engine.
- Modernize PySide6 first.
- Extract `app.py` into page/component/view-model modules.
- Design a backend/frontend boundary before considering WinUI, Avalonia, or Tauri.
- Revisit the frontend rewrite only after R001-R005 prove the boundary and improve the visible product.

## Evidence Commands
- `Get-Content momentum_hunter/app.py | Measure-Object -Line` returned 7,188 lines.
- `rg -n "Daily Workflow|Argus Machine|Gateway|Risk Governor" momentum_hunter/app.py` showed core UI workflows concentrated in `app.py`.
- `rg --files momentum_hunter tests docs/argus-office` showed mature backend/test/docs module boundaries already exist.

## Verification Plan
- `git status`
- `git diff --check`
- Changed-path check confirming only docs changed.
