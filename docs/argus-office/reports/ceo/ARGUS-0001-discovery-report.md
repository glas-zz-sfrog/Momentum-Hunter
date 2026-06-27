# ARGUS-0001 Discovery Report

Date: 2026-06-27
Branch: `codex/ARGUS-0000-office-scaffold`
Mode: read-only discovery/reporting

## 1. Executive Summary
Momentum Hunter appears to be a Windows-first Python/PySide6 desktop research assistant for momentum stock review, watchlist planning, replay, evidence monitoring, and derived trade-readiness reporting. It is repeatedly documented as research/planning only, with no broker connection and no order placement.

The project has a strong amount of test and documentation coverage, but the operational surface is large. The highest-risk areas are the very large GUI composition file, overlapping file/CSV/SQLite data authority boundaries, stale active-monitor/evidence artifacts, broad Qt test-harness risk, and future-facing security hardening before any broker or credentialed provider work.

This swarm made no application changes. The recommended first safe Builder task is a small UI/operator fix: restore a visible Daily Checklist entry or nav destination, because the UI review found it is built and wired but apparently not reachable in the current dashboard/nav.

## 2. Current Apparent Purpose of Momentum Hunter
Momentum Hunter is a local decision-support tool for identifying and reviewing momentum stock candidates. Its purpose appears to be:

- Scan or load candidate stocks from sample/Finviz-style providers.
- Score and explain momentum candidates deterministically.
- Capture point-in-time morning/evening/preopen/manual snapshots.
- Let Steven review candidates, record decisions, build watchlists, and maintain entry plans.
- Track later outcomes and evidence for research quality.
- Surface active monitor, alerts, readiness, and evidence summaries for premarket/live workflow.
- Replay historical captures without mutating raw source data.

It is not currently an automated trading bot. `LIVE` mode is a research label/pathway only in this version.

## 3. Major Code Areas and Entry Points
- `run.py` calls `momentum_hunter.app.main`.
- `Momentum Hunter.bat`, `Momentum Hunter.vbs`, and `tools/launch_momentum_hunter.ps1` launch the desktop app on Windows.
- `momentum_hunter/app.py` is the main PySide6 GUI and workflow coordinator. It is large and mixes navigation, page layout, callbacks, review actions, replay, evidence console, reports, and workflow orchestration.
- `momentum_hunter/models.py` defines core dataclasses and enums such as candidates, news, scanner criteria, trading mode, capture sessions, and market regimes.
- `momentum_hunter/providers.py` contains sample and Finviz provider behavior.
- `momentum_hunter/scoring.py`, `score_breakdowns.py`, and `score_explanation_view_model.py` cover scoring output and score explanation.
- `momentum_hunter/storage.py` owns raw capture/watchlist/snapshot storage, analysis CSV writes, and raw-capture integrity records.
- `momentum_hunter/review.py` and `entry_plans.py` manage user-authored review decisions and entry plans.
- `momentum_hunter/replay.py` builds timeline/replay view models and joins raw captures to later reviews/outcomes/score explanations.
- `momentum_hunter/trade_planning.py`, `active_monitor.py`, `opportunity_alerts.py`, and `alert_outcome_updater.py` drive derived planning, monitoring, alerts, and short-window outcome evidence.
- `momentum_hunter/sqlite_store.py`, `sqlite_migration.py`, `sqlite_validation.py`, `sqlite_reports.py`, and `read_models.py` provide the additive SQLite mirror and read-model reports.
- `tools/*.ps1` and `tools/*.py` provide launch, scheduled capture/evidence jobs, screenshots, audits, and backtests.

## 4. Major Data, Report, and Doc Areas
- `MomentumHunterData/` is ignored by git and contains runtime/generated data, logs, backups, config, reports, captures, SQLite, CSVs, JSON state, and many `_test-*`/`_debug-*` folders.
- Important generated stores include `analysis-captures.csv`, `analysis-outcomes.csv`, `score-breakdowns.json`, `review-decisions.json`, `entry-plans.json`, `opportunity-alerts.json`, `opportunity-minute-bars.json`, and `momentum-hunter.sqlite3`.
- Raw captures live under `MomentumHunterData/data/captures/YYYY-MM-DD/{morning|evening|preopen|manual}.json|md`.
- Integrity/quarantine material lives under `MomentumHunterData/data/integrity/` and `MomentumHunterData/data/quarantine/`.
- Derived readiness/evidence reports live under `MomentumHunterData/data/reports/`.
- Source docs are extensive under `docs/`, especially `docs/storage-map.md`, `docs/testing/`, `docs/storage/`, `docs/platform/`, `docs/operator-experience/`, `docs/project-management/`, and `docs/argus-office/`.
- UI screenshots exist under `docs/screenshots/`, but at least some Evidence screenshots appear effectively unusable because they are only a few pixels tall.

