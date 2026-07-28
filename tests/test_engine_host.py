from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from momentum_hunter.engine_host import (
    COMMAND_CANDIDATE_STORY_SNAPSHOT,
    COMMAND_CHART_SNAPSHOT,
    COMMAND_DAILY_WORKFLOW_SNAPSHOT,
    COMMAND_PAUSE,
    COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT,
    COMMAND_RESEARCH_MATURITY_SNAPSHOT,
    COMMAND_RESUME,
    COMMAND_RUN_CYCLE,
    COMMAND_SAVED_WATCHLIST_SNAPSHOT,
    COMMAND_SHUTDOWN,
    COMMAND_SNAPSHOT,
    COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
    COMMAND_TECHNICAL_RESEARCH_SNAPSHOT,
    ENDPOINT_FILENAME,
    HOST_LOCK_FILENAME,
    PROTOCOL_VERSION,
    EngineHostRuntime,
    EngineHostServer,
    HostLease,
    read_json,
)
from momentum_hunter.providers import ProviderUnavailableError


def staged_preview(symbol: str, interval: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "symbol": symbol,
        "interval": interval,
        "state": "AVAILABLE",
        "observedAt": "2026-07-28T15:02:00Z",
        "asOf": "2026-07-28T15:01:00Z",
        "summary": (
            "STAGED PREVIEW ONLY | AVAILABLE | 2 verified candles; "
            "inactive; no active chart source changed"
        ),
        "previewOnly": True,
        "activeChartSource": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "lineage": {
            "sourceLabel": "Schwab Trader API price history (inactive staging)",
            "asOf": "2026-07-28T15:01:00Z",
            "summary": "Hash-verified inactive staged evidence.",
        },
        "candles": [
            staged_candle("2026-07-28T15:00:00Z", close=101.0),
            staged_candle("2026-07-28T15:01:00Z", close=102.0),
        ],
    }


def staged_candle(timestamp: str, *, close: float) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "open": 100.0,
        "high": max(102.5, close),
        "low": 99.0,
        "close": close,
        "volume": 1000,
    }


