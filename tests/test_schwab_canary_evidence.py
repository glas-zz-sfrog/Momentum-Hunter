from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import momentum_hunter.schwab_canary_evidence as evidence_module
from momentum_hunter.schwab_canary_evidence import (
    AWAITING_PRE_CANARY,
    CANARY_ACTIVE_VERIFIED,
    CANARY_SEQUENCE_COMPLETE,
    PRE_CANARY_VERIFIED,
    CanaryPositionEvidenceError,
    CanaryPositionEvidenceStore,
)
from momentum_hunter.schwab_canary_positions import (
    CANARY_ACTIVE,
    POST_CANARY,
    PRE_CANARY,
    CanaryIntent,
    CanaryPositionFinding,
    CanaryPositionInvariantResult,
)
from momentum_hunter.schwab_emulator import (
    SYNTHETIC_ACCOUNT_HASH,
    SYNTHETIC_ACCOUNT_LAST_FOUR,
    synthetic_source,
)
from momentum_hunter.schwab_readonly import AccountIsolationPolicy


BASE_TIME = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


class CanaryPositionEvidenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "canary-position-evidence.json"
        source = synthetic_source()
        self.binding = AccountIsolationPolicy().create_binding(
            source.list_authorized_accounts(),
            manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR,
        )
        self.intent = CanaryIntent(
            intent_id="PLUMBING-CANARY-0001",
            symbol="TEST",
            quantity=1.0,
        )
        self.store = CanaryPositionEvidenceStore(
            path=self.path,
            sequence_id="CANARY-SEQUENCE-0001",
            binding=self.binding,
            intent=self.intent,
        )

    def test_passing_pre_active_post_results_complete_hash_linked_chain(self) -> None:
        pre = self.record(self.result(PRE_CANARY, "PASS", offset=0), offset=1)
        active = self.record(
            self.result(CANARY_ACTIVE, "PASS", offset=2),
            offset=3,
        )
        complete = self.record(
            self.result(POST_CANARY, "PASS", offset=4),
            offset=5,
        )

        self.assertEqual(PRE_CANARY_VERIFIED, pre["chainState"])
        self.assertEqual(CANARY_ACTIVE_VERIFIED, active["chainState"])
        self.assertEqual(CANARY_SEQUENCE_COMPLETE, complete["chainState"])
        self.assertEqual(3, len(complete["entries"]))
        self.assertEqual(
            complete["entries"][0]["entrySha256"],
            complete["entries"][1]["previousEntrySha256"],
        )
        self.assertEqual(
            complete["entries"][1]["entrySha256"],
            complete["entries"][2]["previousEntrySha256"],
        )
        self.assertEqual(complete, self.store.load())

    def test_blocked_attempt_is_preserved_without_advancing_phase(self) -> None:
        blocked = self.record(
            self.result(PRE_CANARY, "BLOCK", offset=0),
            offset=1,
        )
        passed = self.record(
            self.result(PRE_CANARY, "PASS", offset=2),
            offset=3,
        )

        self.assertEqual(AWAITING_PRE_CANARY, blocked["chainState"])
        self.assertEqual(PRE_CANARY_VERIFIED, passed["chainState"])
        self.assertEqual("BLOCK", passed["entries"][0]["result"]["status"])
        self.assertEqual("PASS", passed["entries"][1]["result"]["status"])

    def test_phase_order_and_completed_sequence_fail_closed_without_mutation(self) -> None:
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "must be PRE_CANARY"):
            self.record(
                self.result(CANARY_ACTIVE, "PASS", offset=0),
                offset=1,
            )
        self.assertFalse(self.path.exists())

        self.record(self.result(PRE_CANARY, "PASS", offset=0), offset=1)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "must be CANARY_ACTIVE"):
            self.record(self.result(POST_CANARY, "PASS", offset=2), offset=3)
        self.assertEqual(before, self.path.read_bytes())

        self.record(self.result(CANARY_ACTIVE, "PASS", offset=2), offset=3)
        self.record(self.result(POST_CANARY, "PASS", offset=4), offset=5)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "already complete"):
            self.record(self.result(POST_CANARY, "BLOCK", offset=6), offset=7)
        self.assertEqual(before, self.path.read_bytes())

    def test_exact_duplicate_retry_is_byte_idempotent(self) -> None:
        result = self.result(PRE_CANARY, "PASS", offset=0)
        first = self.record(result, offset=1)
        before = self.path.read_bytes()
        retried = self.record(result, offset=20)

        self.assertEqual(first, retried)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(1, len(retried["entries"]))

    def test_intent_account_and_binding_changes_are_rejected(self) -> None:
        mismatches = (
            replace(
                self.result(PRE_CANARY, "PASS", offset=0),
                account_ending="9999",
            ),
            replace(
                self.result(PRE_CANARY, "PASS", offset=0),
                canary_intent_id="OTHER-INTENT",
            ),
            replace(
                self.result(PRE_CANARY, "PASS", offset=0),
                canary_symbol="SPY",
            ),
            replace(
                self.result(PRE_CANARY, "PASS", offset=0),
                expected_quantity=2.0,
            ),
        )
        for result in mismatches:
            with self.subTest(result=result), self.assertRaises(
                CanaryPositionEvidenceError
            ):
                self.record(result, offset=1)
        self.assertFalse(self.path.exists())

        other_binding = replace(
            self.binding,
            account_hash="SYNTHETIC-OTHER-BOUND-HASH",
        )
        other_store = CanaryPositionEvidenceStore(
            path=self.path,
            sequence_id="CANARY-SEQUENCE-0001",
            binding=other_binding,
            intent=self.intent,
        )
        self.record(self.result(PRE_CANARY, "PASS", offset=0), offset=1)
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "bindingCommitment"):
            other_store.load()

    def test_tampered_result_entry_link_and_chain_hash_are_detected(self) -> None:
        self.record(self.result(PRE_CANARY, "PASS", offset=0), offset=1)
        original = json.loads(self.path.read_text(encoding="utf-8"))
        cases = {
            "result": lambda payload: payload["entries"][0]["result"].update(
                {"status": "BLOCK"}
            ),
            "entry": lambda payload: payload["entries"][0].update(
                {"stateAfter": AWAITING_PRE_CANARY}
            ),
            "link": lambda payload: payload["entries"][0].update(
                {"previousEntrySha256": "0" * 64}
            ),
            "chain": lambda payload: payload.update(
                {"chainSha256": "0" * 64}
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                payload = json.loads(json.dumps(original))
                mutate(payload)
                self.path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(CanaryPositionEvidenceError):
                    self.store.load()
        self.path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(PRE_CANARY_VERIFIED, self.store.load()["chainState"])

    def test_malformed_missing_and_nonobject_files_fail_without_repair(self) -> None:
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "No canary"):
            self.store.load()
        for content in ("not-json", "[]", "{}"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                before = self.path.read_bytes()
                with self.assertRaises(CanaryPositionEvidenceError):
                    self.store.load()
                self.assertEqual(before, self.path.read_bytes())

    def test_lock_file_blocks_writer_and_is_not_deleted_by_failed_acquisition(self) -> None:
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        lock_path.write_text("other-writer", encoding="ascii")

        with self.assertRaisesRegex(CanaryPositionEvidenceError, "another writer"):
            self.record(self.result(PRE_CANARY, "PASS", offset=0), offset=1)

        self.assertTrue(lock_path.exists())
        self.assertFalse(self.path.exists())

    def test_lock_cleanup_removes_only_the_lock_token_it_owns(self) -> None:
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        with evidence_module._exclusive_lock(self.path):
            lock_path.write_text("replacement-owner", encoding="ascii")
        self.assertEqual(
            "replacement-owner",
            lock_path.read_text(encoding="ascii"),
        )

        lock_path.unlink()
        with self.assertRaisesRegex(RuntimeError, "inside"):
            with evidence_module._exclusive_lock(self.path):
                raise RuntimeError("inside")
        self.assertFalse(lock_path.exists())

    def test_chronology_and_contradictory_result_status_fail_closed(self) -> None:
        result = self.result(PRE_CANARY, "PASS", offset=2)
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "before it was evaluated"):
            self.record(result, offset=1)

        contradictory_pass = replace(
            result,
            findings=(
                CanaryPositionFinding(
                    code="CONTRADICTION",
                    message="Contradictory finding.",
                ),
            ),
        )
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "contradictory"):
            self.record(contradictory_pass, offset=3)

        contradictory_block = replace(
            self.result(PRE_CANARY, "BLOCK", offset=2),
            findings=(),
        )
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "requires findings"):
            self.record(contradictory_block, offset=3)

    def test_older_evaluation_after_newer_blocked_attempt_is_rejected(self) -> None:
        self.record(
            self.result(PRE_CANARY, "BLOCK", offset=4),
            offset=5,
        )
        before = self.path.read_bytes()
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "evaluation order"):
            self.record(
                self.result(PRE_CANARY, "PASS", offset=2),
                offset=6,
            )
        self.assertEqual(before, self.path.read_bytes())

    def test_recording_clock_cannot_move_backward(self) -> None:
        self.record(
            self.result(PRE_CANARY, "BLOCK", offset=0),
            offset=5,
        )
        before = self.path.read_bytes()
        with self.assertRaisesRegex(CanaryPositionEvidenceError, "cannot move backward"):
            self.record(
                self.result(PRE_CANARY, "PASS", offset=2),
                offset=3,
            )
        self.assertEqual(before, self.path.read_bytes())

    def test_persisted_evidence_is_redacted_and_inputs_are_not_mutated(self) -> None:
        result = self.result(PRE_CANARY, "PASS", offset=0)
        before = repr(result)
        payload = self.record(result, offset=1)
        rendered = self.path.read_text(encoding="utf-8")

        self.assertEqual(before, repr(result))
        self.assertNotIn(SYNTHETIC_ACCOUNT_HASH, rendered)
        self.assertNotIn("accountHash", rendered)
        self.assertNotIn("averagePrice", rendered)
        self.assertEqual(SYNTHETIC_ACCOUNT_LAST_FOUR, payload["accountEnding"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def test_invalid_store_identity_and_binding_are_rejected_before_write(self) -> None:
        for sequence_id in ("", "bad sequence", "../escape"):
            with self.subTest(sequence_id=sequence_id), self.assertRaises(
                CanaryPositionEvidenceError
            ):
                CanaryPositionEvidenceStore(
                    path=self.path,
                    sequence_id=sequence_id,
                    binding=self.binding,
                    intent=self.intent,
                )
        for binding in (
            replace(self.binding, account_hash=""),
            replace(self.binding, account_number_last_four="12"),
            replace(self.binding, account_type="MARGIN"),
        ):
            with self.subTest(binding=binding), self.assertRaises(
                CanaryPositionEvidenceError
            ):
                CanaryPositionEvidenceStore(
                    path=self.path,
                    sequence_id="CANARY-SEQUENCE-0001",
                    binding=binding,
                    intent=self.intent,
                )
        self.assertFalse(self.path.exists())

    def test_module_has_no_network_credential_or_order_capability(self) -> None:
        source = inspect.getsource(evidence_module)
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        self.assertFalse(
            imports
            & {
                "requests",
                "httpx",
                "urllib",
                "socket",
                "subprocess",
                "schwab_onboarding",
                "schwab_market_data",
            }
        )
        forbidden = {
            "preview_order",
            "submit_order",
            "replace_order",
            "cancel_order",
            "transmit_order",
        }
        self.assertFalse(functions & forbidden)
        self.assertFalse(calls & forbidden)

    def record(
        self,
        result: CanaryPositionInvariantResult,
        *,
        offset: int,
    ) -> dict[str, object]:
        return self.store.record(
            result,
            recorded_at=BASE_TIME + timedelta(seconds=offset),
        )

    def result(
        self,
        phase: str,
        status: str,
        *,
        offset: int,
    ) -> CanaryPositionInvariantResult:
        evaluated_at = BASE_TIME + timedelta(seconds=offset)
        findings = (
            ()
            if status == "PASS"
            else (
                CanaryPositionFinding(
                    code="POSITION_BLOCKED",
                    message="Synthetic blocked position evidence.",
                ),
            )
        )
        return CanaryPositionInvariantResult(
            phase=phase,
            status=status,
            evaluated_at=evaluated_at.isoformat(),
            request_started_at=(
                evaluated_at - timedelta(seconds=1)
            ).isoformat(),
            observed_at=evaluated_at.isoformat(),
            collection_duration_seconds=1.0,
            account_ending=SYNTHETIC_ACCOUNT_LAST_FOUR,
            account_type="INDIVIDUAL_CASH",
            canary_intent_id=self.intent.intent_id,
            canary_symbol=self.intent.symbol,
            expected_quantity=self.intent.quantity,
            observed_canary_quantity=(
                1.0 if phase == CANARY_ACTIVE and status == "PASS" else None
            ),
            observed_position_count=(
                1 if phase == CANARY_ACTIVE and status == "PASS" else 0
            ),
            findings=findings,
        )


if __name__ == "__main__":
    unittest.main()
