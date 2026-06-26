from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


TEST_GROUPS: dict[str, list[str]] = {
    "storage": [
        "tests.test_sqlite_store",
        "tests.test_sqlite_validation",
        "tests.test_sqlite_reports",
        "tests.test_sqlite_queries",
        "tests.test_sqlite_user_state_store",
        "tests.test_user_state_diff",
        "tests.test_user_state_safety",
        "tests.test_sqlite_system_status_store",
        "tests.test_sqlite_evidence_store",
        "tests.test_sqlite_evidence_runs_store",
        "tests.test_sqlite_capture_index_store",
        "tests.test_sqlite_minute_bars_store",
        "tests.test_read_models",
    ],
    "evidence": [
        "tests.test_active_alert_reliability",
        "tests.test_active_monitor",
        "tests.test_active_monitor_runner",
        "tests.test_opportunity_alerts",
        "tests.test_alert_outcome_updater",
        "tests.test_evidence_health",
        "tests.test_evidence_autopilot",
        "tests.test_reliability_reports",
        "tests.test_alert_performance",
        "tests.test_market_tape_health",
        "tests.test_monitor_targets",
    ],
    "backend": [
        "tests.test_provider_errors",
        "tests.test_scheduling_policy",
        "tests.test_scoring",
        "tests.test_score_breakdowns",
        "tests.test_score_explanation_view_model",
        "tests.test_candidate_story_view_model",
        "tests.test_news_age",
        "tests.test_news_freshness_audit",
        "tests.test_catalyst_age",
        "tests.test_catalyst_clusters",
        "tests.test_headline_events",
        "tests.test_historical_clusters",
        "tests.test_outcomes",
        "tests.test_outcome_explorer",
        "tests.test_outcome_maturity",
        "tests.test_opportunity_research",
        "tests.test_quarantine",
        "tests.test_raw_capture_integrity",
        "tests.test_rebuild_derived",
        "tests.test_legacy_capture_cleanup",
        "tests.test_storage",
        "tests.test_startup",
        "tests.test_trade_planning",
        "tests.test_branding",
        "tests.test_data_view_state",
        "tests.test_operator_review",
    ],
}


DO_NOT_RUN_UNATTENDED = [
    "tests.test_gui_states",
    "tests.test_daily_workflow",
    "tests.test_morning_review_workspace",
    "tests.test_review_workflow",
]


@dataclass(frozen=True)
class TestRunResult:
    module: str
    status: str
    seconds: float
    returncode: int | None


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _modules_for(groups: list[str], only: list[str]) -> list[str]:
    modules: list[str] = []
    for group in groups:
        modules.extend(TEST_GROUPS[group])
    modules = _ordered_unique(modules)
    if only:
        requested = set(only)
        modules = [module for module in modules if module in requested]
        missing = requested.difference(modules)
        if missing:
            raise SystemExit(f"Requested module(s) are not in selected safe group(s): {', '.join(sorted(missing))}")
    return modules


def _run_module(module: str, timeout_seconds: int, verbose: bool) -> TestRunResult:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-B", "-m", "unittest", module]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        seconds = time.perf_counter() - started
        print(f"TIMEOUT {module} {seconds:.2f}s")
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return TestRunResult(module=module, status="TIMEOUT", seconds=seconds, returncode=None)

    seconds = time.perf_counter() - started
    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"{status} {module} {seconds:.2f}s")
    if verbose or completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
    return TestRunResult(module=module, status=status, seconds=seconds, returncode=completed.returncode)


def _print_groups() -> None:
    print("Safe bounded test groups:")
    for group, modules in TEST_GROUPS.items():
        print(f"\n[{group}]")
        for module in modules:
            print(f"  {module}")
    print("\nDo not run unattended:")
    for module in DO_NOT_RUN_UNATTENDED:
        print(f"  {module}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Momentum Hunter safe test groups with per-module timeouts.")
    parser.add_argument("--group", action="append", choices=sorted(TEST_GROUPS), help="Safe group to run.")
    parser.add_argument("--only", action="append", default=[], help="Run only this module from the selected group(s).")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds per test module.")
    parser.add_argument("--list", action="store_true", help="List safe groups and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected modules without running tests.")
    parser.add_argument("--verbose", action="store_true", help="Print passing test output too.")
    args = parser.parse_args()

    if args.list:
        _print_groups()
        return 0

    groups = args.group or ["backend"]
    modules = _modules_for(groups, args.only)
    if args.dry_run:
        for module in modules:
            print(module)
        return 0

    results = [_run_module(module, args.timeout, args.verbose) for module in modules]
    failed = [result for result in results if result.status != "PASS"]
    print("")
    print(f"Modules run: {len(results)}")
    print(f"Passed: {len(results) - len(failed)}")
    print(f"Failed/timeouts: {len(failed)}")
    if failed:
        for result in failed:
            print(f"  {result.status}: {result.module}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
