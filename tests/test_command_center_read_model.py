from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from momentum_hunter.broad_discovery import (
    DiscoveryQueryIdentity,
    DiscoverySourceRow,
    build_discovery_snapshot,
)
from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_CONFIRMED,
    BREAKOUT_FORMING,
    ENTRY_MISSED,
    EXECUTION_ELIGIBLE,
    IMPULSE_DETECTED,
    MONITORING_ACTIVATED,
    SETUP_IDENTITY_CHANGED,
    SETUP_STATE_CHANGED,
    WATCHING,
    CandidateLifecycleCoordinator,
    CandidateLifecyclePolicy,
    CandidateLifecycleStore,
    expected_opportunity_id,
)
from momentum_hunter.hot_universe import HotUniversePolicy, HotUniverseStore
from momentum_hunter.intraday_trade_plan import CONTINUATION_BREAKOUT, PULLBACK
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.time_utils import CENTRAL_TZ
from momentum_hunter.workstation_read_models import (
    COMMAND_CENTER_POPULATION_CONTRACT_VERSION,
    WorkstationReadModelPaths,
    build_read_only_workspace_snapshot,
    order_command_center_lifecycle_events,
    producer_setup_corroboration,
)


BASE = datetime(2026, 8, 17, 10, 0, tzinfo=CENTRAL_TZ)
FAMILY = "CONTINUOUS_HOT_UNIVERSE"


