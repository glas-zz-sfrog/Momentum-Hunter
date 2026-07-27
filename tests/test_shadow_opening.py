from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import momentum_hunter.shadow_opening as shadow_opening
from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_opening import (
    AuditArtifact,
    ShadowOpeningSafetyError,
    build_https_clock_skew_proof,
    build_opening_audit_manifest,
    build_shadow_handoff_receipt,
    classify_opening_heartbeat,
    clock_skew_findings,
    shadow_handoff_findings,
)


UTC = timezone.utc


class ShadowOpeningClockTests(unittest.TestCase):
    def test_clock_proof_passes_within_five_second_uncertainty_gate(self) -> None:
        remote = datetime(2026, 7, 27, 13, 35, 0, tzinfo=UTC)
        proof = build_https_clock_skew_proof(
            request_started_at=remote,
            response_received_at=remote + timedelta(milliseconds=200),
            remote_date_header=format_datetime(remote),
            source_identity="https://api.schwabapi.com/marketdata/v1/quotes",
        )

        self.assertEqual("PASS", proof["status"])
        self.assertEqual([], proof["findings"])
        self.assertEqual(
            (),
            clock_skew_findings(
                proof,
                evaluated_at=remote + timedelta(milliseconds=200),
            ),
        )

    def test_clock_proof_blocks_skew_over_five_seconds(self) -> None:
        remote = datetime(2026, 7, 27, 13, 35, 0, tzinfo=UTC)
        proof = build_https_clock_skew_proof(
            request_started_at=remote + timedelta(seconds=7),
            response_received_at=remote + timedelta(seconds=7, milliseconds=50),
            remote_date_header=format_datetime(remote),
            source_identity="schwab-quotes",
        )

        self.assertEqual("BLOCKED", proof["status"])
        self.assertTrue(proof["findings"])

    def test_clock_proof_blocks_missing_remote_time(self) -> None:
        now = datetime(2026, 7, 27, 13, 35, 0, tzinfo=UTC)

        proof = build_https_clock_skew_proof(
            request_started_at=now,
            response_received_at=now + timedelta(milliseconds=50),
            remote_date_header="",
            source_identity="schwab-quotes",
        )

        self.assertEqual("BLOCKED", proof["status"])
        self.assertIn("missing or invalid", proof["findings"][0])

    def test_clock_proof_blocks_contradictory_local_times(self) -> None:
        now = datetime(2026, 7, 27, 13, 35, 0, tzinfo=UTC)

        proof = build_https_clock_skew_proof(
            request_started_at=now,
            response_received_at=now - timedelta(milliseconds=1),
            remote_date_header=format_datetime(now),
            source_identity="schwab-quotes",
        )

        self.assertEqual("BLOCKED", proof["status"])
        self.assertIn("precedes", proof["findings"][0])

    def test_clock_proof_blocks_excessive_request_uncertainty(self) -> None:
        remote = datetime(2026, 7, 27, 13, 35, 0, tzinfo=UTC)

        proof = build_https_clock_skew_proof(
            request_started_at=remote - timedelta(seconds=3),
            response_received_at=remote + timedelta(seconds=3),
            remote_date_header=format_datetime(remote),
            source_identity="schwab-quotes",
        )

        self.assertEqual("BLOCKED", proof["status"])
        self.assertGreater(
            proof["measurementUncertaintyMilliseconds"],
            proof["maximumAbsoluteSkewMilliseconds"],
        )

    def test_clock_proof_expires_after_five_minutes(self) -> None:
        remote = datetime(2026, 7, 27, 13, 35, 0, tzinfo=UTC)
        proof = build_https_clock_skew_proof(
            request_started_at=remote,
            response_received_at=remote + timedelta(milliseconds=100),
            remote_date_header=format_datetime(remote),
            source_identity="schwab-quotes",
        )

        findings = clock_skew_findings(
            proof,
            evaluated_at=remote + timedelta(minutes=5, seconds=1),
        )

        self.assertTrue(any("older than 300 seconds" in item for item in findings))

    def test_clock_validation_recomputes_and_rejects_tampered_summary(
        self,
    ) -> None:
        remote = datetime(2026, 7, 27, 13, 35, 0, tzinfo=UTC)
        proof = build_https_clock_skew_proof(
            request_started_at=remote,
            response_received_at=remote + timedelta(milliseconds=100),
            remote_date_header=format_datetime(remote),
            source_identity="schwab-quotes",
        )
        proof["absoluteSkewMilliseconds"] = 0

        findings = clock_skew_findings(
            proof,
            evaluated_at=remote + timedelta(milliseconds=100),
        )

        self.assertTrue(
            any("absolute measurement" in item for item in findings)
        )


class ShadowOpeningHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recorded_at = datetime(2026, 7, 27, 13, 50, tzinfo=UTC)
        self.report_hash = "a" * 64
        self.report_path = Path("trade-planning-shadow.json")

    def test_trade_terminal_outcome_builds_complete_receipt(self) -> None:
        receipt = build_shadow_handoff_receipt(
            report_path=self.report_path,
            report_sha256=self.report_hash,
            capture_id="capture-1",
            cycle=self.cycle(
                {
                    "status": "TRADE_STARTED",
                    "decisionCycleId": "cycle-1",
                    "reportSha256": self.report_hash,
                    "shadowTradeId": "trade-1",
                }
            ),
            recorded_at=self.recorded_at,
        )

        self.assertEqual("CYCLE_COMPLETED_TRADE_CREATED", receipt["status"])
        self.assertEqual("trade-1", receipt["shadowTradeId"])
        self.assertEqual(
            (),
            shadow_handoff_findings(
                receipt,
                expected_report_sha256=self.report_hash,
            ),
        )

    def test_no_trade_terminal_outcome_builds_complete_receipt(self) -> None:
        receipt = build_shadow_handoff_receipt(
            report_path=self.report_path,
            report_sha256=self.report_hash,
            capture_id="capture-1",
            cycle=self.cycle(
                {
                    "status": "NO_ELIGIBLE_CANDIDATE",
                    "decisionCycleId": "cycle-1",
                    "reportSha256": self.report_hash,
                    "shadowTradeId": None,
                }
            ),
            recorded_at=self.recorded_at,
        )

        self.assertEqual("CYCLE_COMPLETED_NO_TRADE", receipt["status"])
        self.assertIsNone(receipt["shadowTradeId"])

    def test_failed_or_unknown_cycle_cannot_build_receipt(self) -> None:
        failed = self.cycle(
            {
                "status": "NO_ELIGIBLE_CANDIDATE",
                "decisionCycleId": "cycle-1",
                "reportSha256": self.report_hash,
            },
            accepted=False,
        )
        unknown = self.cycle(
            {
                "status": "UNKNOWN",
                "decisionCycleId": "cycle-1",
                "reportSha256": self.report_hash,
            }
        )

        with self.assertRaisesRegex(
            ShadowOpeningSafetyError,
            "did not accept",
        ):
            build_shadow_handoff_receipt(
                report_path=self.report_path,
                report_sha256=self.report_hash,
                capture_id="capture-1",
                cycle=failed,
                recorded_at=self.recorded_at,
            )
        with self.assertRaisesRegex(
            ShadowOpeningSafetyError,
            "not an allowed terminal state",
        ):
            build_shadow_handoff_receipt(
                report_path=self.report_path,
                report_sha256=self.report_hash,
                capture_id="capture-1",
                cycle=unknown,
                recorded_at=self.recorded_at,
            )

    def test_missing_host_identity_cannot_build_receipt(self) -> None:
        cycle = self.cycle(
            {
                "status": "NO_ELIGIBLE_CANDIDATE",
                "decisionCycleId": "cycle-1",
                "reportSha256": self.report_hash,
            }
        )
        cycle.snapshot["identity"]["hostInstanceId"] = ""

        with self.assertRaisesRegex(
            ShadowOpeningSafetyError,
            "Complete handoff requires host",
        ):
            build_shadow_handoff_receipt(
                report_path=self.report_path,
                report_sha256=self.report_hash,
                capture_id="capture-1",
                cycle=cycle,
                recorded_at=self.recorded_at,
            )

    def cycle(
        self,
        selection: dict[str, object],
        *,
        accepted: bool = True,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            accepted=accepted,
            code="COLLECTION_COMPLETED",
            command_id="command-1",
            payload={"shadowAutomaticSelection": selection},
            snapshot={
                "identity": {
                    "hostInstanceId": "host-1",
                    "processId": 1234,
                    "protocolVersion": "1.0",
                    "transport": "loopback",
                },
                "collection": {
                    "lastCompletedCycleAtUtc": self.recorded_at.isoformat(),
                },
            },
        )


