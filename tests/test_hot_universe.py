from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.broad_discovery import (
    DiscoveryQueryIdentity,
    DiscoverySourceRow,
    build_discovery_snapshot,
)
from momentum_hunter.hot_universe import (
    ADMITTED,
    APPLIED,
    CAPACITY_RESTORED,
    DISCOVERY_FAILURE,
    DUPLICATE,
    EXPIRED,
    EXPIRED_STATE,
    FAILURE_RECORDED,
    HOT,
    HotUniverseError,
    HotUniversePolicy,
    HotUniverseStore,
    PROTECTED,
    PROTECTED_COUNTS_AGAINST_HOT_CAPACITY,
    PROVIDER_BOUND,
    READMITTED_NEW_GENERATION,
    SOURCE_ABSENT,
    TRACKED,
    SetupReferenceInput,
    ProtectedResourceInput,
    WARM,
    apply_discovery_snapshot,
    build_discovery_failure_observation,
    empty_hot_universe_state,
    hot_universe_state_from_wire,
    hot_universe_state_to_wire,
    record_discovery_failure,
)
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.time_utils import CENTRAL_TZ


BASE = datetime(2026, 8, 17, 10, 0, tzinfo=CENTRAL_TZ)
SOURCE_CONTRACT = "a" * 64
SEMANTIC = "b" * 64


def policy(**changes: object) -> HotUniversePolicy:
    return HotUniversePolicy(**changes)


def snapshot(
    minute: int,
    rows: list[tuple[str, bool, int]],
    *,
    day_offset: int = 0,
) -> object:
    observed = BASE + timedelta(days=day_offset, minutes=minute)
    source_rows = []
    for ordinal, (symbol, qualified, volume) in enumerate(rows, start=1):
        source_rows.append(
            DiscoverySourceRow.from_mapping(
                source_row_ordinal=ordinal,
                source_row_identity=f"{symbol}-{ordinal}-{observed.isoformat()}",
                source_values={"Ticker": symbol, "No.": str(ordinal)},
                candidate=Candidate(
                    ticker=symbol,
                    company=f"{symbol} Incorporated",
                    price=20.0,
                    percent_change=5.0 if qualified else 1.0,
                    volume=volume * 1_000_000,
                    relative_volume=2.0,
                    market_cap=10_000_000_000,
                    sector="Technology",
                    industry="Software",
                ),
            )
        )
    return build_discovery_snapshot(
        source="finviz",
        source_version="synthetic-finviz-contract-v1",
        requested_at=observed - timedelta(seconds=2),
        received_at=observed - timedelta(seconds=1),
        evaluated_at=observed,
        query_identity=DiscoveryQueryIdentity.from_criteria(
            INSTITUTIONAL_MOMENTUM,
            source_query="synthetic://bounded-discovery",
            sort_order="-volume",
        ),
        source_contract_fingerprint=SOURCE_CONTRACT,
        semantic_plausibility_fingerprint=SEMANTIC,
        source_rows=source_rows,
    )


def member(state, symbol: str):
    return next(item for item in state.members if item.symbol == symbol and item.current_state != EXPIRED_STATE)


class HotUniverseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = policy()

    def apply(self, state, pulse, **kwargs):
        return apply_discovery_snapshot(state, policy=self.policy, snapshot=pulse, **kwargs)

    def test_normal_retention_and_rediscovery_keep_one_generation(self) -> None:
        initial_snapshot = snapshot(0, [("AAA", True, 100)])
        source_before = initial_snapshot.to_dict()
        first = self.apply(None, initial_snapshot)
        absent = self.apply(first.state, snapshot(5, []))
        rediscovered = self.apply(absent.state, snapshot(10, [("AAA", True, 120)]))

        self.assertEqual(source_before, initial_snapshot.to_dict())
        self.assertEqual(1, rediscovered.summary.total_members)
        self.assertEqual(0, member(rediscovered.state, "AAA").consecutive_absent_observations)
        self.assertEqual("hot-member-AAA-2026-08-17-g1", member(rediscovered.state, "AAA").member_id)
        self.assertIn(SOURCE_ABSENT, [item.transition_type for item in absent.transitions])

    def test_rejected_after_qualified_retains_member_and_records_observation(self) -> None:
        first = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        result = self.apply(first.state, snapshot(5, [("AAA", False, 100)]))

        retained = member(result.state, "AAA")
        self.assertEqual(1, retained.consecutive_rejected_observations)
        self.assertEqual(2, retained.source_observation_count)
        self.assertTrue(retained.last_rejected_at)
        self.assertNotEqual(EXPIRED_STATE, retained.current_state)

    def test_new_rejected_row_is_not_admitted(self) -> None:
        result = self.apply(None, snapshot(0, [("AAA", False, 100)]))
        self.assertEqual(0, result.summary.total_members)
        self.assertEqual(1, result.summary.rejected_observations_this_pulse)

    def test_discovery_failure_does_not_age_absence_or_expire_member(self) -> None:
        first = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        failure = build_discovery_failure_observation(
            source="finviz",
            observed_at=BASE + timedelta(minutes=5),
            session_date="2026-08-17",
            reason="PROVIDER_SCHEMA_FAILURE",
            source_contract_fingerprint=SOURCE_CONTRACT,
        )
        result = record_discovery_failure(first.state, policy=self.policy, failure=failure)

        self.assertEqual(FAILURE_RECORDED, result.status)
        self.assertEqual(0, member(result.state, "AAA").consecutive_absent_observations)
        self.assertEqual(DISCOVERY_FAILURE, result.transitions[0].transition_type)

    def test_absence_beyond_policy_expires_explicitly(self) -> None:
        self.policy = policy(maximum_consecutive_absent_observations=0)
        first = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        result = self.apply(first.state, snapshot(5, []))

        expired = next(item for item in result.state.members if item.symbol == "AAA")
        self.assertEqual(EXPIRED_STATE, expired.current_state)
        self.assertEqual(EXPIRED, expired.current_tier)
        self.assertEqual(1, result.summary.expirations_this_pulse)

    def test_expired_symbol_is_readmitted_as_new_generation(self) -> None:
        self.policy = policy(maximum_consecutive_absent_observations=0)
        first = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        expired = self.apply(first.state, snapshot(5, []))
        result = self.apply(expired.state, snapshot(10, [("AAA", True, 100)]))

        active = member(result.state, "AAA")
        self.assertEqual(2, active.membership_generation)
        self.assertEqual("hot-member-AAA-2026-08-17-g2", active.member_id)
        self.assertIn(READMITTED_NEW_GENERATION, [item.transition_type for item in result.transitions])

    def test_rank_churn_preserves_member_identity(self) -> None:
        first = self.apply(None, snapshot(0, [("AAA", True, 100), ("BBB", True, 90)]))
        second = self.apply(first.state, snapshot(5, [("AAA", True, 90), ("BBB", True, 110)]))
        third = self.apply(second.state, snapshot(10, [("AAA", True, 120), ("BBB", True, 80)]))

        self.assertEqual("hot-member-AAA-2026-08-17-g1", member(third.state, "AAA").member_id)
        self.assertEqual("hot-member-BBB-2026-08-17-g1", member(third.state, "BBB").member_id)

    def test_terminal_setup_does_not_expire_member_or_create_new_setup(self) -> None:
        first = self.apply(
            None,
            snapshot(0, [("AAA", True, 100)]),
            setup_inputs=(SetupReferenceInput("AAA", "setup-1", True),),
        )
        result = self.apply(
            first.state,
            snapshot(5, [("AAA", True, 110)]),
            setup_inputs=(SetupReferenceInput("AAA", "setup-1", True), SetupReferenceInput("AAA", "setup-2", False)),
        )

        retained = member(result.state, "AAA")
        self.assertEqual(1, retained.terminal_setup_count)
        self.assertEqual(("setup-2",), retained.active_setup_ids)
        self.assertEqual(TRACKED, retained.current_state)

    def test_thirty_for_ten_assigns_exactly_ten_hot_and_preserves_provider_bound(self) -> None:
        self.policy = policy(maximum_tracked_symbols=30, maximum_hot_symbols=10, maximum_warm_symbols=0)
        rows = [(f"S{index:02d}", True, 1000 - index) for index in range(30)]
        result = self.apply(None, snapshot(0, rows))

        self.assertEqual(30, result.summary.total_members)
        self.assertEqual(10, result.summary.hot)
        self.assertEqual(20, result.summary.provider_bound)
        self.assertEqual(30, result.summary.hot + result.summary.provider_bound + result.summary.warm + result.summary.protected)
        self.assertTrue(all(item.current_tier in {HOT, PROVIDER_BOUND} for item in result.state.members))

    def test_tracking_capacity_overflow_is_retained_as_explicitly_provider_bound(self) -> None:
        constrained = policy(maximum_tracked_symbols=2, maximum_hot_symbols=1, maximum_warm_symbols=2)
        first = apply_discovery_snapshot(
            None,
            policy=constrained,
            snapshot=snapshot(0, [("AAA", True, 300), ("BBB", True, 200), ("CCC", True, 100)]),
        )
        result = apply_discovery_snapshot(
            first.state,
            policy=constrained,
            snapshot=snapshot(5, []),
        )

        self.assertEqual(3, result.summary.total_members)
        self.assertEqual(HOT, member(result.state, "AAA").current_tier)
        self.assertEqual(WARM, member(result.state, "BBB").current_tier)
        overflow = member(result.state, "CCC")
        self.assertEqual(PROVIDER_BOUND, overflow.current_tier)
        self.assertEqual("TRACKING_CAPACITY_BOUND", overflow.capacity_disposition)

    def test_protected_low_rank_member_outranks_ordinary_churn(self) -> None:
        self.policy = policy(maximum_hot_symbols=1, maximum_warm_symbols=0)
        result = self.apply(
            None,
            snapshot(0, [("AAA", True, 100), ("BBB", True, 200)]),
            protected_inputs=(ProtectedResourceInput("AAA", "ACTIVE_POSITION"),),
        )

        self.assertEqual(PROTECTED, member(result.state, "AAA").current_tier)
        self.assertEqual(PROVIDER_BOUND, member(result.state, "BBB").current_tier)

    def test_protected_count_over_hot_capacity_fails_before_state_commit(self) -> None:
        self.policy = policy(maximum_hot_symbols=1, protected_capacity_policy=PROTECTED_COUNTS_AGAINST_HOT_CAPACITY)
        before = empty_hot_universe_state()
        with self.assertRaisesRegex(HotUniverseError, "Protected members exceed"):
            self.apply(
                before,
                snapshot(0, [("AAA", True, 100), ("BBB", True, 90)]),
                protected_inputs=(ProtectedResourceInput("AAA", "ACTIVE_POSITION"), ProtectedResourceInput("BBB", "ACTIVE_ORDER")),
            )
        self.assertEqual(before, empty_hot_universe_state())

    def test_capacity_restoration_promotes_deterministic_provider_bound_member(self) -> None:
        self.policy = policy(maximum_hot_symbols=1, maximum_warm_symbols=0, maximum_consecutive_absent_observations=0)
        first = self.apply(None, snapshot(0, [("AAA", True, 200), ("BBB", True, 100)]))
        result = self.apply(first.state, snapshot(5, [("BBB", True, 100)]))

        self.assertEqual(HOT, member(result.state, "BBB").current_tier)
        self.assertIn(CAPACITY_RESTORED, [item.transition_type for item in result.transitions])

    def test_restart_reconstructs_state_without_duplicate_admission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hot-universe.json"
            store = HotUniverseStore(path)
            first = store.apply_snapshot(policy=self.policy, snapshot=snapshot(0, [("AAA", True, 100)]))
            absent = store.apply_snapshot(policy=self.policy, snapshot=snapshot(5, []))
            reloaded = HotUniverseStore(path)
            result = reloaded.apply_snapshot(policy=self.policy, snapshot=snapshot(10, [("AAA", True, 100)]))

            self.assertEqual(first.state.members[0].member_id, member(result.state, "AAA").member_id)
            self.assertEqual(0, member(result.state, "AAA").consecutive_absent_observations)
            self.assertEqual(1, len([item for item in result.state.members if item.symbol == "AAA" and item.current_state == TRACKED]))
            self.assertGreater(len(result.state.transitions), len(absent.state.transitions))

    def test_corrupted_restart_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hot-universe.json"
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(HotUniverseError):
                HotUniverseStore(path).load()

    def test_programdata_store_requires_explicit_persistent_opt_in(self) -> None:
        path = Path("C:/ProgramData/MomentumHunter/ContinuousRuntime/session/state/hot-universe.json")

        with self.assertRaisesRegex(HotUniverseError, "must not target ProgramData"):
            HotUniverseStore(path)

        store = HotUniverseStore(path, allow_persistent=True)
        self.assertEqual(path, store.path)

    def test_exact_duplicate_store_replay_is_idempotent_and_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hot-universe.json"
            store = HotUniverseStore(path)
            pulse = snapshot(0, [("AAA", True, 100)])
            first = store.apply_snapshot(policy=self.policy, snapshot=pulse)
            before = path.read_bytes()
            duplicate = store.apply_snapshot(policy=self.policy, snapshot=pulse)

            self.assertEqual(APPLIED, first.status)
            self.assertEqual(DUPLICATE, duplicate.status)
            self.assertEqual(before, path.read_bytes())

    def test_conflicting_policy_drift_fails_closed(self) -> None:
        first = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        with self.assertRaisesRegex(HotUniverseError, "Policy drift"):
            apply_discovery_snapshot(
                first.state,
                policy=policy(maximum_hot_symbols=9),
                snapshot=snapshot(5, [("AAA", True, 100)]),
            )

    def test_tampered_snapshot_and_malformed_input_fail_before_mutation(self) -> None:
        first = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        with self.assertRaises(HotUniverseError):
            self.apply(first.state, replace(snapshot(5, [("AAA", True, 100)]), fingerprint="0" * 64))
        with self.assertRaises(HotUniverseError):
            self.apply(first.state, None)  # type: ignore[arg-type]
        self.assertEqual(first.state, first.state)

    def test_future_dated_timezone_naive_and_out_of_order_snapshots_fail_closed(self) -> None:
        first = self.apply(None, snapshot(10, [("AAA", True, 100)]))
        with self.assertRaisesRegex(HotUniverseError, "future-dated"):
            self.apply(first.state, snapshot(20, [("AAA", True, 100)]), recorded_at=BASE + timedelta(minutes=19))
        naive = replace(snapshot(20, [("AAA", True, 100)]), evaluated_at=(BASE + timedelta(minutes=20)).replace(tzinfo=None))
        with self.assertRaisesRegex(HotUniverseError, "timezone-aware"):
            self.apply(first.state, naive)
        with self.assertRaisesRegex(HotUniverseError, "Out-of-order"):
            self.apply(first.state, snapshot(5, [("AAA", True, 100)]))

    def test_duplicate_symbol_and_partial_input_fail_before_any_update(self) -> None:
        first = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        duplicate_symbol = snapshot(5, [("AAA", True, 100), ("AAA", False, 90)])
        with self.assertRaisesRegex(HotUniverseError, "more than once"):
            self.apply(first.state, duplicate_symbol)
        self.assertEqual(2, len(first.state.transitions))
        self.assertEqual(1, member(first.state, "AAA").source_observation_count)

    def test_session_rollover_expires_old_members_without_carrying_state(self) -> None:
        first = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        result = self.apply(first.state, snapshot(0, [("BBB", True, 100)], day_offset=1))

        old = next(item for item in result.state.members if item.symbol == "AAA")
        self.assertEqual(EXPIRED_STATE, old.current_state)
        self.assertEqual("2026-08-18", result.state.current_session_date)
        self.assertEqual("hot-member-BBB-2026-08-18-g1", member(result.state, "BBB").member_id)

    def test_wire_round_trip_and_tamper_detection(self) -> None:
        result = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        payload = hot_universe_state_to_wire(result.state)
        self.assertEqual(result.state, hot_universe_state_from_wire(json.loads(json.dumps(payload))))
        payload["members"][0]["symbol"] = "ZZZ"
        with self.assertRaises(HotUniverseError):
            hot_universe_state_from_wire(payload)

    def test_failure_replay_is_idempotent(self) -> None:
        failure = build_discovery_failure_observation(
            source="finviz", observed_at=BASE, session_date="2026-08-17", reason="SCHEMA", source_contract_fingerprint=SOURCE_CONTRACT
        )
        first = record_discovery_failure(None, policy=self.policy, failure=failure)
        duplicate = record_discovery_failure(first.state, policy=self.policy, failure=failure)
        self.assertEqual(FAILURE_RECORDED, first.status)
        self.assertEqual(DUPLICATE, duplicate.status)

    def test_bounded_source_scope_is_preserved_on_transitions(self) -> None:
        result = self.apply(None, snapshot(0, [("AAA", True, 100)]))
        self.assertEqual("BOUNDED_PROVIDER_RESPONSE", result.transitions[0].source_scope)

    def test_summary_exposes_required_counts_without_strategy_score(self) -> None:
        result = self.apply(None, snapshot(0, [("AAA", True, 100), ("BBB", False, 50)]))
        summary = result.summary
        self.assertEqual(1, summary.total_members)
        self.assertEqual(1, summary.admitted_this_pulse)
        self.assertEqual(1, summary.rejected_observations_this_pulse)
        self.assertFalse(hasattr(summary, "profitability"))

    def test_policy_rejects_negative_and_impossible_capacity(self) -> None:
        with self.assertRaises(HotUniverseError):
            apply_discovery_snapshot(None, policy=policy(maximum_warm_symbols=-1), snapshot=snapshot(0, []))
        with self.assertRaises(HotUniverseError):
            apply_discovery_snapshot(None, policy=policy(maximum_tracked_symbols=1, maximum_hot_symbols=2), snapshot=snapshot(0, []))

    def test_static_module_boundary_has_no_network_broker_or_runtime_imports(self) -> None:
        module = Path("momentum_hunter/hot_universe.py")
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        prohibited = ("requests", "http", "broker", "alpaca", "schwab", "automation", "engine_host", "scheduler", "paper")
        self.assertFalse([name for name in imports if any(token in name.lower() for token in prohibited)])

    def test_existing_runtime_paths_do_not_import_hot_universe(self) -> None:
        runtime_paths = [
            Path("momentum_hunter/automation_supervisor.py"),
            Path("momentum_hunter/engine_host.py"),
            Path("tools/capture_job.py"),
        ]
        for path in runtime_paths:
            self.assertNotIn("hot_universe", path.read_text(encoding="utf-8"), path.as_posix())


if __name__ == "__main__":
    unittest.main()