## 5. Existing Test Structure and Likely Test Commands
The project uses Python `unittest`. There are 79 `tests/test_*.py` modules.

Likely safe test discovery and execution commands:

```powershell
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --list
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group backend --timeout 60
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group storage --timeout 60
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group evidence --timeout 60
.\.venv\Scripts\python.exe -B -m unittest tests.test_provider_errors tests.test_market_tape_health tests.test_provider_field_quality
.\.venv\Scripts\python.exe -B tools\run_bounded_tests.py --group backend --only tests.test_candidate_story_view_model --only tests.test_data_view_state --timeout 30
```

Do not run unattended:

- `tests.test_gui_states`
- `tests.test_daily_workflow`
- `tests.test_morning_review_workspace`
- `tests.test_review_workflow`

QA found no `.coveragerc`, `pyproject.toml`, `pytest.ini`, `tox.ini`, `Makefile`, or GitHub workflow. The bounded runner omits 25 existing test modules, including `tests.test_active_monitor_dashboard`, `tests.test_entry_plans`, `tests.test_replay_navigation`, `tests.test_report_loader_hardening`, `tests.test_sqlite_maintenance`, `tests.test_sqlite_runtime_adoption`, and `tests.test_user_state_cutover_simulation`.

No test suites were run for this task because many commands can write `_test-*`, SQLite, backup, or report artifacts under `MomentumHunterData/data`.

## 6. Highest-Risk Technical Areas
- `momentum_hunter/app.py` is the primary structural risk because it concentrates much of the UI and workflow surface in one large file.
- `momentum_hunter/sqlite_store.py` is also large and combines schema, migrations, imports, source parsing, and helpers.
- Source-of-truth boundaries are complex across raw captures, analysis CSVs, outcomes, score breakdowns, review JSON, entry plans, watchlists, alert stores, report files, and SQLite mirrors.
- `momentum_hunter.config.load_config()` can create/write runtime config and data directories as a side effect, so static discovery should avoid app imports when no writes are allowed.
- Generated runtime data sits inside the workspace. Although ignored by git, it can confuse broad scans, disk usage, stale-report review, and cleanup work.
- Launch/task scripts contain hard-coded Windows paths that are acceptable locally but fragile if the repo moves.

## 7. Highest-Risk Product/Operator Areas
- Operational trust is stale: latest readiness/evidence state contains warnings, and active monitor status was reported from 2026-06-22 while this discovery is on 2026-06-27.
- `LIVE` mode is documented as research-only, but persistent UI language like "LIVE REVIEW" can still invite broker/order assumptions.
- Dense evidence and execution tables make live/premarket scanning harder than it needs to be.
- Some empty states risk hiding whether a result means clean zero, missing source, stale source, or load failure.
- Existing screenshot baselines are partly stale or unusable, which weakens visual QA trust.

## 8. Replay/Data Integrity Risks
- Current candidate/outcome linkage appears structurally sound: the data-integrity reviewer found 675 `analysis-captures.csv` rows, 675 `analysis-outcomes.csv` rows, 41 raw capture JSON files, 675 raw candidates, no missing raw/source/outcome candidate keys, no candidate identity time collisions, and SQLite validation passing 41 captures / 675 candidates.
- Replay/review `capture_id` excludes `capture_time`, while score/outcome identity includes time and SQLite uses a hashed full capture key. There are no current collisions, but future same date/session/provider/scanner reruns could confuse cross-store joins.
- Raw capture integrity currently reports warning state: 34 active OK records and 8 quarantined raw artifacts. Quarantined files are explicitly excluded from active study use.
- Guardrails look intentional: missing score/outcome data is warned, replay row selection returns `None` rather than silently selecting the first row, and direct historical open with empty capture does not fallback.
- Any change to replay identity or historical capture selection is protected and should require explicit approval.

## 9. UI/Operator Workflow Risks
- P1: `Daily Checklist` appears constructed and wired but not added to the current dashboard layout, and there is no Daily nav page. This may remove the fastest "what is ready / what is incomplete?" workflow from Steven's normal path.
- P1: Evidence screenshots in `docs/screenshots/` include extremely short images that are not trustworthy visual baselines.
- P2: Evidence/alert tables are dense; execution-ready and alert outcome views should lead with compact, time-stamped operator summaries before full grids.
- P2: Some "NONE" displays should distinguish "0 from source at time" from "source missing" or "not loaded."
- P2: `LIVE` mode should carry a persistent "No broker/order placement" trust indicator, not only an informational popup.

