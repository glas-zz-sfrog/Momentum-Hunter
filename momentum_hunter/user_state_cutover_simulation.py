from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.sqlite_store import connect_database, import_user_state
from momentum_hunter.storage import file_sha256
from momentum_hunter.time_utils import now_central
from momentum_hunter.user_state_diff import build_user_state_diff_report
from momentum_hunter.user_state_safety import build_user_state_backup, validate_user_state_backup_restore


USER_STATE_CUTOVER_SIMULATION_VERSION = "user_state_cutover_simulation_v1"
USER_STATE_CUTOVER_SIMULATION_LATEST_JSON = DATA_DIR / "reports" / "user-state-cutover-simulation-latest.json"
USER_STATE_CUTOVER_SIMULATION_LATEST_MD = DATA_DIR / "reports" / "user-state-cutover-simulation-latest.md"


@dataclass(frozen=True)
class SimulationResult:
    name: str
    expected_detection: str
    result: str
    observed_status: str
    source_files_unchanged: bool
    warnings: list[str]
    details: dict[str, Any]


def run_user_state_cutover_simulation(
    *,
    work_dir: Path | None = None,
    keep_work_dir: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or now_central().isoformat()
    work_dir = work_dir or DATA_DIR / "_tmp" / f"user-state-cutover-simulation-{safe_timestamp(generated_at)}"
    if work_dir.exists() and not keep_work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    payload = run_simulation_in_workspace(work_dir, generated_at=generated_at)
    if not keep_work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)
    return payload


def run_simulation_in_workspace(work_dir: Path, *, generated_at: str) -> dict[str, Any]:
    scenarios: list[tuple[str, Callable[[Path, str], SimulationResult]]] = [
        ("clean_import", scenario_clean_import),
        ("missing_watchlist_row", scenario_missing_watchlist_row),
        ("stale_entry_plan", scenario_stale_entry_plan),
        ("duplicate_review", scenario_duplicate_review),
        ("conflicting_review_status", scenario_conflicting_review_status),
        ("malformed_entry_plan", scenario_malformed_entry_plan),
        ("incomplete_entry_plan", scenario_incomplete_entry_plan),
        ("backup_restore_validation_failure", scenario_backup_restore_validation_failure),
        ("rollback_simulation", scenario_rollback_simulation),
        ("source_files_unchanged", scenario_source_files_unchanged),
    ]
    results = [function(work_dir / name, generated_at) for name, function in scenarios]
    failed = [result for result in results if result.result != "PASS"]
    warnings = [f"SCENARIO_FAILED:{result.name}" for result in failed]
    return {
        "schema_version": 1,
        "engine_version": USER_STATE_CUTOVER_SIMULATION_VERSION,
        "generated_at": generated_at,
        "overall_status": "FAIL" if failed else "PASS",
        "scenario_count": len(results),
        "passed_scenarios": len(results) - len(failed),
        "failed_scenarios": len(failed),
        "scenarios": [asdict(result) for result in results],
        "warnings": warnings,
        "safety_notes": [
            "Synthetic fixtures were used.",
            "Production review-decisions.json was not touched.",
            "Production entry-plans.json was not touched.",
            "Production watchlist files were not touched.",
            "SQLite remains an additive mirror and is not authoritative.",
        ],
    }


def scenario_clean_import(root: Path, generated_at: str) -> SimulationResult:
    data_dir, db_path = create_clean_fixture(root)
    before = source_hashes(data_dir)
    import_user_state(
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
        db_path=db_path,
    )
    diff = build_user_state_diff_report(
        db_path=db_path,
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
    )
    unchanged = before == source_hashes(data_dir)
    ok = diff["overall_status"] == "PASS" and unchanged
    return result(
        "clean_import",
        "PASS when files and SQLite mirror match.",
        ok,
        str(diff["overall_status"]),
        unchanged,
        list(diff.get("warnings", [])),
        {"records_in_files": diff.get("records_in_files"), "records_in_sqlite": diff.get("records_in_sqlite")},
    )


def scenario_missing_watchlist_row(root: Path, generated_at: str) -> SimulationResult:
    data_dir, db_path = create_clean_fixture(root)
    before = source_hashes(data_dir)
    import_user_state(
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
        db_path=db_path,
    )
    with connect_database(db_path) as connection:
        connection.execute("DELETE FROM watchlist_items WHERE ticker = 'AAA'")
        connection.commit()
    diff = build_user_state_diff_report(
        db_path=db_path,
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
    )
    table = diff["tables"]["watchlist_items"]
    unchanged = before == source_hashes(data_dir)
    ok = int(table["missing_in_sqlite_count"]) == 1 and unchanged
    return result(
        "missing_watchlist_row",
        "Detect missing SQLite watchlist mirror row.",
        ok,
        str(diff["overall_status"]),
        unchanged,
        list(diff.get("warnings", [])),
        {"missing_in_sqlite": table["missing_in_sqlite"]},
    )


