from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.continuous_research_export import (
    ContinuousResearchExportConflict,
    ContinuousResearchExportError,
    ContinuousResearchExportRecoveryError,
    ContinuousResearchExporterV2,
    SimulatedPublicationCrash,
    evidence_present,
    evidence_unresolved,
    instrument_identity,
    producer_identity,
    time_evidence,
)
from momentum_hunter.strategy_science_recorder import (
    RecorderContractError,
    StrategyScienceRecorder,
    canonical_json_v1,
    parse_export_envelope_v2,
    sha256_hex,
)
from momentum_hunter.strategy_science_recorder.contract import HORIZONS


OWNER = "continuous-research-export-002"
INTERFACE = "continuous-research-export-v2-offline"
SOURCE_ROOT = sha256_hex(canonical_json_v1({"owner": OWNER, "root": "fixture"}))
SESSION = producer_identity("SESSION_ID", OWNER, "session-2026-09-02")
CYCLE = producer_identity("DISCOVERY_CYCLE_ID", OWNER, "cycle-1")
OBSERVATION = producer_identity("OBSERVATION_ID", OWNER, "observation-1")
OBSERVATION_2 = producer_identity("OBSERVATION_ID", OWNER, "observation-2")
SETUP = producer_identity("SETUP", OWNER, "setup-1")
DECISION = producer_identity("DECISION_ID", OWNER, "decision-1")
TRADEPLAN = producer_identity("TRADEPLAN_ID", OWNER, "tradeplan-1")
REFERENCE_PLAN = producer_identity("REFERENCE_PLAN_ID", OWNER, "reference-plan-1")
MARKET = producer_identity("MARKET_SNAPSHOT_ID", OWNER, "market-1")
HEALTH = producer_identity("PROVIDER_HEALTH_EVENT_ID", OWNER, "health-1")

START_TIME = "2026-09-02T13:29:00Z"
DISCOVERY_TIME = "2026-09-02T13:31:00Z"
DECISION_CUTOFF = "2026-09-02T13:32:00Z"
DECISION_TIME = "2026-09-02T13:32:01Z"
MARKET_TIME = "2026-09-02T13:33:00Z"
FINAL_TIME = "2026-09-02T21:01:00Z"


class FixedClock:
    def __init__(self, value: str) -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


def absent(
    *,
    state: str = "NOT_APPLICABLE",
    reason: str = "NOT_APPLICABLE",
) -> dict[str, object]:
    return {"authority": OWNER, "reason_code": reason, "state": state}


def policy() -> dict[str, object]:
    value: dict[str, object] = {
        "bar_interval_semantic": "CANONICAL_ONE_MINUTE_REGULAR_SESSION_V1",
        "eligibility_mode": "ALL_UNIQUE_INSTRUMENTS",
        "exchange_calendar_id_and_version": "XNYS-2026a",
        "frozen_before_session": True,
        "horizons": list(HORIZONS),
        "outcome_selection_hindsight": False,
        "policy_id": "continuous-all-unique-v1",
        "policy_version": "1.0.0",
        "provider_owner_load_limit": evidence_present(100, OWNER),
        "retry_and_finalization_cutoff": {
            "finalization_cutoff": "2026-09-02T21:00:00Z",
            "maximum_attempts": 3,
        },
        "source_priority": ["continuous-canonical-market"],
    }
    value["policy_sha256"] = sha256_hex(canonical_json_v1(value))
    return value


def start_payload() -> dict[str, object]:
    return {
        "exchange_market_date": "2026-09-02",
        "manifest_phase": "START",
        "market_timezone": "America/New_York",
        "outcome_followup_policy": policy(),
        "regular_session_close": "2026-09-02T20:00:00Z",
        "regular_session_open": "2026-09-02T13:30:00Z",
        "session_id": SESSION,
        "session_kind": "REGULAR_SESSION",
        "source_owner_namespace": OWNER,
        "source_root_identity": SOURCE_ROOT,
        "source_runtime_activation_id": "offline-qualification-only",
    }


def resolved_instrument(symbol: str = "AAA") -> dict[str, object]:
    return instrument_identity(
        symbol=evidence_present(symbol, OWNER),
        asset_type=evidence_present("EQUITY", OWNER),
        venue_or_exchange=evidence_present("XNYS", OWNER),
        authoritative_security_id=evidence_present(f"security-{symbol}", OWNER),
        currency=evidence_present("USD", OWNER),
    )