class CommandCenterReadModelTests(unittest.TestCase):
    def test_populations_use_exact_machine_identities_and_first_disposition_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            member_id = write_hot_universe(paths, symbols=("ABC",))
            lifecycle = lifecycle_for(paths, "ABC")
            first_accepted = lifecycle.transition(
                opportunity_id=lifecycle.opportunity_id,
                next_state=EXECUTION_ELIGIBLE,
                evidence_fingerprint="f" * 64,
                source_identity="canonical-bars",
                occurred_at=BASE + timedelta(minutes=5),
                provider_timestamp=BASE + timedelta(minutes=5),
                receipt_timestamp=BASE + timedelta(minutes=5),
                reason="FIRST_EXECUTION_ELIGIBLE",
                material_delta_kind=SETUP_STATE_CHANGED,
            ).event
            first_rejected = lifecycle.transition(
                opportunity_id=lifecycle.opportunity_id,
                next_state=ENTRY_MISSED,
                evidence_fingerprint="1" * 64,
                source_identity="canonical-bars",
                occurred_at=BASE + timedelta(minutes=6),
                provider_timestamp=BASE + timedelta(minutes=6),
                receipt_timestamp=BASE + timedelta(minutes=6),
                reason="FIRST_ENTRY_MISSED",
                material_delta_kind=SETUP_STATE_CHANGED,
            ).event
            write_report(paths, "ABC")

            snapshot = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE + timedelta(minutes=10),
                chart_service=StoredChartStub(),
            )["commandCenter"]

            self.assertEqual(COMMAND_CENTER_POPULATION_CONTRACT_VERSION, snapshot["populationContractVersion"])
            self.assertEqual("AVAILABLE", snapshot["sourceCoverage"]["radar"])
            radar = self.assert_single(snapshot["radarMembers"])
            self.assertEqual(member_id, radar["radarPresentationIdentity"])
            self.assertEqual(
                expected_opportunity_id("ABC", "2026-08-17", FAMILY),
                radar["derivedLifecycleOpportunityId"],
            )
            hot_event = next(
                item for item in snapshot["lifecycleEvents"]
                if item["sourceKind"] == "HOT_UNIVERSE"
            )
            self.assertEqual("", hot_event["opportunityId"])
            self.assertEqual(member_id, hot_event["radarMemberIdentity"])
            self.assertEqual(
                radar["derivedLifecycleOpportunityId"],
                hot_event["derivedLifecycleOpportunityId"],
            )
            self.assertNotEqual(
                hot_event["radarMemberIdentity"],
                hot_event["derivedLifecycleOpportunityId"],
            )
            self.assertIsInstance(hot_event["sourceSequence"], int)
            accepted_event = next(
                item for item in snapshot["lifecycleEvents"]
                if item["eventIdentity"] == first_accepted.event_id
            )
            self.assertEqual(first_accepted.sequence, accepted_event["sourceSequence"])
            accepted = self.assert_single(snapshot["acceptedDispositions"])
            rejected = self.assert_single(snapshot["rejectedDispositions"])
            self.assertEqual(first_accepted.event_id, accepted["dispositionEventId"])
            self.assertEqual("FIRST_EXECUTION_ELIGIBLE", accepted["reason"])
            self.assertEqual(first_rejected.event_id, rejected["dispositionEventId"])
            self.assertEqual("FIRST_ENTRY_MISSED", rejected["reason"])
            ranked = self.assert_single(snapshot["rankedCandidates"])
            self.assertEqual(1, ranked["sourceRank"])
            self.assertEqual(91, ranked["score"])
            self.assertEqual(member_id, ranked["radarMemberIdentity"])
            self.assertEqual([accepted["dispositionPresentationIdentity"]], ranked["acceptedDispositionIds"])
            self.assertEqual([rejected["dispositionPresentationIdentity"]], ranked["rejectedDispositionIds"])

    def test_excluded_states_and_discovery_filter_text_never_create_rejected_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_hot_universe(paths, symbols=("ABC",))
            lifecycle_for(paths, "ABC")
            write_report(paths, "ABC", readiness="REJECTED_FILTER", notes=["readiness blocker", "risk denied"])

            command_center = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE + timedelta(minutes=10),
                chart_service=StoredChartStub(),
            )["commandCenter"]

            self.assertEqual([], command_center["rejectedDispositions"])
            self.assertEqual("AVAILABLE", command_center["sourceCoverage"]["rejected"])

    def test_missing_lifecycle_preserves_radar_but_marks_dispositions_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_hot_universe(paths, symbols=("ABC",))

            command_center = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE,
                chart_service=StoredChartStub(),
            )["commandCenter"]

            self.assertEqual("AVAILABLE", command_center["sourceCoverage"]["radar"])
            self.assertEqual("UNAVAILABLE", command_center["sourceCoverage"]["accepted"])
            self.assertEqual("UNAVAILABLE", command_center["sourceCoverage"]["rejected"])
            self.assertEqual([], command_center["acceptedDispositions"])

    def test_unmatched_continuous_opportunity_fails_dispositions_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_hot_universe(paths, symbols=("ABC",))
            lifecycle_for(paths, "XYZ")

            command_center = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE,
                chart_service=StoredChartStub(),
            )["commandCenter"]

            self.assertEqual("AVAILABLE", command_center["sourceCoverage"]["radar"])
            self.assertEqual("UNAVAILABLE", command_center["sourceCoverage"]["accepted"])
            self.assertTrue(any("deterministic" in item for item in command_center["limitations"]))

    def test_new_hot_universe_generation_gets_a_new_radar_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            store_path = hot_path(paths)
            store = HotUniverseStore(store_path)
            policy = HotUniversePolicy(maximum_consecutive_absent_observations=0)
            first = store.apply_snapshot(policy=policy, snapshot=discovery(0, ("ABC",)))
            first_id = next(item.member_id for item in first.state.members if item.current_state == "TRACKED")
            store.apply_snapshot(policy=policy, snapshot=discovery(1, ()))
            readmitted = store.apply_snapshot(policy=policy, snapshot=discovery(2, ("ABC",)))
            second_id = next(item.member_id for item in readmitted.state.members if item.current_state == "TRACKED")

            command_center = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE + timedelta(minutes=3),
                chart_service=StoredChartStub(),
            )["commandCenter"]

            self.assertNotEqual(first_id, second_id)
            self.assertEqual(second_id, self.assert_single(command_center["radarMembers"])["radarPresentationIdentity"])

    def test_microcharts_keep_last_two_source_sessions_and_missing_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_report(paths, "ABC")
            command_center = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE,
                chart_service=StoredChartStub(),
            )["commandCenter"]
            series = command_center["miniChartsBySymbol"]["ABC"]
            self.assertEqual(["2026-08-14", "2026-08-17"], series["sourceSessionDates"])
            self.assertEqual(4, len(series["points"]))
            self.assertEqual("AVAILABLE", series["state"])

            missing_snapshot = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE,
                chart_service=MissingChartStub(),
            )["commandCenter"]
            missing = missing_snapshot["miniChartsBySymbol"]["ABC"]
            self.assertEqual("UNAVAILABLE", missing["state"])
            self.assertEqual([], missing["points"])
            self.assertEqual("UNAVAILABLE", missing_snapshot["sourceCoverage"]["miniCharts"])
            self.assertEqual([1], [item["sourceRank"] for item in missing_snapshot["rankedCandidates"]])

    def test_missing_or_invalid_ranked_score_remains_unavailable(self) -> None:
        for source_score in (None, "not-a-score"):
            with self.subTest(source_score=source_score), tempfile.TemporaryDirectory() as directory:
                paths = make_paths(Path(directory))
                write_report(paths, "ABC", score=source_score)

                command_center = build_read_only_workspace_snapshot(
                    paths=paths,
                    observed_at=BASE,
                    chart_service=StoredChartStub(),
                )["commandCenter"]

                ranked = self.assert_single(command_center["rankedCandidates"])
                self.assertIsNone(ranked["score"])
                self.assertEqual("PARTIAL", command_center["sourceCoverage"]["rankedCandidates"])
                self.assertTrue(
                    any("score remains unavailable" in item for item in command_center["limitations"])
                )

    def test_successor_setup_is_independent_and_histories_survive_radar_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_hot_universe(paths, symbols=("ABC",))
            lifecycle = lifecycle_for(paths, "ABC")
            original_accepted = lifecycle.transition(
                opportunity_id=lifecycle.opportunity_id,
                next_state=EXECUTION_ELIGIBLE,
                evidence_fingerprint="f" * 64,
                source_identity="canonical-bars",
                occurred_at=BASE + timedelta(minutes=5),
                provider_timestamp=BASE + timedelta(minutes=5),
                receipt_timestamp=BASE + timedelta(minutes=5),
                reason="ORIGINAL_ELIGIBLE",
                material_delta_kind=SETUP_STATE_CHANGED,
            ).event
            original_rejected = lifecycle.transition(
                opportunity_id=lifecycle.opportunity_id,
                next_state=ENTRY_MISSED,
                evidence_fingerprint="1" * 64,
                source_identity="canonical-bars",
                occurred_at=BASE + timedelta(minutes=6),
                provider_timestamp=BASE + timedelta(minutes=6),
                receipt_timestamp=BASE + timedelta(minutes=6),
                reason="ORIGINAL_MISSED",
                material_delta_kind=SETUP_STATE_CHANGED,
            ).event
            successor = lifecycle.transition(
                opportunity_id=lifecycle.opportunity_id,
                next_state="PULLBACK_FORMING",
                evidence_fingerprint="2" * 64,
                source_identity="canonical-bars",
                occurred_at=BASE + timedelta(minutes=7),
                provider_timestamp=BASE + timedelta(minutes=7),
                receipt_timestamp=BASE + timedelta(minutes=7),
                reason="NEW_PULLBACK_SETUP",
                material_delta_kind=SETUP_IDENTITY_CHANGED,
                setup_family=PULLBACK,
                create_new_setup=True,
            ).event
            successor_accepted = lifecycle.transition(
                opportunity_id=lifecycle.opportunity_id,
                next_state=EXECUTION_ELIGIBLE,
                evidence_fingerprint="3" * 64,
                source_identity="canonical-bars",
                occurred_at=BASE + timedelta(minutes=8),
                provider_timestamp=BASE + timedelta(minutes=8),
                receipt_timestamp=BASE + timedelta(minutes=8),
                reason="SUCCESSOR_ELIGIBLE",
                material_delta_kind=SETUP_STATE_CHANGED,
            ).event
            store = HotUniverseStore(hot_path(paths))
            for minute in (9, 10, 11):
                store.apply_snapshot(
                    policy=HotUniversePolicy(),
                    snapshot=discovery(minute, ()),
                )
            write_report(paths, "ABC")

            command_center = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE + timedelta(minutes=10),
                chart_service=StoredChartStub(),
            )["commandCenter"]

            self.assertEqual([], command_center["radarMembers"])
            self.assertEqual(
                {original_accepted.setup_id, successor.setup_id},
                {item["setupId"] for item in command_center["acceptedDispositions"]},
            )
            self.assertEqual(
                [original_rejected.setup_id],
                [item["setupId"] for item in command_center["rejectedDispositions"]],
            )
            self.assertEqual(successor.setup_id, successor_accepted.setup_id)

    def test_wrong_family_for_current_member_fails_dispositions_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_hot_universe(paths, symbols=("ABC",))
            coordinator = CandidateLifecycleCoordinator(
                CandidateLifecycleStore(lifecycle_path(paths)),
                policy=CandidateLifecyclePolicy("test-policy-v1", 60, "test-hysteresis-v1", "test-delta-v1"),
            )
            coordinator.discover(
                symbol="ABC",
                session_date="2026-08-17",
                originating_evidence_family="OTHER_DISCOVERY_FAMILY",
                evidence_fingerprint="a" * 64,
                source_identity="other-source",
                occurred_at=BASE,
                provider_timestamp=BASE,
                receipt_timestamp=BASE,
                reason="OTHER_DISCOVERY",
            )

            command_center = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=BASE,
                chart_service=StoredChartStub(),
            )["commandCenter"]

            self.assertEqual("UNAVAILABLE", command_center["sourceCoverage"]["accepted"])
            self.assertTrue(any("non-authoritative" in item for item in command_center["limitations"]))

    def test_producer_proposal_is_optional_but_any_present_contradiction_fails_closed(self) -> None:
        member_id = "hot-member-ABC-2026-08-17-g1"
        member = SimpleNamespace(symbol="ABC", session_date="2026-08-17")
        opportunity_id = expected_opportunity_id("ABC", "2026-08-17", FAMILY)

        def record(setup_id: str, proposal: dict | None):
            payload = {
                "compositionCycle": {
                    "member_results": [
                        {
                            "universe_member_id": member_id,
                            "symbol": "ABC",
                            "session_date": "2026-08-17",
                            "lifecycle_proposal": proposal,
                        }
                    ]
                }
            }
            return SimpleNamespace(
                record_id=f"record-{setup_id or 'none'}",
                member_id=member_id,
                symbol="ABC",
                session_date="2026-08-17",
                setup_id=setup_id,
                payload_json=json.dumps(payload),
            )

        absent, absent_limitations = producer_setup_corroboration(
            (record("", None),),
            session_date="2026-08-17",
            members_by_id={member_id: member},
        )
        valid, valid_limitations = producer_setup_corroboration(
            (
                record(
                    "setup-1",
                    {
                        "opportunity_id": opportunity_id,
                        "setup_id": "setup-1",
                        "symbol": "ABC",
                        "session_date": "2026-08-17",
                    },
                ),
            ),
            session_date="2026-08-17",
            members_by_id={member_id: member},
        )
        _, contradictory = producer_setup_corroboration(
            (
                record(
                    "setup-1",
                    {
                        "opportunity_id": "wrong-opportunity",
                        "setup_id": "setup-1",
                        "symbol": "ABC",
                        "session_date": "2026-08-17",
                    },
                ),
            ),
            session_date="2026-08-17",
            members_by_id={member_id: member},
        )

        self.assertEqual(set(), absent)
        self.assertEqual([], absent_limitations)
        self.assertEqual({(opportunity_id, "setup-1")}, valid)
        self.assertEqual([], valid_limitations)
        self.assertTrue(any("contradicts" in item for item in contradictory))

    def test_lifecycle_chronology_uses_sequence_only_within_same_source(self) -> None:
        occurred_at = "2026-08-17T15:00:00Z"

        def event(
            identity: str,
            source_kind: str,
            source_sequence: int | None,
            previous_state: str,
            next_state: str,
            timestamp: str | None = None,
        ) -> dict:
            return {
                "eventIdentity": identity,
                "sourceKind": source_kind,
                "sourceSequence": source_sequence,
                "occurredAt": timestamp or occurred_at,
                "previousState": previous_state,
                "nextState": next_state,
            }

        events = [
            event("newest", "HOT_UNIVERSE", 1, "", "", "2026-08-17T15:01:00Z"),
            event("hot-low", "HOT_UNIVERSE", 1, "ZZZ", "AAA"),
            event("candidate-low", "CANDIDATE_LIFECYCLE", 2, "AAA", "ZZZ"),
            event("candidate-tie-b", "CANDIDATE_LIFECYCLE", 5, "B", "A"),
            event("hot-high", "HOT_UNIVERSE", 7, "STATE_2", "STATE_1"),
            event("candidate-tie-a", "CANDIDATE_LIFECYCLE", 5, "A", "B"),
            event("candidate-high", "CANDIDATE_LIFECYCLE", 9, "STATE_1", "STATE_2"),
            event("candidate-no-sequence", "CANDIDATE_LIFECYCLE", None, "", ""),
        ]
        expected = [
            "newest",
            "candidate-high",
            "candidate-tie-a",
            "candidate-tie-b",
            "candidate-low",
            "candidate-no-sequence",
            "hot-high",
            "hot-low",
        ]

        ordered = order_command_center_lifecycle_events(events)
        reshuffled_with_different_state_text = [
            {**item, "previousState": f"IGNORED_{index}", "nextState": "ALSO_IGNORED"}
            for index, item in enumerate(reversed(events))
        ]

        self.assertEqual(expected, [item["eventIdentity"] for item in ordered])
        self.assertEqual(
            expected,
            [
                item["eventIdentity"]
                for item in order_command_center_lifecycle_events(
                    reshuffled_with_different_state_text
                )
            ],
        )

        unrelated_sources = [
            event("candidate", "CANDIDATE_LIFECYCLE", 1, "", ""),
            event("hot", "HOT_UNIVERSE", 999, "", ""),
        ]
        swapped_unrelated_sequences = [
            {**unrelated_sources[0], "sourceSequence": 999},
            {**unrelated_sources[1], "sourceSequence": 1},
        ]
        self.assertEqual(
            ["candidate", "hot"],
            [item["eventIdentity"] for item in order_command_center_lifecycle_events(unrelated_sources)],
        )
        self.assertEqual(
            ["candidate", "hot"],
            [
                item["eventIdentity"]
                for item in order_command_center_lifecycle_events(
                    swapped_unrelated_sequences
                )
            ],
        )

    @staticmethod
    def assert_single(values: list[dict]) -> dict:
        if len(values) != 1:
            raise AssertionError(f"Expected one value, found {len(values)}")
        return values[0]