def scenario_stale_entry_plan(root: Path, generated_at: str) -> SimulationResult:
    data_dir, db_path = create_clean_fixture(root)
    import_user_state(
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
        db_path=db_path,
    )
    mutate_entry_plan(data_dir / "entry-plans.json", "trigger", "above 12")
    before = source_hashes(data_dir)
    diff = build_user_state_diff_report(
        db_path=db_path,
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
    )
    table = diff["tables"]["entry_plans"]
    unchanged = before == source_hashes(data_dir)
    ok = int(table["changed_values_count"]) >= 1 and unchanged
    return result(
        "stale_entry_plan",
        "Detect SQLite entry-plan mirror stale against newer file source.",
        ok,
        str(diff["overall_status"]),
        unchanged,
        list(diff.get("warnings", [])),
        {"changed_values": table["changed_values"][:3]},
    )


def scenario_duplicate_review(root: Path, generated_at: str) -> SimulationResult:
    data_dir, db_path = create_clean_fixture(root)
    payload = read_json(data_dir / "review-decisions.json")
    payload["decisions"]["duplicate"] = dict(payload["decisions"]["a"])
    write_json(data_dir / "review-decisions.json", payload)
    before = source_hashes(data_dir)
    import_result = import_user_state(
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
        db_path=db_path,
    )
    unchanged = before == source_hashes(data_dir)
    warning_text = " ".join(import_result.warnings)
    ok = "DUPLICATE_REVIEW_IDENTITY" in warning_text and unchanged
    return result(
        "duplicate_review",
        "Detect duplicate review identity without duplicating rows.",
        ok,
        "WARN" if import_result.warnings else "PASS",
        unchanged,
        list(import_result.warnings),
        {"review_records_seen": import_result.review_records_seen},
    )


def scenario_conflicting_review_status(root: Path, generated_at: str) -> SimulationResult:
    data_dir, db_path = create_clean_fixture(root)
    payload = read_json(data_dir / "review-decisions.json")
    conflicting = dict(payload["decisions"]["a"])
    conflicting["review_status"] = "rejected"
    payload["decisions"]["conflict"] = conflicting
    write_json(data_dir / "review-decisions.json", payload)
    before = source_hashes(data_dir)
    conflicts = detect_review_status_conflicts(data_dir / "review-decisions.json")
    import_result = import_user_state(
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
        db_path=db_path,
    )
    unchanged = before == source_hashes(data_dir)
    ok = bool(conflicts) and unchanged
    warnings = list(import_result.warnings) + [f"CONFLICTING_REVIEW_STATUS:{item}" for item in conflicts]
    return result(
        "conflicting_review_status",
        "Detect same candidate identity with conflicting review statuses.",
        ok,
        "WARN",
        unchanged,
        warnings,
        {"conflicts": conflicts},
    )


def scenario_malformed_entry_plan(root: Path, generated_at: str) -> SimulationResult:
    data_dir, db_path = create_clean_fixture(root)
    payload = read_json(data_dir / "entry-plans.json")
    payload["plans"]["malformed"] = {"trigger": "above 10"}
    write_json(data_dir / "entry-plans.json", payload)
    before = source_hashes(data_dir)
    import_result = import_user_state(
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
        db_path=db_path,
    )
    unchanged = before == source_hashes(data_dir)
    warning_text = " ".join(import_result.warnings)
    ok = "MALFORMED_ENTRY_PLAN_RECORD" in warning_text and unchanged
    return result(
        "malformed_entry_plan",
        "Detect malformed entry plan without mutating source.",
        ok,
        "WARN" if import_result.warnings else "PASS",
        unchanged,
        list(import_result.warnings),
        {"entry_plan_records_seen": import_result.entry_plan_records_seen},
    )


def scenario_incomplete_entry_plan(root: Path, generated_at: str) -> SimulationResult:
    data_dir, db_path = create_clean_fixture(root)
    before = source_hashes(data_dir)
    import_result = import_user_state(
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
        db_path=db_path,
    )
    unchanged = before == source_hashes(data_dir)
    ok = import_result.incomplete_entry_plans >= 1 and unchanged
    return result(
        "incomplete_entry_plan",
        "Detect incomplete entry plans as safety warnings before cutover.",
        ok,
        "WARN" if import_result.incomplete_entry_plans else "PASS",
        unchanged,
        list(import_result.warnings),
        {"incomplete_entry_plans": import_result.incomplete_entry_plans},
    )


