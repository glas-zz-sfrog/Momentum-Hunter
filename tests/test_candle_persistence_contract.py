from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.candle_persistence_contract import (
    PROVIDER_FINALITY_STATUS,
    PROTOTYPE_CANDLE_STORE_FILENAME,
    VOLUME_AUTHORITY_STATUS,
    CandlePersistenceContractError,
    PrototypeCandleStore,
    assess_candle_health,
    build_revision_chains,
    detect_observed_gaps,
)
from momentum_hunter.schwab_candle_contract import (
    inspect_chart_equity_observations,
)


class CandlePersistenceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.allowed_root = Path(self.temporary.name)
        self.store_root = self.allowed_root / "prototype"
        self.store = PrototypeCandleStore(
            self.store_root,
            allowed_temporary_root=self.allowed_root,
        )
        self.received_at = datetime(2026, 8, 3, 13, 36, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_store_round_trips_observation_without_source_mutation(self) -> None:
        frames = [stream_frame("SPY", 13_000, 100, close=501.0)]
        before = json.dumps(frames, sort_keys=True)
        observations = inspect_chart_equity_observations(
            frames,
            expected_symbols=["SPY"],
            received_at_by_payload=[self.received_at],
        )

        result = self.store.append(observations)
        loaded = self.store.load()

        self.assertEqual(1, result.inserted_count)
        self.assertEqual(1, result.observation_count)
        self.assertTrue(result.changed)
        self.assertEqual(1, len(loaded.observations))
        self.assertEqual("SPY", loaded.observations[0].candle["symbol"])
        self.assertEqual(before, json.dumps(frames, sort_keys=True))

    def test_exact_duplicate_append_is_idempotent_and_byte_identical(self) -> None:
        observations = self._observations(
            [stream_frame("SPY", 13_000, 100, close=501.0)]
        )
        first = self.store.append(observations)
        first_bytes = self._store_path().read_bytes()

        second = self.store.append(observations)

        self.assertEqual(0, second.inserted_count)
        self.assertEqual(1, second.duplicate_count)
        self.assertFalse(second.changed)
        self.assertEqual(first.snapshot_fingerprint, second.snapshot_fingerprint)
        self.assertEqual(first_bytes, self._store_path().read_bytes())

    def test_revision_and_replay_remain_separate_arrival_evidence(self) -> None:
        frames = [
            stream_frame("SPY", 13_000, 100, close=501.0),
            stream_frame("SPY", 13_000, 100, close=501.0),
            stream_frame("SPY", 13_000, 100, close=502.0),
        ]
        receipts = [
            self.received_at,
            self.received_at + timedelta(seconds=1),
            self.received_at + timedelta(seconds=2),
        ]
        observations = inspect_chart_equity_observations(
            frames,
            expected_symbols=["SPY"],
            received_at_by_payload=receipts,
        )

        self.store.append(observations)
        chains = build_revision_chains(self.store.load())

        self.assertEqual(1, len(chains))
        self.assertEqual(3, len(chains[0].observation_ids))
        self.assertEqual(1, chains[0].replay_count)
        self.assertEqual(1, chains[0].revision_count)
        self.assertEqual(chains[0].observation_ids[-1], chains[0].latest_observation_id)

    def test_out_of_order_arrival_is_preserved(self) -> None:
        frames = [
            stream_frame("SPY", 14_000, 101, close=502.0),
            stream_frame("SPY", 13_000, 100, close=501.0),
        ]
        observations = inspect_chart_equity_observations(
            frames,
            expected_symbols=["SPY"],
            received_at_by_payload=[
                self.received_at,
                self.received_at + timedelta(seconds=1),
            ],
        )

        self.store.append(observations)
        loaded = self.store.load()

        self.assertFalse(loaded.observations[0].evidence["outOfOrder"])
        self.assertTrue(loaded.observations[1].evidence["outOfOrder"])

    def test_gap_detection_uses_latest_revision_without_fabricating_bars(self) -> None:
        observations = self._observations(
            [
                stream_frame("SPY", 13_000, 100, close=501.0),
                stream_frame("SPY", 13_180, 101, close=503.0),
            ]
        )
        self.store.append(observations)

        gaps = detect_observed_gaps(self.store.load())

        self.assertEqual(1, len(gaps))
        self.assertEqual(2, gaps[0].missing_interval_count)
        self.assertTrue(gaps[0].interval_aligned)

    def test_irregular_gap_is_reported_honestly(self) -> None:
        observations = self._observations(
            [
                stream_frame("SPY", 13_000, 100, close=501.0),
                stream_frame("SPY", 13_150, 101, close=503.0),
            ]
        )
        self.store.append(observations)

        gap = detect_observed_gaps(self.store.load())[0]

        self.assertEqual(2, gap.missing_interval_count)
        self.assertFalse(gap.interval_aligned)

    def test_health_separates_current_stale_gapped_and_missing(self) -> None:
        observations = self._observations(
            [
                stream_frame("SPY", 13_000, 100, close=501.0),
                stream_frame("SPY", 13_180, 101, close=503.0),
            ]
        )
        self.store.append(observations)

        current = assess_candle_health(
            self.store.load(),
            evaluated_at=self.received_at + timedelta(seconds=20),
            stale_after=timedelta(seconds=30),
            expected_symbols=["SPY", "IWM"],
        )
        stale = assess_candle_health(
            self.store.load(),
            evaluated_at=self.received_at + timedelta(minutes=2),
            stale_after=timedelta(seconds=30),
            expected_symbols=["SPY"],
        )

        by_symbol = {item.symbol: item for item in current}
        self.assertEqual("PROVISIONAL_WITH_GAPS", by_symbol["SPY"].status)
        self.assertEqual("NO_OBSERVATIONS", by_symbol["IWM"].status)
        self.assertEqual("PROVISIONAL_STALE_WITH_GAPS", stale[0].status)
        self.assertEqual(PROVIDER_FINALITY_STATUS, stale[0].provider_finality)
        self.assertEqual(VOLUME_AUTHORITY_STATUS, stale[0].volume_authority)

    def test_future_receipt_fails_health_assessment(self) -> None:
        self.store.append(
            self._observations([stream_frame("SPY", 13_000, 100, close=501.0)])
        )
        with self.assertRaisesRegex(
            CandlePersistenceContractError, "after the evaluation clock"
        ):
            assess_candle_health(
                self.store.load(),
                evaluated_at=self.received_at - timedelta(seconds=1),
                stale_after=timedelta(seconds=30),
            )

    def test_path_outside_explicit_temporary_root_is_rejected(self) -> None:
        outside = self.allowed_root.parent / "not-the-approved-root"
        with self.assertRaisesRegex(
            CandlePersistenceContractError, "below the allowed temporary root"
        ):
            PrototypeCandleStore(
                outside,
                allowed_temporary_root=self.allowed_root,
            )

    def test_non_temp_allowed_root_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            CandlePersistenceContractError, "operating-system temp directory"
        ):
            PrototypeCandleStore(
                Path.home() / "prototype",
                allowed_temporary_root=Path.home(),
            )

    def test_atomic_replace_failure_preserves_previous_snapshot(self) -> None:
        first = self._observations(
            [stream_frame("SPY", 13_000, 100, close=501.0)]
        )
        self.store.append(first)
        before = self._store_path().read_bytes()

        def fail_replace(source: Path, destination: Path) -> None:
            raise OSError("simulated crash before replace")

        failing = PrototypeCandleStore(
            self.store_root,
            allowed_temporary_root=self.allowed_root,
            replace_file=fail_replace,
        )
        second = self._observations(
            [stream_frame("SPY", 13_060, 101, close=502.0)],
            received_at=self.received_at + timedelta(seconds=2),
        )

        with self.assertRaisesRegex(OSError, "simulated crash"):
            failing.append(second)

        self.assertEqual(before, self._store_path().read_bytes())
        self.assertEqual([], list(self.store_root.glob("*.tmp")))
        self.assertEqual([], list(self.store_root.glob(".*.tmp")))

    def test_tampered_hash_fails_closed(self) -> None:
        self.store.append(
            self._observations([stream_frame("SPY", 13_000, 100, close=501.0)])
        )
        payload = json.loads(self._store_path().read_text(encoding="utf-8"))
        payload["observations"][0]["evidence"]["candle"]["close"] = 999.0
        self._store_path().write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            CandlePersistenceContractError, "hash did not match"
        ):
            self.store.load()

    def test_rehashed_contradictory_identity_still_fails_closed(self) -> None:
        self.store.append(
            self._observations([stream_frame("SPY", 13_000, 100, close=501.0)])
        )
        payload = json.loads(self._store_path().read_text(encoding="utf-8"))
        item = payload["observations"][0]
        item["evidence"]["candle"]["sessionDate"] = "1999-01-01"
        item["observationId"] = evidence_hash(item["evidence"])
        self._store_path().write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            CandlePersistenceContractError, "session date contradicted"
        ):
            self.store.load()

    def test_loaded_evidence_is_deeply_immutable(self) -> None:
        self.store.append(
            self._observations([stream_frame("SPY", 13_000, 100, close=501.0)])
        )
        loaded = self.store.load().observations[0]

        with self.assertRaises(TypeError):
            loaded.evidence["updateKind"] = "REVISION"  # type: ignore[index]
        with self.assertRaises(TypeError):
            loaded.candle["close"] = 999.0  # type: ignore[index]

    def test_duplicate_identity_in_file_fails_closed(self) -> None:
        self.store.append(
            self._observations([stream_frame("SPY", 13_000, 100, close=501.0)])
        )
        payload = json.loads(self._store_path().read_text(encoding="utf-8"))
        payload["observations"].append(payload["observations"][0])
        self._store_path().write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            CandlePersistenceContractError, "repeated an observation identity"
        ):
            self.store.load()

    def test_unknown_store_field_fails_closed(self) -> None:
        self.store.append(
            self._observations([stream_frame("SPY", 13_000, 100, close=501.0)])
        )
        payload = json.loads(self._store_path().read_text(encoding="utf-8"))
        payload["canonical"] = True
        self._store_path().write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            CandlePersistenceContractError, "exact supported schema"
        ):
            self.store.load()

    def test_metadata_cannot_claim_provider_finality_or_production_readiness(self) -> None:
        self.store.append(
            self._observations([stream_frame("SPY", 13_000, 100, close=501.0)])
        )
        payload = json.loads(self._store_path().read_text(encoding="utf-8"))

        self.assertEqual("UNVERIFIED", payload["providerFinality"])
        self.assertEqual("UNVERIFIED", payload["volumeAuthority"])
        self.assertFalse(payload["productionReady"])
        self.assertTrue(payload["singleWriterOnly"])

    def test_module_has_no_network_broker_service_or_production_path(self) -> None:
        source_path = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "candle_persistence_contract.py"
        )
        source = source_path.read_text(encoding="utf-8").lower()

        for forbidden in (
            "import requests",
            "import urllib",
            "import websocket",
            "schwabreadonlyclient",
            "submit_order",
            "engine_host",
            "momentumhunterdata",
            "opportunity-minute-bars.json",
        ):
            self.assertNotIn(forbidden, source)

    def _observations(
        self,
        frames: list[dict[str, object]],
        *,
        received_at: datetime | None = None,
    ):
        receipt = received_at or self.received_at
        return inspect_chart_equity_observations(
            frames,
            expected_symbols=["SPY"],
            received_at_by_payload=[
                receipt + timedelta(milliseconds=index)
                for index in range(len(frames))
            ],
        )

    def _store_path(self) -> Path:
        return self.store_root / PROTOTYPE_CANDLE_STORE_FILENAME


def stream_frame(
    symbol: str,
    epoch_seconds: int,
    sequence: int,
    *,
    close: float,
) -> dict[str, object]:
    timestamp_ms = int(
        datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp() * 1000
    ) + epoch_seconds * 1000
    return {
        "data": [
            {
                "service": "CHART_EQUITY",
                "timestamp": timestamp_ms + 200,
                "command": "SUBS",
                "content": [
                    {
                        "key": symbol,
                        "1": sequence,
                        "2": close - 0.5,
                        "3": close + 0.5,
                        "4": close - 1.0,
                        "5": close,
                        "6": 1_000.0 + sequence,
                        "7": timestamp_ms,
                        "8": 20_260_803,
                    }
                ],
            }
        ]
    }


def evidence_hash(evidence: object) -> str:
    encoded = (
        json.dumps(
            evidence,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    unittest.main()
