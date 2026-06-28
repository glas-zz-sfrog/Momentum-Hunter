# App.py Extraction Plan

## Problem
`momentum_hunter/app.py` is the central desktop shell and currently carries too many responsibilities. It is 7,188 lines and includes widget construction, navigation, workflow state mapping, provider calls, persistence calls, report rendering, HTML formatting, chart/table builders, and styling.

## Goal
Shrink `app.py` into an application shell that wires pages together. Move page construction, view-model mapping, reusable components, and formatting helpers into dedicated modules without changing runtime behavior.

## Extraction Principles
- Extract pure helpers first.
- Preserve public UI labels and object names unless the task explicitly allows UI copy/design changes.
- Move code with focused tests.
- Keep protected behavior untouched.
- Use existing tests as guardrails; add narrow tests only when a moved seam needs coverage.

## Target Module Shape

```text
momentum_hunter/
  app.py                         # shell, navigation, top-level orchestration
  ui/
    theme.py                     # design tokens, QSS, state colors
    components.py                # cards, pills, banners, locked buttons
    gateway_page.py              # Steven Desk / Argus Machine gateway
    argus_machine_page.py        # display-only machine console
    daily_workflow_page.py       # dialog/page builder
    daily_workflow_view_model.py # stepper/next-action view mapping
    report_panels.py             # reusable report panel widgets
    replay_views.py              # replay detail HTML/widgets
```

## First Extraction Seams
1. `ARGUS_MACHINE_PLACEHOLDER_CANDIDATES` into an autonomy/UI fixture module or view model.
2. `_build_gateway_page`, `_build_gateway_choice`, `show_gateway`, `open_steven_desk`, `open_argus_machine_console`.
3. `_build_argus_machine_console_page` and its panel builders.
4. `_select_argus_machine_candidate` view update logic.
5. `build_daily_workflow_guided_panel`.
6. `daily_workflow_next_action` and step helper functions.
7. `build_daily_workflow_summary_table` and warning table builders.
8. `STYLESHEET` plus daily-workflow style helper functions.
9. Report widget builders such as historical, catalyst, outcome, opportunity, and recommendation panels.
10. Replay/news HTML formatters.

## First Implementation Order
1. Responsibility map only.
2. Gateway and Argus Machine extraction.
3. Daily Workflow UI/view-model extraction.
4. Design-system layer.
5. Backend boundary definition and DTO prototype docs.

## Testing Strategy
- Existing GUI tests remain the first safety net:
  - `tests/test_autonomy_gateway.py`
  - `tests/test_daily_workflow.py`
  - `tests/test_gui_states.py`
  - `tests/test_morning_review_workspace.py`
- Add pure view-model tests for extracted Daily Workflow and Argus Machine mappings.
- Use compile checks after every extraction.
- Use screenshot sanity checks for visible UI redesign tasks.

## Stop Conditions
Stop if an extraction changes:
- Scoring output.
- Readiness semantics.
- Replay identity.
- Capture selection.
- Broker/order behavior.
- Database/schema files.
- Package/dependency files.
- Generated data or runtime report output.

## Acceptance Direction
`app.py` becomes smaller and easier to review while Steven sees the same behavior unless a task explicitly approves a visual/UI change.