class LifecycleHarness:
    def __init__(self, coordinator: CandidateLifecycleCoordinator, opportunity_id: str) -> None:
        self.coordinator = coordinator
        self.opportunity_id = opportunity_id

    def transition(self, **kwargs):
        return self.coordinator.transition(**kwargs)


def lifecycle_for(paths: WorkstationReadModelPaths, symbol: str) -> LifecycleHarness:
    policy = CandidateLifecyclePolicy("test-policy-v1", 60, "test-hysteresis-v1", "test-delta-v1")
    coordinator = CandidateLifecycleCoordinator(CandidateLifecycleStore(lifecycle_path(paths)), policy=policy)
    discovered = coordinator.discover(
        symbol=symbol,
        session_date="2026-08-17",
        originating_evidence_family=FAMILY,
        evidence_fingerprint="a" * 64,
        source_identity="continuous-hot-universe",
        occurred_at=BASE,
        provider_timestamp=BASE,
        receipt_timestamp=BASE,
        reason="NATURAL_HOT_UNIVERSE_ADMISSION",
    )
    opportunity_id = discovered.snapshot.opportunity_id
    for minute, state, evidence, delta, family in (
        (1, WATCHING, "b" * 64, MONITORING_ACTIVATED, ""),
        (2, IMPULSE_DETECTED, "c" * 64, SETUP_STATE_CHANGED, ""),
        (3, BREAKOUT_FORMING, "d" * 64, SETUP_IDENTITY_CHANGED, CONTINUATION_BREAKOUT),
        (4, BREAKOUT_CONFIRMED, "e" * 64, SETUP_STATE_CHANGED, ""),
    ):
        coordinator.transition(
            opportunity_id=opportunity_id,
            next_state=state,
            evidence_fingerprint=evidence,
            source_identity="canonical-bars",
            occurred_at=BASE + timedelta(minutes=minute),
            provider_timestamp=BASE + timedelta(minutes=minute),
            receipt_timestamp=BASE + timedelta(minutes=minute),
            reason=f"TO_{state}",
            material_delta_kind=delta,
            setup_family=family,
        )
    return LifecycleHarness(coordinator, opportunity_id)