class ShadowOpeningHeartbeatAndManifestTests(unittest.TestCase):
    def test_heartbeat_is_tri_state_and_retires_only_complete_result(self) -> None:
        completed = classify_opening_heartbeat(
            task_running=False,
            process_alive=False,
            retry_pending=False,
            final_result_available=True,
            final_result_succeeded=True,
            proof_complete=True,
            handoff_complete=True,
        )
        running = classify_opening_heartbeat(
            task_running=True,
            process_alive=False,
            retry_pending=False,
            final_result_available=False,
            final_result_succeeded=False,
            proof_complete=False,
            handoff_complete=False,
        )
        retrying = classify_opening_heartbeat(
            task_running=False,
            process_alive=False,
            retry_pending=True,
            final_result_available=False,
            final_result_succeeded=False,
            proof_complete=False,
            handoff_complete=False,
        )
        failed = classify_opening_heartbeat(
            task_running=False,
            process_alive=False,
            retry_pending=False,
            final_result_available=True,
            final_result_succeeded=False,
            proof_complete=False,
            handoff_complete=False,
        )

        self.assertEqual(("COMPLETED", True), (completed.outcome, completed.retire_heartbeat))
        self.assertEqual(("IN_PROGRESS", False), (running.outcome, running.retire_heartbeat))
        self.assertEqual(("IN_PROGRESS", False), (retrying.outcome, retrying.retire_heartbeat))
        self.assertEqual(("FAILED", False), (failed.outcome, failed.retire_heartbeat))

    def test_heartbeat_contract_is_read_only(self) -> None:
        source = inspect.getsource(shadow_opening)

        self.assertNotIn("subprocess", source)
        self.assertNotIn("Popen", source)
        self.assertNotIn("Start-ScheduledTask", source)

    def test_manifest_has_twelve_hash_addressed_categories(self) -> None:
        now = datetime(2026, 7, 27, 13, 50, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts: list[AuditArtifact] = []
            for index, name in enumerate(
                shadow_opening.SHADOW_OPENING_AUDIT_CATEGORIES
            ):
                if index % 2 == 0:
                    path = root / f"{name}.json"
                    path.write_text(name, encoding="utf-8")
                    artifacts.append(
                        AuditArtifact(
                            name=name,
                            purpose=f"Proof for {name}",
                            required=True,
                            status="PRESENT",
                            path=path,
                        )
                    )
                else:
                    artifacts.append(
                        AuditArtifact(
                            name=name,
                            purpose=f"Proof for {name}",
                            required=False,
                            status="NOT_CREATED",
                            not_created_reason="Terminal path did not create it.",
                        )
                    )

            manifest = build_opening_audit_manifest(
                artifacts,
                created_at=now,
            )

            self.assertEqual(12, len(manifest["artifacts"]))
            self.assertEqual("SHA256_CONTENT_ADDRESS", manifest["signatureMode"])
            for item in manifest["artifacts"]:
                if item["status"] == "PRESENT":
                    self.assertEqual(64, len(item["sha256"]))
                    self.assertFalse(Path(item["location"]).is_absolute())
                else:
                    self.assertIsNone(item["sha256"])
                    self.assertTrue(item["notCreatedReason"])

    def test_manifest_rejects_not_created_claim_for_existing_file(self) -> None:
        now = datetime(2026, 7, 27, 13, 50, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "unexpected.json"
            existing.write_text("exists", encoding="utf-8")
            artifacts = [
                AuditArtifact(
                    name=name,
                    purpose=name,
                    required=True,
                    status="NOT_CREATED",
                    path=(existing if index == 0 else None),
                    not_created_reason="claimed absent",
                )
                for index, name in enumerate(
                    shadow_opening.SHADOW_OPENING_AUDIT_CATEGORIES
                )
            ]

            with self.assertRaisesRegex(
                ShadowOpeningSafetyError,
                "NOT_CREATED audit artifact exists",
            ):
                build_opening_audit_manifest(
                    artifacts,
                    created_at=now,
                )

    def test_pure_opening_contracts_do_not_mutate_production_shadow_state(
        self,
    ) -> None:
        shadow_dir = DATA_DIR / "shadow-trading"
        before = production_shadow_snapshot(shadow_dir)

        classify_opening_heartbeat(
            task_running=False,
            process_alive=False,
            retry_pending=False,
            final_result_available=False,
            final_result_succeeded=False,
            proof_complete=False,
            handoff_complete=False,
        )
        build_https_clock_skew_proof(
            request_started_at=datetime(
                2026,
                7,
                27,
                13,
                35,
                tzinfo=UTC,
            ),
            response_received_at=datetime(
                2026,
                7,
                27,
                13,
                35,
                0,
                100_000,
                tzinfo=UTC,
            ),
            remote_date_header="Mon, 27 Jul 2026 13:35:00 GMT",
            source_identity="synthetic-test-source",
        )

        self.assertEqual(before, production_shadow_snapshot(shadow_dir))


def production_shadow_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    protected_names = {
        "shadow-sample-activation.json",
        "shadow-selection-policy.json",
        "shadow-selector-arm.json",
        "shadow-decision-cycles.json",
        "shadow-trading-state.json",
    }
    result: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in protected_names or "capture-handoffs" in path.parts:
            result[str(path.resolve())] = path.read_bytes()
    return result


if __name__ == "__main__":
    unittest.main()
