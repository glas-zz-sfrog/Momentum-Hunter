from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from momentum_hunter.candidate_lifecycle import (
    expected_opportunity_id,
    expected_setup_id,
)
from momentum_hunter.canonical_candle_evidence import CanonicalMinuteBar
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    OPENING_BREAKOUT,
    PULLBACK,
    RECLAIM,
)
from momentum_hunter.sequential_breakout_research import (
    BREAKOUT_CONFIRMED,
    DATA_UNAVAILABLE,
    ENTRY_MISSED,
    EXHAUSTION_RISK,
    FAILED_BREAKOUT,
    HISTORICAL_REPLAY,
    IMPULSE_DETECTED,
    PULLBACK_FORMING,
    PROSPECTIVE,
    RECLAIM_CONFIRMED,
    RESEARCH_ONLY,
    SequentialBreakoutError,
    SequentialBreakoutPolicy,
    SequentialBreakoutStore,
    build_observation,
    detect_sequential_breakout_events,
    event_fingerprint,
    expected_event_id,
    observation_from_canonical_bar,
    validate_event,
    validate_event_sequence,
)


BASE = datetime.fromisoformat("2026-08-10T09:30:00-04:00")
FAMILY = "OPENING_BOOTSTRAP"


class SequentialBreakoutResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "sequential-breakouts.json"
        self.policy = SequentialBreakoutPolicy(
            prior_range_bars=3,
            opening_range_bars=3,
            range_baseline_bars=3,
            volume_baseline_bars=3,
            impulse_window_bars=2,
            impulse_range_multiple=1.0,
            volume_confirmation_multiple=1.5,
            missed_range_multiple=0.5,
            pullback_range_multiple=0.25,
            exhaustion_range_multiple=3.0,
            max_sequence_bars=10,
            opening_range_start="09:30",
            opening_breakout_cutoff="09:40",
        )

    def bar(
        self,
        minute: int,
        *,
        base: datetime = BASE,
        open: float = 9.9,
        high: float = 10.0,
        low: float = 9.8,
        close: float = 9.9,
        volume: float = 100.0,
        symbol: str = "ABC",
        source_state: str = "RECONCILED",
    ):
        provider = base + timedelta(minutes=minute)
        return build_observation(
            symbol=symbol,
            session_date=provider.date().isoformat(),
            provider_timestamp=provider,
            receipt_timestamp=provider + timedelta(seconds=1),
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source="SCHWAB_PRICE_HISTORY",
            source_state=source_state,
            observation_mode=HISTORICAL_REPLAY,
        )

    def opening_sequence(self):
        return (
            self.bar(0),
            self.bar(1),
            self.bar(2),
            self.bar(
                3,
                open=10.05,
                high=10.30,
                low=10.01,
                close=10.20,
                volume=200.0,
            ),
            self.bar(
                4,
                open=10.20,
                high=10.22,
                low=10.03,
                close=10.05,
                volume=110.0,
            ),
            self.bar(
                5,
                open=10.05,
                high=10.08,
                low=9.90,
                close=9.95,
                volume=120.0,
            ),
            self.bar(
                6,
                open=9.95,
                high=10.15,
                low=9.94,
                close=10.10,
                volume=130.0,
            ),
        )

    def detect(self, observations=None):
        return detect_sequential_breakout_events(
            observations or self.opening_sequence(),
            originating_evidence_family=FAMILY,
            policy=self.policy,
        )

    def test_opening_sequence_preserves_monitor_identity_and_lineage(self) -> None:
        events = self.detect()
        self.assertEqual(
            [event.event_type for event in events],
            [
                IMPULSE_DETECTED,
                BREAKOUT_CONFIRMED,
                PULLBACK_FORMING,
                FAILED_BREAKOUT,
                RECLAIM_CONFIRMED,
            ],
        )
        opportunity_id = expected_opportunity_id("ABC", "2026-08-10", FAMILY)
        breakout = events[1]
        pullback = events[2]
        reclaim = events[4]
        self.assertTrue(all(event.opportunity_id == opportunity_id for event in events))
        self.assertEqual(
            breakout.setup_id,
            expected_setup_id(opportunity_id, OPENING_BREAKOUT, 1),
        )
        self.assertEqual(
            pullback.setup_id,
            expected_setup_id(opportunity_id, PULLBACK, 2),
        )
        self.assertEqual(pullback.predecessor_setup_id, breakout.setup_id)
        self.assertEqual(
            reclaim.setup_id,
            expected_setup_id(opportunity_id, RECLAIM, 3),
        )
        self.assertEqual(reclaim.predecessor_setup_id, breakout.setup_id)
        self.assertTrue(all(event.authority == RESEARCH_ONLY for event in events))
        self.assertTrue(all(event.execution_authority is False for event in events))

    def test_continuation_breakout_uses_prior_completed_range(self) -> None:
        later = datetime.fromisoformat("2026-08-10T11:00:00-04:00")
        bars = tuple(self.bar(index, base=later) for index in range(4)) + (
            self.bar(
                4,
                base=later,
                open=10.05,
                high=10.30,
                low=10.01,
                close=10.20,
                volume=200.0,
            ),
        )
        events = self.detect(bars)
        breakout = next(
            event for event in events if event.event_type == BREAKOUT_CONFIRMED
        )
        self.assertEqual(breakout.setup_family, CONTINUATION_BREAKOUT)
        self.assertEqual(breakout.trigger_price, 10.0)
        self.assertEqual(breakout.relative_volume, 2.0)

    def test_gap_up_breakout_is_preserved_as_missed_entry(self) -> None:
        bars = tuple(self.bar(index) for index in range(3)) + (
            self.bar(
                3,
                open=10.15,
                high=10.30,
                low=10.11,
                close=10.20,
                volume=200.0,
            ),
        )
        events = self.detect(bars)
        self.assertIn(ENTRY_MISSED, [event.event_type for event in events])
        breakout = next(
            event for event in events if event.event_type == BREAKOUT_CONFIRMED
        )
        missed = next(event for event in events if event.event_type == ENTRY_MISSED)
        self.assertEqual(missed.setup_id, breakout.setup_id)
        self.assertEqual(missed.trigger_price, 10.0)

    def test_extended_confirmation_is_marked_as_exhaustion_risk(self) -> None:
        bars = tuple(self.bar(index) for index in range(3)) + (
            self.bar(
                3,
                open=10.10,
                high=10.75,
                low=10.01,
                close=10.70,
                volume=250.0,
            ),
        )
        events = self.detect(bars)
        exhaustion = next(
            event for event in events if event.event_type == EXHAUSTION_RISK
        )
        self.assertEqual(exhaustion.trigger_price, 10.0)
        self.assertGreater(exhaustion.distance_from_trigger_pct, 6.0)

    def test_gap_is_visible_and_resets_sequence(self) -> None:
        bars = (
            self.bar(0),
            self.bar(1),
            self.bar(2),
            self.bar(4),
            self.bar(
                5,
                open=10.05,
                high=10.30,
                low=10.01,
                close=10.20,
                volume=200.0,
            ),
        )
        events = self.detect(bars)
        self.assertEqual([event.event_type for event in events], [DATA_UNAVAILABLE])
        self.assertIn("120 seconds", events[0].reason)

    def test_post_gap_breakout_cannot_reuse_opening_range_identity(self) -> None:
        bars = (
            self.bar(0),
            self.bar(1),
            self.bar(2),
            self.bar(4),
            self.bar(5),
            self.bar(6),
            self.bar(7),
            self.bar(
                8,
                open=10.05,
                high=10.30,
                low=10.01,
                close=10.20,
                volume=200.0,
            ),
        )
        events = self.detect(bars)
        breakouts = [
            event for event in events if event.event_type == BREAKOUT_CONFIRMED
        ]
        self.assertEqual(len(breakouts), 1)
        self.assertEqual(breakouts[0].setup_family, CONTINUATION_BREAKOUT)
        self.assertIn(DATA_UNAVAILABLE, [event.event_type for event in events])

    def test_insufficient_data_is_explicit(self) -> None:
        events = detect_sequential_breakout_events(
            (self.bar(0), self.bar(1)),
            originating_evidence_family=FAMILY,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, DATA_UNAVAILABLE)
        self.assertIn("required", events[0].reason)

    def test_future_bars_cannot_rewrite_prefix_events(self) -> None:
        bars = self.opening_sequence()
        prefix_events = self.detect(bars[:4])
        full_events = self.detect(bars)
        self.assertEqual(full_events[: len(prefix_events)], prefix_events)
        changed_future = bars[:4] + (
            self.bar(
                4,
                open=10.20,
                high=10.60,
                low=10.18,
                close=10.55,
                volume=500.0,
            ),
        )
        changed_events = self.detect(changed_future)
        self.assertEqual(changed_events[: len(prefix_events)], prefix_events)

    def test_canonical_bar_is_copied_without_source_mutation(self) -> None:
        canonical = CanonicalMinuteBar(
            symbol="abc",
            timestamp="2026-08-10T09:30:00-04:00",
            open=9.9,
            high=10.0,
            low=9.8,
            close=9.9,
            volume=100.0,
            source="SCHWAB_PRICE_HISTORY",
            state="RECONCILED",
            session_date="2026-08-10",
        )
        before = asdict(canonical)
        observation = observation_from_canonical_bar(
            canonical,
            receipt_timestamp="2026-08-10T09:30:01-04:00",
            observation_mode=HISTORICAL_REPLAY,
        )
        self.assertEqual(asdict(canonical), before)
        self.assertEqual(observation.symbol, "ABC")
        self.assertEqual(observation.source_state, "RECONCILED")

    def test_invalid_source_and_time_order_fail_closed(self) -> None:
        with self.assertRaisesRegex(SequentialBreakoutError, "terminal canonical"):
            self.bar(0, source_state="IN_PROGRESS")
        with self.assertRaisesRegex(SequentialBreakoutError, "UTC offset"):
            build_observation(
                symbol="ABC",
                session_date="2026-08-10",
                provider_timestamp="2026-08-10T09:30:00",
                receipt_timestamp="2026-08-10T09:30:01-04:00",
                open=9.9,
                high=10.0,
                low=9.8,
                close=9.9,
                volume=100.0,
                source="FIXTURE",
                source_state="RECONCILED",
                observation_mode=HISTORICAL_REPLAY,
            )
        with self.assertRaisesRegex(SequentialBreakoutError, "strictly chronological"):
            self.detect((self.bar(1), self.bar(0), self.bar(2), self.bar(3)))

    def test_exact_store_rerun_is_byte_identical(self) -> None:
        events = self.detect()
        store = SequentialBreakoutStore(self.path, policy=self.policy)
        first = store.append(events)
        content = self.path.read_bytes()
        second = store.append(events)
        self.assertEqual(first, second)
        self.assertEqual(self.path.read_bytes(), content)

    def test_conflicting_same_event_identity_fails_closed(self) -> None:
        events = self.detect()
        store = SequentialBreakoutStore(self.path, policy=self.policy)
        store.append(events)
        conflicting = replace(events[0], reason="Contradictory research history.")
        conflicting = replace(
            conflicting, fingerprint=event_fingerprint(conflicting)
        )
        with self.assertRaisesRegex(SequentialBreakoutError, "conflicts"):
            store.append((conflicting,))

    def test_tampered_persisted_event_is_rejected(self) -> None:
        store = SequentialBreakoutStore(self.path, policy=self.policy)
        store.append(self.detect())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["events"][0]["reason"] = "Tampered without a new fingerprint."
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(SequentialBreakoutError, "fingerprint"):
            store.load()

    def test_atomic_replace_failure_preserves_prior_ledger(self) -> None:
        events = self.detect()
        store = SequentialBreakoutStore(self.path, policy=self.policy)
        store.append(events[:2])
        before = self.path.read_bytes()
        with mock.patch(
            "momentum_hunter.sequential_breakout_research.os.replace",
            side_effect=OSError("synthetic replacement failure"),
        ):
            with self.assertRaises(OSError):
                store.append(events[2:])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_setup_lineage_and_authority_tampering_are_rejected(self) -> None:
        events = list(self.detect())
        pullback_index = next(
            index
            for index, event in enumerate(events)
            if event.event_type == PULLBACK_FORMING
        )
        tampered = replace(
            events[pullback_index], predecessor_setup_id="f" * 64
        )
        tampered = replace(tampered, fingerprint=event_fingerprint(tampered))
        events[pullback_index] = tampered
        with self.assertRaisesRegex(SequentialBreakoutError, "not observed"):
            validate_event_sequence(events, policy=self.policy)

        unauthorized = replace(self.detect()[0], execution_authority=True)
        unauthorized = replace(
            unauthorized, fingerprint=event_fingerprint(unauthorized)
        )
        with self.assertRaisesRegex(SequentialBreakoutError, "execution authority"):
            validate_event(unauthorized, policy=self.policy)

    def test_reclaim_without_a_failed_breakout_is_rejected(self) -> None:
        events = [
            event
            for event in self.detect()
            if event.event_type != FAILED_BREAKOUT
        ]
        rebuilt = []
        previous_id = ""
        for index, event in enumerate(events, start=1):
            current = replace(
                event,
                event_index=index,
                previous_event_id=previous_id,
            )
            current = replace(current, event_id=expected_event_id(current))
            current = replace(
                current, fingerprint=event_fingerprint(current)
            )
            rebuilt.append(current)
            previous_id = current.event_id
        with self.assertRaisesRegex(SequentialBreakoutError, "lacks a prior failed"):
            validate_event_sequence(rebuilt, policy=self.policy)

    def test_mixed_observation_modes_and_invalid_numbers_are_rejected(self) -> None:
        events = list(self.detect())
        mixed = replace(events[-1], observation_mode=PROSPECTIVE)
        mixed = replace(mixed, fingerprint=event_fingerprint(mixed))
        events[-1] = mixed
        with self.assertRaisesRegex(SequentialBreakoutError, "mixed observation modes"):
            validate_event_sequence(events, policy=self.policy)

        invalid_volume = replace(self.detect()[0], volume=-1.0)
        with self.assertRaisesRegex(SequentialBreakoutError, "cannot be negative"):
            validate_event(invalid_volume, policy=self.policy)

    def test_event_type_cannot_masquerade_as_another_setup_family(self) -> None:
        breakout = next(
            event for event in self.detect() if event.event_type == BREAKOUT_CONFIRMED
        )
        malformed = replace(
            breakout,
            event_type=PULLBACK_FORMING,
            setup_family=PULLBACK,
            setup_id=expected_setup_id(
                breakout.opportunity_id, PULLBACK, breakout.setup_sequence
            ),
        )
        malformed = replace(malformed, event_id=expected_event_id(malformed))
        malformed = replace(
            malformed, fingerprint=event_fingerprint(malformed)
        )
        with self.assertRaisesRegex(SequentialBreakoutError, "lineage"):
            validate_event(malformed, policy=self.policy)

    def test_policy_rejects_invalid_thresholds(self) -> None:
        invalid = replace(self.policy, prior_range_bars=0)
        with self.assertRaisesRegex(SequentialBreakoutError, "must be positive"):
            SequentialBreakoutStore(self.path, policy=invalid)

    def test_module_has_no_network_broker_or_runtime_activation_import(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module_path = root / "momentum_hunter" / "sequential_breakout_research.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        plan_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                if node.module == "momentum_hunter.intraday_trade_plan":
                    plan_names.update(alias.name for alias in node.names)
        banned = (
            "requests",
            "urllib",
            "httpx",
            "socket",
            "momentum_hunter.execution",
            "momentum_hunter.alpaca",
            "momentum_hunter.broker",
            "momentum_hunter.risk_governor",
            "momentum_hunter.scoring",
            "momentum_hunter.readiness",
        )
        self.assertFalse(
            any(
                name == prefix or name.startswith(prefix + ".")
                for name in imported
                for prefix in banned
            )
        )
        self.assertEqual(
            plan_names,
            {OPENING_BREAKOUT, CONTINUATION_BREAKOUT, PULLBACK, RECLAIM},
        )

        importers: list[str] = []
        for path in (root / "momentum_hunter").rglob("*.py"):
            if path == module_path:
                continue
            parsed = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(parsed):
                if isinstance(node, ast.ImportFrom) and node.module == (
                    "momentum_hunter.sequential_breakout_research"
                ):
                    importers.append(str(path.relative_to(root)))
                if isinstance(node, ast.Import) and any(
                    alias.name == "momentum_hunter.sequential_breakout_research"
                    for alias in node.names
                ):
                    importers.append(str(path.relative_to(root)))
        self.assertEqual(importers, [])


if __name__ == "__main__":
    unittest.main()
