# ARGUS-R002 Extract Gateway / Argus Machine UI Module

## Branch
`codex/ARGUS-R002-extract-gateway-machine-ui`

## Scope
Extracted the Gateway and Argus Machine console UI construction out of `momentum_hunter/app.py` into a dedicated PySide module while preserving behavior and safety wording.

## Files Changed
- `momentum_hunter/app.py`
- `momentum_hunter/ui/autonomy_gateway.py`
- `docs/argus-office/reports/releases/ARGUS-R002-extract-gateway-machine-ui.md`
- `docs/argus-office/reports/releases/ARGUS-R002-gateway-ui-proof.png`
- `docs/argus-office/reports/releases/ARGUS-R002-machine-console-ui-proof.png`
- `docs/argus-office/CURRENT_STATE.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`

## What Moved
- Gateway screen construction.
- Steven Desk / Argus Machine choice cards and button layout.
- Argus Machine console shell construction.
- Machine Status Bar.
- Top 5 placeholder candidate panel.
- Selected Candidate Workbench.
- Trade Plan Ladder panel and placeholder row population.
- Risk Governor display shell.
- Locked Order Console display shell.
- Machine Log shell.
- Argus Machine placeholder candidate data.

## What Remains In App.py
- Main window creation and stack ownership.
- Gateway, Steven Desk, and Argus Machine route methods.
- Dashboard, workflow, evidence, replay, research, capture, and scanner behavior.
- Status messaging for route changes.

## Behavior Preservation
Momentum Hunter still opens to the gateway. Steven Desk opens the existing dashboard path. Argus Machine opens the same display-only console shell. Five placeholder candidate buttons appear, candidate clicks populate the Trade Plan Ladder, and all order controls remain disabled and locked. No broker, order execution, scoring, readiness, replay, database/schema, package, generated data, or runtime market-data behavior changed.

## Verification
- `.\.venv\Scripts\python.exe -B -m compileall -q momentum_hunter tests` passed.
- `.\.venv\Scripts\python.exe -B -m unittest tests.test_autonomy_gateway tests.test_daily_workflow tests.test_gui_states.GuiStateTests.test_command_center_navigation_pages_exist -v` passed: 16 tests.
- `git diff --check` passed during verification.
- Protected-path review confirmed no scoring, readiness, replay identity, storage/schema, broker/order, package/dependency, generated-data, or runtime market-data paths changed.

## UI Evidence
Fresh R002 screenshots were generated and verified:
- `docs/argus-office/reports/releases/ARGUS-R002-gateway-ui-proof.png`: 1280x780, 47,138 bytes, 45 sampled colors.
- `docs/argus-office/reports/releases/ARGUS-R002-machine-console-ui-proof.png`: 1280x780, 96,159 bytes, 41 sampled colors.

The screenshots show the startup gateway, Steven Desk and Argus Machine choices, safe simulation wording, Machine Status Bar, Top 5 placeholder candidates, Trade Plan Ladder, Risk Governor display shell, locked Order Console, and Machine Log.

## Self-Review Findings
- `app.py` is smaller and no longer owns the Gateway / Argus Machine layout block.
- `momentum_hunter/ui/autonomy_gateway.py` owns the extracted UI construction and placeholder candidate data.
- Existing focused tests still prove gateway routing, dashboard preservation, candidate count, ladder population, and disabled order controls.
- Live trading remains locked and placeholder/demo state remains explicit.
- No protected areas were modified.

## Manual QA
1. Launch Momentum Hunter.
2. Confirm the first screen is the gateway.
3. Click Steven Desk and confirm the existing dashboard opens.
4. Return to Gateway.
5. Click Argus Machine and confirm the console shell opens.
6. Click each Top 5 candidate and confirm the Trade Plan Ladder updates.
7. Confirm Preview Order, Submit Paper Order, and Submit Live Order remain disabled.

## Risks
This is a structural UI extraction only. Future work must still avoid mutating scoring, readiness, replay identity, broker/order behavior, and runtime market-data behavior while extracting additional seams.

## Recommendation
Steven should manually QA the two gateway paths and the Argus Machine ladder behavior, then approve a fast-forward merge if the UI remains materially equivalent.
