from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.workstation_technical_research import (
    TechnicalResearchPaths,
    WorkstationTechnicalResearchService,
)


class WorkstationTechnicalResearchTests(unittest.TestCase):
    def test_available_snapshot_preserves_stored_events_studies_and_full_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_reports(paths)
            service = WorkstationTechnicalResearchService(paths)

            snapshot = service.snapshot("nvda", observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual(1, snapshot["schemaVersion"])
            self.assertEqual("NVDA", snapshot["symbol"])
            self.assertEqual("AVAILABLE", snapshot["state"])
            self.assertEqual(3, snapshot["globalEventCount"])
            self.assertEqual(2, snapshot["globalStudyCount"])
            self.assertEqual(2, snapshot["symbolEventCount"])
            self.assertEqual(1, snapshot["symbolStudyCount"])
            self.assertEqual(1, snapshot["presentEventCount"])
            self.assertEqual(1, snapshot["failedStudyCount"])
            self.assertEqual(["new", "old"], [row["eventId"] for row in snapshot["events"]])
            newest = snapshot["events"][0]
            self.assertEqual("Breakout present", newest["status"])
            self.assertEqual(2.25, newest["relativeVolume"])
            self.assertTrue(newest["volumeConfirmed"])
            study = snapshot["studies"][0]
            self.assertEqual("Breakout failed", study["status"])
            self.assertEqual(4.5, study["return5dPct"])
            self.assertEqual(-2.0, study["maxAdverseExcursionPct"])
            self.assertTrue(study["failedBackBelowBreakoutLevel"])
            self.assertIn("Research evidence only", snapshot["summary"])

    def test_old_report_is_stale_without_discarding_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_reports(paths, generated_at="2026-07-20T12:00:00Z")

            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "NVDA",
                observed_at=at("2026-07-23T15:00:00Z"),
            )

            self.assertEqual("STALE", snapshot["state"])
            self.assertEqual(2, len(snapshot["events"]))
            self.assertIn("24-hour", snapshot["summary"])

    def test_missing_or_invalid_event_report_is_unavailable_not_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "NVDA",
                observed_at=at("2026-07-23T15:00:00Z"),
            )
            self.assertEqual("UNAVAILABLE", snapshot["state"])
            self.assertEqual([], snapshot["events"])

            paths.events_path.write_text(
                json.dumps({"schema_version": 1, "research_only": True, "events": ["bad-row"]}),
                encoding="utf-8",
            )
            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "NVDA",
                observed_at=at("2026-07-23T15:00:00Z"),
            )
            self.assertEqual("UNAVAILABLE", snapshot["state"])
            self.assertIn("invalid events collection", snapshot["summary"])

    def test_missing_study_report_is_partial_and_preserves_event_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_event_report(paths.events_path)

            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "NVDA",
                observed_at=at("2026-07-23T15:00:00Z"),
            )

            self.assertEqual("PARTIAL", snapshot["state"])
            self.assertEqual(2, snapshot["symbolEventCount"])
            self.assertEqual(0, snapshot["symbolStudyCount"])
            self.assertEqual([], snapshot["studies"])
            self.assertTrue(any("does not exist" in warning for warning in snapshot["warnings"]))

    def test_missing_study_report_is_partial_even_when_symbol_has_no_event_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_event_report(paths.events_path, events=[])

            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "NVDA",
                observed_at=at("2026-07-23T15:00:00Z"),
            )

            self.assertEqual("PARTIAL", snapshot["state"])
            self.assertIn("one source", snapshot["summary"])

    def test_event_without_studied_outcome_is_partial_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_event_report(
                paths.events_path,
                events=[event("event-only", "NVDA", "2026-07-23T14:00:00Z")],
            )
            write_study_report(paths.study_path, studies=[])

            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "NVDA",
                observed_at=at("2026-07-23T15:00:00Z"),
            )

            self.assertEqual("PARTIAL", snapshot["state"])
            self.assertEqual(1, snapshot["symbolEventCount"])
            self.assertEqual(0, snapshot["symbolStudyCount"])
            self.assertIn("evidence chain is incomplete", snapshot["summary"])

    def test_study_without_event_evidence_is_partial_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_event_report(paths.events_path, events=[])
            write_study_report(
                paths.study_path,
                studies=[study("orphan-study", "NVDA", "2026-07-23T14:00:00Z")],
            )

            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "NVDA",
                observed_at=at("2026-07-23T15:00:00Z"),
            )

            self.assertEqual("PARTIAL", snapshot["state"])
            self.assertEqual(0, snapshot["symbolEventCount"])
            self.assertEqual(1, snapshot["symbolStudyCount"])
            self.assertIn("evidence chain is incomplete", snapshot["summary"])

    def test_symbol_without_rows_is_empty_not_breakout_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_reports(paths)

            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "MSFT",
                observed_at=at("2026-07-23T15:00:00Z"),
            )

            self.assertEqual("EMPTY", snapshot["state"])
            self.assertEqual([], snapshot["events"])
            self.assertEqual([], snapshot["studies"])
            self.assertIn("not evidence that a breakout is absent", snapshot["summary"])

    def test_row_limits_preserve_full_symbol_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            events = [
                event(
                    f"event-{index:03d}",
                    "NVDA",
                    f"2026-07-{(index % 20) + 1:02d}T{index % 24:02d}:00:00Z",
                )
                for index in range(60)
            ]
            studies = [
                study(
                    f"study-{index:03d}",
                    "NVDA",
                    f"2026-07-{(index % 20) + 1:02d}T{index % 24:02d}:00:00Z",
                )
                for index in range(70)
            ]
            write_event_report(paths.events_path, events=events)
            write_study_report(paths.study_path, studies=studies)

            snapshot = WorkstationTechnicalResearchService(paths).snapshot(
                "NVDA",
                observed_at=at("2026-07-23T15:00:00Z"),
            )

            self.assertEqual(60, snapshot["symbolEventCount"])
            self.assertEqual(70, snapshot["symbolStudyCount"])
            self.assertEqual(50, len(snapshot["events"]))
            self.assertEqual(50, len(snapshot["studies"]))
            self.assertIn("Counts cover the full reports", snapshot["summary"])

    def test_reads_do_not_mutate_sources_and_cache_refreshes_after_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_reports(paths)
            before_events = sha256(paths.events_path)
            before_studies = sha256(paths.study_path)
            service = WorkstationTechnicalResearchService(paths)

            first = service.snapshot("NVDA", observed_at=at("2026-07-23T15:00:00Z"))
            second = service.snapshot("NVDA", observed_at=at("2026-07-23T15:00:01Z"))

            self.assertEqual(2, first["symbolEventCount"])
            self.assertEqual(2, second["symbolEventCount"])
            self.assertEqual(before_events, sha256(paths.events_path))
            self.assertEqual(before_studies, sha256(paths.study_path))

            updated = [event("replacement", "NVDA", "2026-07-23T14:00:00Z")]
            write_event_report(paths.events_path, events=updated)
            refreshed = service.snapshot("NVDA", observed_at=at("2026-07-23T15:00:02Z"))
            self.assertEqual(1, refreshed["symbolEventCount"])
            self.assertEqual("replacement", refreshed["events"][0]["eventId"])

    def test_blank_symbol_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = WorkstationTechnicalResearchService(make_paths(Path(directory)))
            with self.assertRaises(ValueError):
                service.snapshot(" ")