def scenario_backup_restore_validation_failure(root: Path, generated_at: str) -> SimulationResult:
    data_dir, _db_path = create_clean_fixture(root)
    before = source_hashes(data_dir)
    backup = build_user_state_backup(data_dir=data_dir, backup_root=root / "backups", generated_at=generated_at)
    backup_dir = Path(str(backup["backup_dir"]))
    for candidate in backup_dir.glob("data/review-decisions.json"):
        candidate.unlink()
    validation = validate_user_state_backup_restore(backup_dir, validation_dir=root / "restore-validation", generated_at=generated_at)
    unchanged = before == source_hashes(data_dir)
    ok = validation["overall_status"] == "FAIL" and int(validation["missing_files"]) >= 1 and unchanged
    return result(
        "backup_restore_validation_failure",
        "Detect a broken backup restore before any live rollback.",
        ok,
        str(validation["overall_status"]),
        unchanged,
        list(validation.get("warnings", [])),
        {"missing_files": validation.get("missing_files")},
    )


def scenario_rollback_simulation(root: Path, generated_at: str) -> SimulationResult:
    data_dir, _db_path = create_clean_fixture(root)
    backup = build_user_state_backup(data_dir=data_dir, backup_root=root / "backups", generated_at=generated_at)
    backup_dir = Path(str(backup["backup_dir"]))
    mutate_entry_plan(data_dir / "entry-plans.json", "trigger", "broken mutation")
    rollback_dir = root / "rollback-target"
    restore_backup_to_directory(backup_dir, rollback_dir)
    restored_hash = file_sha256(rollback_dir / "data" / "entry-plans.json")
    expected_hash = next(item["sha256"] for item in backup["files"] if item["category"] == "entry_plans")
    ok = restored_hash == expected_hash
    return result(
        "rollback_simulation",
        "Prove backup files can restore user-state contents into a safe target directory.",
        ok,
        "PASS" if ok else "FAIL",
        True,
        [],
        {"rollback_dir": str(rollback_dir), "restored_hash_matches_backup": ok},
    )


def scenario_source_files_unchanged(root: Path, generated_at: str) -> SimulationResult:
    data_dir, db_path = create_clean_fixture(root)
    before = source_hashes(data_dir)
    import_user_state(
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
        db_path=db_path,
    )
    build_user_state_diff_report(
        db_path=db_path,
        review_decisions_path=data_dir / "review-decisions.json",
        entry_plans_path=data_dir / "entry-plans.json",
        data_dir=data_dir,
    )
    after = source_hashes(data_dir)
    ok = before == after
    return result(
        "source_files_unchanged",
        "Prove import/diff simulation does not mutate source JSON files.",
        ok,
        "PASS" if ok else "FAIL",
        ok,
        [],
        {"before": before, "after": after},
    )


def create_clean_fixture(root: Path) -> tuple[Path, Path]:
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = root / "momentum-hunter.sqlite3"
    identity_a = {
        "capture_id": "cap-2026-06-25-morning",
        "capture_date": "2026-06-25",
        "session": "morning",
        "provider": "finviz",
        "scanner": "Base Momentum",
        "ticker": "AAA",
    }
    identity_b = dict(identity_a, ticker="BBB")
    write_json(
        data_dir / "review-decisions.json",
        {
            "schema_version": 1,
            "decisions": {
                "a": {
                    "identity": identity_a,
                    "review_status": "watchlist",
                    "decision_timestamp": "2026-06-25T09:00:00-05:00",
                    "decision_note": "watch breakout",
                },
                "b": {
                    "identity": identity_b,
                    "review_status": "interested",
                    "decision_timestamp": "2026-06-25T09:05:00-05:00",
                    "decision_note": "needs plan",
                },
            },
        },
    )
    write_json(
        data_dir / "entry-plans.json",
        {
            "schema_version": 1,
            "plans": {
                "a": {
                    "identity": identity_a,
                    "trigger": "above 10",
                    "stop": "9.50",
                    "thesis": "continuation",
                    "invalidation": "loses 9.50",
                    "max_loss": "$20",
                    "position_size": "$100",
                    "planned_hold_time": "1 day",
                    "notes": "tight plan",
                    "plan_complete": True,
                    "updated_at": "2026-06-25T09:10:00-05:00",
                },
                "b": {
                    "identity": identity_b,
                    "trigger": "",
                    "stop": "",
                    "invalidation": "",
                    "max_loss": "",
                    "plan_complete": False,
                    "updated_at": "2026-06-25T09:15:00-05:00",
                },
            },
        },
    )
    write_json(data_dir / "watchlist-2026-06-25.json", [{"ticker": "AAA", "company": "AAA Co", "score": 91, "price": 10.0}])
    return data_dir, db_path


