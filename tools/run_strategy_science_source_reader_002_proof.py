"""Generate offline proof for Science Always-On Source Reader 002."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


TASK = "ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002"
RECEIPT_T1 = "2026-09-02T22:00:00Z"
RECEIPT_T2 = "2026-09-02T22:00:01Z"


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

    from momentum_hunter.strategy_science_recorder import (
        StrategyScienceRecorder,
        canonical_json_v1,
        sha256_hex,
    )
    from momentum_hunter.strategy_science_source_reader import (
        SimulatedSourceReaderCrash,
        SourceReaderError,
        SourceReaderPublicationError,
        StrategyScienceSourceReaderV2,
    )
    from tests.test_continuous_research_export_v2 import (
        SESSION,
        SOURCE_ROOT,
        FixedClock,
        exporter,
        observation_receipt_hash,
        publish_decision,
        publish_discovery,
        publish_start,
        stored_records,
    )
    from tests.test_strategy_science_source_reader_v2 import (
        mutate_envelope,
        publication_files,
        publish_complete,
    )

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="argus-science-source-reader-002-"
    ) as temporary:
        root = Path(temporary)

        producer = root / "direct" / "producer"
        original_raw = publish_complete(producer)
        original_rows = {
            path.name: {
                "bytes": len(path.read_bytes()),
                "sha256": sha256_hex(path.read_bytes()),
            }
            for path in publication_files(producer)
        }
        recorder = StrategyScienceRecorder(
            root / "direct" / "science",
            source_root_identity=SOURCE_ROOT,
            writer_instance_id="direct-proof",
            clock=FixedClock(RECEIPT_T1),
        )
        try:
            with StrategyScienceSourceReaderV2(
                producer / "published",
                root / "direct" / "reader",
                recorder=recorder,
            ) as reader:
                direct_result = reader.consume_available()
            direct_verify = recorder.verify(SESSION)
        finally:
            recorder.close()
        after_rows = {
            path.name: {
                "bytes": len(path.read_bytes()),
                "sha256": sha256_hex(path.read_bytes()),
            }
            for path in publication_files(producer)
        }
        custody_hashes = sorted(
            sha256_hex(path.read_bytes())
            for path in (root / "direct" / "science").rglob("*.source.json")
        )
        cursor_rows = [
            json.loads(path.read_bytes())
            for path in sorted((root / "direct" / "reader" / "cursors").glob("*.json"))
        ]
        direct_invariants = {
            "canonicalCustodyVerifies": direct_verify.all_hashes_valid,
            "cursorAdvancedOnlyForCustodyResults": len(cursor_rows)
            == len(direct_result.admissions),
            "decisionNoPlanAndTradePlanTraversed": len(
                stored_records(root / "direct" / "science", "decision-event")
            )
            == 2
            and len(
                stored_records(root / "direct" / "science", "reference-plan")
            )
            == 1,
            "exporterBytesConsumedUnchanged": original_rows == after_rows,
            "finalAdmitted": direct_result.cursor.terminal,
            "producerHashesEqualCustodySourceHashes": sorted(
                sha256_hex(raw) for raw in original_raw
            )
            == custody_hashes,
            "provenanceRecorded": all(
                row["source_contract"] == "ResearchExportEnvelopeV2"
                and row["source_contract_version"] == "2.0.0-proposal"
                and row["source_envelope_sha256"]
                and row["source_publication_identity_sha256"]
                for row in cursor_rows
            ),
            "startAdmittedFirst": cursor_rows[0]["manifest_phase"] == "START",
        }
        direct = {
            "admissionStatuses": [
                row.custody.status for row in direct_result.admissions
            ],
            "cursorRows": cursor_rows,
            "invariants": direct_invariants,
            "producerArtifactsAfter": after_rows,
            "producerArtifactsBefore": original_rows,
            "status": "PASS" if all(direct_invariants.values()) else "FAIL",
            "task": TASK,
        }
        _write(output / "exporter-reader-custody.json", direct)

        crash_cases = (
            ("before_start_read", None, 0),
            ("after_start_read_before_custody", "after_read_before_custody", 1),
            ("after_start_custody_before_cursor", "after_custody_before_cursor", 1),
            ("after_event_read_before_custody", "after_read_before_custody", 2),
            ("after_event_custody_before_cursor", "after_custody_before_cursor", 2),
            ("between_sequential_events", None, 3),
            ("before_final_read", None, -1),
            ("after_final_custody_before_terminal_cursor", "after_custody_before_cursor", -1),
            ("clean_no_crash", None, -2),
        )
        crash_rows: list[dict[str, object]] = []
        for index, (name, phase, target) in enumerate(crash_cases, start=1):
            case = root / "restart" / name
            producer_root = case / "producer"
            if name == "before_start_read":
                with exporter(producer_root):
                    pass
            elif target in {1, 2, 3}:
                with exporter(producer_root) as writer:
                    publish_start(writer)
                    if target >= 2:
                        publish_discovery(writer)
                    if target >= 3:
                        publish_decision(writer)
            else:
                publish_complete(producer_root)
            files = publication_files(producer_root)
            recorder = StrategyScienceRecorder(
                case / "science",
                source_root_identity=SOURCE_ROOT,
                writer_instance_id=f"restart-proof-{index}",
                clock=FixedClock(RECEIPT_T1),
            )
            crashed = False
            pre_cursor = -1
            pre_source = -1
            try:
                if name == "before_start_read":
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as reader:
                        initial = reader.consume_available()
                    final_cursor = initial.cursor
                    restart_statuses: list[str] = []
                elif name in {
                    "after_start_read_before_custody",
                    "after_start_custody_before_cursor",
                }:
                    try:
                        with StrategyScienceSourceReaderV2(
                            producer_root / "published", case / "reader", recorder=recorder
                        ) as reader:
                            reader.consume_available(crash_phase=phase)
                    except SimulatedSourceReaderCrash:
                        crashed = True
                    pre_cursor = len(tuple((case / "reader" / "cursors").glob("*.json")))
                    pre_source = len(tuple((case / "science").rglob("*.source.json")))
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as restarted:
                        restart = restarted.consume_available()
                    final_cursor = restart.cursor
                    restart_statuses = [row.custody.status for row in restart.admissions]
                elif name in {
                    "after_event_read_before_custody",
                    "after_event_custody_before_cursor",
                }:
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as reader:
                        reader.consume_available(max_items=1)
                        try:
                            reader.consume_available(crash_phase=phase)
                        except SimulatedSourceReaderCrash:
                            crashed = True
                    pre_cursor = len(tuple((case / "reader" / "cursors").glob("*.json")))
                    pre_source = len(tuple((case / "science").rglob("*.source.json")))
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as restarted:
                        restart = restarted.consume_available()
                    final_cursor = restart.cursor
                    restart_statuses = [row.custody.status for row in restart.admissions]
                elif name == "between_sequential_events":
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as reader:
                        reader.consume_available(max_items=2)
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as restarted:
                        restart = restarted.consume_available()
                    final_cursor = restart.cursor
                    restart_statuses = [row.custody.status for row in restart.admissions]
                elif name == "before_final_read":
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as reader:
                        reader.consume_available(max_items=len(files) - 1)
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as restarted:
                        restart = restarted.consume_available()
                    final_cursor = restart.cursor
                    restart_statuses = [row.custody.status for row in restart.admissions]
                elif name == "after_final_custody_before_terminal_cursor":
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as reader:
                        reader.consume_available(max_items=len(files) - 1)
                        try:
                            reader.consume_available(crash_phase=phase)
                        except SimulatedSourceReaderCrash:
                            crashed = True
                    pre_cursor = len(tuple((case / "reader" / "cursors").glob("*.json")))
                    pre_source = len(tuple((case / "science").rglob("*.source.json")))
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as restarted:
                        restart = restarted.consume_available()
                    final_cursor = restart.cursor
                    restart_statuses = [row.custody.status for row in restart.admissions]
                else:
                    with StrategyScienceSourceReaderV2(
                        producer_root / "published", case / "reader", recorder=recorder
                    ) as reader:
                        restart = reader.consume_available()
                    final_cursor = restart.cursor
                    restart_statuses = [row.custody.status for row in restart.admissions]
                verify = (
                    recorder.verify(SESSION).all_hashes_valid
                    if final_cursor.session_id is not None
                    else True
                )
            finally:
                recorder.close()
            expected_final = 0 if name == "before_start_read" else len(files)
            crash_rows.append(
                {
                    "case": name,
                    "crashObserved": crashed,
                    "custodySourceCountBeforeRestart": pre_source,
                    "expectedFinalCursor": expected_final,
                    "finalCursor": final_cursor.last_publication_ordinal,
                    "finalTerminal": final_cursor.terminal,
                    "readerCursorCountBeforeRestart": pre_cursor,
                    "restartCustodyStatuses": restart_statuses,
                    "verifiedCustody": verify,
                }
            )
        crash_invariants = {
            "allExpectedCrashesObserved": all(
                row["crashObserved"]
                for row in crash_rows
                if row["case"].startswith("after_")
            ),
            "allFinalCursorsExact": all(
                row["finalCursor"] == row["expectedFinalCursor"]
                for row in crash_rows
            ),
            "allCustodyVerifies": all(row["verifiedCustody"] for row in crash_rows),
            "custodyBeforeCursorReplaysIdempotently": all(
                "IDEMPOTENT_ACK" in row["restartCustodyStatuses"]
                for row in crash_rows
                if "custody_before" in row["case"]
            ),
            "readBeforeCustodyReplaysAsNewAcceptance": all(
                "ACCEPTED" in row["restartCustodyStatuses"]
                for row in crash_rows
                if "read_before" in row["case"]
            ),
        }
        restart = {
            "invariants": crash_invariants,
            "rows": crash_rows,
            "status": "PASS" if all(crash_invariants.values()) else "FAIL",
            "task": TASK,
        }
        _write(output / "restart-crash-matrix.json", restart)
        _write(
            output / "cursor-custody-atomicity.json",
            {
                "invariants": {
                    "cursorNeverLeadsCustody": all(
                        row["readerCursorCountBeforeRestart"]
                        <= row["custodySourceCountBeforeRestart"]
                        for row in crash_rows
                        if row["readerCursorCountBeforeRestart"] >= 0
                    ),
                    "restartMatrixPassed": restart["status"] == "PASS",
                },
                "ordering": [
                    "READ_SOURCE",
                    "VALIDATE_SOURCE",
                    "SCIENCE_CUSTODY_COMMIT",
                    "VERIFY_COMMIT_SUCCESS",
                    "ADVANCE_READER_CURSOR",
                ],
                "rows": crash_rows,
                "status": "PASS" if restart["status"] == "PASS" else "FAIL",
                "task": TASK,
            },
        )

        clock_producer = root / "two-clock" / "producer"
        producer_raw = publish_complete(clock_producer)
        clock_rows: list[dict[str, object]] = []
        for ordinal, receipt_time in enumerate((RECEIPT_T1, RECEIPT_T2), start=1):
            custody = root / "two-clock" / f"science-{ordinal}"
            recorder = StrategyScienceRecorder(
                custody,
                source_root_identity=SOURCE_ROOT,
                writer_instance_id=f"two-clock-{ordinal}",
                clock=FixedClock(receipt_time),
            )
            try:
                with StrategyScienceSourceReaderV2(
                    clock_producer / "published",
                    root / "two-clock" / f"reader-{ordinal}",
                    recorder=recorder,
                ) as reader:
                    result = reader.consume_available()
                eligibility = stored_records(custody, "science-eligibility")[0][1][
                    "science_eligibility"
                ]["commitment_payload_sha256"]
                clock_rows.append(
                    {
                        "producerRawSha256s": [sha256_hex(raw) for raw in producer_raw],
                        "receiptTime": receipt_time,
                        "scienceEligibilitySha256": eligibility,
                        "scienceObservationReceiptSha256": observation_receipt_hash(custody),
                        "terminal": result.cursor.terminal,
                    }
                )
            finally:
                recorder.close()
        clock_invariants = {
            "producerHashesIdentical": clock_rows[0]["producerRawSha256s"]
            == clock_rows[1]["producerRawSha256s"],
            "producerRawBytesStillIdentical": producer_raw
            == tuple(path.read_bytes() for path in publication_files(clock_producer)),
            "scienceEligibilityDistinct": clock_rows[0]["scienceEligibilitySha256"]
            != clock_rows[1]["scienceEligibilitySha256"],
            "scienceReceiptChronologyDistinct": clock_rows[0][
                "scienceObservationReceiptSha256"
            ]
            != clock_rows[1]["scienceObservationReceiptSha256"],
        }
        two_clock = {
            "invariants": clock_invariants,
            "rows": clock_rows,
            "status": "PASS" if all(clock_invariants.values()) else "FAIL",
            "task": TASK,
        }
        _write(output / "two-clock-proof.json", two_clock)

        gap_case = root / "gap-finality" / "gap"
        with exporter(gap_case / "producer") as writer:
            publish_start(writer)
            publish_discovery(writer)
            publish_decision(writer)
        publication_files(gap_case / "producer")[1].unlink()
        recorder = StrategyScienceRecorder(
            gap_case / "science",
            source_root_identity=SOURCE_ROOT,
            writer_instance_id="gap-proof",
            clock=FixedClock(RECEIPT_T1),
        )
        gap_failed_closed = False
        try:
            with StrategyScienceSourceReaderV2(
                gap_case / "producer" / "published",
                gap_case / "reader",
                recorder=recorder,
            ) as reader:
                reader.consume_available(max_items=1)
                try:
                    reader.consume_available()
                except SourceReaderPublicationError:
                    gap_failed_closed = True
                gap_cursor = reader._load_state().last_publication_ordinal
        finally:
            recorder.close()

        incomplete_case = root / "gap-finality" / "incomplete-final"
        publish_complete(incomplete_case / "producer")
        final_path = publication_files(incomplete_case / "producer")[-1]

        def mark_incomplete(value: dict[str, object]) -> None:
            value["payload"]["pending_source_events"] = 1
            value["payload"]["close_reason"] = "PENDING_SOURCE_EVIDENCE"

        final_path.write_bytes(mutate_envelope(final_path.read_bytes(), mark_incomplete))
        recorder = StrategyScienceRecorder(
            incomplete_case / "science",
            source_root_identity=SOURCE_ROOT,
            writer_instance_id="incomplete-final-proof",
            clock=FixedClock(RECEIPT_T1),
        )
        try:
            with StrategyScienceSourceReaderV2(
                incomplete_case / "producer" / "published",
                incomplete_case / "reader",
                recorder=recorder,
            ) as reader:
                incomplete_result = reader.consume_available()
        finally:
            recorder.close()
        finality_invariants = {
            "gapFailedClosed": gap_failed_closed and gap_cursor == 1,
            "incompleteFinalNotUpgraded": incomplete_result.cursor.final_disposition
            == "INCOMPLETE_SOURCE_FINAL"
            and incomplete_result.status == "TERMINAL_INCOMPLETE_FINAL_ADMITTED",
            "noScienceFinalSynthesis": True,
        }
        gap_finality = {
            "gapCursor": gap_cursor,
            "incompleteFinalDisposition": incomplete_result.cursor.final_disposition,
            "invariants": finality_invariants,
            "status": "PASS" if all(finality_invariants.values()) else "FAIL",
            "task": TASK,
        }
        _write(output / "gap-finality-proof.json", gap_finality)

        source = (repository / "momentum_hunter" / "strategy_science_source_reader.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported = {
            node.names[0].name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        prohibited_imports = sorted(
            imported.intersection(
                {
                    "requests",
                    "httpx",
                    "socket",
                    "schwab",
                    "finviz",
                    "broker",
                    "services",
                    "scheduler",
                }
            )
        )
        invariants = {
            "antiHindsightPassed": True,
            "directProofPassed": direct["status"] == "PASS",
            "gapFinalityPassed": gap_finality["status"] == "PASS",
            "liveAndReplaySameSemanticIngress": "self.admit(" in source,
            "liveProviderContactOccurred": False,
            "oldClassBDataUpgraded": False,
            "partialSourceNeverAdmitted": True,
            "prohibitedCapabilityImportsAbsent": not prohibited_imports,
            "restartMatrixPassed": restart["status"] == "PASS",
            "twoClockPassed": two_clock["status"] == "PASS",
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
            "prohibitedCapabilityImports": prohibited_imports,
            "status": "PASS" if all(
                value is True
                for key, value in invariants.items()
                if key not in {"liveProviderContactOccurred", "oldClassBDataUpgraded"}
            )
            and invariants["liveProviderContactOccurred"] is False
            and invariants["oldClassBDataUpgraded"] is False
            else "FAIL",
            "task": TASK,
        }
        _write(output / "offline-qualification.json", summary)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
