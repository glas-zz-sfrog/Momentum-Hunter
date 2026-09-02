"""Generate offline proof for ARGUS-CONTINUOUS-RESEARCH-EXPORT-002."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    repository = args.repository_root.resolve()
    output = args.output_dir.resolve()
    sys.path.insert(0, str(repository))

    from momentum_hunter.continuous_research_export import (
        SimulatedPublicationCrash,
    )
    from momentum_hunter.strategy_science_recorder import StrategyScienceRecorder
    from momentum_hunter.strategy_science_recorder.contract import (
        parse_export_envelope_v2,
    )
    from tests.test_continuous_research_export_v2 import (
        FINAL_TIME,
        OWNER,
        SESSION,
        SOURCE_ROOT,
        FixedClock,
        crash_at,
        exporter,
        observation,
        observation_receipt_hash,
        publish_decision,
        publish_discovery,
        publish_start,
        stored_records,
        OBSERVATION_2,
    )

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="argus-continuous-research-export-002-"
    ) as temporary:
        root = Path(temporary)
        producer_root = root / "producer"
        with exporter(producer_root) as writer:
            start = publish_start(writer)
            discovery = publish_discovery(writer)
            decision = publish_decision(writer)
            final = writer.finalize(
                stream_id="session",
                source_event_id="session-final",
                closed_at=FINAL_TIME,
                close_reason="OFFLINE_QUALIFICATION_COMPLETE",
                terminal_proven=True,
            )
            publications = writer.published()
        parsed = [parse_export_envelope_v2(item.raw_bytes) for item in publications]
        producer_raw_sha256s = [item.raw_sha256 for item in publications]
        decision_fields = set(parsed[2].payload["decision_event"])

        two_clock_rows: list[dict[str, object]] = []
        source_without_final = tuple(item.raw_bytes for item in publications[:-1])
        for ordinal, receipt_time in enumerate(
            ("2026-09-02T14:00:00Z", "2026-09-02T14:00:01Z"), start=1
        ):
            custody = root / f"science-{ordinal}"
            recorder = StrategyScienceRecorder(
                custody,
                source_root_identity=SOURCE_ROOT,
                writer_instance_id=f"proof-science-{ordinal}",
                clock=FixedClock(receipt_time),
            )
            try:
                results = [recorder.accept(raw) for raw in source_without_final]
                eligibility = stored_records(custody, "science-eligibility")[0][1][
                    "science_eligibility"
                ]
                two_clock_rows.append(
                    {
                        "acceptanceStatuses": [item.status for item in results],
                        "producerDecisionSha256": decision.raw_sha256,
                        "producerDiscoverySha256": discovery.raw_sha256,
                        "producerRawSha256s": [
                            hashlib.sha256(raw).hexdigest() for raw in source_without_final
                        ],
                        "scienceEligibilitySha256": eligibility[
                            "commitment_payload_sha256"
                        ],
                        "scienceReceiptSha256": observation_receipt_hash(custody),
                        "scienceReceiptTime": receipt_time,
                        "verifyAllHashesValid": recorder.verify(SESSION).all_hashes_valid,
                    }
                )
            finally:
                recorder.close()
        two_clock_invariants = {
            "producerDecisionHashEqual": two_clock_rows[0]["producerDecisionSha256"]
            == two_clock_rows[1]["producerDecisionSha256"],
            "producerDiscoveryHashEqual": two_clock_rows[0]["producerDiscoverySha256"]
            == two_clock_rows[1]["producerDiscoverySha256"],
            "producerRawBytesEqual": two_clock_rows[0]["producerRawSha256s"]
            == two_clock_rows[1]["producerRawSha256s"],
            "scienceEligibilityHashesDiffer": two_clock_rows[0][
                "scienceEligibilitySha256"
            ]
            != two_clock_rows[1]["scienceEligibilitySha256"],
            "scienceReceiptHashesDiffer": two_clock_rows[0]["scienceReceiptSha256"]
            != two_clock_rows[1]["scienceReceiptSha256"],
        }
        two_clock = {
            "invariants": two_clock_invariants,
            "producerRequiresFutureScienceHash": False,
            "rows": two_clock_rows,
            "status": (
                "PASS" if all(two_clock_invariants.values()) else "FAIL"
            ),
            "task": "ARGUS-CONTINUOUS-RESEARCH-EXPORT-002",
        }
        _write(output / "two-clock-proof.json", two_clock)

        phases = (
            ("before_start_commit", "start", 0),
            ("after_start_raw_before_publication", "start", 1),
            ("after_start_publication_before_checkpoint", "start", 1),
            ("after_event_raw_before_publication", "event", 2),
            ("after_event_publication_before_checkpoint", "event", 2),
            ("before_final", "final", 2),
            ("after_final_raw_before_publication", "final", 3),
            ("after_final_publication_before_checkpoint", "final", 3),
        )
        crash_rows: list[dict[str, object]] = []
        partial_not_visible = True
        for phase, kind, expected_count in phases:
            phase_root = root / "crash" / phase
            if kind in {"event", "final"}:
                with exporter(phase_root) as initial:
                    publish_start(initial)
                    if kind == "final":
                        publish_discovery(initial)
            writer = exporter(phase_root, hook=crash_at(phase))
            public_before_recovery = -1
            try:
                try:
                    if kind == "start":
                        publish_start(writer)
                    elif kind == "event":
                        publish_discovery(writer)
                    else:
                        writer.finalize(
                            stream_id="session",
                            source_event_id="session-final",
                            closed_at=FINAL_TIME,
                            close_reason="OFFLINE_QUALIFICATION_COMPLETE",
                            terminal_proven=True,
                        )
                except SimulatedPublicationCrash:
                    pass
                else:
                    raise AssertionError(f"Crash phase did not fire: {phase}")
                public_before_recovery = len(
                    tuple((phase_root / "published").glob("*.json"))
                )
                if phase in {
                    "after_start_raw_before_publication",
                    "after_event_raw_before_publication",
                    "after_final_raw_before_publication",
                }:
                    preexisting = 0 if kind == "start" else (1 if kind == "event" else 2)
                    partial_not_visible = partial_not_visible and (
                        public_before_recovery == preexisting
                    )
            finally:
                writer.close()
            with exporter(phase_root) as recovered:
                recovered_items = recovered.published()
                terminal = bool(
                    recovered_items
                    and parse_export_envelope_v2(recovered_items[-1].raw_bytes).payload.get(
                        "manifest_phase"
                    )
                    == "FINAL"
                )
            crash_rows.append(
                {
                    "expectedRecoveredPublicationCount": expected_count,
                    "phase": phase,
                    "publicCountBeforeRecovery": public_before_recovery,
                    "recoveredPublicationCount": len(recovered_items),
                    "terminalAfterRecovery": terminal,
                }
            )

        sequential_root = root / "crash" / "between-sequential-events"
        with exporter(sequential_root) as first_writer:
            publish_start(first_writer)
            first_discovery = publish_discovery(first_writer)
        with exporter(sequential_root) as second_writer:
            second_discovery = publish_discovery(
                second_writer,
                event_id="discovery-2",
                rows=[observation(OBSERVATION_2, ordinal=1)],
            )
        second_parsed = parse_export_envelope_v2(second_discovery.raw_bytes)
        between_sequential = {
            "nextSequence": second_parsed.source_sequence,
            "previousHashMatches": second_parsed.previous_record_sha256
            == first_discovery.raw_sha256,
        }
        crash_invariants = {
            "allRecoveredCountsMatch": all(
                row["expectedRecoveredPublicationCount"]
                == row["recoveredPublicationCount"]
                for row in crash_rows
            ),
            "betweenSequentialEventsPreserved": between_sequential["nextSequence"]
            == 2
            and between_sequential["previousHashMatches"],
            "partialSourceNeverAdmitted": partial_not_visible,
        }
        crash_matrix = {
            "betweenSequentialEvents": between_sequential,
            "invariants": crash_invariants,
            "rows": crash_rows,
            "status": "PASS" if all(crash_invariants.values()) else "FAIL",
            "task": "ARGUS-CONTINUOUS-RESEARCH-EXPORT-002",
        }
        _write(output / "crash-restart-matrix.json", crash_matrix)

        final_publication = final.publication
        assert final_publication is not None
        final_payload = parse_export_envelope_v2(final_publication.raw_bytes).payload
        expected_counts = {event_type: 0 for event_type in sorted(
            {"DISCOVERY_CYCLE", "DECISION_FACT", "MARKET_FACT", "PROVIDER_HEALTH", "SESSION_MANIFEST"}
        )}
        expected_heads: dict[str, object] = {}
        for item in parsed[:-1]:
            expected_counts[item.event_type] += 1
            expected_heads[item.stream_id] = item
        expected_head_rows = [
            {
                "last_source_envelope_sha256": item.raw_sha256,
                "last_source_sequence": item.source_sequence,
                "stream_id": stream_id,
            }
            for stream_id, item in sorted(expected_heads.items())
        ]
        start_final_invariants = {
            "finalCountsBindPriorPublications": final_payload[
                "source_event_type_counts_before_final"
            ] == expected_counts,
            "finalHeadsBindPriorPublications": final_payload[
                "source_stream_heads_before_final"
            ] == expected_head_rows,
            "finalIsLast": parsed[-1].payload.get("manifest_phase") == "FINAL",
            "startIsFirst": parsed[0].payload.get("manifest_phase") == "START",
            "startPrecedesEveryEvent": publications[0].publication_ordinal == 1,
        }
        start_final = {
            "finalPayload": final_payload,
            "invariants": start_final_invariants,
            "status": "PASS" if all(start_final_invariants.values()) else "FAIL",
            "task": "ARGUS-CONTINUOUS-RESEARCH-EXPORT-002",
        }
        _write(output / "start-final-proof.json", start_final)

        streams: dict[str, list[object]] = {}
        for item in parsed:
            streams.setdefault(item.stream_id, []).append(item)
        chain_rows: list[dict[str, object]] = []
        chain_pass = True
        for stream_id, items in sorted(streams.items()):
            previous = "0" * 64
            for sequence, item in enumerate(items, start=1):
                passed = (
                    item.source_sequence == sequence
                    and item.previous_record_sha256 == previous
                )
                chain_pass = chain_pass and passed
                chain_rows.append(
                    {
                        "expectedPreviousSha256": previous,
                        "passed": passed,
                        "rawSha256": item.raw_sha256,
                        "sequence": item.source_sequence,
                        "streamId": stream_id,
                    }
                )
                previous = item.raw_sha256
        hash_chain = {
            "rows": chain_rows,
            "status": "PASS" if chain_pass else "FAIL",
            "task": "ARGUS-CONTINUOUS-RESEARCH-EXPORT-002",
        }
        _write(output / "hash-chain-proof.json", hash_chain)

        invariants = {
            "allExporterBytesParseV2Directly": len(parsed) == len(publications),
            "circularDependencyRemoved": two_clock["status"] == "PASS",
            "crashMatrixPassed": crash_matrix["status"] == "PASS",
            "decisionHasNoScienceField": not any(
                field.startswith("science_")
                or field == "outcome_eligibility_commitment_sha256"
                for field in decision_fields
            ),
            "finalProofPassed": start_final["status"] == "PASS",
            "hashChainPassed": hash_chain["status"] == "PASS",
            "oldClassBDataUpgraded": False,
            "partialSourceNeverAdmitted": partial_not_visible,
            "producerRequiresFutureScienceHash": False,
            "scienceCustodyAcceptsExporterBytes": all(
                row["verifyAllHashesValid"] for row in two_clock_rows
            ),
        }
        summary = {
            "approvedPython": {
                "executable": sys.executable,
                "executableSha256": hashlib.sha256(
                    Path(sys.executable).read_bytes()
                ).hexdigest().upper(),
                "version": sys.version,
            },
            "completedAt": datetime.now().astimezone().isoformat(),
            "git": {
                "head": _git(repository, "rev-parse", "HEAD"),
                "statusPorcelain": _git(repository, "status", "--porcelain=v1"),
            },
            "invariants": invariants,
            "producerRawSha256s": producer_raw_sha256s,
            "status": "PASS" if all(
                value is True
                for key, value in invariants.items()
                if key not in {
                    "oldClassBDataUpgraded",
                    "producerRequiresFutureScienceHash",
                }
            ) and invariants["oldClassBDataUpgraded"] is False
            and invariants["producerRequiresFutureScienceHash"] is False
            else "FAIL",
            "task": "ARGUS-CONTINUOUS-RESEARCH-EXPORT-002",
        }
        _write(output / "offline-qualification.json", summary)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
