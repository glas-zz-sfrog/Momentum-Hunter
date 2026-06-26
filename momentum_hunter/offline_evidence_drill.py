from __future__ import annotations

import argparse
import csv
import gc
import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import MinutePriceBar, update_alert_store_from_minute_bars
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH, OpportunityAlert, is_completed_alert, load_alerts, save_alerts
from momentum_hunter.sqlite_store import (
    import_capture_candidate_index,
    import_evidence_runs,
    import_minute_bars,
    import_opportunity_alerts,
    import_provider_quality_report,
    import_system_status_events,
)
from momentum_hunter.sqlite_validation import build_sqlite_validation_report
from momentum_hunter.storage import file_sha256
from momentum_hunter.time_utils import now_central


REPORTS_DIR = DATA_DIR / "reports"
DRILL_ENGINE_VERSION = "offline_evidence_drill_v1"


def run_offline_evidence_drill(
    *,
    output_dir: Path = REPORTS_DIR,
    workspace_root: Path | None = None,
    cleanup_workspace: bool = True,
    simulate_missing_bars: bool = False,
) -> dict[str, Any]:
    production_alert_hash_before = safe_hash(OPPORTUNITY_ALERTS_PATH)
    if workspace_root is None:
        ensure_app_dirs()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        workspace = DATA_DIR / f"_offline-evidence-drill-{now_central().strftime('%Y%m%d%H%M%S%f')}"
        workspace.mkdir(parents=True, exist_ok=False)
    else:
        workspace = workspace_root
        workspace.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    try:
        sources = write_drill_fixture_sources(workspace)
        bars = {} if simulate_missing_bars else {"DRILL": drill_minute_bars()}
        update_report = update_alert_store_from_minute_bars(
            alerts_path=sources["alerts"],
            minute_bars_path=sources["minute_bars"],
            bars_by_symbol=bars,
            fetch_missing_bars=False,
            status_path=sources["outcome_status"],
        )
        alerts = load_alerts(sources["alerts"])
        completed_alerts = [alert for alert in alerts if is_completed_alert(alert)]
        if not completed_alerts:
            warnings.append("DRILL_NO_COMPLETED_OUTCOME")

        write_drill_evidence_run(sources["evidence_run"], update_report)
        write_drill_system_status(sources["system_status"], update_report)
        import_results = import_drill_sources(sources)
        validation = build_sqlite_validation_report(
            db_path=sources["db"],
            data_quality_report=sources["data_quality"],
            alerts_path=sources["alerts"],
            minute_bars_path=sources["minute_bars"],
            analysis_captures_path=sources["analysis_captures"],
            evidence_run_source_paths=[sources["evidence_run"]],
            system_status_source_paths=[sources["system_status"]],
        )
        if validation.get("overall_status") != "PASS":
            warnings.append(f"DRILL_SQLITE_VALIDATION_NOT_PASS:{validation.get('overall_status')}")

        production_alert_hash_after = safe_hash(OPPORTUNITY_ALERTS_PATH)
        production_mutated = production_alert_hash_before != production_alert_hash_after
        if production_mutated:
            warnings.append("PRODUCTION_ALERT_STORE_HASH_CHANGED")

        status = "FAIL" if production_mutated else "WARN" if warnings else "PASS"
        payload = {
            "schema_version": 1,
            "engine_version": DRILL_ENGINE_VERSION,
            "generated_at": now_central().isoformat(),
            "overall_status": status,
            "workspace": str(workspace),
            "workspace_cleanup_requested": cleanup_workspace,
            "fixture_symbols": ["DRILL"],
            "alerts_processed": update_report.alert_count,
            "outcomes_completed": update_report.completed_alert_count,
            "outcomes_pending": update_report.pending_alert_count,
            "outcomes_unscorable": update_report.unscorable_alert_count,
            "sqlite_fixture_import_status": import_results,
            "sqlite_validation_status": validation.get("overall_status", "UNKNOWN"),
            "sqlite_validation_checks": validation.get("checks", []),
            "production_alert_store_mutated": production_mutated,
            "production_alert_store_hash_before": production_alert_hash_before,
            "production_alert_store_hash_after": production_alert_hash_after,
            "source_paths": {key: str(path) for key, path in sources.items()},
            "outcome_update_report": asdict(update_report),
            "warnings": warnings,
        }
        paths = write_offline_evidence_drill_report(payload, output_dir=output_dir)
        payload["report_paths"] = {"json": str(paths[0]), "markdown": str(paths[1])}
        return payload
    finally:
        if cleanup_workspace:
            if workspace.exists() and workspace.name.startswith("_offline-evidence-drill-"):
                remove_workspace_with_retries(workspace)


