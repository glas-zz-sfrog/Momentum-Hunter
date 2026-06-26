from __future__ import annotations

import csv
import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_store import (
    import_capture_candidate_index,
    import_evidence_runs,
    import_minute_bars,
    import_opportunity_alerts,
    import_provider_quality_report,
    import_system_status_events,
)
from momentum_hunter.sqlite_validation import build_sqlite_validation_report, write_sqlite_validation_report


class SQLiteValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-validation-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.sources = write_validation_sources(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_sqlite_validation_passes_for_matching_imported_sources(self) -> None:
        import_all_sources(self.db_path, self.sources)

        payload = build_sqlite_validation_report(
            db_path=self.db_path,
            data_quality_report=self.sources["data_quality"],
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            analysis_captures_path=self.sources["analysis_captures"],
            evidence_run_source_paths=[self.sources["evidence_run"]],
            system_status_source_paths=[self.sources["system_status"]],
        )
        write_sqlite_validation_report(
            payload,
            json_path=self.root / "sqlite-validation-latest.json",
            markdown_path=self.root / "sqlite-validation-latest.md",
        )

        self.assertEqual("PASS", payload["overall_status"])
        self.assertTrue(all(check["status"] == "PASS" for check in payload["checks"]))
        self.assertEqual(1, payload["alert_state_counts"]["source"]["completed"])
        self.assertEqual(1, payload["alert_state_counts"]["sqlite"]["completed"])
        self.assertEqual(1, payload["alert_state_counts"]["source"]["pending"])
        self.assertEqual(1, payload["alert_state_counts"]["sqlite"]["pending"])
        self.assertEqual(1, payload["alert_state_counts"]["source"]["unscorable"])
        self.assertEqual(1, payload["alert_state_counts"]["sqlite"]["unscorable"])
        self.assertEqual(1, payload["minute_bar_symbol_counts"]["source"]["AAA"]["count"])
        self.assertEqual("2026-06-25T09:01:00-05:00", payload["minute_bar_symbol_counts"]["sqlite"]["AAA"]["first_timestamp"])
        self.assertEqual(1, payload["capture_session_counts"]["source"]["morning"])
        self.assertEqual(1, payload["capture_session_counts"]["sqlite"]["morning"])
        self.assertEqual(1, payload["capture_candidate_symbol_counts"]["source"]["AAA"]["count"])
        self.assertIn("opportunity_alerts", payload["import_timestamps"])
        self.assertEqual([], payload["missing_slices"])
        self.assertTrue((self.root / "sqlite-validation-latest.json").exists())
        self.assertTrue((self.root / "sqlite-validation-latest.md").exists())

    def test_sqlite_validation_fails_when_a_mirror_is_missing_rows(self) -> None:
        import_provider_quality_report(self.sources["data_quality"], db_path=self.db_path)

        payload = build_sqlite_validation_report(
            db_path=self.db_path,
            data_quality_report=self.sources["data_quality"],
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            analysis_captures_path=self.sources["analysis_captures"],
            evidence_run_source_paths=[self.sources["evidence_run"]],
            system_status_source_paths=[self.sources["system_status"]],
        )

        self.assertEqual("FAIL", payload["overall_status"])
        self.assertTrue(any(check["status"] == "FAIL" for check in payload["checks"]))


def import_all_sources(db_path: Path, sources: dict[str, Path]) -> None:
    import_provider_quality_report(sources["data_quality"], db_path=db_path)
    import_opportunity_alerts(sources["alerts"], db_path=db_path)
    import_minute_bars(sources["minute_bars"], db_path=db_path)
    import_evidence_runs(db_path=db_path, source_paths=[sources["evidence_run"]])
    import_system_status_events(db_path=db_path, source_paths=[sources["system_status"]])
    import_capture_candidate_index(sources["analysis_captures"], db_path=db_path, captures_dir=sources["captures_dir"])


def write_validation_sources(root: Path) -> dict[str, Path]:
    data_quality = root / "data-quality-latest.json"
    write_json(
        data_quality,
        {
            "engine_version": "data_quality_audit_v1",
            "report": {
                "generated_at": "2026-06-25T09:00:00-05:00",
                "symbol_rows": [{"symbol": "AAA", "usable_market_tape": True, "best_provider": "combined"}],
            },
        },
    )
    alerts = root / "opportunity-alerts.json"
    write_json(
        alerts,
        {
            "schema_version": 1,
            "alerts": [
                {
                    "alert_id": "alert-1",
                    "symbol": "AAA",
                    "timestamp": "2026-06-25T09:01:00-05:00",
                    "alert_type": "TEST_ALERT",
                    "current_state": "PLANNING_SCAFFOLD",
                    "price": 10.0,
                    "outcome": {"status": "COMPLETED", "classification": "SUCCESSFUL"},
                },
                {
                    "alert_id": "alert-2",
                    "symbol": "BBB",
                    "timestamp": "2026-06-25T09:02:00-05:00",
                    "alert_type": "TEST_PENDING",
                    "current_state": "PLANNING_SCAFFOLD",
                    "price": 11.0,
                    "outcome": {"status": "PENDING_OUTCOME", "classification": "PENDING"},
                },
                {
                    "alert_id": "alert-3",
                    "symbol": "CCC",
                    "timestamp": "2026-06-25T09:03:00-05:00",
                    "alert_type": "TEST_UNSCORABLE",
                    "current_state": "PLANNING_SCAFFOLD",
                    "price": None,
                    "outcome": {
                        "status": "UNSCORABLE_OUTCOME",
                        "classification": "UNSCORABLE_MISSING_ENTRY_PRICE",
                        "evaluation_notes": ["Missing alert price."],
                    },
                }
            ],
        },
    )
    minute_bars = root / "opportunity-minute-bars.json"
    write_json(
        minute_bars,
        {
            "bars": {
                "AAA": [
                    {
                        "symbol": "AAA",
                        "timestamp": "2026-06-25T09:01:00-05:00",
                        "open": 10.0,
                        "high": 10.5,
                        "low": 9.9,
                        "close": 10.2,
                        "volume": 1000,
                        "source": "test_1m",
                    }
                ]
            }
        },
    )
    evidence_run = root / "evidence-health-report-20260625T090200-0500.json"
    write_json(
        evidence_run,
        {
            "engine_version": "evidence_health_v1",
            "report": {
                "generated_at": "2026-06-25T09:02:00-05:00",
                "completed_alerts": 1,
                "pending_alerts": 0,
                "warnings": [],
            },
        },
    )
    system_status = root / "system-readiness-latest.json"
    write_json(
        system_status,
        {
            "engine_version": "system_readiness_v1",
            "report": {
                "generated_at": "2026-06-25T09:03:00-05:00",
                "overall_status": "READY",
                "sections": [],
                "issues_requiring_attention": [],
            },
        },
    )
    captures_dir = root / "captures"
    raw_capture = captures_dir / "2026-06-25" / "morning.json"
    write_json(raw_capture, {"capture_date": "2026-06-25", "capture_time": "2026-06-25T09:00:00-05:00", "session": "morning"})
    analysis_captures = root / "analysis-captures.csv"
    write_analysis_csv(analysis_captures)
    return {
        "data_quality": data_quality,
        "alerts": alerts,
        "minute_bars": minute_bars,
        "evidence_run": evidence_run,
        "system_status": system_status,
        "captures_dir": captures_dir,
        "analysis_captures": analysis_captures,
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_analysis_csv(path: Path) -> None:
    row = {
        "capture_date": "2026-06-25",
        "capture_time": "2026-06-25T09:00:00-05:00",
        "session": "morning",
        "provider": "finviz",
        "scanner": "Base Momentum",
        "rank": 1,
        "ticker": "AAA",
        "score": 91,
        "price": 10.0,
        "percent_change": 5.0,
        "volume": 1000000,
        "relative_volume": 1.5,
        "market_cap": 5000000000,
        "sector": "Technology",
        "industry": "Software",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
