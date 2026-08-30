from __future__ import annotations

import ast
import base64
import dataclasses
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import momentum_hunter.current_edge_research_ledger as ledger


EXPECTED_TRUTHS = {
    "PREDICT_FIRST_FREEZE_REVEAL_LATER": True,
    "PREDICTION_MUTATED_AFTER_FREEZE": False,
    "PREDICTION_MUTATED_AFTER_REVEAL": False,
    "CONFLICTING_DUPLICATE_ACCEPTED": False,
    "FUTURE_EVIDENCE_ACCEPTED_AT_FREEZE": False,
    "INVALID_CHRONOLOGY_ACCEPTED": False,
    "TAMPERING_UNDETECTED": False,
    "ROOT_ESCAPE_POSSIBLE": False,
    "PRODUCTION_WRITE_PATH": "NONE",
    "PRODUCTION_DECISION_AUTHORITY": "NONE",
    "EXECUTION_AUTHORITY": "NONE",
    "NEW_DATABASE_REQUIRED": False,
    "NEW_SERVICE_REQUIRED": False,
    "ROLLBACK_REQUIRES_PRODUCTION_REPAIR": False,
}


def _plain(value):
    return ledger._plain(value)


def _prediction_kwargs(packet=None):
    value = _plain(packet or ledger._test1_prediction())
    for field in (
        "packet_schema_version",
        "packet_type",
        "research_only",
        "production_decision_authority",
        "execution_authority",
        "canonical_fingerprint",
        "immutable_receipt_id",
    ):
        value.pop(field)
    return value


def _reveal_kwargs(packet=None):
    value = _plain(packet or ledger._test1_reveal(ledger._test1_prediction()))
    for field in (
        "reveal_schema_version",
        "packet_type",
        "research_only",
        "production_decision_authority",
        "execution_authority",
        "canonical_fingerprint",
        "immutable_receipt_id",
    ):
        value.pop(field)
    return value


def _snapshot(root: Path):
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _tree_snapshot(root: Path):
    if not root.exists():
        return ()
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        entries.append(("D", relative) if path.is_dir() else ("F", relative, path.read_bytes()))
    return tuple(entries)


class CurrentEdgeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="argus-ledger-test-")
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def assertRejectedWithoutMutation(self, category, operation, root=None):
        observed_root = root or self.root
        before = _snapshot(observed_root)
        with self.assertRaises(ledger.LedgerError) as caught:
            operation()
        self.assertEqual(caught.exception.category, category)
        self.assertEqual(_snapshot(observed_root), before)

    def _valid_store(self, name="valid"):
        root = self.root / name
        store = ledger.CurrentEdgeResearchLedger(root)
        prediction = ledger._test1_prediction()
        stored = store.freeze_prediction(prediction)
        return root, store, prediction, stored

    def _valid_lifecycle(self, name="valid-lifecycle"):
        root, store, prediction, stored_prediction = self._valid_store(name)
        reveal = ledger._test1_reveal(prediction)
        stored_reveal = store.reveal_outcome(reveal)
        return root, store, prediction, stored_prediction, reveal, stored_reveal

    def test_observe_freeze_restart_wait_reveal_compare(self):
        root, store, prediction, stored_prediction = self._valid_store()
        prediction_bytes = stored_prediction.packet_path.read_bytes()
        prediction_receipt = stored_prediction.receipt_path.read_bytes()
        restarted = ledger.CurrentEdgeResearchLedger(root)
        reloaded = restarted.read_prediction(ledger.prediction_logical_key_digest(prediction))
        self.assertEqual(reloaded.packet_path.read_bytes(), prediction_bytes)
        self.assertEqual(reloaded.receipt_path.read_bytes(), prediction_receipt)

        reveal = ledger._test1_reveal(prediction)
        stored_reveal = restarted.reveal_outcome(reveal)
        compared = restarted.read_prediction(ledger.prediction_logical_key_digest(prediction))
        self.assertEqual(compared.packet_path.read_bytes(), prediction_bytes)
        self.assertEqual(compared.receipt_path.read_bytes(), prediction_receipt)
        self.assertEqual(compared.packet.canonical_fingerprint, prediction.canonical_fingerprint)
        self.assertEqual(
            stored_reveal.packet.original_prediction_fingerprint,
            prediction.canonical_fingerprint,
        )
        self.assertNotIn(b"TEST1-EVIDENCE-D", prediction_bytes)
        self.assertIn(b"TEST1-EVIDENCE-D", stored_reveal.packet_path.read_bytes())

    def test_first_writes_and_identical_duplicates_are_byte_idempotent(self):
        root, store, prediction, stored_prediction = self._valid_store()
        before = _snapshot(root)
        duplicate_prediction = store.freeze_prediction(ledger._test1_prediction())
        self.assertFalse(duplicate_prediction.created)
        self.assertTrue(duplicate_prediction.idempotent)
        self.assertEqual(_snapshot(root), before)

        reveal = ledger._test1_reveal(prediction)
        stored_reveal = store.reveal_outcome(reveal)
        self.assertTrue(stored_reveal.created)
        before_duplicate = _snapshot(root)
        duplicate_reveal = store.reveal_outcome(ledger._test1_reveal(prediction))
        self.assertFalse(duplicate_reveal.created)
        self.assertTrue(duplicate_reveal.idempotent)
        self.assertEqual(_snapshot(root), before_duplicate)
        self.assertEqual(stored_prediction.packet_path.read_bytes(), before[stored_prediction.packet_path.relative_to(root).as_posix()])

    def test_fixed_layout_uses_only_domain_digest_paths(self):
        root, store, prediction, stored_prediction, reveal, stored_reveal = self._valid_lifecycle()
        prediction_digest = ledger.prediction_logical_key_digest(prediction)
        reveal_digest = ledger.reveal_logical_key_digest(reveal)
        self.assertEqual(
            stored_prediction.packet_path.relative_to(store.root).as_posix(),
            f"predictions/{prediction_digest[:2]}/{prediction_digest}.json",
        )
        self.assertEqual(
            stored_prediction.receipt_path.relative_to(store.root).as_posix(),
            f"prediction-receipts/{prediction_digest[:2]}/{prediction_digest}.json",
        )
        self.assertEqual(
            stored_reveal.packet_path.relative_to(store.root).as_posix(),
            f"reveals/{reveal_digest[:2]}/{reveal_digest}.json",
        )
        self.assertNotIn("TEST1", stored_prediction.packet_path.as_posix())

    def test_receipt_binds_stored_bytes_and_separate_packet(self):
        _, _, prediction, stored = self._valid_store()
        self.assertNotEqual(stored.packet_path, stored.receipt_path)
        self.assertEqual(
            stored.receipt.stored_bytes_sha256,
            ledger._stored_bytes_sha256(stored.packet_path.read_bytes()),
        )
        self.assertEqual(
            stored.receipt.stored_bytes_fingerprint,
            ledger._stored_bytes_fingerprint(
                stored.packet.packet_type, stored.packet_path.read_bytes()
            ),
        )
        self.assertEqual(stored.receipt.immutable_receipt_id, prediction.immutable_receipt_id)
        self.assertEqual(stored.receipt.terminal_write_result, "CREATED_IMMUTABLE")

    def test_packet_and_nested_authority_markers_are_in_memory_immutable(self):
        packet = ledger._test1_prediction()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            packet.execution_authority = "ANY"
        with self.assertRaises(TypeError):
            packet.strategy_identity["owner_identity"] = "MUTATED"
        with self.assertRaises(TypeError):
            packet.feature_observations[0]["value"] = "MUTATED"
        self.assertIs(packet.research_only, True)
        self.assertEqual(packet.production_decision_authority, "NONE")
        self.assertEqual(packet.execution_authority, "NONE")

    def test_all_seven_missingness_states_are_preserved(self):
        packet = ledger._test1_prediction()
        self.assertEqual(
            {entry["state"] for entry in packet.missingness_ledger},
            ledger.MISSINGNESS_STATES,
        )
        parsed = ledger.parse_prediction_json(ledger.packet_bytes(packet))
        self.assertEqual(_plain(parsed), _plain(packet))

    def test_missingness_does_not_accept_null_or_fabricated_value(self):
        kwargs = _prediction_kwargs()
        kwargs["missingness_ledger"][1]["value"] = 0
        self.assertRejectedWithoutMutation(
            "UNKNOWN_FIELD", lambda: ledger.build_frozen_prediction_packet(**kwargs)
        )
        kwargs = _prediction_kwargs()
        kwargs["feature_observations"][0]["value"] = None
        self.assertRejectedWithoutMutation(
            "INVALID_VALUE", lambda: ledger.build_frozen_prediction_packet(**kwargs)
        )

    def test_strict_duplicate_key_and_unknown_field_json(self):
        data = ledger.packet_bytes(ledger._test1_prediction())
        duplicate = b'{"packet_type":"FROZEN_PREDICTION_PACKET",' + data[1:]
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.parse_prediction_json(duplicate)
        self.assertEqual(caught.exception.category, "JSON_DUPLICATE_KEY")

        value = json.loads(data)
        value["unexpected"] = True
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.parse_prediction_json(json.dumps(value).encode("utf-8"))
        self.assertEqual(caught.exception.category, "UNKNOWN_FIELD")

        kwargs = _prediction_kwargs()
        kwargs["source_evidence_refs"][0]["unexpected"] = "blocked"
        self.assertRejectedWithoutMutation(
            "UNKNOWN_FIELD", lambda: ledger.build_frozen_prediction_packet(**kwargs)
        )

    def test_utc_z_is_exact_and_created_at_has_no_market_authority(self):
        for timestamp in (
            "2026-08-29T14:00:00",
            "2026-08-29T09:00:00-05:00",
            "2026-08-29 14:00:00Z",
            "2026-08-29T14:00:00.1Z",
        ):
            kwargs = _prediction_kwargs()
            kwargs["prediction_cutoff_at"] = timestamp
            self.assertRejectedWithoutMutation(
                "INVALID_TIMESTAMP", lambda kwargs=kwargs: ledger.build_frozen_prediction_packet(**kwargs)
            )
        kwargs = _prediction_kwargs()
        kwargs["created_at"] = "2020-01-01T00:00:00Z"
        packet = ledger.build_frozen_prediction_packet(**kwargs)
        self.assertEqual(packet.created_at, "2020-01-01T00:00:00Z")

    def test_nonfinite_numbers_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            kwargs = _prediction_kwargs()
            kwargs["feature_observations"][0]["value"] = value
            self.assertRejectedWithoutMutation(
                "NONFINITE_NUMBER", lambda kwargs=kwargs: ledger.build_frozen_prediction_packet(**kwargs)
            )

    def test_file_times_are_not_chronology_authority(self):
        root, _, prediction, stored = self._valid_store()
        os.utime(stored.packet_path, (1, 1))
        os.utime(stored.receipt_path, (2_000_000_000, 2_000_000_000))
        restarted = ledger.CurrentEdgeResearchLedger(root)
        loaded = restarted.read_prediction(ledger.prediction_logical_key_digest(prediction))
        self.assertEqual(loaded.packet.canonical_fingerprint, prediction.canonical_fingerprint)

    def test_serialization_and_identity_are_stable_across_clean_subprocesses(self):
        script = (
            "import base64,json; import momentum_hunter.current_edge_research_ledger as m; "
            "p=m._test1_prediction(); print(json.dumps({'bytes':base64.b64encode(m.packet_bytes(p)).decode(),"
            "'key':m.prediction_logical_key_digest(p),'fingerprint':p.canonical_fingerprint,"
            "'receipt':p.immutable_receipt_id},sort_keys=True))"
        )
        outputs = []
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )
            outputs.append(result.stdout.strip())
        self.assertEqual(outputs[0], outputs[1])
        parsed = json.loads(outputs[0])
        self.assertEqual(base64.b64decode(parsed["bytes"]), ledger.packet_bytes(ledger._test1_prediction()))

    def test_h01_future_evidence_inside_prediction(self):
        kwargs = _prediction_kwargs()
        kwargs["source_evidence_refs"][0]["available_at"] = "2026-08-29T14:00:01Z"
        self.assertRejectedWithoutMutation(
            "FUTURE_EVIDENCE", lambda: ledger.build_frozen_prediction_packet(**kwargs)
        )

    def test_h02_outcome_timestamp_before_prediction_cutoff(self):
        root, store, prediction, _ = self._valid_store()
        kwargs = _reveal_kwargs()
        kwargs["outcome_resolved_at"] = "2026-08-29T13:59:59Z"
        reveal = ledger.build_outcome_reveal_packet(**kwargs)
        self.assertRejectedWithoutMutation(
            "INVALID_CHRONOLOGY", lambda: store.reveal_outcome(reveal), root
        )

    def test_h03_reveal_attached_to_wrong_prediction(self):
        root, store, _, _ = self._valid_store()
        kwargs = _reveal_kwargs()
        kwargs["original_prediction_fingerprint"] = "f" * 64
        kwargs["original_prediction_receipt_id"] = "e" * 64
        reveal = ledger.build_outcome_reveal_packet(**kwargs)
        self.assertRejectedWithoutMutation(
            "PREDICTION_REFERENCE_MISMATCH", lambda: store.reveal_outcome(reveal), root
        )

    def test_h04_conflicting_duplicate_prediction(self):
        root, store, _, _ = self._valid_store()
        conflicting = ledger._test1_prediction(reason="different immutable content")
        self.assertRejectedWithoutMutation(
            "IMMUTABLE_CONFLICT", lambda: store.freeze_prediction(conflicting), root
        )

    def test_h05_conflicting_duplicate_reveal(self):
        root, store, prediction, _, _, _ = self._valid_lifecycle()
        conflicting = ledger._test1_reveal(prediction, outcome_value=-2.0)
        self.assertRejectedWithoutMutation(
            "IMMUTABLE_CONFLICT", lambda: store.reveal_outcome(conflicting), root
        )

    def test_h06_missing_required_strategy_code_or_configuration_identity(self):
        for identity_field in ("strategy_identity", "code_identity", "configuration_identity"):
            kwargs = _prediction_kwargs()
            kwargs[identity_field] = {}
            self.assertRejectedWithoutMutation(
                "INCOMPLETE_IDENTITY",
                lambda kwargs=kwargs: ledger.build_frozen_prediction_packet(**kwargs),
            )

    def test_h07_prediction_packet_manually_edited(self):
        root, _, _, stored = self._valid_store()
        original_receipt = stored.receipt_path.read_bytes()
        stored.packet_path.write_bytes(stored.packet_path.read_bytes().replace(b"WATCH", b"ABSTAINED"))
        attacked = _snapshot(root)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(root)
        self.assertEqual(caught.exception.category, "FINGERPRINT_MISMATCH")
        self.assertEqual(_snapshot(root), attacked)
        self.assertEqual(stored.receipt_path.read_bytes(), original_receipt)

    def test_h08_receipt_manually_edited(self):
        root, _, _, stored = self._valid_store()
        packet_before = stored.packet_path.read_bytes()
        receipt = json.loads(stored.receipt_path.read_bytes())
        receipt["stored_bytes_sha256"] = "0" * 64
        stored.receipt_path.write_bytes(ledger._canonical_json(receipt, newline=True))
        attacked = _snapshot(root)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(root)
        self.assertEqual(caught.exception.category, "RECEIPT_MISMATCH")
        self.assertEqual(_snapshot(root), attacked)
        self.assertEqual(stored.packet_path.read_bytes(), packet_before)

    def test_h09_truncated_packet(self):
        root, _, _, stored = self._valid_store()
        receipt_before = stored.receipt_path.read_bytes()
        stored.packet_path.write_bytes(stored.packet_path.read_bytes()[:40])
        attacked = _snapshot(root)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(root)
        self.assertEqual(caught.exception.category, "MALFORMED_JSON")
        self.assertEqual(_snapshot(root), attacked)
        self.assertEqual(stored.receipt_path.read_bytes(), receipt_before)

    def test_h10_partial_interrupted_artifact(self):
        root, _, _, stored = self._valid_store()
        partial = stored.packet_path.parent / ".interrupted.tmp"
        partial.write_bytes(b"partial")
        attacked = _snapshot(root)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(root)
        self.assertEqual(caught.exception.category, "PARTIAL_ARTIFACT")
        self.assertEqual(_snapshot(root), attacked)

    def test_h11_invalid_hash(self):
        root, _, _, stored = self._valid_store()
        value = json.loads(stored.packet_path.read_bytes())
        value["canonical_fingerprint"] = "0" * 64
        stored.packet_path.write_bytes(ledger._canonical_json(value, newline=True))
        attacked = _snapshot(root)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(root)
        self.assertEqual(caught.exception.category, "FINGERPRINT_MISMATCH")
        self.assertEqual(_snapshot(root), attacked)

    def test_h12_malformed_timestamp(self):
        kwargs = _prediction_kwargs()
        kwargs["prediction_cutoff_at"] = "not-a-timestamp"
        self.assertRejectedWithoutMutation(
            "INVALID_TIMESTAMP", lambda: ledger.build_frozen_prediction_packet(**kwargs)
        )

    def test_h13_same_logical_identity_different_claimed_content_identity(self):
        root, store, _, stored = self._valid_store()
        conflicting = ledger._test1_prediction(reason="attacker-selected-content")
        self.assertNotEqual(conflicting.canonical_fingerprint, stored.packet.canonical_fingerprint)
        self.assertNotEqual(conflicting.immutable_receipt_id, stored.packet.immutable_receipt_id)
        self.assertRejectedWithoutMutation(
            "IMMUTABLE_CONFLICT", lambda: store.freeze_prediction(conflicting), root
        )

    def test_h14_path_traversal_identity(self):
        root, _, _, _ = self._valid_store()
        kwargs = _prediction_kwargs()
        kwargs["research_opportunity_id"]["owner_identity"] = "../outside"
        self.assertRejectedWithoutMutation(
            "ROOT_PATH_INVALID", lambda: ledger.build_frozen_prediction_packet(**kwargs), root
        )

    def test_h15_storage_root_escape_and_reparse_point(self):
        case_root = self.root / "h15"
        caller = case_root / "caller"
        outside = case_root / "outside"
        caller.mkdir(parents=True)
        outside.mkdir()
        sentinel = outside / "sentinel.bin"
        sentinel.write_bytes(b"outside-unchanged")
        link = caller / ledger.LEDGER_DIRECTORY
        if os.name == "nt":
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
        else:
            os.symlink(outside, link, target_is_directory=True)
        outside_before = _snapshot(outside)
        try:
            with self.assertRaises(ledger.LedgerError) as caught:
                ledger.CurrentEdgeResearchLedger(caller)
            self.assertEqual(caught.exception.category, "ROOT_REPARSE_POINT")
            self.assertEqual(_snapshot(outside), outside_before)
        finally:
            if os.name == "nt":
                os.rmdir(link)
            else:
                link.unlink()

    def test_absolute_root_with_traversal_is_rejected_before_write(self):
        attempted = self.root / "inside" / ".." / "outside"
        outside = self.root / "outside"
        self.assertFalse(outside.exists())
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(attempted)
        self.assertEqual(caught.exception.category, "ROOT_PATH_INVALID")
        self.assertFalse(outside.exists())

    def test_preexisting_empty_ledger_directory_is_not_initialized_or_repaired(self):
        caller = self.root / "precreated-empty"
        ledger_root = caller / ledger.LEDGER_DIRECTORY
        ledger_root.mkdir(parents=True)
        before = _tree_snapshot(caller)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(caller)
        self.assertEqual(caught.exception.category, "ROOT_LAYOUT_INVALID")
        self.assertEqual(_tree_snapshot(caller), before)
        self.assertEqual(tuple(ledger_root.iterdir()), ())

    def test_reopen_rejects_missing_empty_collection_without_repair(self):
        caller, store, _, _ = self._valid_store("missing-empty-collection")
        missing_collection = store.root / "reveal-receipts"
        missing_collection.rmdir()
        before = _tree_snapshot(caller)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(caller)
        self.assertEqual(caught.exception.category, "ROOT_LAYOUT_INVALID")
        self.assertEqual(_tree_snapshot(caller), before)
        self.assertFalse(missing_collection.exists())

    def test_packet_and_receipt_hardlink_aliases_fail_closed_without_mutation(self):
        hardlink_supported = False
        for artifact_kind in ("packet", "receipt"):
            with self.subTest(artifact_kind=artifact_kind):
                caller, _, _, stored = self._valid_store(f"hardlink-{artifact_kind}")
                target = stored.packet_path if artifact_kind == "packet" else stored.receipt_path
                outside = self.root / f"outside-{artifact_kind}.json"
                try:
                    os.link(target, outside)
                except (NotImplementedError, OSError) as exc:
                    if not hardlink_supported:
                        self.skipTest(f"filesystem hard links unavailable: {exc}")
                    self.fail(f"hardlink capability changed during test: {exc}")
                hardlink_supported = True
                inside_before = target.read_bytes()
                outside_before = outside.read_bytes()
                self.assertGreaterEqual(target.stat().st_nlink, 2)
                with self.assertRaises(ledger.LedgerError) as caught:
                    ledger.CurrentEdgeResearchLedger(caller)
                self.assertEqual(caught.exception.category, "ARTIFACT_LINK_COUNT_INVALID")
                self.assertEqual(target.read_bytes(), inside_before)
                self.assertEqual(outside.read_bytes(), outside_before)
                outside.unlink()
                self.assertEqual(target.stat().st_nlink, 1)

    def test_h16_restart_with_corrupted_existing_artifact_blocks_continuation(self):
        root, _, _, stored = self._valid_store()
        unexpected = stored.packet_path.parent / "unexpected.json"
        unexpected.write_bytes(b"{}\n")
        attacked = _snapshot(root)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(root)
        self.assertEqual(caught.exception.category, "ROOT_LAYOUT_INVALID")
        self.assertEqual(_snapshot(root), attacked)

    def test_h17_attempted_prediction_mutation_after_reveal(self):
        root, store, prediction, stored_prediction, _, stored_reveal = self._valid_lifecycle()
        before = _snapshot(root)
        conflicting = ledger._test1_prediction(reason="mutation-after-reveal")
        self.assertRejectedWithoutMutation(
            "IMMUTABLE_CONFLICT", lambda: store.freeze_prediction(conflicting), root
        )
        self.assertEqual(stored_prediction.packet_path.read_bytes(), before[stored_prediction.packet_path.relative_to(root).as_posix()])
        self.assertEqual(stored_reveal.packet_path.read_bytes(), before[stored_reveal.packet_path.relative_to(root).as_posix()])
        for method in ("update", "delete", "mutate"):
            self.assertFalse(hasattr(store, method))

    def test_h18_unexpected_outcome_information_during_freeze(self):
        prohibited_values = (
            "OUTCOME_OBSERVED",
            {"ReAlIzEd-Outcome.Value": 1.25},
            ("apparently harmless", "FuTuRe-EvIdEnCe D was known after cutoff"),
            "the realized outcome return was positive",
            "the result was positive",
            "post-event return was positive",
        )
        for prohibited in prohibited_values:
            with self.subTest(prohibited=prohibited):
                kwargs = _prediction_kwargs()
                kwargs["feature_observations"][0]["value"] = prohibited
                self.assertRejectedWithoutMutation(
                    "PROHIBITED_PREDICTION_CONTENT",
                    lambda kwargs=kwargs: ledger.build_frozen_prediction_packet(**kwargs),
                )
        kwargs = _prediction_kwargs()
        kwargs["feature_observations"][0]["observation_id"] = "FINAL-PNL"
        kwargs["feature_observations"][0]["value"] = 1.25
        self.assertRejectedWithoutMutation(
            "PROHIBITED_PREDICTION_CONTENT",
            lambda: ledger.build_frozen_prediction_packet(**kwargs),
        )

    def test_legitimate_prediction_language_is_not_mistaken_for_revealed_information(self):
        kwargs = _prediction_kwargs()
        kwargs["feature_observations"][0]["value"] = "trailing realized volatility"
        kwargs["research_predictions"] = (
            {
                "prediction_id": "TEST1-FUTURE-RETURN",
                "prediction_object": "future return distribution",
                "value": 0.6,
                "horizon": "next synthetic session",
                "units": "probability",
                "rule_identity": ledger._synthetic_identity(
                    "RESEARCH_RULE", "TEST1-RULE-V1", "TEST1-FIXTURE-V1"
                ),
                "evidence_coverage": ("TEST1-EVIDENCE-A",),
            },
        )
        packet = ledger.build_frozen_prediction_packet(**kwargs)
        self.assertEqual(packet.research_predictions[0]["prediction_object"], "future return distribution")
        self.assertEqual(packet.feature_observations[0]["value"], "trailing realized volatility")

        legitimate_values = (
            "settlement probability estimate",
            "provisional answer probability",
            "profit probability forecast",
            "loss severity forecast",
        )
        for legitimate in legitimate_values:
            with self.subTest(legitimate=legitimate):
                control_kwargs = _prediction_kwargs()
                control_kwargs["feature_observations"][0]["value"] = legitimate
                control_packet = ledger.build_frozen_prediction_packet(**control_kwargs)
                self.assertEqual(control_packet.feature_observations[0]["value"], legitimate)

    def test_prediction_rejects_settled_verdict_and_known_result_language(self):
        prohibited_values = (
            "the settled answer was green",
            "the AnSwEr.WaS green",
            "FiNaL-Answer: green",
            "the verdict was returned",
            "position WON",
            "trade lost",
            "PnL was +1.2R",
            "final profit",
            "actual loss",
        )
        for prohibited in prohibited_values:
            with self.subTest(prohibited=prohibited):
                kwargs = _prediction_kwargs()
                kwargs["feature_observations"][0]["value"] = prohibited
                self.assertRejectedWithoutMutation(
                    "PROHIBITED_PREDICTION_CONTENT",
                    lambda kwargs=kwargs: ledger.build_frozen_prediction_packet(**kwargs),
                )

        kwargs = _prediction_kwargs()
        kwargs["feature_observations"][0]["observation_id"] = "SETTLED-ANSWER"
        kwargs["feature_observations"][0]["value"] = 1
        self.assertRejectedWithoutMutation(
            "PROHIBITED_PREDICTION_CONTENT",
            lambda: ledger.build_frozen_prediction_packet(**kwargs),
        )

    def test_reconstructed_symbol_and_event_refs_must_exist_by_evidence_cutoff(self):
        cases = (
            (
                "symbol_entity_ref",
                {"symbol": "TEST1", "entity_identity": "TEST1-ENTITY"},
            ),
            (
                "event_ref",
                {"event_identity": "TEST1-EVENT", "event_type": "SYNTHETIC_EVENT"},
            ),
        )
        for field, value in cases:
            with self.subTest(field=field):
                kwargs = _prediction_kwargs()
                kwargs[field] = {
                    "state": "RECONSTRUCTED",
                    "value": value,
                    "reconstruction_method": "synthetic point-in-time reconstruction",
                    "source_inputs": ("TEST1-EVIDENCE-A",),
                    "reconstructed_at": "2026-08-29T14:00:01Z",
                    "non_recorded": True,
                }
                self.assertRejectedWithoutMutation(
                    "FUTURE_EVIDENCE",
                    lambda kwargs=kwargs: ledger.build_frozen_prediction_packet(**kwargs),
                )

    def test_reconstructed_symbol_and_event_refs_at_cutoff_are_admissible(self):
        kwargs = _prediction_kwargs()
        kwargs["symbol_entity_ref"] = {
            "state": "RECONSTRUCTED",
            "value": {"symbol": "TEST1", "entity_identity": "TEST1-ENTITY"},
            "reconstruction_method": "synthetic point-in-time reconstruction",
            "source_inputs": ("TEST1-EVIDENCE-A",),
            "reconstructed_at": "2026-08-29T14:00:00Z",
            "non_recorded": True,
        }
        kwargs["event_ref"] = {
            "state": "RECONSTRUCTED",
            "value": {"event_identity": "TEST1-EVENT", "event_type": "SYNTHETIC_EVENT"},
            "reconstruction_method": "synthetic point-in-time reconstruction",
            "source_inputs": ("TEST1-EVIDENCE-B",),
            "reconstructed_at": "2026-08-29T14:00:00Z",
            "non_recorded": True,
        }
        packet = ledger.build_frozen_prediction_packet(**kwargs)
        self.assertEqual(packet.symbol_entity_ref["state"], "RECONSTRUCTED")
        self.assertEqual(packet.event_ref["state"], "RECONSTRUCTED")

    def test_all_reconstructed_prediction_records_require_bound_canonical_unique_lineage(self):
        evidence_a = "TEST1-EVIDENCE-A"
        evidence_b = "TEST1-EVIDENCE-B"
        mutations = (
            ((evidence_a, evidence_a), "duplicate"),
            ((evidence_b, evidence_a), "noncanonical"),
            ((evidence_a, "TEST1-EVIDENCE-Z"), "unbound"),
        )
        for target in ("symbol_entity_ref", "event_ref", "feature_observations", "missingness_ledger"):
            for source_inputs, case in mutations:
                with self.subTest(target=target, case=case):
                    kwargs = _prediction_kwargs()
                    if target == "symbol_entity_ref":
                        kwargs[target] = {
                            "state": "RECONSTRUCTED",
                            "value": {"symbol": "TEST1", "entity_identity": "TEST1-ENTITY"},
                            "reconstruction_method": "synthetic reconstruction",
                            "source_inputs": source_inputs,
                            "reconstructed_at": "2026-08-29T14:00:00Z",
                            "non_recorded": True,
                        }
                    elif target == "event_ref":
                        kwargs[target] = {
                            "state": "RECONSTRUCTED",
                            "value": {
                                "event_identity": "TEST1-EVENT",
                                "event_type": "SYNTHETIC_EVENT",
                            },
                            "reconstruction_method": "synthetic reconstruction",
                            "source_inputs": source_inputs,
                            "reconstructed_at": "2026-08-29T14:00:00Z",
                            "non_recorded": True,
                        }
                    elif target == "feature_observations":
                        kwargs[target][0] = {
                            "observation_id": "TEST1-OBSERVATION",
                            "state": "RECONSTRUCTED",
                            "value": "WATCH",
                            "evidence_ids": (evidence_a,),
                            "reconstruction_method": "synthetic reconstruction",
                            "source_inputs": source_inputs,
                            "reconstructed_at": "2026-08-29T14:00:00Z",
                            "non_recorded": True,
                        }
                    else:
                        reconstructed = next(
                            entry
                            for entry in kwargs[target]
                            if entry["state"] == "RECONSTRUCTED"
                        )
                        reconstructed["source_inputs"] = source_inputs
                    self.assertRejectedWithoutMutation(
                        "INVALID_EVIDENCE",
                        lambda kwargs=kwargs: ledger.build_frozen_prediction_packet(**kwargs),
                    )

    def test_reveal_evidence_must_be_strictly_after_prediction_and_at_or_before_cutoff(self):
        root, store, _, _ = self._valid_store()
        for available_at, category in (
            ("2026-08-29T14:00:00Z", "INVALID_CHRONOLOGY"),
            ("2026-08-29T14:10:01Z", "INVALID_CHRONOLOGY"),
        ):
            kwargs = _reveal_kwargs()
            kwargs["outcome_evidence"][0]["available_at"] = available_at
            if available_at > kwargs["outcome_cutoff_at"]:
                self.assertRejectedWithoutMutation(
                    category, lambda kwargs=kwargs: ledger.build_outcome_reveal_packet(**kwargs), root
                )
            else:
                reveal = ledger.build_outcome_reveal_packet(**kwargs)
                self.assertRejectedWithoutMutation(
                    category, lambda reveal=reveal: store.reveal_outcome(reveal), root
                )

    def test_reveal_exact_protocol_opportunity_and_receipt_reference(self):
        root, store, _, _ = self._valid_store()
        mutations = (
            ("original_prediction_receipt_id", "0" * 64),
            ("research_protocol_id", ledger._synthetic_identity("RESEARCH_PROTOCOL", "OTHER-PROTOCOL", "TEST1-FIXTURE-V1")),
            ("research_opportunity_id", ledger._synthetic_identity("STAT_DATA_OPPORTUNITY", "OTHER-OPPORTUNITY", "TEST1-FIXTURE-V1")),
        )
        for field, value in mutations:
            kwargs = _reveal_kwargs()
            kwargs[field] = value
            reveal = ledger.build_outcome_reveal_packet(**kwargs)
            self.assertRejectedWithoutMutation(
                "PREDICTION_REFERENCE_MISMATCH",
                lambda reveal=reveal: store.reveal_outcome(reveal),
                root,
            )

    def test_multiple_outcome_horizons_have_distinct_immutable_keys(self):
        root, store, prediction, stored_prediction = self._valid_store()
        first = store.reveal_outcome(ledger._test1_reveal(prediction))
        second_packet = ledger._test1_reveal(
            prediction,
            outcome_cutoff_at="2026-08-29T14:20:00Z",
            outcome_resolved_at="2026-08-29T14:06:00Z",
        )
        second = store.reveal_outcome(second_packet)
        self.assertNotEqual(first.packet_path, second.packet_path)
        self.assertNotEqual(
            ledger.reveal_logical_key_digest(first.packet),
            ledger.reveal_logical_key_digest(second.packet),
        )
        self.assertEqual(
            stored_prediction.packet.canonical_fingerprint,
            prediction.canonical_fingerprint,
        )
        self.assertEqual(len(list((Path(root) / ledger.LEDGER_DIRECTORY / "reveals").rglob("*.json"))), 2)

    def test_source_provenance_locator_is_inert_and_never_a_storage_path(self):
        kwargs = _prediction_kwargs()
        kwargs["source_evidence_refs"][0]["provenance_locator"] = "../../outside/provider?id=A"
        packet = ledger.build_frozen_prediction_packet(**kwargs)
        store = ledger.CurrentEdgeResearchLedger(self.root / "inert-locator")
        stored = store.freeze_prediction(packet)
        self.assertIn(b"../../outside/provider?id=A", stored.packet_path.read_bytes())
        self.assertFalse((self.root / "outside").exists())

    def test_restart_rejects_orphan_receipt_or_packet(self):
        for name, remove_receipt in (("orphan-packet", True), ("orphan-receipt", False)):
            root, _, _, stored = self._valid_store(name)
            if remove_receipt:
                stored.receipt_path.unlink()
            else:
                stored.packet_path.unlink()
            attacked = _snapshot(root)
            with self.assertRaises(ledger.LedgerError) as caught:
                ledger.CurrentEdgeResearchLedger(root)
            self.assertEqual(caught.exception.category, "ORPHAN_ARTIFACT")
            self.assertEqual(_snapshot(root), attacked)

    def test_restart_rejects_noncanonical_json_bytes(self):
        root, _, _, stored = self._valid_store()
        value = json.loads(stored.packet_path.read_bytes())
        stored.packet_path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        attacked = _snapshot(root)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger(root)
        self.assertEqual(caught.exception.category, "NONCANONICAL_ARTIFACT")
        self.assertEqual(_snapshot(root), attacked)

    def test_no_default_or_relative_root(self):
        signature = inspect.signature(ledger.CurrentEdgeResearchLedger)
        self.assertIs(signature.parameters["root"].default, inspect.Parameter.empty)
        with self.assertRaises(ledger.LedgerError) as caught:
            ledger.CurrentEdgeResearchLedger("relative-ledger")
        self.assertEqual(caught.exception.category, "ROOT_NOT_ABSOLUTE")
        source = Path(ledger.__file__).read_text(encoding="utf-8")
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.getenv", source)
        self.assertNotIn("MomentumHunterData", source)

    def test_structural_no_authority_and_no_production_consumer(self):
        source_path = Path(ledger.__file__).resolve()
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        forbidden = {
            "requests",
            "websocket",
            "sqlite3",
            "threading",
            "asyncio",
            "PySide6",
            "momentum_hunter",
        }
        self.assertFalse(imports & forbidden)
        self.assertTrue(ledger._module_imports_are_stdlib_only())
        self.assertTrue(ledger._no_production_consumer_imports())
        self.assertIs(ledger.RESEARCH_ONLY, True)
        self.assertEqual(ledger.PRODUCTION_DECISION_AUTHORITY, "NONE")
        self.assertEqual(ledger.EXECUTION_AUTHORITY, "NONE")
        for name in (
            "update",
            "delete",
            "mutate",
            "execute",
            "submit_order",
            "transmit_order",
            "start_service",
            "install",
        ):
            self.assertFalse(hasattr(ledger.CurrentEdgeResearchLedger, name))
        consumers = []
        for path in source_path.parent.glob("*.py"):
            if path == source_path:
                continue
            if "current_edge_research_ledger" in path.read_text(encoding="utf-8"):
                consumers.append(path.name)
        self.assertEqual(consumers, [])

    def test_demonstration_returns_all_truths_only_after_proof(self):
        result = ledger.run_synthetic_demonstration(self.root / "demo")
        self.assertEqual(result["truths"], EXPECTED_TRUTHS)
        self.assertEqual(result["experiment"], "TEST1")
        self.assertEqual(
            result["lifecycle"],
            "OBSERVE->FREEZE->RESTART->WAIT->REVEAL->COMPARE",
        )
        for field in (
            "prediction_logical_key_digest",
            "prediction_fingerprint",
            "prediction_receipt_id",
            "prediction_stored_bytes_sha256",
            "prediction_stored_bytes_fingerprint",
            "prediction_receipt_stored_bytes_sha256",
            "reveal_logical_key_digest",
            "reveal_fingerprint",
            "reveal_receipt_id",
            "reveal_stored_bytes_sha256",
            "reveal_stored_bytes_fingerprint",
            "reveal_receipt_stored_bytes_sha256",
        ):
            self.assertRegex(result[field], r"^[0-9a-f]{64}$")
        self.assertEqual(
            result["clean_restart_process_proof"],
            {
                "bytes": result["prediction_stored_bytes_sha256"],
                "fingerprint": result["prediction_fingerprint"],
                "receipt": result["prediction_receipt_id"],
            },
        )


if __name__ == "__main__":
    unittest.main()