def unresolved_instrument(symbol: str = "ZZZ") -> dict[str, object]:
    return instrument_identity(
        symbol=evidence_present(symbol, OWNER),
        asset_type=evidence_unresolved(OWNER),
        venue_or_exchange=evidence_unresolved(OWNER),
        authoritative_security_id=evidence_unresolved(OWNER),
    )


def observation(
    observation_id: dict[str, object] = OBSERVATION,
    *,
    ordinal: int = 0,
    instrument: dict[str, object] | None = None,
) -> dict[str, object]:
    frozen_instrument = resolved_instrument() if instrument is None else instrument
    return {
        "candidate_facts": {
            "persisted_score": evidence_present("79", OWNER),
            "price": evidence_present("12.34", OWNER),
            "volume": evidence_present(123456, OWNER),
        },
        "candidate_or_setup_identity": SETUP,
        "discovery_cycle_id": CYCLE,
        "discovery_time": time_evidence("DISCOVERY_TIME", DISCOVERY_TIME, OWNER),
        "instrument_identity": frozen_instrument,
        "materially_evaluated": True,
        "observation_id": observation_id,
        "rank": evidence_present(ordinal + 1, OWNER),
        "rejection_or_gap_reasons": [],
        "source_row_fingerprint_sha256": sha256_hex(
            canonical_json_v1(
                {
                    "instrument": frozen_instrument,
                    "observation_id": observation_id,
                    "ordinal": ordinal,
                }
            )
        ),
        "source_row_ordinal": ordinal,
    }


