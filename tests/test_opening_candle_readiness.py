from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from momentum_hunter.canonical_candle_evidence import CanonicalMinuteBar
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE, EXECUTION_INELIGIBLE
from momentum_hunter.opening_candle_readiness import (
    OPENING_CANDLE_BACKFILL_FAILED,
    OPENING_CANDLE_READY,
    OPENING_CANDLE_TIMEOUT,
    OpeningCandleReadinessCoordinator,
    failed_opening_candle_readiness,
    inspect_opening_candle_store,
)
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabMinuteCandle,
)
from momentum_hunter.schwab_candle_observer import (
    SchwabCandleObserverHttpForbiddenError,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.time_normalized_rvol import TimeNormalizedRvolEvidence


AS_OF = datetime(2026, 8, 13, 9, 35, 1, tzinfo=EASTERN_TZ)


class OpeningCandleReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_inspector_accepts_five_opening_bars_and_five_baselines(self) -> None:
        self._append_sessions(
            (date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10),
             date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13))
        )

        bars, rvol, evidence, findings = inspect_opening_candle_store(
            ("AAA",),
            evidence_as_of=AS_OF,
            minute_store_root=self.root,
        )

        self.assertEqual(30, len(bars["AAA"]))
        self.assertEqual(EXECUTION_ELIGIBLE, rvol["AAA"].status)
        self.assertEqual(OPENING_CANDLE_READY, evidence["AAA"]["status"])
        self.assertEqual(5, evidence["AAA"]["openingBarCount"])
        self.assertEqual(5, evidence["AAA"]["baselineSessionCount"])
        self.assertEqual(("AAA:TIME_NORMALIZED_RVOL_AVAILABLE",), findings)

    def test_inspector_exposes_missing_current_bar_and_baseline(self) -> None:
        self._append_sessions((date(2026, 8, 11), date(2026, 8, 12)))
        self._append_sessions((date(2026, 8, 13),), count=4)

        _bars, rvol, evidence, findings = inspect_opening_candle_store(
            ("AAA",),
            evidence_as_of=AS_OF,
            minute_store_root=self.root,
        )

        self.assertEqual(EXECUTION_INELIGIBLE, rvol["AAA"].status)
        self.assertEqual("WAITING", evidence["AAA"]["status"])
        self.assertIn("MISSING_CURRENT_SESSION_BARS", evidence["AAA"]["findings"])
        self.assertIn(
            "INSUFFICIENT_COMPARABLE_BASELINE_SESSIONS",
            evidence["AAA"]["findings"],
        )
        self.assertIn("AAA:OPENING_RANGE_FIVE_COMPLETED_BARS_REQUIRED", findings)

    def test_empty_cache_is_waiting_and_execution_ineligible(self) -> None:
        bars, rvol, evidence, findings = inspect_opening_candle_store(
            ("AAA",),
            evidence_as_of=AS_OF,
            minute_store_root=self.root,
        )

        self.assertEqual((), bars["AAA"])
        self.assertFalse(rvol["AAA"].execution_eligible)
        self.assertEqual("WAITING", evidence["AAA"]["status"])
        self.assertIn("AAA:OPENING_RANGE_FIVE_COMPLETED_BARS_REQUIRED", findings)

    def test_wrong_symbol_and_stale_session_cannot_satisfy_current_readiness(self) -> None:
        self._append_sessions(
            (date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10),
             date(2026, 8, 11), date(2026, 8, 12))
        )
        self._append_sessions((date(2026, 8, 13),), symbol="BBB")

        bars, rvol, evidence, _findings = inspect_opening_candle_store(
            ("AAA",),
            evidence_as_of=AS_OF,
            minute_store_root=self.root,
        )

        self.assertTrue(all(bar.symbol == "AAA" for bar in bars["AAA"]))
        self.assertFalse(rvol["AAA"].execution_eligible)
        self.assertEqual(0, evidence["AAA"]["openingBarCount"])
        self.assertEqual("WAITING", evidence["AAA"]["status"])

    def test_inspector_rejects_tampered_partition(self) -> None:
        self._append_sessions((date(2026, 8, 13),))
        SchwabCandleStore(self.root).partition_path("AAA", "2026-08-13").write_text(
            "{}", encoding="utf-8"
        )

        bars, rvol, evidence, findings = inspect_opening_candle_store(
            ("AAA",),
            evidence_as_of=AS_OF,
            minute_store_root=self.root,
        )

        self.assertEqual({}, bars)
        self.assertEqual({}, rvol)
        self.assertEqual("INVALID", evidence["AAA"]["status"])
        self.assertEqual(("CANONICAL_CANDLE_EVIDENCE_INVALID",), findings)

    def test_coordinator_waits_then_accepts_ready_snapshot(self) -> None:
        calls = {"backfill": 0, "inspect": 0}

        def backfill():
            calls["backfill"] += 1
            return {
                "status": "COMPLETE",
                "resultFingerprint": str(calls["backfill"]) * 64,
                "findings": [],
            }

        def inspect(_symbols, _as_of):
            calls["inspect"] += 1
            ready = calls["inspect"] >= 3
            return snapshot(ready=ready)

        coordinator = OpeningCandleReadinessCoordinator(
            run_backfill=backfill,
            inspect_store=inspect,
            sleep=lambda _seconds: None,
        )

        result = coordinator.prepare(("AAA",), evidence_as_of=AS_OF)

        self.assertTrue(result.ready)
        self.assertEqual(OPENING_CANDLE_READY, result.status)
        self.assertEqual(2, calls["backfill"])
        self.assertEqual(2, len(result.attempts))

    def test_coordinator_times_out_without_fabricating_readiness(self) -> None:
        delays: list[float] = []
        coordinator = OpeningCandleReadinessCoordinator(
            run_backfill=lambda: {"status": "PARTIAL", "findings": []},
            inspect_store=lambda _symbols, _as_of: snapshot(ready=False),
            sleep=delays.append,
        )

        result = coordinator.prepare(("AAA",), evidence_as_of=AS_OF)

        self.assertFalse(result.ready)
        self.assertEqual(OPENING_CANDLE_TIMEOUT, result.status)
        self.assertEqual(3, len(result.attempts))
        self.assertEqual([10.0, 25.0], delays)
        self.assertIn(OPENING_CANDLE_TIMEOUT, result.findings)

    def test_coordinator_classifies_repeated_provider_failure(self) -> None:
        def failed():
            raise ConnectionError("synthetic provider failure")

        coordinator = OpeningCandleReadinessCoordinator(
            run_backfill=failed,
            inspect_store=lambda _symbols, _as_of: snapshot(ready=False),
            sleep=lambda _seconds: None,
        )

        result = coordinator.prepare(("AAA",), evidence_as_of=AS_OF)

        self.assertEqual(OPENING_CANDLE_BACKFILL_FAILED, result.status)
        self.assertEqual(3, len(result.attempts))
        self.assertTrue(
            all(item["error"] == "ConnectionError" for item in result.attempts)
        )

    def test_coordinator_preserves_sanitized_underlying_auth_classification(self) -> None:
        def failed():
            raise SchwabCandleObserverHttpForbiddenError("synthetic secret sentinel")

        result = OpeningCandleReadinessCoordinator(
            run_backfill=failed,
            inspect_store=lambda _symbols, _as_of: snapshot(ready=False),
            sleep=lambda _seconds: None,
        ).prepare(("AAA",), evidence_as_of=AS_OF)

        self.assertEqual(OPENING_CANDLE_BACKFILL_FAILED, result.status)
        self.assertTrue(
            all(
                attempt["failureClassification"] == "SCHWAB_HTTP_FORBIDDEN"
                and attempt["httpStatus"] == 403
                and not attempt["errorMessageIncluded"]
                for attempt in result.attempts
            )
        )
        self.assertNotIn("synthetic secret sentinel", str(result.to_evidence()))

    def test_setup_failure_creates_explicit_ineligible_rvol_for_every_symbol(self) -> None:
        result = failed_opening_candle_readiness(
            ("AAA", "BBB"),
            evidence_as_of=AS_OF,
            finding="OPENING_CANDLE_READINESS_FAILED:RuntimeError",
        )

        self.assertEqual(OPENING_CANDLE_BACKFILL_FAILED, result.status)
        self.assertEqual({"AAA", "BBB"}, set(result.rvol_by_symbol))
        self.assertTrue(
            all(not evidence.execution_eligible for evidence in result.rvol_by_symbol.values())
        )
        self.assertEqual({"AAA": (), "BBB": ()}, result.bars_by_symbol)

    def _append_sessions(
        self,
        sessions: tuple[date, ...],
        *,
        count: int = 5,
        symbol: str = "AAA",
    ) -> None:
        candles: list[SchwabMinuteCandle] = []
        for session_date in sessions:
            start = datetime.combine(session_date, time(9, 30), EASTERN_TZ)
            for offset in range(count):
                candles.append(
                    SchwabMinuteCandle(
                        symbol=symbol,
                        timestamp=start + timedelta(minutes=offset),
                        open=10.0,
                        high=10.2,
                        low=9.9,
                        close=10.1,
                        volume=100.0,
                        source=SCHWAB_PRICE_HISTORY_SOURCE,
                    )
                )
        SchwabCandleStore(self.root).append_history(
            tuple(candles), received_at=AS_OF.astimezone(timezone.utc)
        )