class EngineHostRuntimeTests(unittest.TestCase):
    def test_host_lease_allows_one_owner_and_releases_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / HOST_LOCK_FILENAME
            first = HostLease(lock_path, "first-host")
            second = HostLease(lock_path, "second-host")

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()
            self.assertFalse(lock_path.exists())

    def test_duplicate_command_id_runs_a_collection_cycle_only_once(self) -> None:
        runs: list[str] = []
        runtime = EngineHostRuntime(cycle_runner=lambda: runs.append("cycle") or SimpleNamespace(target_count=3))

        first = runtime.execute(COMMAND_RUN_CYCLE, "same-command")
        repeated = runtime.execute(COMMAND_RUN_CYCLE, "same-command")

        self.assertTrue(first.accepted)
        self.assertEqual(first, repeated)
        self.assertEqual(["cycle"], runs)
        self.assertEqual(1, first.snapshot["collection"]["cycleCount"])
        self.assertEqual(3, first.snapshot["collection"]["monitoredSymbolCount"])

    def test_production_collection_advances_shadow_observations_once_after_capture(self) -> None:
        calls: list[str] = []
        outcomes: list[tuple[str, dict[str, object]]] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: calls.append("capture") or SimpleNamespace(target_count=3),
            shadow_workspace_loader=lambda: {},
            shadow_starter=lambda _symbol, _command_id: {},
            shadow_auto_selector=lambda: calls.append("select") or {"status": "TRADE_STARTED"},
            shadow_observation_runner=lambda: calls.append("shadow") or {},
            shadow_cycle_attempt_recorder=(
                lambda: {"recorded": True, "cycleId": "attempt-1"}
            ),
            shadow_cycle_outcome_recorder=(
                lambda attempt_id, selection: outcomes.append(
                    (attempt_id, selection)
                )
                or {"recorded": True}
            ),
            advance_shadow_after_collection=True,
        )

        result = runtime.execute(COMMAND_RUN_CYCLE, "capture-and-shadow")

        self.assertTrue(result.accepted)
        self.assertEqual(["capture", "select", "shadow"], calls)
        self.assertEqual("attempt-1", outcomes[0][0])
        self.assertEqual("TRADE_STARTED", outcomes[0][1]["status"])
        self.assertEqual(
            "TRADE_STARTED",
            result.payload["shadowAutomaticSelection"]["status"],
        )

    def test_selection_failure_still_advances_existing_shadow_observations(
        self,
    ) -> None:
        calls: list[str] = []
        recorded_failures: list[str] = []

        def fail_selection() -> dict[str, object]:
            calls.append("select")
            raise ValueError("bad report")

        runtime = EngineHostRuntime(
            cycle_runner=(
                lambda: calls.append("capture")
                or SimpleNamespace(target_count=3)
            ),
            shadow_workspace_loader=lambda: {},
            shadow_starter=lambda _symbol, _command_id: {},
            shadow_auto_selector=fail_selection,
            shadow_observation_runner=(
                lambda: calls.append("shadow") or {"activeTradeCount": 1}
            ),
            shadow_cycle_failure_recorder=(
                lambda reason: recorded_failures.append(reason)
                or {"recorded": True}
            ),
            shadow_cycle_attempt_recorder=(
                lambda: {"recorded": True, "cycleId": "attempt-failure"}
            ),
            advance_shadow_after_collection=True,
        )

        result = runtime.execute(
            COMMAND_RUN_CYCLE,
            "capture-selection-failure",
        )

        self.assertFalse(result.accepted)
        self.assertEqual("COLLECTION_FAILED", result.code)
        self.assertIn("Automatic Shadow selection failed", result.summary)
        self.assertEqual(["capture", "select", "shadow"], calls)
        self.assertEqual([], recorded_failures)

    def test_observation_failure_closes_attempt_as_post_collection_failure(
        self,
    ) -> None:
        outcomes: list[tuple[str, dict[str, object]]] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: SimpleNamespace(target_count=1),
            shadow_workspace_loader=lambda: {},
            shadow_starter=lambda _symbol, _command_id: {},
            shadow_auto_selector=lambda: {"status": "NO_ELIGIBLE_CANDIDATE"},
            shadow_observation_runner=lambda: (_ for _ in ()).throw(
                RuntimeError("observation store unavailable")
            ),
            shadow_cycle_attempt_recorder=(
                lambda: {"recorded": True, "cycleId": "attempt-observation"}
            ),
            shadow_cycle_outcome_recorder=(
                lambda attempt_id, outcome: outcomes.append(
                    (attempt_id, outcome)
                )
                or {"recorded": True}
            ),
            advance_shadow_after_collection=True,
        )

        result = runtime.execute(COMMAND_RUN_CYCLE, "observation-failure")

        self.assertFalse(result.accepted)
        self.assertEqual("COLLECTION_FAILED", result.code)
        self.assertEqual("attempt-observation", outcomes[0][0])
        self.assertEqual("POST_COLLECTION_FAILED", outcomes[0][1]["status"])

    def test_pause_blocks_collection_until_resume(self) -> None:
        runs: list[str] = []
        runtime = EngineHostRuntime(cycle_runner=lambda: runs.append("cycle") or SimpleNamespace(target_count=1))

        paused = runtime.execute(COMMAND_PAUSE, "pause")
        blocked = runtime.execute(COMMAND_RUN_CYCLE, "blocked-cycle")
        resumed = runtime.execute(COMMAND_RESUME, "resume")
        completed = runtime.execute(COMMAND_RUN_CYCLE, "completed-cycle")

        self.assertTrue(paused.accepted)
        self.assertFalse(blocked.accepted)
        self.assertEqual("COLLECTION_PAUSED", blocked.code)
        self.assertTrue(resumed.accepted)
        self.assertTrue(completed.accepted)
        self.assertEqual(["cycle"], runs)

    def test_existing_legacy_monitor_runner_blocks_duplicate_collection_loop(self) -> None:
        runs: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: runs.append("cycle") or SimpleNamespace(target_count=1),
            external_monitor_running=lambda: True,
        )

        result = runtime.execute(COMMAND_RUN_CYCLE, "legacy-monitor-active")

        self.assertFalse(result.accepted)
        self.assertEqual("EXISTING_MONITOR_RUNNER_ACTIVE", result.code)
        self.assertEqual("Blocked", result.snapshot["collection"]["state"])
        self.assertEqual([], runs)

    def test_concurrent_cycle_request_does_not_start_a_second_loop(self) -> None:
        started = threading.Event()
        release = threading.Event()
        runs: list[str] = []

        def cycle_runner() -> SimpleNamespace:
            runs.append("cycle")
            started.set()
            self.assertTrue(release.wait(timeout=3))
            return SimpleNamespace(target_count=2)

        runtime = EngineHostRuntime(cycle_runner=cycle_runner)
        first_result: list[object] = []
        first = threading.Thread(target=lambda: first_result.append(runtime.execute(COMMAND_RUN_CYCLE, "first")))
        first.start()
        self.assertTrue(started.wait(timeout=3))
        overlapping = runtime.execute(COMMAND_RUN_CYCLE, "second")
        release.set()
        first.join(timeout=3)

        self.assertFalse(overlapping.accepted)
        self.assertEqual("COLLECTION_IN_PROGRESS", overlapping.code)
        self.assertEqual(["cycle"], runs)
        self.assertEqual(1, len(first_result))

    def test_collection_failure_is_visible_without_stopping_the_host(self) -> None:
        recorded_failures: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(
                RuntimeError("provider unavailable")
            ),
            shadow_cycle_failure_recorder=(
                lambda reason: recorded_failures.append(reason)
                or {"recorded": True}
            ),
            advance_shadow_after_collection=True,
        )

        failed = runtime.execute(COMMAND_RUN_CYCLE, "failing-cycle")
        snapshot = runtime.execute(COMMAND_SNAPSHOT, "snapshot")

        self.assertFalse(failed.accepted)
        self.assertEqual("COLLECTION_FAILED", failed.code)
        self.assertEqual("Blocked", failed.snapshot["health"]["state"])
        self.assertTrue(snapshot.accepted)
        self.assertEqual("Blocked", snapshot.snapshot["collection"]["state"])
        self.assertEqual(1, len(recorded_failures))
        self.assertIn("provider unavailable", recorded_failures[0])
        self.assertEqual(
            {"failureType": "RuntimeError", "retryable": False},
            failed.payload,
        )

    def test_recognized_provider_failure_is_marked_retryable(self) -> None:
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(
                ProviderUnavailableError(
                    "finviz",
                    "temporary provider outage",
                    "network",
                )
            ),
        )

        failed = runtime.execute(COMMAND_RUN_CYCLE, "provider-outage")

        self.assertFalse(failed.accepted)
        self.assertEqual("COLLECTION_FAILED", failed.code)
        self.assertEqual("ProviderUnavailableError", failed.payload["failureType"])
        self.assertIs(True, failed.payload["retryable"])

    def test_unexpected_command_failure_stays_structured(self) -> None:
        runtime = EngineHostRuntime(external_monitor_running=lambda: (_ for _ in ()).throw(RuntimeError("unexpected")))

        result = runtime.execute(COMMAND_RUN_CYCLE, "unexpected-command-failure")

        self.assertFalse(result.accepted)
        self.assertEqual("HOST_COMMAND_FAILED", result.code)

    def test_host_runtime_does_not_mutate_canonical_monitor_source(self) -> None:
        source = Path("momentum_hunter") / "active_monitor.py"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        runtime = EngineHostRuntime(cycle_runner=lambda: SimpleNamespace(target_count=1))

        result = runtime.execute(COMMAND_RUN_CYCLE, "source-integrity")

        self.assertTrue(result.accepted)
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_read_only_workspace_command_returns_injected_payload_without_starting_collection(self) -> None:
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(AssertionError("collection should not run")),
            workspace_snapshot_loader=lambda: {"schemaVersion": 1, "planningAvailable": False, "candidates": []},
        )

        result = runtime.execute(COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT, "read-only-snapshot")

        self.assertTrue(result.accepted)
        self.assertEqual("READ_ONLY_WORKSPACE_SNAPSHOT", result.code)
        self.assertEqual({"schemaVersion": 1, "planningAvailable": False, "candidates": []}, result.payload)
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])

    def test_chart_command_returns_injected_read_only_payload_without_starting_collection(self) -> None:
        calls: list[tuple[str, str]] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(AssertionError("collection should not run")),
            chart_snapshot_loader=lambda symbol, interval: calls.append((symbol, interval))
            or {"schemaVersion": 1, "symbol": symbol, "interval": interval, "state": "AVAILABLE", "candles": []},
        )

        result = runtime.execute(
            COMMAND_CHART_SNAPSHOT,
            "chart-snapshot",
            {"symbol": "AAA", "interval": "5m"},
        )
        repeated = runtime.execute(
            COMMAND_CHART_SNAPSHOT,
            "chart-snapshot",
            {"symbol": "AAA", "interval": "5m"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual("CHART_SNAPSHOT", result.code)
        self.assertEqual(result, repeated)
        self.assertEqual([("AAA", "5m")], calls)
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])

    def test_chart_command_rejects_missing_or_invalid_arguments(self) -> None:
        runtime = EngineHostRuntime(
            chart_snapshot_loader=lambda symbol, interval: (_ for _ in ()).throw(ValueError("unsupported interval"))
        )

        missing_symbol = runtime.execute(COMMAND_CHART_SNAPSHOT, "missing-symbol", {"interval": "5m"})
        missing_interval = runtime.execute(COMMAND_CHART_SNAPSHOT, "missing-interval", {"symbol": "AAA"})
        invalid = runtime.execute(COMMAND_CHART_SNAPSHOT, "invalid", {"symbol": "AAA", "interval": "60m"})

        self.assertFalse(missing_symbol.accepted)
        self.assertEqual("CHART_SYMBOL_REQUIRED", missing_symbol.code)
        self.assertFalse(missing_interval.accepted)
        self.assertEqual("CHART_INTERVAL_REQUIRED", missing_interval.code)
        self.assertFalse(invalid.accepted)
        self.assertEqual("INVALID_CHART_REQUEST", invalid.code)

    def test_staged_chart_preview_is_read_only_idempotent_and_inactive(self) -> None:
        calls: list[tuple[str, str]] = []

        def load_preview(symbol: str, interval: str) -> dict[str, object]:
            calls.append((symbol, interval))
            return staged_preview(symbol, interval)

        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(
                AssertionError("collection should not run")
            ),
            staged_chart_preview_loader=load_preview,
        )

        result = runtime.execute(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            "staged-chart-preview",
            {"symbol": "nvda", "interval": "5m"},
        )
        repeated = runtime.execute(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            "staged-chart-preview",
            {"symbol": "nvda", "interval": "5m"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual("STAGED_SCHWAB_CHART_PREVIEW", result.code)
        self.assertEqual(result, repeated)
        self.assertEqual([("NVDA", "5m")], calls)
        self.assertTrue(result.payload["previewOnly"])
        self.assertFalse(result.payload["activeChartSource"])
        self.assertFalse(result.payload["transmitting"])
        self.assertEqual("UNAVAILABLE", result.payload["orderTransmission"])
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])

    def test_staged_chart_preview_rejects_bad_request_and_unsafe_payload(self) -> None:
        runtime = EngineHostRuntime(
            staged_chart_preview_loader=lambda symbol, interval: {
                **staged_preview(symbol, interval),
                "activeChartSource": True,
            }
        )

        missing_symbol = runtime.execute(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            "staged-missing-symbol",
            {"interval": "5m"},
        )
        missing_interval = runtime.execute(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            "staged-missing-interval",
            {"symbol": "NVDA"},
        )
        invalid_interval = runtime.execute(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            "staged-invalid-interval",
            {"symbol": "NVDA", "interval": "60m"},
        )
        unsafe = runtime.execute(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            "staged-unsafe",
            {"symbol": "NVDA", "interval": "5m"},
        )

        self.assertFalse(missing_symbol.accepted)
        self.assertEqual("STAGED_CHART_SYMBOL_REQUIRED", missing_symbol.code)
        self.assertFalse(missing_interval.accepted)
        self.assertEqual(
            "STAGED_CHART_INTERVAL_REQUIRED",
            missing_interval.code,
        )
        self.assertFalse(invalid_interval.accepted)
        self.assertEqual(
            "INVALID_STAGED_CHART_REQUEST",
            invalid_interval.code,
        )
        self.assertFalse(unsafe.accepted)
        self.assertEqual("UNSAFE_STAGED_CHART_PREVIEW", unsafe.code)

    def test_staged_chart_preview_accepts_insufficient_data_display_label(self) -> None:
        payload = staged_preview("NVDA", "Daily")
        payload.update(
            {
                "state": "INSUFFICIENT_DATA",
                "asOf": "2026-07-28T15:00:00Z",
                "summary": (
                    "STAGED PREVIEW ONLY | INSUFFICIENT DATA | "
                    "1 verified Daily candle; inactive"
                ),
                "lineage": {
                    **payload["lineage"],
                    "asOf": "2026-07-28T15:00:00Z",
                },
                "candles": [payload["candles"][0]],
            }
        )
        runtime = EngineHostRuntime(
            staged_chart_preview_loader=lambda _symbol, _interval: payload
        )

        result = runtime.execute(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            "staged-insufficient",
            {"symbol": "NVDA", "interval": "Daily"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual("INSUFFICIENT_DATA", result.payload["state"])
        self.assertEqual(1, len(result.payload["candles"]))

    def test_staged_chart_preview_rejects_malformed_or_expanded_wire_payload(self) -> None:
        base = staged_preview("NVDA", "5m")
        unsafe_payloads = (
            {**base, "accountNumber": "must-not-cross-boundary"},
            {
                **base,
                "lineage": {
                    **base["lineage"],
                    "providerToken": "must-not-cross-boundary",
                },
            },
            {
                **base,
                "candles": [
                    *base["candles"],
                    staged_candle("2026-07-28T15:01:00Z", close=103.0),
                ],
            },
            {
                **base,
                "candles": [
                    {
                        **base["candles"][0],
                        "low": 103.0,
                    },
                    base["candles"][1],
                ],
            },
            {
                **base,
                "state": "UNAVAILABLE",
            },
            {
                **base,
                "state": [],
            },
            {
                **base,
                "summary": (
                    "STAGED PREVIEW ONLY | STALE | "
                    "mismatched state label"
                ),
            },
            {
                **base,
                "observedAt": "timezone-missing",
            },
            {
                **base,
                "summary": "x" * 2049,
            },
        )
        for index, payload in enumerate(unsafe_payloads):
            with self.subTest(index=index):
                runtime = EngineHostRuntime(
                    staged_chart_preview_loader=(
                        lambda _symbol, _interval, value=payload: value
                    )
                )
                result = runtime.execute(
                    COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
                    f"staged-malformed-{index}",
                    {"symbol": "NVDA", "interval": "5m"},
                )
                self.assertFalse(result.accepted)
                self.assertEqual("UNSAFE_STAGED_CHART_PREVIEW", result.code)

    def test_staged_chart_preview_sanitizes_unavailable_evidence_failure(self) -> None:
        from momentum_hunter.staged_schwab_charts import (
            StagedSchwabChartError,
        )

        runtime = EngineHostRuntime(
            staged_chart_preview_loader=lambda _symbol, _interval: (
                _ for _ in ()
            ).throw(
                StagedSchwabChartError(
                    r"C:\sensitive\staged-path.json failed verification"
                )
            )
        )

        result = runtime.execute(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            "staged-unavailable",
            {"symbol": "NVDA", "interval": "Daily"},
        )

        self.assertFalse(result.accepted)
        self.assertEqual("STAGED_CHART_PREVIEW_UNAVAILABLE", result.code)
        self.assertNotIn("sensitive", result.summary)
        self.assertNotIn("staged-path", result.summary)

    def test_default_staged_preview_loader_uses_only_inactive_stage_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged_path = root / "staging" / "candles.json"
            expected = staged_preview("NVDA", "15m")
            with (
                patch(
                    "momentum_hunter.schwab_candle_staging."
                    "DEFAULT_STAGED_CANDLES_PATH",
                    staged_path,
                ),
                patch(
                    "momentum_hunter.staged_schwab_charts."
                    "StagedSchwabChartService"
                ) as service_type,
            ):
                service_type.return_value.snapshot.return_value = expected

                payload = EngineHostRuntime._load_staged_schwab_chart_preview(
                    "NVDA",
                    "15m",
                )

            self.assertEqual(expected, payload)
            paths = service_type.call_args.kwargs["paths"]
            self.assertEqual(staged_path, paths.candles_path)
            self.assertEqual(
                staged_path.with_name("candles.manifest.json"),
                paths.manifest_path,
            )
            service_type.return_value.snapshot.assert_called_once_with(
                "NVDA",
                "15m",
            )
            self.assertEqual([], list(root.rglob("*")))

    def test_technical_research_command_is_read_only_idempotent_and_requires_symbol(self) -> None:
        calls: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(AssertionError("collection should not run")),
            technical_research_snapshot_loader=lambda symbol: calls.append(symbol)
            or {"schemaVersion": 1, "symbol": symbol, "state": "AVAILABLE", "events": [], "studies": []},
        )

        missing = runtime.execute(COMMAND_TECHNICAL_RESEARCH_SNAPSHOT, "missing", {})
        result = runtime.execute(
            COMMAND_TECHNICAL_RESEARCH_SNAPSHOT,
            "research",
            {"symbol": "nvda"},
        )
        repeated = runtime.execute(
            COMMAND_TECHNICAL_RESEARCH_SNAPSHOT,
            "research",
            {"symbol": "nvda"},
        )

        self.assertFalse(missing.accepted)
        self.assertEqual("TECHNICAL_RESEARCH_SYMBOL_REQUIRED", missing.code)
        self.assertTrue(result.accepted)
        self.assertEqual(result, repeated)
        self.assertEqual(["NVDA"], calls)
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])

    def test_saved_watchlist_command_returns_injected_payload_without_starting_collection(self) -> None:
        calls: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(AssertionError("collection should not run")),
            saved_watchlist_snapshot_loader=lambda: calls.append("read")
            or {
                "schemaVersion": 1,
                "state": "STALE",
                "sourceLabel": "watchlist-2026-06-18.json",
                "items": [],
            },
        )

        result = runtime.execute(COMMAND_SAVED_WATCHLIST_SNAPSHOT, "saved-watchlist")
        repeated = runtime.execute(COMMAND_SAVED_WATCHLIST_SNAPSHOT, "saved-watchlist")

        self.assertTrue(result.accepted)
        self.assertEqual("SAVED_WATCHLIST_SNAPSHOT", result.code)
        self.assertEqual("STALE", result.payload["state"])
        self.assertEqual(result, repeated)
        self.assertEqual(["read"], calls)
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])

    def test_research_maturity_command_returns_injected_read_only_payload_without_collection(self) -> None:
        payload = {
            "schemaVersion": 1,
            "state": "STALE",
            "researchOnly": True,
            "readOnly": True,
            "strategyChangeRecommendationsAllowed": False,
        }
        calls: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(
                AssertionError("collection should not run")
            ),
            research_maturity_loader=lambda: calls.append("read") or payload,
        )

        result = runtime.execute(
            COMMAND_RESEARCH_MATURITY_SNAPSHOT,
            "research-maturity",
        )
        repeated = runtime.execute(
            COMMAND_RESEARCH_MATURITY_SNAPSHOT,
            "research-maturity",
        )
        invalid = runtime.execute(
            COMMAND_RESEARCH_MATURITY_SNAPSHOT,
            "research-maturity-invalid",
            {"refresh": "true"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual("RESEARCH_MATURITY_SNAPSHOT", result.code)
        self.assertEqual(payload, result.payload)
        self.assertEqual(result, repeated)
        self.assertEqual(["read"], calls)
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])
        self.assertFalse(invalid.accepted)
        self.assertEqual("INVALID_RESEARCH_MATURITY_REQUEST", invalid.code)

    def test_daily_workflow_snapshot_is_read_only_argument_free_and_idempotent(self) -> None:
        cycle_runs: list[str] = []
        loads: list[str] = []
        payload = {"schemaVersion": 1, "state": "AVAILABLE", "readOnly": True}
        runtime = EngineHostRuntime(
            cycle_runner=lambda: cycle_runs.append("cycle") or SimpleNamespace(target_count=1),
            daily_workflow_snapshot_loader=lambda: loads.append("load") or payload,
        )

        first = runtime.execute(COMMAND_DAILY_WORKFLOW_SNAPSHOT, "daily-workflow")
        repeated = runtime.execute(COMMAND_DAILY_WORKFLOW_SNAPSHOT, "daily-workflow")
        invalid = runtime.execute(COMMAND_DAILY_WORKFLOW_SNAPSHOT, "daily-workflow-invalid", {"refresh": "true"})

        self.assertTrue(first.accepted)
        self.assertEqual("DAILY_WORKFLOW_SNAPSHOT", first.code)
        self.assertEqual(payload, first.payload)
        self.assertEqual(first, repeated)
        self.assertEqual(["load"], loads)
        self.assertEqual([], cycle_runs)
        self.assertFalse(invalid.accepted)
        self.assertEqual("INVALID_DAILY_WORKFLOW_REQUEST", invalid.code)

    def test_candidate_story_command_is_read_only_idempotent_and_argument_scoped(self) -> None:
        calls: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(AssertionError("collection should not run")),
            candidate_story_loader=lambda symbol: calls.append(symbol)
            or {
                "schemaVersion": 1,
                "symbol": symbol,
                "state": "EMPTY",
                "points": [],
                "readOnly": True,
            },
        )

        result = runtime.execute(
            COMMAND_CANDIDATE_STORY_SNAPSHOT,
            "candidate-story",
            {"symbol": "COO"},
        )
        repeated = runtime.execute(
            COMMAND_CANDIDATE_STORY_SNAPSHOT,
            "candidate-story",
            {"symbol": "COO"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual("CANDIDATE_STORY_SNAPSHOT", result.code)
        self.assertEqual(result, repeated)
        self.assertEqual(["COO"], calls)
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])
        self.assertTrue(result.payload["readOnly"])

    def test_candidate_story_command_rejects_missing_or_invalid_symbol(self) -> None:
        runtime = EngineHostRuntime(
            candidate_story_loader=lambda symbol: (_ for _ in ()).throw(ValueError("invalid symbol"))
        )

        missing = runtime.execute(COMMAND_CANDIDATE_STORY_SNAPSHOT, "missing-story-symbol", {})
        invalid = runtime.execute(
            COMMAND_CANDIDATE_STORY_SNAPSHOT,
            "invalid-story-symbol",
            {"symbol": "../COO"},
        )

        self.assertFalse(missing.accepted)
        self.assertEqual("CANDIDATE_STORY_SYMBOL_REQUIRED", missing.code)
        self.assertFalse(invalid.accepted)
        self.assertEqual("INVALID_CANDIDATE_STORY_REQUEST", invalid.code)

class EngineHostProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = EngineHostRuntime(cycle_runner=lambda: SimpleNamespace(target_count=4))
        self.token = "test-token"
        self.server = EngineHostServer(self.runtime, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_protocol_rejects_bad_token_and_bad_version(self) -> None:
        bad_token = self.send(command=COMMAND_SNAPSHOT, command_id="bad-token", token="wrong")
        bad_version = self.send(command=COMMAND_SNAPSHOT, command_id="bad-version", version="9.9")

        self.assertFalse(bad_token["accepted"])
        self.assertEqual("UNAUTHENTICATED", bad_token["error"]["code"])
        self.assertFalse(bad_version["accepted"])
        self.assertEqual("PROTOCOL_VERSION_MISMATCH", bad_version["error"]["code"])

    def test_protocol_returns_versioned_snapshot_and_no_execution_capability(self) -> None:
        response = self.send(command=COMMAND_SNAPSHOT, command_id="snapshot")
        snapshot = response["result"]["snapshot"]

        self.assertTrue(response["accepted"])
        self.assertEqual(PROTOCOL_VERSION, response["protocolVersion"])
        self.assertEqual("loopback-tcp", snapshot["identity"]["transport"])
        self.assertIn(COMMAND_RUN_CYCLE, snapshot["capabilities"])
        self.assertIn(COMMAND_CHART_SNAPSHOT, snapshot["capabilities"])
        self.assertIn(
            COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            snapshot["capabilities"],
        )
        self.assertIn(COMMAND_TECHNICAL_RESEARCH_SNAPSHOT, snapshot["capabilities"])
        self.assertIn(COMMAND_SAVED_WATCHLIST_SNAPSHOT, snapshot["capabilities"])
        self.assertIn(COMMAND_DAILY_WORKFLOW_SNAPSHOT, snapshot["capabilities"])
        self.assertIn(COMMAND_CANDIDATE_STORY_SNAPSHOT, snapshot["capabilities"])
        self.assertIn(COMMAND_RESEARCH_MATURITY_SNAPSHOT, snapshot["capabilities"])
        self.assertNotIn("submit_order", snapshot["capabilities"])
        self.assertNotIn("paper_order", snapshot["capabilities"])
        self.assertNotIn("live_order", snapshot["capabilities"])

    def test_protocol_returns_read_only_workspace_payload(self) -> None:
        self.runtime._workspace_snapshot_loader = lambda: {"schemaVersion": 1, "planningAvailable": False, "candidates": []}

        response = self.send(command=COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT, command_id="read-only-workspace")

        self.assertTrue(response["accepted"])
        self.assertEqual("READ_ONLY_WORKSPACE_SNAPSHOT", response["result"]["code"])
        self.assertEqual([], response["result"]["payload"]["candidates"])
        self.assertFalse(response["result"]["payload"]["planningAvailable"])

    def test_protocol_returns_chart_payload_with_arguments(self) -> None:
        self.runtime._chart_snapshot_loader = lambda symbol, interval: {
            "schemaVersion": 1,
            "symbol": symbol,
            "interval": interval,
            "state": "AVAILABLE",
            "candles": [],
        }

        response = self.send(
            command=COMMAND_CHART_SNAPSHOT,
            command_id="chart",
            arguments={"symbol": "AAA", "interval": "Daily"},
        )

        self.assertTrue(response["accepted"])
        self.assertEqual("CHART_SNAPSHOT", response["result"]["code"])
        self.assertEqual("AAA", response["result"]["payload"]["symbol"])
        self.assertEqual("Daily", response["result"]["payload"]["interval"])

    def test_protocol_returns_inactive_staged_chart_preview(self) -> None:
        self.runtime._staged_chart_preview_loader = staged_preview

        response = self.send(
            command=COMMAND_STAGED_SCHWAB_CHART_PREVIEW,
            command_id="staged-chart-preview",
            arguments={"symbol": "nvda", "interval": "15m"},
        )

        self.assertTrue(response["accepted"])
        self.assertEqual(
            "STAGED_SCHWAB_CHART_PREVIEW",
            response["result"]["code"],
        )
        payload = response["result"]["payload"]
        self.assertEqual("NVDA", payload["symbol"])
        self.assertEqual("15m", payload["interval"])
        self.assertTrue(payload["previewOnly"])
        self.assertFalse(payload["activeChartSource"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def test_protocol_returns_technical_research_payload_with_symbol(self) -> None:
        self.runtime._technical_research_snapshot_loader = lambda symbol: {
            "schemaVersion": 1,
            "symbol": symbol,
            "state": "AVAILABLE",
            "events": [],
            "studies": [],
        }

        response = self.send(
            command=COMMAND_TECHNICAL_RESEARCH_SNAPSHOT,
            command_id="technical-research",
            arguments={"symbol": "nvda"},
        )

        self.assertTrue(response["accepted"])
        self.assertEqual("TECHNICAL_RESEARCH_SNAPSHOT", response["result"]["code"])
        self.assertEqual("NVDA", response["result"]["payload"]["symbol"])

    def test_protocol_returns_saved_watchlist_payload_without_arguments(self) -> None:
        self.runtime._saved_watchlist_snapshot_loader = lambda: {
            "schemaVersion": 1,
            "state": "EMPTY",
            "sourceLabel": "No saved watchlist file",
            "items": [],
        }

        response = self.send(
            command=COMMAND_SAVED_WATCHLIST_SNAPSHOT,
            command_id="saved-watchlist",
        )

        self.assertTrue(response["accepted"])
        self.assertEqual("SAVED_WATCHLIST_SNAPSHOT", response["result"]["code"])
        self.assertEqual("EMPTY", response["result"]["payload"]["state"])
        self.assertEqual([], response["result"]["payload"]["items"])

    def test_protocol_returns_candidate_story_payload_with_symbol(self) -> None:
        self.runtime._candidate_story_loader = lambda symbol: {
            "schemaVersion": 1,
            "symbol": symbol,
            "state": "EMPTY",
            "points": [],
            "readOnly": True,
        }

        response = self.send(
            command=COMMAND_CANDIDATE_STORY_SNAPSHOT,
            command_id="candidate-story",
            arguments={"symbol": "COO"},
        )

        self.assertTrue(response["accepted"])
        self.assertEqual("CANDIDATE_STORY_SNAPSHOT", response["result"]["code"])
        self.assertEqual("COO", response["result"]["payload"]["symbol"])
        self.assertTrue(response["result"]["payload"]["readOnly"])

    def test_shutdown_command_stops_server_after_a_response(self) -> None:
        response = self.send(command=COMMAND_SHUTDOWN, command_id="shutdown")

        self.assertTrue(response["accepted"])
        self.assertEqual("SHUTDOWN_REQUESTED", response["result"]["code"])
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())

    def send(
        self,
        *,
        command: str,
        command_id: str,
        token: str | None = None,
        version: str = PROTOCOL_VERSION,
        arguments: dict[str, str] | None = None,
    ) -> dict:
        address, port = self.server.server_address
        payload = {
            "protocolVersion": version,
            "requestId": f"request-{command_id}",
            "accessToken": self.token if token is None else token,
            "command": command,
            "commandId": command_id,
            "arguments": arguments or {},
        }
        with socket.create_connection((address, port), timeout=3) as connection:
            connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            raw = connection.makefile("rb").readline()
        return json.loads(raw.decode("utf-8"))


class EngineHostProcessProofTests(unittest.TestCase):
    def test_separate_client_exit_does_not_stop_host_and_shutdown_cleans_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_directory = Path(directory)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "momentum_hunter.engine_host",
                    "--state-directory",
                    str(state_directory),
                    "--collection-interval-seconds",
                    "3600",
                ],
                cwd=Path.cwd(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                descriptor_path = state_directory / ENDPOINT_FILENAME
                descriptor = wait_for_descriptor(descriptor_path, process)
                first_host_id = descriptor["hostInstanceId"]

                client_code = """
import json, socket, sys
from pathlib import Path
descriptor = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
payload = {'protocolVersion': '1.0', 'requestId': 'separate-client', 'accessToken': descriptor['accessToken'], 'command': 'get_host_snapshot', 'commandId': 'separate-client-snapshot'}
with socket.create_connection((descriptor['address'], descriptor['port']), timeout=3) as connection:
    connection.sendall((json.dumps(payload) + '\\n').encode('utf-8'))
    response = json.loads(connection.makefile('rb').readline().decode('utf-8'))
assert response['accepted']
"""
                completed_client = subprocess.run(
                    [sys.executable, "-c", client_code, str(descriptor_path)],
                    cwd=Path.cwd(),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(0, completed_client.returncode, completed_client.stderr)
                self.assertIsNone(process.poll())

                snapshot = send_process_request(descriptor, COMMAND_SNAPSHOT, "reconnect-snapshot")
                self.assertTrue(snapshot["accepted"])
                self.assertEqual(first_host_id, snapshot["result"]["snapshot"]["identity"]["hostInstanceId"])

                shutdown = send_process_request(descriptor, COMMAND_SHUTDOWN, "deliberate-shutdown")
                self.assertTrue(shutdown["accepted"])
                self.assertEqual(0, process.wait(timeout=10))
                self.assertFalse(descriptor_path.exists())
                self.assertFalse((state_directory / HOST_LOCK_FILENAME).exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                if process.stderr is not None:
                    process.stderr.close()


def wait_for_descriptor(path: Path, process: subprocess.Popen[str]) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        descriptor = read_json(path)
        if descriptor:
            return descriptor
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            raise AssertionError(f"Python Engine Host exited before publishing an endpoint: {stderr}")
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for the Python Engine Host endpoint descriptor.")


def send_process_request(descriptor: dict, command: str, command_id: str) -> dict:
    payload = {
        "protocolVersion": PROTOCOL_VERSION,
        "requestId": command_id,
        "accessToken": descriptor["accessToken"],
        "command": command,
        "commandId": command_id,
    }
    with socket.create_connection((descriptor["address"], descriptor["port"]), timeout=3) as connection:
        connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        raw = connection.makefile("rb").readline()
    return json.loads(raw.decode("utf-8"))