def make_paths(root: Path) -> WorkstationReadModelPaths:
    data = root / "data"
    reports = data / "reports"
    reports.mkdir(parents=True)
    runtime = root / "runtime"
    return WorkstationReadModelPaths(
        data,
        reports,
        data / "active-monitor-status.json",
        data / "opportunity-alerts.json",
        runtime,
    )


def hot_path(paths: WorkstationReadModelPaths) -> Path:
    return paths.continuous_runtime_state_root / "session" / "state" / "hot-universe.json"


def lifecycle_path(paths: WorkstationReadModelPaths) -> Path:
    return paths.continuous_runtime_state_root / "session" / "state" / "continuous-natural-setup" / "candidate-lifecycle.json"


def write_hot_universe(paths: WorkstationReadModelPaths, *, symbols: tuple[str, ...]) -> str:
    result = HotUniverseStore(hot_path(paths)).apply_snapshot(
        policy=HotUniversePolicy(),
        snapshot=discovery(0, symbols),
    )
    return next(item.member_id for item in result.state.members if item.current_state == "TRACKED")


def discovery(minute: int, symbols: tuple[str, ...]):
    observed = BASE + timedelta(minutes=minute)
    rows = []
    for ordinal, symbol in enumerate(symbols, start=1):
        rows.append(
            DiscoverySourceRow.from_mapping(
                source_row_ordinal=ordinal,
                source_row_identity=f"{symbol}-{ordinal}-{observed.isoformat()}",
                source_values={"Ticker": symbol, "No.": str(ordinal)},
                candidate=Candidate(
                    ticker=symbol,
                    company=f"{symbol} Incorporated",
                    price=20.0,
                    percent_change=5.0,
                    volume=10_000_000,
                    relative_volume=2.0,
                    market_cap=10_000_000_000,
                    sector="Technology",
                    industry="Software",
                ),
            )
        )
    return build_discovery_snapshot(
        source="finviz",
        source_version="test-contract-v1",
        requested_at=observed - timedelta(seconds=2),
        received_at=observed - timedelta(seconds=1),
        evaluated_at=observed,
        query_identity=DiscoveryQueryIdentity.from_criteria(
            INSTITUTIONAL_MOMENTUM,
            source_query="test://bounded-discovery",
            sort_order="-volume",
        ),
        source_contract_fingerprint="2" * 64,
        semantic_plausibility_fingerprint="3" * 64,
        source_rows=rows,
    )