def snapshot(*, ready: bool):
    status = EXECUTION_ELIGIBLE if ready else EXECUTION_INELIGIBLE
    bars = tuple(
        CanonicalMinuteBar(
            symbol="AAA",
            timestamp=(AS_OF.replace(minute=30) + timedelta(minutes=offset)).isoformat(),
            open=10.0,
            high=10.2,
            low=9.9,
            close=10.1,
            volume=100.0,
            source=SCHWAB_PRICE_HISTORY_SOURCE,
            state="HISTORY_ONLY_GAP_FILL",
            session_date="2026-08-13",
        )
        for offset in range(5 if ready else 4)
    )
    rvol = TimeNormalizedRvolEvidence(
        status=status,
        symbol="AAA",
        session_name="REGULAR",
        session_date="2026-08-13",
        session_minute=5,
        current_bar_count=5 if ready else 4,
        expected_current_bar_count=5,
        baseline_session_count=5 if ready else 0,
        minimum_baseline_sessions=5,
        relative_volume=1.2 if ready else None,
        findings=("TIME_NORMALIZED_RVOL_AVAILABLE",) if ready else ("MISSING_CURRENT_SESSION_BARS",),
    )
    evidence = {
        "AAA": {
            "status": OPENING_CANDLE_READY if ready else "WAITING",
            "openingBarCount": len(bars),
            "requiredOpeningBarCount": 5,
            "rvolStatus": status,
            "currentBarCount": 5 if ready else 4,
            "expectedCurrentBarCount": 5,
            "baselineSessionCount": 5 if ready else 0,
            "minimumBaselineSessions": 5,
            "findings": list(rvol.findings),
        }
    }
    return {"AAA": bars}, {"AAA": rvol}, evidence, tuple(rvol.findings)


if __name__ == "__main__":
    unittest.main()
