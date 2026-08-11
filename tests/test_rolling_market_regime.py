from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from momentum_hunter.canonical_candle_evidence import CanonicalMinuteBar
from momentum_hunter.rolling_market_regime import (
    DATA_STALE,
    EVENT_RISK,
    HIGH,
    INSUFFICIENT,
    MEDIUM,
    MIXED,
    NEGATIVE,
    NO_REEVALUATION,
    NO_SCORE_AUTHORITY,
    PARTIAL,
    POSITIVE,
    REGIME_CHANGED,
    RISK_OFF,
    RISK_ON,
    SECTOR_ROTATION,
    STALE,
    SUFFICIENT,
    UNAVAILABLE,
    VOLATILITY_SHOCK,
    CandidateRegimeTarget,
    EventRiskContext,
    RegimeBar,
    RegimePolicy,
    RegimeSnapshotStore,
    RollingMarketRegimeError,
    bars_from_canonical,
    derive_regime_snapshot,
    fan_out_regime_context,
)


BASE = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)


class RollingMarketRegimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = policy()
        self.market = {
            symbol: bars(symbol, step=0.20)
            for symbol in self.policy.market_symbols
        }

    def derive(self, values=None, **kwargs):
        return derive_regime_snapshot(
            bars_by_symbol=values or self.market,
            sector_symbols=kwargs.pop("sector_symbols", ()),
            policy=self.policy,
            evaluated_at=kwargs.pop("evaluated_at", BASE + timedelta(seconds=30)),
            **kwargs,
        )

    def test_risk_on_requires_aligned_positive_benchmarks(self) -> None:
        snapshot = self.derive()

        self.assertEqual(RISK_ON, snapshot.regime)
        self.assertEqual(SUFFICIENT, snapshot.input_sufficiency)
        self.assertEqual(HIGH, snapshot.confidence)
        self.assertEqual({POSITIVE}, {row.direction for row in snapshot.metrics})
        self.assertEqual(NO_SCORE_AUTHORITY, snapshot.score_authority)
        self.assertFalse(snapshot.trade_recommendation)
        self.assertEqual(self.policy, snapshot.policy)
        self.assertEqual(self.policy.fingerprint, snapshot.policy_fingerprint)

    def test_risk_off_requires_aligned_negative_benchmarks(self) -> None:
        values = {
            symbol: bars(symbol, step=-0.20)
            for symbol in self.policy.market_symbols
        }

        snapshot = self.derive(values)

        self.assertEqual(RISK_OFF, snapshot.regime)
        self.assertEqual({NEGATIVE}, {row.direction for row in snapshot.metrics})

    def test_mixed_when_benchmark_directions_do_not_align(self) -> None:
        values = {
            "SPY": bars("SPY", step=0.20),
            "QQQ": bars("QQQ", step=-0.20),
            "IWM": bars("IWM", step=0.0),
        }

        snapshot = self.derive(values)

        self.assertEqual(MIXED, snapshot.regime)
        self.assertIn("BENCHMARK_ALIGNMENT_MIXED", snapshot.transition_reason)

    def test_volatility_shock_precedes_directional_label(self) -> None:
        values = dict(self.market)
        values["SPY"] = bars("SPY", step=0.20, shock=True)

        snapshot = self.derive(values)

        self.assertEqual(VOLATILITY_SHOCK, snapshot.regime)
        self.assertGreaterEqual(
            next(row for row in snapshot.metrics if row.symbol == "SPY").volatility_multiple,
            self.policy.volatility_shock_multiple,
        )

    def test_event_risk_is_explicit_external_context(self) -> None:
        snapshot = self.derive(
            event_risk=EventRiskContext(
                active=True,
                context_id="event-fed-20260810-1400",
                reason="Synthetic scheduled-event window.",
            )
        )

        self.assertEqual(EVENT_RISK, snapshot.regime)
        self.assertTrue(snapshot.event_risk_active)
        self.assertEqual("event-fed-20260810-1400", snapshot.event_risk_context_id)

    def test_sector_rotation_requires_divergence_and_mixed_market(self) -> None:
        values = {
            "SPY": bars("SPY", step=0.20),
            "QQQ": bars("QQQ", step=-0.20),
            "IWM": bars("IWM", step=0.0),
            "XLK": bars("XLK", step=0.50),
            "XLE": bars("XLE", step=-0.50),
        }

        snapshot = self.derive(values, sector_symbols=("XLK", "XLE"))

        self.assertEqual(SECTOR_ROTATION, snapshot.regime)
        self.assertEqual(SUFFICIENT, snapshot.input_sufficiency)
        self.assertEqual(("XLE", "XLK"), tuple(
            row.symbol for row in snapshot.metrics if row.role == "SECTOR"
        ))

    def test_missing_market_history_fails_closed_as_insufficient(self) -> None:
        values = {"SPY": bars("SPY", step=0.20)}

        snapshot = self.derive(values)

        self.assertEqual(DATA_STALE, snapshot.regime)
        self.assertEqual(INSUFFICIENT, snapshot.input_sufficiency)
        self.assertEqual((), snapshot.metrics)
        self.assertIn("QQQ", snapshot.transition_reason)

    def test_stale_market_evidence_fails_closed(self) -> None:
        snapshot = self.derive(evaluated_at=BASE + timedelta(minutes=5))

        self.assertEqual(DATA_STALE, snapshot.regime)
        self.assertEqual(STALE, snapshot.input_sufficiency)
        self.assertIn("SPY_STALE", snapshot.transition_reason)

    def test_cross_symbol_timestamp_skew_fails_closed(self) -> None:
        values = dict(self.market)
        values["QQQ"] = shift_bars(values["QQQ"], timedelta(seconds=-30))

        snapshot = self.derive(values)

        self.assertEqual(DATA_STALE, snapshot.regime)
        self.assertIn("MARKET_TIMESTAMP_SKEW", snapshot.transition_reason)

    def test_internal_gap_fails_closed(self) -> None:
        values = dict(self.market)
        values["IWM"] = shift_one_bar(
            values["IWM"], index=3, delta=timedelta(seconds=-90)
        )

        snapshot = self.derive(values)

        self.assertEqual(DATA_STALE, snapshot.regime)
        self.assertIn("IWM_GAP", snapshot.transition_reason)

    def test_missing_sector_data_is_partial_without_blocking_market_context(self) -> None:
        values = dict(self.market)
        values["XLK"] = bars("XLK", step=0.30)

        snapshot = self.derive(values, sector_symbols=("XLK", "XLE"))

        self.assertEqual(RISK_ON, snapshot.regime)
        self.assertEqual(PARTIAL, snapshot.input_sufficiency)
        self.assertEqual(MEDIUM, snapshot.confidence)

    def test_future_bar_is_rejected(self) -> None:
        values = dict(self.market)
        values["SPY"] = (
            *values["SPY"],
            bars(
                "SPY",
                step=0.0,
                count=1,
                start_at=BASE + timedelta(minutes=1),
            )[0],
        )

        with self.assertRaisesRegex(RollingMarketRegimeError, "future bar"):
            self.derive(values)

    def test_mixed_source_identity_within_symbol_is_rejected(self) -> None:
        values = dict(self.market)
        rows = list(values["SPY"])
        rows[0] = replace(rows[0], source_identity="another-canonical-source")
        values["SPY"] = tuple(rows)

        with self.assertRaisesRegex(RollingMarketRegimeError, "mixed source"):
            self.derive(values)

    def test_provisional_bar_state_is_rejected(self) -> None:
        values = dict(self.market)
        rows = list(values["SPY"])
        rows[-1] = replace(rows[-1], source_state="IN_PROGRESS")
        values["SPY"] = tuple(rows)

        with self.assertRaisesRegex(RollingMarketRegimeError, "terminal canonical"):
            self.derive(values)

    def test_derivation_is_replay_deterministic(self) -> None:
        first = self.derive()
        second = self.derive()

        self.assertEqual(first, second)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_transition_reason_binds_previous_snapshot(self) -> None:
        first = self.derive()
        values = {
            symbol: bars(symbol, step=-0.20, start_at=BASE + timedelta(minutes=1))
            for symbol in self.policy.market_symbols
        }

        second = self.derive(
            values,
            evaluated_at=BASE + timedelta(minutes=1, seconds=30),
            previous_snapshot=first,
        )

        self.assertEqual(first.snapshot_id, second.previous_snapshot_id)
        self.assertEqual(RISK_ON, second.previous_regime)
        self.assertEqual(RISK_OFF, second.regime)
        self.assertIn("RISK_ON_TO_RISK_OFF", second.transition_reason)
        self.assertEqual(2, second.sequence)

    def test_transition_cannot_move_backward_or_repeat_evaluation_time(self) -> None:
        first = self.derive()

        with self.assertRaisesRegex(RollingMarketRegimeError, "chronology"):
            self.derive(
                previous_snapshot=first,
                evaluated_at=BASE + timedelta(seconds=30),
            )

    def test_inactive_event_context_cannot_carry_evidence(self) -> None:
        with self.assertRaisesRegex(RollingMarketRegimeError, "Inactive event risk"):
            self.derive(
                event_risk=EventRiskContext(
                    active=False,
                    context_id="should-not-exist",
                    reason="Contradictory context.",
                )
            )


class RegimeFanOutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = policy()
        values = {
            symbol: bars(symbol, step=0.20)
            for symbol in self.policy.market_symbols
        }
        values["XLK"] = bars("XLK", step=0.30)
        self.snapshot = derive_regime_snapshot(
            bars_by_symbol=values,
            sector_symbols=("XLK", "XLE"),
            policy=self.policy,
            evaluated_at=BASE + timedelta(seconds=30),
        )

    def test_fan_out_preserves_order_and_missing_sector_honesty(self) -> None:
        targets = (
            CandidateRegimeTarget("opportunity-a", "AAA", "XLK"),
            CandidateRegimeTarget("opportunity-b", "BBB", "XLE"),
        )

        contexts = fan_out_regime_context(
            self.snapshot,
            targets,
            policy=self.policy,
        )

        self.assertEqual(("AAA", "BBB"), tuple(item.symbol for item in contexts))
        self.assertTrue(contexts[0].sector_context_available)
        self.assertEqual(POSITIVE, contexts[0].sector_direction)
        self.assertFalse(contexts[1].sector_context_available)
        self.assertEqual(UNAVAILABLE, contexts[1].sector_direction)
        self.assertEqual(
            {NO_SCORE_AUTHORITY}, {item.score_authority for item in contexts}
        )
        self.assertEqual(
            {NO_REEVALUATION}, {item.reevaluation_status for item in contexts}
        )

    def test_changed_regime_requests_bounded_reevaluation_context(self) -> None:
        previous = derive_regime_snapshot(
            bars_by_symbol={
                symbol: bars(symbol, step=-0.20)
                for symbol in self.policy.market_symbols
            },
            sector_symbols=(),
            policy=self.policy,
            evaluated_at=BASE + timedelta(seconds=30),
        )
        current = derive_regime_snapshot(
            bars_by_symbol={
                symbol: bars(symbol, step=0.20, start_at=BASE + timedelta(minutes=1))
                for symbol in self.policy.market_symbols
            },
            sector_symbols=(),
            policy=self.policy,
            evaluated_at=BASE + timedelta(minutes=1, seconds=30),
            previous_snapshot=previous,
        )

        context = fan_out_regime_context(
            current,
            (CandidateRegimeTarget("opportunity-a", "AAA"),),
            policy=self.policy,
        )[0]

        self.assertEqual(REGIME_CHANGED, context.reevaluation_status)

    def test_fan_out_limit_fails_closed(self) -> None:
        targets = tuple(
            CandidateRegimeTarget(f"opportunity-{index}", f"A{index}")
            for index in range(self.policy.maximum_candidate_fan_out + 1)
        )

        with self.assertRaisesRegex(RollingMarketRegimeError, "bounded candidate"):
            fan_out_regime_context(self.snapshot, targets, policy=self.policy)

    def test_duplicate_opportunity_identity_is_rejected(self) -> None:
        targets = (
            CandidateRegimeTarget("same", "AAA"),
            CandidateRegimeTarget("same", "BBB"),
        )

        with self.assertRaisesRegex(RollingMarketRegimeError, "repeated an opportunity"):
            fan_out_regime_context(self.snapshot, targets, policy=self.policy)


class RegimeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "regime-ledger.json"
        self.store = RegimeSnapshotStore(self.path)
        self.policy = policy()

    def snapshot(self, *, previous=None, step=0.20, offset=0):
        when = BASE + timedelta(minutes=offset)
        return derive_regime_snapshot(
            bars_by_symbol={
                symbol: bars(symbol, step=step, start_at=when)
                for symbol in self.policy.market_symbols
            },
            sector_symbols=(),
            policy=self.policy,
            evaluated_at=when + timedelta(seconds=30),
            previous_snapshot=previous,
        )

    def test_append_and_reload_preserves_exact_snapshot(self) -> None:
        snapshot = self.snapshot()

        self.store.append(snapshot)

        self.assertEqual((snapshot,), self.store.load().snapshots)

    def test_exact_duplicate_is_idempotent_and_byte_identical(self) -> None:
        snapshot = self.snapshot()
        self.store.append(snapshot)
        before = self.path.read_bytes()

        repeated = self.store.append(snapshot)

        self.assertEqual(snapshot, repeated)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(1, len(self.store.load().snapshots))

    def test_new_snapshot_must_extend_current_chain(self) -> None:
        first = self.snapshot()
        self.store.append(first)
        unrelated = self.snapshot(offset=1)

        with self.assertRaisesRegex(
            RollingMarketRegimeError, "sequence|extend"
        ):
            self.store.append(unrelated)

    def test_tampered_snapshot_is_rejected(self) -> None:
        snapshot = self.snapshot()
        self.store.append(snapshot)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["snapshots"][0]["regime"] = RISK_OFF
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(RollingMarketRegimeError, "fingerprint"):
            self.store.load()

    def test_atomic_replace_failure_preserves_prior_ledger(self) -> None:
        first = self.snapshot()
        self.store.append(first)
        before = self.path.read_bytes()
        second = self.snapshot(previous=first, step=-0.20, offset=1)

        with mock.patch(
            "momentum_hunter.rolling_market_regime.os.replace",
            side_effect=OSError("synthetic replace failure"),
        ):
            with self.assertRaises(OSError):
                self.store.append(second)

        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual((first,), self.store.load().snapshots)