def make_paths(root: Path) -> TechnicalResearchPaths:
    return TechnicalResearchPaths(
        events_path=root / "technical-breakout-events-latest.json",
        study_path=root / "technical-breakout-study-latest.json",
    )


def write_reports(paths: TechnicalResearchPaths, *, generated_at: str = "2026-07-23T14:30:00Z") -> None:
    write_event_report(paths.events_path, generated_at=generated_at)
    write_study_report(paths.study_path, generated_at=generated_at)


def write_event_report(
    path: Path,
    *,
    generated_at: str = "2026-07-23T14:30:00Z",
    events: list[dict] | None = None,
) -> None:
    if events is None:
        events = [
            event("old", "NVDA", "2026-07-21", status="Insufficient data"),
            event("other", "AMD", "2026-07-22"),
            event("new", "NVDA", "2026-07-23T14:00:00Z"),
        ]
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine_version": "technical_breakout_research_engine_v1",
                "generated_at": generated_at,
                "research_only": True,
                "events": events,
                "warnings": ["Stored report warning."],
            }
        ),
        encoding="utf-8",
    )


def write_study_report(
    path: Path,
    *,
    generated_at: str = "2026-07-23T14:30:00Z",
    studies: list[dict] | None = None,
) -> None:
    if studies is None:
        studies = [
            study("new", "NVDA", "2026-07-23T14:00:00Z"),
            study("other", "AMD", "2026-07-22T14:00:00Z"),
        ]
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine_version": "technical_breakout_research_engine_v1",
                "generated_at": generated_at,
                "research_only": True,
                "studies": studies,
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )


def event(
    event_id: str,
    symbol: str,
    timestamp: str,
    *,
    status: str = "Breakout present",
) -> dict:
    return {
        "event_id": event_id,
        "symbol": symbol,
        "event_timestamp": timestamp,
        "event_type": "donchian_20_day_breakout",
        "timeframe": "daily",
        "status": status,
        "quality_flag": "HIGH",
        "data_sufficiency": "Sufficient" if status == "Breakout present" else "Insufficient",
        "trigger_price": 125.5,
        "distance_above_trigger_pct": 1.25,
        "relative_volume": 2.25,
        "volume_confirmed": True,
        "relative_strength_confirmed": False,
        "notes": ["Stored event note."],
    }


def study(event_id: str, symbol: str, timestamp: str) -> dict:
    return {
        "event_id": event_id,
        "symbol": symbol,
        "event_timestamp": timestamp,
        "event_type": "donchian_20_day_breakout",
        "timeframe": "daily",
        "status": "Breakout failed",
        "data_sufficiency": "Sufficient",
        "forward_returns_pct": {"1d": 1.0, "5d": 4.5, "10d": -1.0},
        "max_favorable_excursion_pct": 6.0,
        "max_adverse_excursion_pct": -2.0,
        "held_above_breakout_level": False,
        "failed_back_below_breakout_level": True,
        "became_extended": False,
        "volume_confirmed": True,
        "notes": [],
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