## 10. Security/Configuration Risks
- No tracked `.env`, key, token, credential, broker SDK, order submission, or execution API was found in the discovery pass.
- `.gitignore` excludes `.venv/`, `.tmp/`, `MomentumHunterData/`, `__pycache__/`, and bytecode.
- `requirements.txt` pins `requests==2.32.3` and `lxml==5.3.0`; OSV reported advisories fixed in newer versions. `pip check` passed, but `pip_audit` is not installed.
- Capture failures save full tracebacks under `MomentumHunterData/data/capture-failures`. This is acceptable for current non-credentialed flows but should be redacted before any broker/API-key work.
- Some `requests.Session()` call sites appear to trust ambient environment settings, while at least one market-data path disables environment trust. Network session policy should be made consistent before credentialed integrations.
- External links are escaped but URL schemes should be allowlisted before broader automation or untrusted content flows.
- Public Yahoo/Nasdaq/Finviz data can influence `EXECUTION_READY_*` labels. These must remain research labels until broker-grade validation and explicit order-sink tests exist.

## 11. Recommended First 5 Builder Tasks
1. Restore a visible Daily Checklist path in the dashboard/nav without changing scoring, readiness, replay, data, or runtime semantics.
2. Add or repair screenshot-capture validation so UI screenshots must be nonblank and have sane dimensions before they become evidence.
3. Add a persistent "research only / no broker orders" trust indicator near Mode/Session, especially when `LIVE` is selected.
4. Improve alert/evidence empty-state copy so source, timestamp, and missing-vs-zero state are visible.
5. Create a docs-only side-effect/write-path map before touching data writers, SQLite, replay identity, scoring, alert thresholds, or readiness logic.

## 12. Recommended First 5 QA Tasks
1. Classify the 25 test modules omitted from `tools/run_bounded_tests.py` as safe group, isolated-only, or do-not-run-unattended.
2. Add a dry-run suite map report showing exactly which modules each approved QA command will execute.
3. Define the safe validation menu for the Daily Checklist visibility task, including an isolated UI probe rather than broad Qt modules.
4. Create a regression matrix for replay identity, raw capture immutability, outcomes, score breakdown linkage, and SQLite mirror validation.
5. Document which commands write `MomentumHunterData/data/_test-*`, reports, backups, SQLite, or status files so future QA runs start with known side effects.

## 13. Recommended First 3 UI Review Tasks
1. Decide whether Daily Checklist belongs as a dashboard action, a nav destination, or both.
2. Review the Evidence Console for compact operator-first alert rows and drilldown paths.
3. Audit all empty/loading/error states for source path, generated time, freshness, and stale-vs-missing language.

## 14. Recommended First 3 Data Integrity Tasks
1. Refresh and review active monitor, evidence autopilot, active alert reliability, provider field quality, and system readiness artifacts before using current alerts for decisions.
2. Produce a read-only identity adapter note explaining replay/review capture IDs versus score/outcome/SQLite identities, without changing identity rules.
3. Audit runtime `_test-*` and `_debug-*` folders under `MomentumHunterData/data` and recommend a cleanup policy, but do not delete anything until Steven approves.

## 15. Things Steven Should Not Touch Yet
- Core scoring logic and `config/scoring_profiles.json`.
- Trade readiness logic and alert threshold semantics.
- Replay identity rules and historical capture selection.
- SQLite schema/migrations or any source-of-truth migration.
- Raw captures, quarantined captures, integrity manifests, or generated runtime data cleanup.
- Broker/order-execution concepts, credentials, API keys, or order sinks.
- Dependency/package changes until they are scoped as a security/QA task.
- Broad Qt test modules unless wrapped in the existing bounded/isolated safety policy.

## 16. Questions for Steven
1. Should the first Builder task prioritize restoring Daily Checklist visibility, or should the stale active-monitor/evidence refresh process be addressed first?
2. Should `LIVE` remain a visible mode label, or should the UI rename it to something like "Live Research" until a formal broker gate exists?
3. Should `MomentumHunterData` cleanup become an office-managed task, or should generated data remain untouched unless a specific operational issue appears?
4. Should Argus treat dependency upgrades as a security task now, or wait until the first code-change sprint?
5. For future reports, should generated/runtime data be reviewed in every discovery pass or only when data integrity is explicitly assigned?

## 17. Recommended Next CEO Decision
Approve ARGUS-0002 as the first small Builder task: restore a visible Daily Checklist entry/path and add a bounded UI visibility verification plan. Keep the scope UI/operator only. Explicitly exclude scoring, readiness, replay identity, data stores, SQLite, dependencies, and runtime behavior.

Suggested ARGUS-0002 acceptance criteria:

- Daily Checklist is reachable from the main operator workflow.
- No scoring, readiness, replay, data, SQLite, dependency, or generated-data behavior changes.
- QA uses only an isolated/bounded UI verification path.
- Final report includes screenshots or an explicit reason screenshots were not regenerated.

## Swarm Notes
Roles used: Code Mapper, QA Regression, Data Integrity Reviewer, UI Operator Designer, Security Reviewer, and Release Scribe/Orchestrator consolidation.

Checks run by the Orchestrator were read-only static inspections plus final git verification. No application tests were run. No app launch was performed. No source, test, package, database, generated data, or runtime files were edited.