class RegimeBoundaryTests(unittest.TestCase):
    def test_canonical_adapter_copies_without_source_mutation(self) -> None:
        source = {
            "SPY": [
                CanonicalMinuteBar(
                    symbol="SPY",
                    timestamp=BASE.isoformat(),
                    open=100.0,
                    high=100.2,
                    low=99.8,
                    close=100.1,
                    volume=1000.0,
                    source="schwab-price-history",
                    state="RECONCILED",
                    session_date="2026-08-10",
                )
            ]
        }
        before = repr(source)

        converted = bars_from_canonical(source)

        self.assertEqual(before, repr(source))
        self.assertEqual("schwab-price-history", converted["SPY"][0].source_identity)
        self.assertEqual("RECONCILED", converted["SPY"][0].source_state)
        self.assertIsNot(source["SPY"][0], converted["SPY"][0])

    def test_module_has_no_network_broker_scoring_or_trade_plan_import(self) -> None:
        path = Path(__file__).parents[1] / "momentum_hunter" / "rolling_market_regime.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        forbidden = (
            "requests",
            "urllib",
            "httpx",
            "socket",
            "alpaca",
            "schwab_market_data",
            "scoring",
            "trade_planning",
            "intraday_trade_plan",
            "risk_governor",
            "broker",
            "execution",
        )
        self.assertFalse(
            [name for name in imports if any(part in name for part in forbidden)]
        )


def policy() -> RegimePolicy:
    return RegimePolicy(
        policy_version="synthetic-regime-policy-v1",
        market_symbols=("SPY", "QQQ", "IWM"),
        short_window_bars=3,
        long_window_bars=6,
        volatility_baseline_bars=5,
        directional_return_threshold_pct=0.10,
        alignment_fraction=2 / 3,
        volatility_shock_multiple=5.0,
        sector_rotation_dispersion_pct=1.0,
        stale_after_seconds=90,
        maximum_cross_symbol_skew_seconds=5,
        maximum_internal_gap_seconds=65,
        minimum_sector_symbols=2,
        maximum_candidate_fan_out=3,
    )


def bars(
    symbol: str,
    *,
    step: float,
    count: int = 8,
    shock: bool = False,
    start_at: datetime = BASE,
) -> tuple[RegimeBar, ...]:
    first = start_at - timedelta(minutes=max(0, count - 1))
    result = []
    for index in range(count):
        close = 100.0 + (index * step)
        half_range = 2.0 if shock and index == count - 1 else 0.05
        result.append(
            RegimeBar(
                symbol=symbol,
                timestamp=(first + timedelta(minutes=index)).isoformat(),
                open=close,
                high=close + half_range,
                low=close - half_range,
                close=close,
                volume=1000.0 + index,
                source_identity="synthetic-canonical-bars",
                source_state="RECONCILED",
            )
        )
    return tuple(result)


def shift_bars(
    values: tuple[RegimeBar, ...], delta: timedelta
) -> tuple[RegimeBar, ...]:
    return tuple(
        replace(
            item,
            timestamp=(datetime.fromisoformat(item.timestamp) + delta).isoformat(),
        )
        for item in values
    )


def shift_one_bar(
    values: tuple[RegimeBar, ...], *, index: int, delta: timedelta
) -> tuple[RegimeBar, ...]:
    result = list(values)
    item = result[index]
    result[index] = replace(
        item,
        timestamp=(datetime.fromisoformat(item.timestamp) + delta).isoformat(),
    )
    return tuple(result)


if __name__ == "__main__":
    unittest.main()