def discovery_payload(
    rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    observations = [observation()] if rows is None else rows
    return {
        "discovery_cycle": {
            "completeness": evidence_present("COMPLETE", OWNER),
            "cycle_state": "COMPLETE",
            "discovery_cycle_id": CYCLE,
            "discovery_time": time_evidence("DISCOVERY_TIME", DISCOVERY_TIME, OWNER),
            "observation_ids_in_source_order": [
                row["observation_id"] for row in observations
            ],
            "provider_health_event_ids": [],
            "provider_received_at": time_evidence(
                "PROVIDER_RECEIVED_AT", DISCOVERY_TIME, OWNER
            ),
            "query_or_policy_fingerprint_sha256": sha256_hex(
                canonical_json_v1({"policy": "fixture-v2"})
            ),
            "returned_row_count": len(observations),
            "row_order_complete": evidence_present(True, OWNER),
            "zero_result": False,
        },
        "observations": observations,
    }


def reference_level(role: str, value: str) -> dict[str, object]:
    result = evidence_present(value, OWNER)
    result.update(
        {
            "currency": "USD",
            "level_role": role,
            "level_source_fingerprint_sha256": sha256_hex(
                canonical_json_v1({"role": role, "value": value})
            ),
            "reference_level_id": producer_identity(
                "REFERENCE_LEVEL_ID", OWNER, f"level-{role}"
            ),
        }
    )
    return result


def decision_payload() -> dict[str, object]:
    return {
        "decision_event": {
            "candidate_or_setup_identity": SETUP,
            "config_fingerprint_sha256": sha256_hex(
                canonical_json_v1({"config": "fixture"})
            ),
            "decision_cutoff": time_evidence(
                "DECISION_CUTOFF", DECISION_CUTOFF, OWNER
            ),
            "decision_id": DECISION,
            "decision_policy_fingerprint_sha256": sha256_hex(
                canonical_json_v1({"policy": "decision-v1"})
            ),
            "decision_state": "TRADEPLAN",
            "decision_time": time_evidence("DECISION_TIME", DECISION_TIME, OWNER),
            "known_at_evidence_refs": [],
            "market_snapshot_id": absent(reason="NO_CONTEMPORANEOUS_SNAPSHOT"),
            "observation_id": OBSERVATION,
            "reason_codes": [{"code": "TRADEPLAN", "version": "1"}],
            "reference_plan_id": evidence_present(REFERENCE_PLAN, OWNER),
            "runtime_fingerprint_sha256": sha256_hex(
                canonical_json_v1({"runtime": "offline"})
            ),
            "strategy_identity": evidence_present("momentum-control-v1", OWNER),
            "tradeplan_id": evidence_present(TRADEPLAN, OWNER),
        },
        "reference_plan": {
            "candidate_or_setup_identity": SETUP,
            "decision_id": DECISION,
            "entry": reference_level("ENTRY", "12.40"),
            "plan_created_at": time_evidence(
                "DECISION_TIME", DECISION_CUTOFF, OWNER
            ),
            "plan_owner": OWNER,
            "plan_schema_version": "1.0.0",
            "plan_source_fingerprint_sha256": sha256_hex(
                canonical_json_v1({"plan": "fixture"})
            ),
            "reference_plan_id": REFERENCE_PLAN,
            "stop": reference_level("STOP", "11.90"),
            "t1": reference_level("T1", "13.00"),
            "t2": reference_level("T2", "13.60"),
            "tradeplan_id": TRADEPLAN,
        },
    }


def market_payload() -> dict[str, object]:
    return {
        "market_snapshot": {
            "decision_id": evidence_present(DECISION, OWNER),
            "instrument_identity": resolved_instrument(),
            "market_data_owner": OWNER,
            "market_facts": {"price": evidence_present("12.50", OWNER)},
            "market_snapshot_id": MARKET,
            "observation_id": evidence_present(OBSERVATION, OWNER),
            "outcome_series_id": absent(),
            "provider_known_at": time_evidence(
                "PROVIDER_KNOWN_AT", MARKET_TIME, OWNER
            ),
            "provider_received_at": time_evidence(
                "PROVIDER_RECEIVED_AT", MARKET_TIME, OWNER
            ),
            "snapshot_kind": "DECISION_SNAPSHOT",
            "source_event_time": time_evidence(
                "SOURCE_EVENT_TIME", MARKET_TIME, OWNER
            ),
            "source_market_fact_fingerprint_sha256": sha256_hex(
                canonical_json_v1({"market": "fixture"})
            ),
        }
    }


def health_payload() -> dict[str, object]:
    return {
        "provider_health_event": {
            "affected_record_ids": [OBSERVATION],
            "attempt_number": evidence_present(1, OWNER),
            "event_class": "SOURCE_OUTAGE",
            "event_state": "UNAVAILABLE",
            "interface_or_owner": OWNER,
            "provider_health_event_id": HEALTH,
            "provider_received_at": time_evidence(
                "PROVIDER_RECEIVED_AT", MARKET_TIME, OWNER
            ),
            "reason_code": "SOURCE_OUTAGE",
            "secret_material_present": False,
            "source_event_time": time_evidence(
                "SOURCE_EVENT_TIME", MARKET_TIME, OWNER
            ),
            "terminal": False,
        }
    }


def exporter(
    root: Path,
    *,
    hook: object = None,
) -> ContinuousResearchExporterV2:
    return ContinuousResearchExporterV2(
        root,
        session_id=SESSION,
        source_owner_identity=OWNER,
        source_interface_identity=INTERFACE,
        source_root_identity=SOURCE_ROOT,
        crash_hook=hook,
    )


def publish_start(writer: ContinuousResearchExporterV2):
    return writer.start(
        start_payload(),
        stream_id="session",
        source_event_id="session-start",
        emitted_at=START_TIME,
    )


def publish_discovery(
    writer: ContinuousResearchExporterV2,
    *,
    event_id: str = "discovery-1",
    rows: list[dict[str, object]] | None = None,
):
    return writer.publish_event(
        "DISCOVERY_CYCLE",
        discovery_payload(rows),
        stream_id="discovery",
        source_event_id=event_id,
        emitted_at=DISCOVERY_TIME,
    )


def publish_decision(writer: ContinuousResearchExporterV2):
    return writer.publish_event(
        "DECISION_FACT",
        decision_payload(),
        stream_id="decision",
        source_event_id="decision-1",
        emitted_at=DECISION_TIME,
    )


def crash_at(target: str):
    def hook(phase: str) -> None:
        if phase == target:
            raise SimulatedPublicationCrash(target)

    return hook


def stored_records(root: Path, record_type: str) -> list[tuple[Path, dict[str, object]]]:
    results: list[tuple[Path, dict[str, object]]] = []
    for path in root.rglob("*.payload.json"):
        value = json.loads(path.read_bytes())
        if value.get("record_type") == record_type:
            results.append((path, value))
    return results


def observation_receipt_hash(root: Path) -> str:
    payload_path, _value = stored_records(root, "candidate-observation")[0]
    key = payload_path.name.removesuffix(".payload.json")
    receipt = next(root.rglob(f"{key}.receipt.json"))
    return sha256_hex(receipt.read_bytes())


class ContinuousResearchExportV2Tests(unittest.TestCase):
    def test_exact_v2_bytes_are_directly_parseable_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_sets: list[tuple[bytes, ...]] = []
            for name in ("first", "second"):
                with exporter(root / name) as writer:
                    publish_start(writer)
                    publish_discovery(writer)
                    publish_decision(writer)
                    raw_sets.append(tuple(item.raw_bytes for item in writer.published()))
            self.assertEqual(raw_sets[0], raw_sets[1])
            for raw in raw_sets[0]:
                parsed = parse_export_envelope_v2(raw)
                self.assertEqual("2.0.0", parsed.schema_version)
                self.assertEqual(sha256_hex(raw), parsed.raw_sha256)

    def test_start_is_required_first_and_late_start_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                with self.assertRaises(ContinuousResearchExportError):
                    publish_discovery(writer)
                publish_start(writer)
                with self.assertRaises(ContinuousResearchExportError):
                    writer.start(
                        start_payload(),
                        stream_id="another-session-stream",
                        source_event_id="late-start",
                        emitted_at=START_TIME,
                    )

    def test_v2_decision_contains_no_future_science_fact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                publish_start(writer)
                publish_discovery(writer)
                result = publish_decision(writer)
                decision = parse_export_envelope_v2(result.raw_bytes).payload[
                    "decision_event"
                ]
                for field in (
                    "outcome_eligibility_commitment_sha256",
                    "science_receipt_hash",
                    "science_eligibility_hash",
                    "science_evaluated_at",
                ):
                    self.assertNotIn(field, decision)
                changed = decision_payload()
                changed["decision_event"]["science_eligibility_hash"] = "f" * 64
                with self.assertRaises(ContinuousResearchExportError):
                    writer.publish_event(
                        "DECISION_FACT",
                        changed,
                        stream_id="decision",
                        source_event_id="decision-injected",
                        emitted_at=DECISION_TIME,
                    )

    def test_unknown_field_malformed_and_wrong_payload_hash_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                raw = publish_start(writer).raw_bytes
            value = json.loads(raw)
            value["unknown"] = "forbidden"
            with self.assertRaises(RecorderContractError):
                parse_export_envelope_v2(canonical_json_v1(value))
            with self.assertRaises(RecorderContractError):
                parse_export_envelope_v2(b'{"not":"canonical"}')
            value = json.loads(raw)
            value["payload_sha256"] = "f" * 64
            with self.assertRaises(RecorderContractError):
                parse_export_envelope_v2(canonical_json_v1(value))

    def test_per_stream_sequence_and_previous_raw_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                start = publish_start(writer)
                first = publish_discovery(writer)
                second = publish_discovery(
                    writer,
                    event_id="discovery-2",
                    rows=[observation(OBSERVATION_2, ordinal=1)],
                )
                health = writer.publish_event(
                    "PROVIDER_HEALTH",
                    health_payload(),
                    stream_id="health",
                    source_event_id="health-1",
                    emitted_at=MARKET_TIME,
                )
                first_parsed = parse_export_envelope_v2(first.raw_bytes)
                second_parsed = parse_export_envelope_v2(second.raw_bytes)
                health_parsed = parse_export_envelope_v2(health.raw_bytes)
                self.assertEqual(1, first_parsed.source_sequence)
                self.assertEqual(2, second_parsed.source_sequence)
                self.assertEqual(first.raw_sha256, second_parsed.previous_record_sha256)
                self.assertEqual(1, health_parsed.source_sequence)
                self.assertEqual("0" * 64, health_parsed.previous_record_sha256)
                self.assertEqual(1, parse_export_envelope_v2(start.raw_bytes).source_sequence)

    def test_duplicate_is_idempotent_and_conflicting_reuse_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                publish_start(writer)
                first = publish_discovery(writer)
                same = publish_discovery(writer)
                self.assertEqual("IDEMPOTENT_ACK", same.status)
                self.assertEqual(first.raw_bytes, same.raw_bytes)
                changed = discovery_payload()
                changed["observations"][0]["rank"] = evidence_present(2, OWNER)
                with self.assertRaises(ContinuousResearchExportConflict):
                    writer.publish_event(
                        "DISCOVERY_CYCLE",
                        changed,
                        stream_id="discovery",
                        source_event_id="discovery-1",
                        emitted_at=DISCOVERY_TIME,
                    )
                final = writer.finalize(
                    stream_id="session",
                    source_event_id="session-final",
                    closed_at=FINAL_TIME,
                    close_reason="COMPLETE",
                    terminal_proven=True,
                )
                self.assertEqual("INCOMPLETE_NO_FINAL", final.status)
                self.assertEqual(1, final.conflict_count)

    def test_restart_restores_next_sequence_and_prior_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as writer:
                publish_start(writer)
                first = publish_discovery(writer)
            with exporter(root) as restarted:
                second = publish_discovery(
                    restarted,
                    event_id="discovery-2",
                    rows=[observation(OBSERVATION_2, ordinal=1)],
                )
                parsed = parse_export_envelope_v2(second.raw_bytes)
                self.assertEqual(2, parsed.source_sequence)
                self.assertEqual(first.raw_sha256, parsed.previous_record_sha256)

    def test_recovery_rejects_sequence_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as writer:
                publish_start(writer)
                publish_discovery(writer)
                second = publish_discovery(
                    writer,
                    event_id="discovery-2",
                    rows=[observation(OBSERVATION_2, ordinal=1)],
                )
            path = root / second.relative_path
            value = json.loads(path.read_bytes())
            value["source_sequence"] = 3
            path.write_bytes(canonical_json_v1(value))
            renamed = path.with_name(path.name[:-25] + f"{3:020d}.json")
            path.rename(renamed)
            with self.assertRaises(ContinuousResearchExportRecoveryError):
                exporter(root)

    def test_recovery_rejects_previous_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as writer:
                publish_start(writer)
                publish_discovery(writer)
                second = publish_discovery(
                    writer,
                    event_id="discovery-2",
                    rows=[observation(OBSERVATION_2, ordinal=1)],
                )
            path = root / second.relative_path
            value = json.loads(path.read_bytes())
            value["previous_record_sha256"] = "f" * 64
            path.write_bytes(canonical_json_v1(value))
            with self.assertRaises(ContinuousResearchExportRecoveryError):
                exporter(root)

    def test_start_crash_boundaries_recover_without_duplicate(self) -> None:
        phases = (
            ("before_start_commit", 0),
            ("after_start_raw_before_publication", 1),
            ("after_start_publication_before_checkpoint", 1),
        )
        for phase, expected in phases:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                writer = exporter(root, hook=crash_at(phase))
                try:
                    with self.assertRaises(SimulatedPublicationCrash):
                        publish_start(writer)
                finally:
                    writer.close()
                with exporter(root) as recovered:
                    self.assertEqual(expected, len(recovered.published()))
                    if expected == 0:
                        publish_start(recovered)
                    else:
                        self.assertEqual(
                            "IDEMPOTENT_ACK", publish_start(recovered).status
                        )
                    self.assertEqual(1, len(recovered.published()))

    def test_event_crash_boundaries_recover_exact_bytes(self) -> None:
        phases = (
            "after_event_raw_before_publication",
            "after_event_publication_before_checkpoint",
        )
        for phase in phases:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with exporter(root) as initial:
                    publish_start(initial)
                writer = exporter(root, hook=crash_at(phase))
                try:
                    with self.assertRaises(SimulatedPublicationCrash):
                        publish_discovery(writer)
                finally:
                    writer.close()
                with exporter(root) as recovered:
                    self.assertEqual(2, len(recovered.published()))
                    self.assertEqual(
                        "IDEMPOTENT_ACK", publish_discovery(recovered).status
                    )

    def test_staged_bytes_are_not_publicly_visible_before_atomic_admission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as initial:
                publish_start(initial)
            writer = exporter(
                root, hook=crash_at("after_event_raw_before_publication")
            )
            try:
                with self.assertRaises(SimulatedPublicationCrash):
                    publish_discovery(writer)
                self.assertEqual(1, len(tuple((root / "published").glob("*.json"))))
                self.assertEqual(1, len(tuple((root / "staging").glob("*.json"))))
            finally:
                writer.close()
            with exporter(root) as recovered:
                self.assertEqual(2, len(recovered.published()))

    def test_restart_between_sequential_events_preserves_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as first_writer:
                publish_start(first_writer)
                first = publish_discovery(first_writer)
            with exporter(root) as second_writer:
                second = publish_discovery(
                    second_writer,
                    event_id="discovery-2",
                    rows=[observation(OBSERVATION_2, ordinal=1)],
                )
            self.assertEqual(
                first.raw_sha256,
                parse_export_envelope_v2(second.raw_bytes).previous_record_sha256,
            )

    def test_final_is_truthful_unique_and_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as writer:
                publish_start(writer)
                publish_discovery(writer)
                publish_decision(writer)
                result = writer.finalize(
                    stream_id="session",
                    source_event_id="session-final",
                    closed_at=FINAL_TIME,
                    close_reason="SESSION_COMPLETE",
                    terminal_proven=True,
                )
                self.assertEqual("FINAL_PUBLISHED", result.status)
                assert result.publication is not None
                payload = parse_export_envelope_v2(
                    result.publication.raw_bytes
                ).payload
                self.assertEqual(1, payload["source_event_type_counts_before_final"]["SESSION_MANIFEST"])
                self.assertEqual(1, payload["source_event_type_counts_before_final"]["DISCOVERY_CYCLE"])
                self.assertEqual(1, payload["source_event_type_counts_before_final"]["DECISION_FACT"])
                with self.assertRaises(ContinuousResearchExportError):
                    writer.publish_event(
                        "PROVIDER_HEALTH",
                        health_payload(),
                        stream_id="health",
                        source_event_id="late-health",
                        emitted_at=FINAL_TIME,
                    )

    def test_unproven_or_incomplete_session_never_publishes_false_final(self) -> None:
        cases = (
            {"terminal_proven": False},
            {"terminal_proven": True, "pending_source_events": 1},
            {"terminal_proven": True, "source_gap_count": 1},
            {"terminal_proven": True, "upstream_conflict_count": 1},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as temporary:
                with exporter(Path(temporary)) as writer:
                    publish_start(writer)
                    result = writer.finalize(
                        stream_id="session",
                        source_event_id="session-final",
                        closed_at=FINAL_TIME,
                        close_reason="INCOMPLETE",
                        **kwargs,
                    )
                    self.assertEqual("INCOMPLETE_NO_FINAL", result.status)
                    self.assertEqual(1, len(writer.published()))

    def test_incomplete_final_disposition_survives_close_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as writer:
                publish_start(writer)
                result = writer.finalize(
                    stream_id="session",
                    source_event_id="session-final",
                    closed_at=FINAL_TIME,
                    close_reason="PENDING_SOURCE",
                    terminal_proven=True,
                    pending_source_events=1,
                )
                self.assertEqual("INCOMPLETE_NO_FINAL", result.status)
            with exporter(root) as restarted:
                checkpoint = json.loads(
                    (root / "checkpoint" / "state.json").read_bytes()
                )
                self.assertEqual(
                    1,
                    checkpoint["incomplete_finalization"][
                        "pending_source_events"
                    ],
                )
                self.assertFalse(checkpoint["terminal"])

    def test_final_crash_boundaries_recover_terminal_bytes(self) -> None:
        phases = (
            ("before_final", 2),
            ("after_final_raw_before_publication", 3),
            ("after_final_publication_before_checkpoint", 3),
        )
        for phase, expected in phases:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with exporter(root) as initial:
                    publish_start(initial)
                    publish_discovery(initial)
                writer = exporter(root, hook=crash_at(phase))
                try:
                    with self.assertRaises(SimulatedPublicationCrash):
                        writer.finalize(
                            stream_id="session",
                            source_event_id="session-final",
                            closed_at=FINAL_TIME,
                            close_reason="SESSION_COMPLETE",
                            terminal_proven=True,
                        )
                finally:
                    writer.close()
                with exporter(root) as recovered:
                    self.assertEqual(expected, len(recovered.published()))
                    if expected == 2:
                        result = recovered.finalize(
                            stream_id="session",
                            source_event_id="session-final",
                            closed_at=FINAL_TIME,
                            close_reason="SESSION_COMPLETE",
                            terminal_proven=True,
                        )
                        self.assertEqual("FINAL_PUBLISHED", result.status)
                    else:
                        self.assertEqual(
                            "IDEMPOTENT_ACK",
                            recovered.finalize(
                                stream_id="session",
                                source_event_id="session-final",
                                closed_at=FINAL_TIME,
                                close_reason="SESSION_COMPLETE",
                                terminal_proven=True,
                            ).status,
                        )

    def test_final_retry_with_changed_truth_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                publish_start(writer)
                publish_discovery(writer)
                first = writer.finalize(
                    stream_id="session",
                    source_event_id="session-final",
                    closed_at=FINAL_TIME,
                    close_reason="SESSION_COMPLETE",
                    terminal_proven=True,
                )
                self.assertEqual("FINAL_PUBLISHED", first.status)
                with self.assertRaises(ContinuousResearchExportConflict):
                    writer.finalize(
                        stream_id="session",
                        source_event_id="session-final",
                        closed_at=FINAL_TIME,
                        close_reason="CHANGED_REASON",
                        terminal_proven=True,
                    )

    def test_published_final_cannot_be_downgraded_to_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as writer:
                publish_start(writer)
                publish_discovery(writer)
                writer.finalize(
                    stream_id="session",
                    source_event_id="session-final",
                    closed_at=FINAL_TIME,
                    close_reason="SESSION_COMPLETE",
                    terminal_proven=True,
                )
                with self.assertRaises(ContinuousResearchExportConflict):
                    writer.finalize(
                        stream_id="session",
                        source_event_id="session-final",
                        closed_at=FINAL_TIME,
                        close_reason="SESSION_COMPLETE",
                        terminal_proven=False,
                    )
                checkpoint = json.loads(
                    (root / "checkpoint" / "state.json").read_bytes()
                )
                self.assertTrue(checkpoint["terminal"])
                self.assertFalse(checkpoint["incomplete_finalization"])

    def test_terminal_proof_requires_an_actual_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                publish_start(writer)
                with self.assertRaises(ContinuousResearchExportError):
                    writer.finalize(
                        stream_id="session",
                        source_event_id="session-final",
                        closed_at=FINAL_TIME,
                        close_reason="SESSION_COMPLETE",
                        terminal_proven=1,  # type: ignore[arg-type]
                    )

    def test_final_cannot_precede_source_fact_or_frozen_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                publish_start(writer)
                publish_discovery(writer)
                with self.assertRaises(ContinuousResearchExportError):
                    writer.finalize(
                        stream_id="session",
                        source_event_id="session-final",
                        closed_at="2026-09-02T13:30:00Z",
                        close_reason="TOO_EARLY",
                        terminal_proven=True,
                    )
                with self.assertRaises(ContinuousResearchExportError):
                    writer.finalize(
                        stream_id="session",
                        source_event_id="session-final",
                        closed_at="2026-09-02T20:59:59Z",
                        close_reason="BEFORE_CUTOFF",
                        terminal_proven=True,
                    )

    def test_direct_science_custody_accepts_exact_exporter_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root / "producer") as writer:
                publish_start(writer)
                publish_discovery(writer)
                publish_decision(writer)
                raw = tuple(item.raw_bytes for item in writer.published())
            recorder = StrategyScienceRecorder(
                root / "science",
                source_root_identity=SOURCE_ROOT,
                writer_instance_id="science-direct",
                clock=FixedClock("2026-09-02T14:00:00Z"),
            )
            try:
                results = [recorder.accept(item) for item in raw]
                self.assertTrue(all(item.status == "ACCEPTED" for item in results))
                self.assertEqual(1, len(stored_records(root / "science", "science-eligibility")))
                self.assertTrue(recorder.verify(SESSION).all_hashes_valid)
            finally:
                recorder.close()

    def test_two_science_clocks_never_change_producer_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root / "producer") as writer:
                publish_start(writer)
                discovery = publish_discovery(writer)
                decision = publish_decision(writer)
                raw = tuple(item.raw_bytes for item in writer.published())
            evidence: list[tuple[str, str, str, str]] = []
            for ordinal, receipt_time in enumerate(
                ("2026-09-02T14:00:00Z", "2026-09-02T14:00:01Z"), start=1
            ):
                custody = root / f"science-{ordinal}"
                recorder = StrategyScienceRecorder(
                    custody,
                    source_root_identity=SOURCE_ROOT,
                    writer_instance_id=f"science-{ordinal}",
                    clock=FixedClock(receipt_time),
                )
                try:
                    for item in raw:
                        recorder.accept(item)
                    eligibility = stored_records(custody, "science-eligibility")[0][1][
                        "science_eligibility"
                    ]
                    evidence.append(
                        (
                            discovery.raw_sha256,
                            decision.raw_sha256,
                            observation_receipt_hash(custody),
                            str(eligibility["commitment_payload_sha256"]),
                        )
                    )
                finally:
                    recorder.close()
            self.assertEqual(evidence[0][0:2], evidence[1][0:2])
            self.assertNotEqual(evidence[0][2], evidence[1][2])
            self.assertNotEqual(evidence[0][3], evidence[1][3])

    def test_unresolved_instrument_identity_is_preserved_without_invention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                publish_start(writer)
                row = observation(instrument=unresolved_instrument())
                result = publish_discovery(writer, rows=[row])
                parsed = parse_export_envelope_v2(result.raw_bytes)
                frozen = parsed.payload["observations"][0]["instrument_identity"]
                self.assertEqual("PRESENT", frozen["symbol"]["state"])
                for field in (
                    "asset_type",
                    "venue_or_exchange",
                    "authoritative_security_id",
                ):
                    self.assertEqual("UNKNOWN", frozen[field]["state"])
                    self.assertNotIn("value", frozen[field])

    def test_decision_dependency_must_already_be_producer_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                publish_start(writer)
                with self.assertRaises(ContinuousResearchExportError):
                    publish_decision(writer)

    def test_market_dependency_must_already_be_producer_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with exporter(Path(temporary)) as writer:
                publish_start(writer)
                with self.assertRaises(ContinuousResearchExportError):
                    writer.publish_event(
                        "MARKET_FACT",
                        market_payload(),
                        stream_id="market",
                        source_event_id="market-1",
                        emitted_at=MARKET_TIME,
                    )
                publish_discovery(writer)
                publish_decision(writer)
                result = writer.publish_event(
                    "MARKET_FACT",
                    market_payload(),
                    stream_id="market",
                    source_event_id="market-1",
                    emitted_at=MARKET_TIME,
                )
                self.assertEqual("PUBLISHED", result.status)

    def test_delivery_order_is_not_claimed_as_universal_semantic_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root) as writer:
                publish_start(writer)
                publish_discovery(writer)
            checkpoint = json.loads((root / "checkpoint" / "state.json").read_bytes())
            self.assertEqual(
                "PUBLICATION_DELIVERY_ONLY_NOT_UNIVERSAL_SOURCE_CHRONOLOGY",
                checkpoint["delivery_order_semantic"],
            )

    def test_writer_ownership_is_single_instance_and_restartable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = exporter(root)
            try:
                with self.assertRaises(ContinuousResearchExportError):
                    exporter(root)
            finally:
                first.close()
            with exporter(root) as restarted:
                self.assertEqual(0, len(restarted.published()))

    def test_corrupt_stage_is_never_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with exporter(root):
                pass
            (root / "staging" / ("a" * 64 + ".json")).write_bytes(b"not-json")
            with self.assertRaises(ContinuousResearchExportRecoveryError):
                exporter(root)
            self.assertEqual([], list((root / "published").glob("*.json")))

    def test_no_historical_upgrade_or_outcome_backpropagation_surface_exists(self) -> None:
        for name in (
            "upgrade_historical_corpus",
            "reconstruct_start",
            "reconstruct_final",
            "retrofit_outcome",
            "publish_outcome",
        ):
            self.assertFalse(hasattr(ContinuousResearchExporterV2, name))

    def test_module_has_no_network_runtime_service_or_execution_import(self) -> None:
        source = Path(
            "momentum_hunter/continuous_research_export.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = {
            node.names[0].name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertTrue(
            {
                "requests",
                "httpx",
                "urllib",
                "socket",
                "subprocess",
                "continuous_runtime",
                "continuous_production",
            }.isdisjoint(modules)
        )
        lowered = source.casefold()
        for capability in (
            "submit_order",
            "place_order",
            "cancel_order",
            "start-service",
            "schtasks",
        ):
            self.assertNotIn(capability, lowered)


if __name__ == "__main__":
    unittest.main()