def write_drill_fixture_sources(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    alerts_path = root / "opportunity-alerts.json"
    minute_bars_path = root / "opportunity-minute-bars.json"
    outcome_status_path = root / "alert-outcome-update-status.json"
    db_path = root / "momentum-hunter.sqlite3"
    data_quality_path = root / "data-quality-latest.json"
    evidence_run_path = root / "evidence-health-report-drill.json"
    system_status_path = root / "system-readiness-latest.json"
    captures_dir = root / "captures"
    raw_capture_path = captures_dir / "2026-06-25" / "morning.json"
    analysis_captures_path = root / "analysis-captures.csv"

    save_alerts([drill_alert()], alerts_path)
    write_json(
        data_quality_path,
        {
            "engine_version": "offline_drill_data_quality_fixture_v1",
            "report": {
                "generated_at": "2026-06-25T09:00:00-05:00",
                "symbol_rows": [
                    {
                        "symbol": "DRILL",
                        "provider": "fixture",
                        "usable_market_tape": True,
                        "last_price": 10.0,
                        "bid": 9.99,
                        "ask": 10.01,
                        "spread_percent": 0.2,
                        "relative_volume": 1.5,
                        "fields_returned": ["last_price", "bid", "ask", "volume"],
                        "missing_fields": [],
                        "warnings": [],
                    }
                ],
            },
        },
    )
    write_json(raw_capture_path, {"capture_date": "2026-06-25", "capture_time": "2026-06-25T09:00:00-05:00", "session": "morning"})
    write_analysis_capture_fixture(analysis_captures_path)
    return {
        "alerts": alerts_path,
        "minute_bars": minute_bars_path,
        "outcome_status": outcome_status_path,
        "db": db_path,
        "data_quality": data_quality_path,
        "evidence_run": evidence_run_path,
        "system_status": system_status_path,
        "captures_dir": captures_dir,
        "analysis_captures": analysis_captures_path,
    }


def drill_alert() -> OpportunityAlert:
    return OpportunityAlert(
        alert_id="offline-drill-alert-1",
        symbol="DRILL",
        timestamp="2026-06-25T09:00:00-05:00",
        alert_type="OFFLINE_DRILL_BREAKOUT",
        current_state="EXECUTION_READY_TRADE",
        previous_state="PLANNING_SCAFFOLD",
        reason="Offline fixture breakout alert.",
        price=10.0,
        bid=9.99,
        ask=10.01,
        spread_percent=0.2,
        volume=1_000_000,
        premarket_volume=250_000,
        premarket_percent=1.1,
        rvol=1.5,
        rvol_type="INTRADAY_RVOL",
        suggested_entry=10.0,
        stop=9.7,
        target_1=10.5,
        target_2=11.0,
        news_catalyst="Offline drill catalyst",
        market_regime="bull",
        event_mode=False,
        source_report="offline_evidence_drill_fixture",
    )


def drill_minute_bars() -> list[MinutePriceBar]:
    return [
        MinutePriceBar("DRILL", "2026-06-25T09:00:00-05:00", 10.0, 10.1, 9.98, 10.05, 1000, "offline_drill"),
        MinutePriceBar("DRILL", "2026-06-25T09:05:00-05:00", 10.05, 10.3, 10.0, 10.2, 1500, "offline_drill"),
        MinutePriceBar("DRILL", "2026-06-25T09:15:00-05:00", 10.2, 10.65, 10.15, 10.55, 2000, "offline_drill"),
        MinutePriceBar("DRILL", "2026-06-25T09:30:00-05:00", 10.55, 10.8, 10.5, 10.7, 2500, "offline_drill"),
        MinutePriceBar("DRILL", "2026-06-25T10:00:00-05:00", 10.7, 11.05, 10.65, 10.95, 3000, "offline_drill"),
    ]


def write_drill_evidence_run(path: Path, update_report: object) -> None:
    write_json(
        path,
        {
            "engine_version": "offline_drill_evidence_health_fixture_v1",
            "report": {
                "generated_at": now_central().isoformat(),
                "completed_alerts": getattr(update_report, "completed_alert_count", 0),
                "pending_alerts": getattr(update_report, "pending_alert_count", 0),
                "unscorable_alerts": getattr(update_report, "unscorable_alert_count", 0),
                "warnings": list(getattr(update_report, "warnings", [])),
            },
        },
    )


def write_drill_system_status(path: Path, update_report: object) -> None:
    status = "READY" if getattr(update_report, "completed_alert_count", 0) else "WARNING"
    write_json(
        path,
        {
            "engine_version": "offline_drill_system_readiness_fixture_v1",
            "report": {
                "generated_at": now_central().isoformat(),
                "overall_status": status,
                "sections": [],
                "issues_requiring_attention": list(getattr(update_report, "warnings", [])),
            },
        },
    )


def import_drill_sources(sources: dict[str, Path]) -> dict[str, Any]:
    provider = import_provider_quality_report(sources["data_quality"], db_path=sources["db"])
    alerts = import_opportunity_alerts(sources["alerts"], db_path=sources["db"])
    bars = import_minute_bars(sources["minute_bars"], db_path=sources["db"])
    evidence = import_evidence_runs(db_path=sources["db"], source_paths=[sources["evidence_run"]])
    status = import_system_status_events(db_path=sources["db"], source_paths=[sources["system_status"]])
    captures = import_capture_candidate_index(
        sources["analysis_captures"],
        db_path=sources["db"],
        captures_dir=sources["captures_dir"],
    )
    return {
        "provider_quality_rows": provider.rows_seen,
        "alerts_seen": alerts.alerts_seen,
        "outcomes_seen": alerts.outcomes_seen,
        "minute_bars_seen": bars.valid_bars,
        "evidence_runs_seen": evidence.runs_seen,
        "system_status_events_seen": status.events_seen,
        "captures_seen": captures.captures_seen,
        "capture_candidates_seen": captures.candidates_seen,
    }


def write_analysis_capture_fixture(path: Path) -> None:
    row = {
        "capture_date": "2026-06-25",
        "capture_time": "2026-06-25T09:00:00-05:00",
        "session": "morning",
        "provider": "fixture",
        "scanner": "Offline Drill",
        "rank": 1,
        "ticker": "DRILL",
        "score": 91,
        "price": 10.0,
        "percent_change": 5.0,
        "volume": 1_000_000,
        "relative_volume": 1.5,
        "market_cap": 5_000_000_000,
        "sector": "Technology",
        "industry": "Software",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def write_offline_evidence_drill_report(payload: dict[str, Any], *, output_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    ensure_app_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "offline-evidence-drill-latest.json"
    markdown_path = output_dir / "offline-evidence-drill-latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(offline_evidence_drill_markdown(payload), encoding="utf-8")
    return json_path, markdown_path


def offline_evidence_drill_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Offline Evidence Pipeline Drill",
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Fixture symbols: {', '.join(payload.get('fixture_symbols', []) or [])}",
        f"- Alerts processed: {payload.get('alerts_processed', 0)}",
        f"- Outcomes completed: {payload.get('outcomes_completed', 0)}",
        f"- Outcomes pending: {payload.get('outcomes_pending', 0)}",
        f"- Outcomes unscorable: {payload.get('outcomes_unscorable', 0)}",
        f"- SQLite validation: {payload.get('sqlite_validation_status', 'UNKNOWN')}",
        f"- Production alert store mutated: {payload.get('production_alert_store_mutated', False)}",
        "",
        "## Fixture Import",
        "",
    ]
    for key, value in sorted((payload.get("sqlite_fixture_import_status") or {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings") or []
    lines.extend([f"- {item}" for item in warnings] if warnings else ["- None"])
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def safe_hash(path: Path) -> str:
    return file_sha256(path) if path.exists() else ""


def remove_workspace_with_retries(path: Path, *, attempts: int = 20, delay_seconds: float = 0.1) -> None:
    for _attempt in range(attempts):
        gc.collect()
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(delay_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a fixture-based offline evidence pipeline drill.")
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--simulate-missing-bars", action="store_true")
    args = parser.parse_args(argv)

    payload = run_offline_evidence_drill(
        output_dir=args.output_dir,
        workspace_root=args.workspace,
        cleanup_workspace=not args.keep_workspace,
        simulate_missing_bars=args.simulate_missing_bars,
    )
    print(json.dumps(payload, indent=2))
    return 1 if payload.get("overall_status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
