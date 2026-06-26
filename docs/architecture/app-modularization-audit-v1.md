# App Modularization Audit v1

Date: 2026-06-26

Purpose: reduce risk from `momentum_hunter/app.py` without changing UI layout, trading logic, scoring, readiness rules, alert thresholds, outcome classification, trade planning, SQLite authority, or raw-capture behavior.

## Current State

`momentum_hunter/app.py` remains the primary PySide6 composition root for Momentum Hunter. Before this phase it contained roughly 7,714 lines and mixed:

- top-level Qt window construction
- dashboard and page layout code
- candidate selection callbacks
- score explanation HTML formatting
- Candidate Story data preparation and chart construction
- Replay detail HTML formatting
- Evidence Console dashboard helpers
- Research Lab panel builders
- chart/color helpers
- CLI/app entry point

This creates maintenance risk because small helper changes require importing a very large UI module and because pure formatting behavior is harder to test without touching Qt-heavy surfaces.

## Extraction Candidates

| Candidate | Risk | Recommendation |
| --- | --- | --- |
| Score explanation formatting | Low | Extract now. Pure string/HTML formatting with direct tests. |
| Candidate Story summary data model | Medium | Extract later with care; intertwined with `TimelineRow` and chart/table builders. |
| Replay HTML/detail formatting | Medium | Extract after Candidate Story helper split; must preserve point-in-time wording. |
| Evidence Console row loaders | Medium | Extract later; many file-path/report dependencies but mostly non-widget. |
| Research Lab panel builders | High | Defer. Qt widget construction and lazy loading are sensitive. |
| Dashboard/watchlist page layout | High | Defer to explicit UI milestones only. |
| Chart rendering helpers | Medium/High | Defer unless doing bounded Candidate Story chart polish. |
| SQLite/read-model wrappers | Low/Medium | Already mostly outside `app.py`; keep adding read models outside UI. |

## Implemented Extraction

Created:

```text
momentum_hunter/score_explanation_view_model.py
```

Moved from `app.py`:

- `format_score_breakdown_html`
- compact score summary grouping
- score raw-input formatting
- score rule threshold formatting
- score component explanation wording
- latest valid article context formatting for score explanations

`app.py` now imports:

```python
from momentum_hunter.score_explanation_view_model import format_score_breakdown_html
```

This preserves the existing `momentum_hunter.app.format_score_breakdown_html` access path for older tests and call sites while removing the implementation details from the UI module.

## Behavior Preservation

The extraction preserves:

- human-readable market cap display such as `$40.0B`
- compact volume display such as `20.0M`
- relative volume display such as `1.56x`
- `Base Points` / `Applied Impact` wording
- freshness context explanation showing that HOT freshness can contribute zero points in `momentum_score_v1`
- latest valid article headline/source/age display when available

No scoring values are recalculated by this view-model. It formats stored score breakdown records only.

## Test Coverage

Added:

```text
tests/test_score_explanation_view_model.py
```

Coverage:

- score raw value formatting
- rule threshold formatting
- compact component grouping
- full HTML output including freshness context and latest article information

## Deferred Work

Do not extract these during this sprint unless a later phase explicitly allows it:

- broad Dashboard layout code
- Watchlist Center layout code
- Research Lab widget builders
- Evidence Console widget layout
- Candidate Story chart rendering
- full Qt lifecycle helpers

Recommended next low-risk extraction:

1. `candidate_story_view_model.py` for `CandidateStoryPoint`, `CandidateStorySummary`, and pure summary/format helpers only.
2. Leave chart/table widget builders in `app.py` until a separate chart polish or UI refactor milestone.

## Safety Notes

- Raw captures were not touched.
- User-authored review/watchlist/entry-plan stores were not touched.
- SQLite remains additive and non-authoritative.
- File-based fallback behavior is unchanged.
- Engine modules do not import UI modules.
- This extraction moves UI-facing formatting out of the Qt composition root; it does not move business logic into the UI.
