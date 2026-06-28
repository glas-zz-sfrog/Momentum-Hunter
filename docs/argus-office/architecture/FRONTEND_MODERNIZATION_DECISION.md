# Frontend Modernization Decision

## Decision
Momentum Hunter should modernize the existing PySide6 frontend first while preparing a future backend/API boundary for replaceable frontends. A full C# or Tauri rewrite is not recommended now.

## Why This Decision
The current pain is real: the interface feels older than the product ambition. The evidence says the root cause is not PySide6 itself, but the lack of modular UI architecture and reusable design components.

Key facts:
- `momentum_hunter/app.py` is 7,188 lines.
- Gateway, Argus Machine, Daily Workflow, scanner orchestration, report widgets, HTML formatting, and QSS styling all live in `app.py`.
- The Python backend already has meaningful module boundaries for daily workflow, storage, replay, scoring, evidence, SQLite, trade planning, and view state.
- Existing GUI tests cover key workflows, so incremental PySide6 modernization can be protected.

## Recommended Path
1. Stay PySide6 for the next modernization wave.
2. Extract UI modules from `app.py`.
3. Build a design-system layer with tokens and reusable components.
4. Convert high-value screens first: Gateway, Argus Machine, Daily Workflow, Watchlist Center.
5. Define backend/frontend DTO boundaries so a future C# or web frontend is optional rather than forced.

## Option Scorecard

| Option | Near-Term Value | Risk | Fit |
| --- | --- | --- | --- |
| PySide6 modernization | High | Low | Best immediate choice |
| PySide6 + MVVM extraction | High | Medium | Required architecture bridge |
| C# WinUI 3 rewrite | Medium | High | Revisit after boundary |
| C# Avalonia rewrite | Medium | High | Revisit if cross-platform matters |
| Tauri/web frontend | High later | High now | Good north-star candidate |
| Hybrid backend/API | High | Medium | Target architecture |

## Design System Requirements
The PySide6 design system should include:
- Dark premium trading theme.
- Gold/red accent language.
- Status pills.
- Mode banners.
- Command cards.
- Risk-gate rows.
- Locked action controls.
- Trade Plan Ladder components.
- Consistent spacing and typography.
- Screenshot verification rules for UI changes.

## Do Not Decide Yet
Do not choose WinUI, Avalonia, or Tauri as the implementation platform until:
- R001-R005 are complete.
- `app.py` is smaller and page boundaries are clear.
- Core engine DTOs exist.
- Steven has seen whether modernized PySide6 is good enough.

## CEO Decision
Approve PySide6 modernization plus extraction as the first path. Keep C#/web rewrite as an option, not the next task.