def mutate_entry_plan(path: Path, field: str, value: Any) -> None:
    payload = read_json(path)
    first_key = next(iter(payload["plans"]))
    payload["plans"][first_key][field] = value
    write_json(path, payload)


def detect_review_status_conflicts(path: Path) -> list[str]:
    payload = read_json(path)
    raw_decisions = payload.get("decisions", {})
    seen: dict[str, str] = {}
    conflicts: list[str] = []
    if not isinstance(raw_decisions, dict):
        return conflicts
    for key, item in raw_decisions.items():
        if not isinstance(item, dict):
            continue
        identity = item.get("identity")
        if not isinstance(identity, dict):
            continue
        identity_key = "|".join(
            str(identity.get(part, ""))
            for part in ["capture_id", "capture_date", "session", "provider", "scanner", "ticker"]
        )
        status = str(item.get("review_status", ""))
        previous = seen.get(identity_key)
        if previous is not None and previous != status:
            conflicts.append(f"{identity_key}:{previous}!={status}:{key}")
        seen[identity_key] = status
    return conflicts


def restore_backup_to_directory(backup_dir: Path, target_dir: Path) -> None:
    manifest = read_json(backup_dir / "manifest.json")
    for item in manifest.get("files", []):
        if not isinstance(item, dict) or not item.get("exists"):
            continue
        relative = Path(str(item.get("backup_relative_path", "")))
        source = backup_dir / relative
        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def source_hashes(data_dir: Path) -> dict[str, str]:
    paths = [
        data_dir / "review-decisions.json",
        data_dir / "entry-plans.json",
        *sorted(data_dir.glob("watchlist-*.json")),
    ]
    return {path.name: file_sha256(path) for path in paths if path.exists()}


def safe_timestamp(value: str) -> str:
    clean = "".join(character for character in str(value) if character.isdigit())
    return clean[:20] or now_central().strftime("%Y%m%d%H%M%S")


def result(
    name: str,
    expected_detection: str,
    ok: bool,
    observed_status: str,
    source_files_unchanged: bool,
    warnings: list[str],
    details: dict[str, Any],
) -> SimulationResult:
    return SimulationResult(
        name=name,
        expected_detection=expected_detection,
        result="PASS" if ok else "FAIL",
        observed_status=observed_status,
        source_files_unchanged=source_files_unchanged,
        warnings=warnings,
        details=details,
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_user_state_cutover_simulation_report(
    payload: dict[str, Any],
    *,
    json_path: Path = USER_STATE_CUTOVER_SIMULATION_LATEST_JSON,
    markdown_path: Path = USER_STATE_CUTOVER_SIMULATION_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_cutover_simulation_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_cutover_simulation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Hunter User-State Cutover Simulation",
        "",
        "Synthetic dry-run report. Production user-state files are not modified.",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Scenarios: {payload.get('scenario_count', 0)}",
        f"- Passed: {payload.get('passed_scenarios', 0)}",
        f"- Failed: {payload.get('failed_scenarios', 0)}",
        "",
        "## Scenario Results",
        "",
        "| Scenario | Result | Observed | Source Files Unchanged | Expected Detection | Warnings |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for scenario in payload.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        warnings = ", ".join(scenario.get("warnings", []))
        lines.append(
            "| "
            + " | ".join(
                [
                    str(scenario.get("name", "")),
                    str(scenario.get("result", "")),
                    str(scenario.get("observed_status", "")),
                    str(scenario.get("source_files_unchanged", "")),
                    str(scenario.get("expected_detection", "")).replace("|", "/"),
                    warnings.replace("|", "/"),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Safety Notes", ""])
    notes = payload.get("safety_notes", [])
    lines.extend([f"- {note}" for note in notes] if isinstance(notes, list) and notes else ["- None."])
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings", [])
    lines.extend([f"- {warning}" for warning in warnings] if isinstance(warnings, list) and warnings else ["- None."])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run synthetic user-state disaster recovery and cutover simulation.")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--keep-work-dir", action="store_true")
    parser.add_argument("--json", type=Path, default=USER_STATE_CUTOVER_SIMULATION_LATEST_JSON)
    parser.add_argument("--markdown", type=Path, default=USER_STATE_CUTOVER_SIMULATION_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_user_state_cutover_simulation(work_dir=args.work_dir, keep_work_dir=args.keep_work_dir)
    paths = write_user_state_cutover_simulation_report(payload, json_path=args.json, markdown_path=args.markdown)
    print(json.dumps({"overall_status": payload.get("overall_status"), "warnings": payload.get("warnings", []), "paths": {key: str(value) for key, value in paths.items()}}, indent=2))
    return 0 if payload.get("overall_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