def write_report(
    paths: WorkstationReadModelPaths,
    symbol: str,
    *,
    readiness: str = "EXECUTION_READY",
    notes: list[str] | None = None,
    score: object = 91,
) -> None:
    payload = {
        "metadata": {
            "generated_at": "2026-08-17T15:05:00Z",
            "source_capture_time": "2026-08-17T10:00:00-05:00",
            "source_session": "opening",
        },
        "candidates": [
            {
                "rank": 1,
                "symbol": symbol,
                "company": f"{symbol} Incorporated",
                "market_data": {"last_price": 21.0, "premarket_percent": 4.0, "relative_volume": 2.2},
                "scoring": {"composite_score": score, "catalyst_summary": "Stored catalyst"},
                "trade_plan": {"readiness": readiness},
                "opportunity_notes": notes or [],
            }
        ],
    }
    (paths.reports_dir / "trade-plan-briefing-2026-08-17-opening.json").write_text(json.dumps(payload), encoding="utf-8")


class StoredChartStub:
    def snapshot(self, symbol: str, interval: str, *, observed_at: datetime):
        candles = []
        for session_date, day in (("2026-08-13", 13), ("2026-08-14", 14), ("2026-08-17", 17)):
            for minute, close in ((30, 20.0), (45, 21.0)):
                candles.append(
                    {
                        "sessionDate": session_date,
                        "timestamp": f"2026-08-{day:02d}T14:{minute}:00Z",
                        "close": close,
                    }
                )
        return {
            "symbol": symbol,
            "state": "AVAILABLE",
            "candles": candles,
            "quality": {"gapCount": 0, "correctionCount": 0, "findings": []},
            "lineage": {"sourceLabel": "Stored canonical candles; no provider call."},
        }


class MissingChartStub:
    def snapshot(self, symbol: str, interval: str, *, observed_at: datetime):
        return {
            "symbol": symbol,
            "state": "UNAVAILABLE",
            "summary": "No stored candles are available.",
            "candles": [],
            "quality": {"gapCount": 0, "correctionCount": 0, "findings": []},
            "lineage": {"sourceLabel": "Stored canonical candles; no provider call."},
        }


if __name__ == "__main__":
    unittest.main()
