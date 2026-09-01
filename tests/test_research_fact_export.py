from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.research_fact_export import (
    AUTHORITY,
    COVERAGE_METRIC_IDS,
    EXECUTION_AUTHORITY,
    OUTCOME_HORIZONS,
    SCHEMA_VERSION,
    ZERO_SHA256,
    QualificationInterruption,
    ResearchFactConflict,
    ResearchFactExportError,
    ResearchFactExportStore,
    build_envelope,
    canonical_json_bytes,
    evidence_absent,
    evidence_present,
    fingerprint,
    instrument_identity,
    outcome_followup_policy,
    owner_identity,
    recorder_identity,
    time_evidence,
    validate_envelope,
    validate_evidence_value,
    validate_outcome_followup_policy,
    validate_time_evidence,
)


T_DISCOVERY = "2026-08-31T14:59:00.000Z"
T_KNOWN = "2026-08-31T14:59:30.000Z"
T_CUTOFF = "2026-08-31T15:00:00.000Z"
T_DECISION = "2026-08-31T15:00:01.000Z"
T_OUTCOME = "2026-08-31T15:05:00.000Z"


def h(label: str) -> str:
    return fingerprint({"fixture": label})


class FixtureFactory:
    def __init__(self) -> None:
        self.session = recorder_identity(
            "SESSION",
            {"market_date": "2026-08-31", "runtime_instance": "qualification-fixture"},
        )
        self.session_id = self.session["recorder_id"]
        self.policy = outcome_followup_policy(
            policy_id="outcome-policy-fixture",
            policy_version="1",
            eligibility_mode="ALL_UNIQUE_INSTRUMENTS",
            exchange_calendar_id_and_version="XNYS-2026.1",
            bar_interval_semantic="ONE_MINUTE_REGULAR_SESSION",
            source_priority=("OWNER_MARKET_FACTS_V1",),
            provider_owner_load_limit=evidence_present(100, "OWNER_RUNTIME"),
            retry_and_finalization_cutoff={
                "authority": "EXCHANGE_CALENDAR",
                "bounded_policy": "SESSION_CLOSE_PLUS_10M",
            },
        )
        self.cycle = recorder_identity(
            "DISCOVERY_CYCLE",
            {"session_id": self.session_id, "source_attempt": "cycle-0001"},
        )
        self.observation = recorder_identity(
            "OBSERVATION",
            {"cycle_id": self.cycle["recorder_id"], "source_row_ordinal": 0},
        )
        self.setup = owner_identity("SETUP", "OPENING_ENGINE", "setup-0001")
        self.decision = owner_identity("DECISION", "OPENING_ENGINE", "decision-0001")
        self.tradeplan = owner_identity("TRADEPLAN", "OPENING_ENGINE", "plan-0001")
        self.reference_plan = recorder_identity(
            "REFERENCE_PLAN",
            {"decision_id": self.decision["recorder_id"], "owner_plan_id": "plan-0001"},
        )
        self.market_snapshot = owner_identity(
            "MARKET_SNAPSHOT", "OWNER_MARKET_FACTS", "snapshot-0001"
        )
        self.outcome_series = recorder_identity(
            "OUTCOME_SERIES",
            {"session_id": self.session_id, "instrument_security_id": "US0378331005"},
        )
        self.provider_event = recorder_identity(
            "PROVIDER_HEALTH_EVENT",
            {"session_id": self.session_id, "owner_event_id": "health-0001"},
        )
        self.instrument = instrument_identity(
            symbol=evidence_present("AAPL", "OWNER_DISCOVERY"),
            asset_type=evidence_present("EQUITY", "OWNER_DISCOVERY"),
            venue_or_exchange=evidence_present("NASDAQ", "OWNER_DISCOVERY"),
            authoritative_security_id=evidence_present("US0378331005", "OWNER_DISCOVERY"),
            currency=evidence_present("USD", "OWNER_DISCOVERY"),
        )

    def session_start(self) -> dict[str, object]:
        return {
            "authority": AUTHORITY,
            "config_fingerprint_sha256": h("config"),
            "execution_authority": EXECUTION_AUTHORITY,
            "market_calendar_id_and_version": "XNYS-2026.1",
            "market_date": "2026-08-31",
            "policy_fingerprint_sha256": self.policy["policy_sha256"],
            "runtime_fingerprint_sha256": h("runtime"),
            "session_id": self.session_id,
        }

    def store(self, root: Path, *, protected_roots: tuple[Path, ...] = ()) -> ResearchFactExportStore:
        store = ResearchFactExportStore(
            root,
            market_date="2026-08-31",
            session_id=self.session_id,
            protected_roots=protected_roots,
        )
        store.initialize(self.session_start())
        return store

    def base(
        self,
        record_type: str,
        record_id: dict[str, object],
        *,
        envelope_id: str,
        record_sequence: int,
        availability: str = "PRESENT",
    ) -> dict[str, object]:
        return {
            "availability": availability,
            "partition_id": "2026-08-31/qualification-fixture",
            "producer_export_envelope_id": envelope_id,
            "record_id": record_id,
            "record_sequence": record_sequence,
            "record_type": record_type,
            "recorder_capture_time": time_evidence(
                "RECORDER_CAPTURE_TIME", T_DECISION, "EXPORT_PRODUCER"
            ),
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session,
            "source_fingerprint_sha256": h(f"source-{record_type}-{record_sequence}"),
            "source_owner": "OWNER_RUNTIME",
            "source_record_identity": evidence_present(
                f"owner:{record_type}:{record_sequence}", "OWNER_RUNTIME"
            ),
        }

    def eligibility(
        self,
        observation: dict[str, object] | None = None,
        instrument: dict[str, object] | None = None,
    ) -> dict[str, object]:
        observation = observation or self.observation
        instrument = instrument or self.instrument
        semantic = {
            "committed_at": time_evidence("DISCOVERY_TIME", T_DISCOVERY, "OWNER_RUNTIME"),
            "eligibility_state": "ELIGIBLE",
            "first_observation_id": observation,
            "instrument_identity_fingerprint_sha256": instrument[
                "instrument_identity_fingerprint_sha256"
            ],
            "policy_id": self.policy["policy_id"],
            "policy_sha256": self.policy["policy_sha256"],
            "policy_version": self.policy["policy_version"],
        }
        return {**semantic, "commitment_payload_sha256": fingerprint(semantic)}

    def observation_record(
        self,
        *,
        envelope_id: str,
        ordinal: int = 0,
        observation: dict[str, object] | None = None,
        setup: dict[str, object] | None = None,
        symbol: str = "AAPL",
    ) -> dict[str, object]:
        observation = observation or self.observation
        setup = setup or self.setup
        instrument = self.instrument
        if symbol != "AAPL":
            instrument = instrument_identity(
                symbol=evidence_present(symbol, "OWNER_DISCOVERY"),
                asset_type=evidence_present("EQUITY", "OWNER_DISCOVERY"),
                venue_or_exchange=evidence_present("NASDAQ", "OWNER_DISCOVERY"),
                authoritative_security_id=evidence_present(
                    f"SECURITY-{symbol}-{ordinal}", "OWNER_DISCOVERY"
                ),
            )
        return {
            **self.base(
                "candidate-observation",
                observation,
                envelope_id=envelope_id,
                record_sequence=ordinal + 1,
            ),
            "candidate_facts": {
                "gap_percent": evidence_present("4.25", "OWNER_DISCOVERY"),
                "float": evidence_absent(
                    "NOT_OBSERVED", "OWNER_DISCOVERY", "SOURCE_DID_NOT_EXPOSE"
                ),
                "market_cap": evidence_absent(
                    "NOT_OBSERVED", "OWNER_DISCOVERY", "SOURCE_DID_NOT_EXPOSE"
                ),
                "persisted_score": evidence_present("81.5", "OWNER_SCORER"),
                "price": evidence_present("192.50", "OWNER_DISCOVERY"),
                "rvol": evidence_present("2.10", "OWNER_DISCOVERY"),
                "score_version": evidence_present("momentum-score-v1", "OWNER_SCORER"),
                "volume": evidence_present(1000000, "OWNER_DISCOVERY"),
            },
            "candidate_or_setup_identity": setup,
            "discovery_cycle_id": self.cycle,
            "discovery_time": time_evidence(
                "DISCOVERY_TIME", T_DISCOVERY, "OWNER_DISCOVERY"
            ),
            "instrument_identity": instrument,
            "materially_evaluated": True,
            "observation_id": observation,
            "outcome_eligibility": self.eligibility(observation, instrument),
            "rank": evidence_present(ordinal + 1, "OWNER_DISCOVERY"),
            "rejection_or_gap_reasons": [],
            "source_row_fingerprint_sha256": h(f"row-{ordinal}-{symbol}"),
            "source_row_ordinal": ordinal,
        }

    def discovery_envelope(
        self,
        *,
        state: str = "COMPLETE",
        observations: list[dict[str, object]] | None = None,
        source_event_id: str = "owner-discovery-cycle-0001",
        source_sequence: int = 0,
        previous: str = ZERO_SHA256,
    ) -> dict[str, object]:
        if observations is None:
            observations = [self.observation_record(envelope_id=source_event_id)]
        ids = [record["observation_id"] for record in observations]
        zero_result = state == "ZERO_RESULT"
        cycle = {
            **self.base(
                "discovery-cycle",
                self.cycle,
                envelope_id=source_event_id,
                record_sequence=0,
                availability="FAILED" if state == "FAILED" else "PRESENT",
            ),
            "completeness": (
                evidence_absent(state, "OWNER_DISCOVERY", f"CYCLE_{state}")
                if state in {"PARTIAL", "FAILED"}
                else evidence_present(state, "OWNER_DISCOVERY")
            ),
            "cycle_state": state,
            "discovery_cycle_id": self.cycle,
            "discovery_time": time_evidence(
                "DISCOVERY_TIME", T_DISCOVERY, "OWNER_DISCOVERY"
            ),
            "observation_ids_in_source_order": ids,
            "provider_health_event_ids": [],
            "provider_received_at": time_evidence(
                "PROVIDER_RECEIVED_AT", T_KNOWN, "OWNER_DISCOVERY"
            ),
            "query_or_policy_fingerprint_sha256": h("query-policy"),
            "returned_row_count": len(observations),
            "row_order_complete": evidence_present(state != "PARTIAL", "OWNER_DISCOVERY"),
            "zero_result": zero_result,
        }
        return build_envelope(
            event_type="DISCOVERY_CYCLE",
            stream_id="owner-discovery-stream",
            session_id=self.session_id,
            source_contract="OWNER_DISCOVERY_CONTRACT",
            source_contract_version="1",
            source_event_id=source_event_id,
            source_event_fingerprint_sha256=h(source_event_id),
            source_sequence=source_sequence,
            event_time=T_DISCOVERY,
            effective_known_at=T_KNOWN,
            emitted_at=T_KNOWN,
            previous_record_sha256=previous,
            records=[cycle, *observations],
        )

    def decision_envelope(
        self,
        *,
        source_event_id: str = "owner-decision-0001",
        source_sequence: int = 0,
        previous: str = ZERO_SHA256,
        decision: dict[str, object] | None = None,
        decision_state: str = "BLOCKED",
        known_at: str = T_KNOWN,
        with_plan: bool = False,
    ) -> dict[str, object]:
        decision = decision or self.decision
        plan_ref = (
            evidence_present(self.tradeplan, "OWNER_TRADEPLAN")
            if with_plan
            else evidence_absent("NOT_APPLICABLE", "OWNER_TRADEPLAN", "NO_CONTEMPORANEOUS_PLAN")
        )
        reference_ref = (
            evidence_present(self.reference_plan, "OWNER_TRADEPLAN")
            if with_plan
            else evidence_absent("NOT_APPLICABLE", "OWNER_TRADEPLAN", "NO_CONTEMPORANEOUS_PLAN")
        )
        decision_record = {
            **self.base(
                "decision-event",
                decision,
                envelope_id=source_event_id,
                record_sequence=100,
            ),
            "candidate_or_setup_identity": self.setup,
            "config_fingerprint_sha256": h("config"),
            "decision_cutoff": time_evidence(
                "DECISION_CUTOFF", T_CUTOFF, "OWNER_DECISION"
            ),
            "decision_id": decision,
            "decision_policy_fingerprint_sha256": h("decision-policy"),
            "decision_state": "TRADEPLAN" if with_plan else decision_state,
            "decision_time": time_evidence(
                "DECISION_TIME", T_DECISION, "OWNER_DECISION"
            ),
            "known_at_evidence_refs": [
                {
                    "evidence_field_path": "candidate_facts.price",
                    "known_at": time_evidence(
                        "PROVIDER_KNOWN_AT", known_at, "OWNER_MARKET_FACTS"
                    ),
                    "payload_sha256": h("known-price"),
                    "record_id": self.observation,
                }
            ],
            "market_snapshot_id": evidence_present(
                self.market_snapshot, "OWNER_MARKET_FACTS"
            ),
            "observation_id": self.observation,
            "outcome_eligibility_commitment_sha256": self.eligibility()[
                "commitment_payload_sha256"
            ],
            "reason_codes": [{"code": "RISK_BOUNDARY", "version": "1"}],
            "reference_plan_id": reference_ref,
            "runtime_fingerprint_sha256": h("runtime"),
            "strategy_identity": evidence_present(
                "MOMENTUM_HUNTER_CANONICAL", "OWNER_DECISION"
            ),
            "tradeplan_id": plan_ref,
        }
        records: list[dict[str, object]] = [decision_record]
        if with_plan:
            level = lambda name, value: evidence_present(
                {
                    "level_id": owner_identity(
                        "REFERENCE_LEVEL", "OWNER_TRADEPLAN", f"plan-0001-{name}"
                    ),
                    "provenance": "OWNER_PASSTHROUGH",
                    "value": value,
                },
                "OWNER_TRADEPLAN",
            )
            plan = {
                **self.base(
                    "reference-plan",
                    self.reference_plan,
                    envelope_id=source_event_id,
                    record_sequence=101,
                ),
                "candidate_or_setup_identity": self.setup,
                "decision_id": decision,
                "entry": level("entry", "192.50"),
                "plan_created_at": time_evidence(
                    "DECISION_TIME", T_DECISION, "OWNER_TRADEPLAN"
                ),
                "plan_owner": "OWNER_TRADEPLAN",
                "plan_schema_version": "1",
                "plan_source_fingerprint_sha256": h("owner-plan"),
                "reference_plan_id": self.reference_plan,
                "stop": level("stop", "190.00"),
                "t1": level("t1", "195.00"),
                "t2": level("t2", "197.50"),
                "tradeplan_id": self.tradeplan,
            }
            records.append(plan)
        return build_envelope(
            event_type="DECISION_FACT",
            stream_id="owner-decision-stream",
            session_id=self.session_id,
            source_contract="OWNER_DECISION_CONTRACT",
            source_contract_version="1",
            source_event_id=source_event_id,
            source_event_fingerprint_sha256=h(source_event_id),
            source_sequence=source_sequence,
            event_time=T_DECISION,
            effective_known_at=T_DECISION,
            emitted_at=T_DECISION,
            previous_record_sha256=previous,
            records=records,
        )

    def market_envelope(
        self,
        *,
        source_event_id: str = "owner-market-0001",
    ) -> dict[str, object]:
        record = {
            **self.base(
                "market-snapshot",
                self.market_snapshot,
                envelope_id=source_event_id,
                record_sequence=200,
            ),
            "decision_id": evidence_present(self.decision, "OWNER_DECISION"),
            "instrument_identity": self.instrument,
            "market_data_owner": "OWNER_MARKET_FACTS",
            "market_facts": {
                "ask": evidence_present("192.55", "OWNER_MARKET_FACTS"),
                "bar_close": evidence_absent(
                    "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
                ),
                "bar_complete": evidence_absent(
                    "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
                ),
                "bar_high": evidence_absent(
                    "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
                ),
                "bar_interval_end": evidence_absent(
                    "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
                ),
                "bar_interval_start": evidence_absent(
                    "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
                ),
                "bar_low": evidence_absent(
                    "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
                ),
                "bar_open": evidence_absent(
                    "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
                ),
                "bar_volume": evidence_absent(
                    "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
                ),
                "bid": evidence_present("192.45", "OWNER_MARKET_FACTS"),
                "mark": evidence_present("192.50", "OWNER_MARKET_FACTS"),
                "market_cap": evidence_absent(
                    "NOT_OBSERVED", "OWNER_MARKET_FACTS", "SOURCE_DID_NOT_EXPOSE"
                ),
                "persisted_score": evidence_present("81.5", "OWNER_SCORER"),
                "price": evidence_present("192.50", "OWNER_MARKET_FACTS"),
                "rvol": evidence_present("2.10", "OWNER_MARKET_FACTS"),
                "score_version": evidence_present("momentum-score-v1", "OWNER_SCORER"),
                "spread": evidence_present("0.10", "OWNER_MARKET_FACTS"),
                "volume": evidence_present(1000000, "OWNER_MARKET_FACTS"),
            },
            "market_snapshot_id": self.market_snapshot,
            "observation_id": evidence_present(self.observation, "OWNER_DISCOVERY"),
            "outcome_series_id": evidence_absent(
                "NOT_APPLICABLE", "OWNER_MARKET_FACTS", "DECISION_SNAPSHOT"
            ),
            "provider_known_at": time_evidence(
                "PROVIDER_KNOWN_AT", T_KNOWN, "OWNER_MARKET_FACTS"
            ),
            "provider_received_at": time_evidence(
                "PROVIDER_RECEIVED_AT", T_KNOWN, "OWNER_MARKET_FACTS"
            ),
            "snapshot_kind": "DECISION_SNAPSHOT",
            "source_event_time": time_evidence(
                "SOURCE_EVENT_TIME", T_KNOWN, "OWNER_MARKET_FACTS"
            ),
            "source_market_fact_fingerprint_sha256": h("market-fact"),
        }
        return build_envelope(
            event_type="MARKET_FACT",
            stream_id="owner-market-stream",
            session_id=self.session_id,
            source_contract="OWNER_MARKET_CONTRACT",
            source_contract_version="1",
            source_event_id=source_event_id,
            source_event_fingerprint_sha256=h(source_event_id),
            source_sequence=0,
            event_time=T_KNOWN,
            effective_known_at=T_KNOWN,
            emitted_at=T_KNOWN,
            previous_record_sha256=ZERO_SHA256,
            records=[record],
        )

    def provider_envelope(self) -> dict[str, object]:
        source_event_id = "owner-provider-health-0001"
        record = {
            **self.base(
                "provider-health-event",
                self.provider_event,
                envelope_id=source_event_id,
                record_sequence=300,
                availability="PROVIDER_FAILED",
            ),
            "affected_record_ids": [self.observation],
            "attempt_number": 1,
            "event_class": "SOURCE_OUTAGE",
            "event_state": "PROVIDER_FAILED",
            "interface_or_owner": "OWNER_MARKET_FACTS",
            "provider_health_event_id": self.provider_event,
            "provider_received_at": time_evidence(
                "PROVIDER_RECEIVED_AT", T_KNOWN, "OWNER_MARKET_FACTS"
            ),
            "reason_code": "UPSTREAM_TIMEOUT",
            "secret_material_present": False,
            "source_event_time": time_evidence(
                "SOURCE_EVENT_TIME", T_KNOWN, "OWNER_MARKET_FACTS"
            ),
            "terminal": True,
        }
        return build_envelope(
            event_type="PROVIDER_HEALTH",
            stream_id="owner-health-stream",
            session_id=self.session_id,
            source_contract="OWNER_HEALTH_CONTRACT",
            source_contract_version="1",
            source_event_id=source_event_id,
            source_event_fingerprint_sha256=h(source_event_id),
            source_sequence=0,
            event_time=T_KNOWN,
            effective_known_at=T_KNOWN,
            emitted_at=T_KNOWN,
            previous_record_sha256=ZERO_SHA256,
            records=[record],
        )

    def outcome_envelope(
        self,
        semantic: str,
        *,
        sequence: int = 0,
        previous: str = ZERO_SHA256,
        state: str = "PRESENT",
    ) -> dict[str, object]:
        source_event_id = f"owner-outcome-{semantic.lower()}"
        outcome_id = recorder_identity(
            "OUTCOME_OBSERVATION",
            {
                "decision_id": self.decision["recorder_id"],
                "outcome_semantic": semantic,
                "series_id": self.outcome_series["recorder_id"],
            },
        )
        value = (
            evidence_present("0.0125", "OWNER_MARKET_FACTS")
            if state == "PRESENT"
            else evidence_absent(state, "OWNER_MARKET_FACTS", state)
        )
        bars = (
            [
                owner_identity(
                    "MARKET_SNAPSHOT", "OWNER_MARKET_FACTS", f"bar-{semantic.lower()}"
                )
            ]
            if state == "PRESENT"
            else []
        )
        record = {
            **self.base(
                "outcome-observation",
                outcome_id,
                envelope_id=source_event_id,
                record_sequence=400 + sequence,
                availability=state,
            ),
            "candidate_or_setup_identity": self.setup,
            "canonical_bar_record_ids": bars,
            "canonical_path_fingerprint_sha256": h(f"path-{semantic}"),
            "decision_id": self.decision,
            "decision_payload_sha256": fingerprint(
                self.decision_envelope()["payload"]["records"][0]
            ),
            "eligibility_commitment_sha256": self.eligibility()[
                "commitment_payload_sha256"
            ],
            "linkage_receipt_sha256": h(f"linkage-{semantic}"),
            "observation_id": self.observation,
            "outcome_observation_id": outcome_id,
            "outcome_semantic": semantic,
            "outcome_semantic_version": "1",
            "outcome_series_id": self.outcome_series,
            "outcome_state": state,
            "outcome_time": time_evidence(
                "OUTCOME_TIME", T_OUTCOME, "OWNER_MARKET_FACTS"
            ),
            "outcome_value": value,
            "path_completeness": (
                evidence_present("COMPLETE", "OWNER_MARKET_FACTS")
                if state == "PRESENT"
                else evidence_absent(state, "OWNER_MARKET_FACTS", state)
            ),
            "target_time": time_evidence(
                "OUTCOME_TIME", T_OUTCOME, "EXCHANGE_CALENDAR"
            ),
            "transform_version": "RETURN_FROM_DECISION_REFERENCE_V1",
        }
        return build_envelope(
            event_type="MARKET_FACT",
            stream_id="owner-outcome-stream",
            session_id=self.session_id,
            source_contract="OWNER_OUTCOME_CONTRACT",
            source_contract_version="1",
            source_event_id=source_event_id,
            source_event_fingerprint_sha256=h(source_event_id),
            source_sequence=sequence,
            event_time=T_OUTCOME,
            effective_known_at=T_OUTCOME,
            emitted_at=T_OUTCOME,
            previous_record_sha256=previous,
            records=[record],
        )


class ResearchFactExportAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = FixtureFactory()

    def test_at_001_durable_session_identity_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "export"
            first = self.fx.store(root)
            partition = first.partition
            second = self.fx.store(root)
            self.assertEqual(partition, second.partition)
            self.assertEqual(self.fx.session_id, json.loads((partition / "manifests/session-start.json").read_text(encoding="utf-8"))["session_id"])

    def test_at_002_all_ordered_discovery_rows_retained(self) -> None:
        second_observation = recorder_identity(
            "OBSERVATION", {"cycle_id": self.fx.cycle["recorder_id"], "source_row_ordinal": 1}
        )
        second_setup = owner_identity("SETUP", "OPENING_ENGINE", "setup-0002")
        records = [
            self.fx.observation_record(envelope_id="ordered", ordinal=0),
            self.fx.observation_record(
                envelope_id="ordered", ordinal=1, observation=second_observation, setup=second_setup, symbol="MSFT"
            ),
        ]
        envelope = self.fx.discovery_envelope(observations=records, source_event_id="ordered")
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            store.append(envelope)
            restored = list(store.iter_verified_records())
            observations = [record for record in restored if record["record_type"] == "candidate-observation"]
            self.assertEqual([0, 1], [record["source_row_ordinal"] for record in observations])

    def test_at_003_zero_result_cycle_retained(self) -> None:
        envelope = self.fx.discovery_envelope(state="ZERO_RESULT", observations=[])
        cycle = envelope["payload"]["records"][0]
        self.assertTrue(cycle["zero_result"])
        self.assertEqual(0, cycle["returned_row_count"])
        validate_envelope(envelope)

    def test_at_004_partial_failed_and_repeated_cycle_behavior(self) -> None:
        partial = self.fx.discovery_envelope(state="PARTIAL")
        validate_envelope(partial)
        failed = self.fx.discovery_envelope(
            state="FAILED", observations=[], source_event_id="failed-cycle"
        )
        validate_envelope(failed)
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            first = store.append(partial)
            repeated = store.append(partial)
            self.assertEqual("APPENDED", first.status)
            self.assertEqual("IDEMPOTENT_ACK", repeated.status)

    def test_at_005_golden_identity_fixtures(self) -> None:
        first = recorder_identity("DECISION", {"owner": "fixture", "event": 7})
        second = recorder_identity("DECISION", {"event": 7, "owner": "fixture"})
        self.assertEqual(first, second)
        expected_material = {
            "identity_type": "DECISION",
            "logical_key": {"event": 7, "owner": "fixture"},
            "namespace": "argus-science-recorder-v1",
        }
        self.assertEqual(
            f"ar1:decision:{fingerprint(expected_material)}", first["recorder_id"]
        )

    def test_at_006_repeated_ticker_multiple_setups_separate(self) -> None:
        one = recorder_identity("SETUP", {"session": self.fx.session_id, "symbol": "AAPL", "ordinal": 1})
        two = recorder_identity("SETUP", {"session": self.fx.session_id, "symbol": "AAPL", "ordinal": 2})
        self.assertNotEqual(one["recorder_id"], two["recorder_id"])
        with self.assertRaises(ResearchFactExportError):
            recorder_identity("SETUP", {"symbol": "AAPL"})

    def test_at_007_complete_material_decision_freeze(self) -> None:
        envelope = self.fx.decision_envelope(with_plan=True)
        validate_envelope(envelope)
        late = copy.deepcopy(envelope)
        late["payload"]["records"][0]["known_at_evidence_refs"][0]["known_at"] = time_evidence(
            "PROVIDER_KNOWN_AT", "2026-08-31T15:00:02.000Z", "OWNER_MARKET_FACTS"
        )
        late["payload_sha256"] = fingerprint(late["payload"])
        with self.assertRaises(ResearchFactExportError):
            validate_envelope(late)

    def test_at_008_decision_bytes_immutable_after_outcome(self) -> None:
        first = self.fx.decision_envelope()
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            store.append(self.fx.discovery_envelope())
            store.append(first)
            store.append(self.fx.outcome_envelope("PLUS_5M"))
            changed = self.fx.decision_envelope(
                source_event_id="owner-decision-correction-bad",
                source_sequence=1,
                previous=fingerprint(first),
                decision_state="REJECTED",
            )
            with self.assertRaises(ResearchFactConflict):
                store.append(changed)

    def test_at_009_required_horizon_linkage(self) -> None:
        self.assertEqual(
            (
                "PLUS_5M",
                "PLUS_15M",
                "PLUS_30M",
                "PLUS_60M",
                "SESSION_CLOSE",
                "MFE",
                "MAE",
            ),
            OUTCOME_HORIZONS,
        )
        for horizon in OUTCOME_HORIZONS:
            validate_envelope(self.fx.outcome_envelope(horizon))

    def test_at_010_session_close_truncation_and_mfe_path(self) -> None:
        truncated = self.fx.outcome_envelope("PLUS_60M", state="SESSION_TRUNCATED")
        validate_envelope(truncated)
        mfe = self.fx.outcome_envelope("MFE")
        mfe["payload"]["records"][0]["canonical_bar_record_ids"] = []
        mfe["payload_sha256"] = fingerprint(mfe["payload"])
        with self.assertRaises(ResearchFactExportError):
            validate_envelope(mfe)

    def test_at_011_provider_failures_remain_evidence(self) -> None:
        envelope = self.fx.provider_envelope()
        validate_envelope(envelope)
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            store.append(envelope)
            snapshot = store.verify()
            self.assertEqual(1, snapshot["record_counts"]["provider-health-event"])
            self.assertEqual(1, snapshot["record_state_counts"]["PROVIDER_FAILED"])

    def test_at_012_no_science_provider_duplication(self) -> None:
        module_path = Path(__file__).parents[1] / "momentum_hunter" / "research_fact_export.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertFalse(imported & {"requests", "httpx", "schwab", "alpaca", "socket"})

    def test_at_013_restart_and_partial_write_recovery(self) -> None:
        first = self.fx.discovery_envelope()
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            with self.assertRaises(QualificationInterruption):
                store.append(first, _qualification_interrupt_after="payload")
            reopened = self.fx.store(Path(folder) / "export")
            recovered = reopened.recover()
            self.assertEqual(1, len(recovered))
            second = self.fx.provider_envelope()
            with self.assertRaises(QualificationInterruption):
                reopened.append(second, _qualification_interrupt_after="receipt")
            restarted = self.fx.store(Path(folder) / "export")
            restarted.recover()
            self.assertEqual(2, restarted.verify()["event_count"])

    def test_at_014_eligibility_cannot_use_hindsight(self) -> None:
        self.assertTrue(self.fx.policy["frozen_before_session"])
        self.assertFalse(self.fx.policy["outcome_selection_hindsight"])
        changed = copy.deepcopy(self.fx.policy)
        changed["outcome_selection_hindsight"] = True
        semantic = dict(changed)
        semantic.pop("policy_sha256")
        changed["policy_sha256"] = fingerprint(semantic)
        with self.assertRaises(ResearchFactExportError):
            validate_outcome_followup_policy(changed)

    def test_at_015_evidence_root_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            protected = Path(folder) / "production"
            protected.mkdir()
            with self.assertRaises(ResearchFactExportError):
                ResearchFactExportStore(
                    protected / "export",
                    market_date="2026-08-31",
                    session_id=self.fx.session_id,
                    protected_roots=(protected,),
                )
            with self.assertRaises(ResearchFactExportError):
                ResearchFactExportStore(
                    "relative/export", market_date="2026-08-31", session_id=self.fx.session_id
                )

    def test_at_016_duplicate_and_conflict_fail_closed(self) -> None:
        envelope = self.fx.discovery_envelope()
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            store.append(envelope)
            self.assertEqual("IDEMPOTENT_ACK", store.append(envelope).status)
            changed = copy.deepcopy(envelope)
            changed["payload"]["records"][1]["candidate_facts"]["price"] = evidence_present(
                "999.00", "OWNER_DISCOVERY"
            )
            changed["payload_sha256"] = fingerprint(changed["payload"])
            with self.assertRaises(ResearchFactConflict):
                store.append(changed)
            self.assertEqual(1, len(list((store.partition / "conflicts").glob("*.json"))))
            with self.assertRaises(ResearchFactConflict):
                store.verify()

    def test_at_017_coverage_and_manifest_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            store.append(self.fx.discovery_envelope())
            store.append(self.fx.decision_envelope())
            snapshot = store.verify()
            manifest = store.manifest_payload(
                close_state="QUALIFICATION_CLOSED", policy_sha256=self.fx.policy["policy_sha256"]
            )
            self.assertEqual(snapshot["record_counts"], manifest["record_counts"])
            self.assertEqual(set(COVERAGE_METRIC_IDS), set(manifest["coverage_metric_ids"]))

    def test_at_018_source_hashes_receipt_chains_and_checksums(self) -> None:
        envelope = self.fx.discovery_envelope()
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            receipt = store.append(envelope)
            self.assertEqual(hashlib.sha256(canonical_json_bytes(envelope)).hexdigest(), receipt.envelope_sha256)
            receipt_path = next((store.partition / "receipts/discovery").glob("*.json"))
            document = json.loads(receipt_path.read_text(encoding="utf-8"))
            document["payload_sha256"] = h("tampered")
            receipt_path.write_bytes(canonical_json_bytes(document))
            with self.assertRaises(ResearchFactExportError):
                store.verify()

    def test_at_019_schema_missingness_and_time_authority(self) -> None:
        with self.assertRaises(ResearchFactExportError):
            canonical_json_bytes({"ambiguous": None})
        with self.assertRaises(ResearchFactExportError):
            validate_evidence_value(
                {"authority": "OWNER", "reason_code": "MISSING", "state": "UNAVAILABLE", "value": 0}
            )
        with self.assertRaises(ResearchFactExportError):
            validate_time_evidence(
                {
                    "authority": "OWNER",
                    "normalized_rfc3339": "2026-08-31T15:00:00",
                    "precision": "SECOND",
                    "reason_code": "PRESENT",
                    "role": "DECISION_TIME",
                    "state": "PRESENT",
                    "timezone_or_offset": "UNKNOWN",
                    "value": "2026-08-31T15:00:00",
                }
            )

    def test_at_020_full_session_outcome_storage_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            store.append(self.fx.discovery_envelope())
            store.append(self.fx.decision_envelope())
            previous = ZERO_SHA256
            for index, horizon in enumerate(OUTCOME_HORIZONS):
                envelope = self.fx.outcome_envelope(horizon, sequence=index, previous=previous)
                store.append(envelope)
                previous = fingerprint(envelope)
            snapshot = store.verify()
            self.assertTrue(all(snapshot["outcome_horizon_counts"][item] == 1 for item in OUTCOME_HORIZONS))
            total = sum(path.stat().st_size for path in store.partition.rglob("*") if path.is_file())
            self.assertLess(total, 1024 * 1024)

    def test_at_021_no_account_order_execution_capability_or_import_side_effect(self) -> None:
        envelope = self.fx.discovery_envelope()
        envelope["payload"]["records"][0]["account_id"] = "forbidden"
        envelope["payload_sha256"] = fingerprint(envelope["payload"])
        with self.assertRaises(ResearchFactExportError):
            validate_envelope(envelope)
        module_path = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as folder:
            before = set(Path(folder).iterdir())
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(module_path)
            completed = subprocess.run(
                [sys.executable, "-c", "import momentum_hunter.research_fact_export"],
                cwd=folder,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(before, set(Path(folder).iterdir()))

    def test_at_022_one_semantic_source_of_truth(self) -> None:
        envelope = self.fx.market_envelope()
        validate_envelope(envelope)
        record = envelope["payload"]["records"][0]
        self.assertEqual(h("market-fact"), record["source_market_fact_fingerprint_sha256"])
        self.assertEqual(h("owner-market-0001"), envelope["source_event_fingerprint_sha256"])

    def test_at_023_extraction_and_point_in_time_replay_sanity(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = self.fx.store(Path(folder) / "export")
            store.append(self.fx.discovery_envelope())
            first = list(store.iter_verified_records())
            second = list(store.iter_verified_records())
            self.assertEqual(first, second)
            cycle = next(record for record in first if record["record_type"] == "discovery-cycle")
            self.assertEqual(T_DISCOVERY, cycle["discovery_time"]["normalized_rfc3339"])

    def test_at_024_source_correction_and_finalization_cutoff(self) -> None:
        first = self.fx.decision_envelope()
        corrected_id = owner_identity("DECISION", "OPENING_ENGINE", "decision-0002-correction")
        correction = self.fx.decision_envelope(
            source_event_id="owner-decision-correction-0002",
            source_sequence=1,
            previous=fingerprint(first),
            decision=corrected_id,
            decision_state="REJECTED",
        )
        correction["payload"]["records"][0]["supersedes_decision_id"] = evidence_present(
            self.fx.decision, "OWNER_DECISION"
        )
        correction["payload_sha256"] = fingerprint(correction["payload"])
        validate_envelope(correction)
        self.assertNotEqual(
            first["payload"]["records"][0]["decision_id"],
            correction["payload"]["records"][0]["decision_id"],
        )

    def test_at_025_protected_and_predecessor_bytes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            protected = root / "preserved-evidence.json"
            protected.write_bytes(canonical_json_bytes({"immutable": "predecessor"}))
            before = hashlib.sha256(protected.read_bytes()).hexdigest()
            store = self.fx.store(root / "isolated-export", protected_roots=(protected,))
            store.append(self.fx.discovery_envelope())
            after = hashlib.sha256(protected.read_bytes()).hexdigest()
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
