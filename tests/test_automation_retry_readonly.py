"""Retry observer tests: no service/provider access and no production writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import automation_retry_readonly as ro
from tests import test_automation_state_recovery as fixtures


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.config = {"expectedLoadedBytes": {"loaded_supervisor_sha256": "a" * 64}}
        self.owner = {"binding": {"wrapperProcessId": 123, "epochId": "epoch"},
            "supervisorCreatedAt": "2026-09-09T23:00:00+00:00", "previousServiceInstanceId": "old"}
        self.value = {"service_instance_id": "fresh", "service_started_at": "2026-09-09T23:00:01+00:00",
            "last_heartbeat_at": "2026-09-09T23:00:02+00:00", "state_version": 2,
            "loaded_supervisor_sha256": "a" * 64}

    def test_first_binding_is_explicit_and_does_not_mutate_inputs(self):
        before = deepcopy(self.owner)
        bound = ro.runtime_binding(self.config, self.owner, self.value)
        self.assertEqual("fresh", bound["serviceInstanceId"])
        self.assertEqual(2, bound["minimumStateVersion"])
        self.assertEqual(before, self.owner)

    def test_existing_binding_cannot_be_rebased_to_other_instance(self):
        self.owner["binding"] = ro.runtime_binding(self.config, self.owner, self.value)
        for field, value in (("service_instance_id", "other"),
                             ("service_started_at", "2026-09-09T23:00:01.1+00:00"), ("state_version", 1)):
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                ro.runtime_binding(self.config, self.owner, dict(self.value, **{field: value}))

    def test_advancing_state_preserves_original_floor(self):
        bound = ro.runtime_binding(self.config, self.owner, self.value)
        self.owner["binding"] = bound
        self.assertEqual(bound, ro.runtime_binding(self.config, self.owner, dict(self.value, state_version=9)))

    def test_old_instance_rejected_even_with_new_birth_timestamp(self):
        with self.assertRaisesRegex(RuntimeError, "OLD_SUPERVISOR_INSTANCE"):
            ro.runtime_binding(self.config, self.owner, dict(self.value, service_instance_id="old"))

    def test_loaded_bytes_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "LOADED_RUNTIME_DRIFT"):
            ro.runtime_binding(self.config, self.owner, dict(self.value, loaded_supervisor_sha256="b" * 64))

    def test_preexisting_or_no_heartbeat_state_cannot_grant_binding(self):
        for change in ({"service_started_at": "2026-09-09T22:00:00+00:00"}, {"last_heartbeat_at": ""}):
            with self.subTest(change=change):
                self.assertNotIn("serviceInstanceId", ro.runtime_binding(self.config, self.owner, dict(self.value, **change)))

    def test_native_ownership_missing_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "NATIVE_OWNERSHIP_REQUIRED"):
            ro.runtime_binding(self.config, None, self.value)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MH-Prechild-Input-")
        self.root = Path(self.temp.name)
        self.file = self.root / "host.dll"
        self.file.write_bytes(b"fixture-bytes-not-executable")
        self.config = {"staticFiles": {str(self.file): ro.digest(self.file)},
            "dynamicStateFiles": {"state": "bound"}, "staticDirectories": {str(self.root): ["host.dll"]}}

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_inputs_pass(self):
        ro.verify_input_files(self.config)

    def test_changed_bytes_rejected(self):
        self.file.write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "CURRENT_INPUT_DRIFT"):
            ro.verify_input_files(self.config)

    def test_new_uninventoried_file_rejected(self):
        (self.root / "injected.dll").write_bytes(b"extra")
        with self.assertRaisesRegex(RuntimeError, "DIRECTORY_MEMBERSHIP_DRIFT"):
            ro.verify_input_files(self.config)

    def test_missing_directory_inventory_rejected(self):
        self.config.pop("staticDirectories")
        with self.assertRaisesRegex(RuntimeError, "DIRECTORY_MEMBERSHIP_UNBOUND"):
            ro.verify_input_files(self.config)

    def test_missing_file_rejected(self):
        self.file.unlink()
        with self.assertRaises(FileNotFoundError):
            ro.verify_input_files(self.config)

    def test_duplicate_nonfinite_and_malformed_json_rejected(self):
        for raw in ('{"v":1,"v":2}', '{"v":NaN}', '{', 'null trailing'):
            with self.subTest(raw=raw):
                self.file.write_text(raw)
                with self.assertRaises((ValueError, RuntimeError)):
                    ro.load(self.file)

    def test_canonical_dirty_wrong_head_branch_or_tracking_rejected(self):
        config = {"canonicalRoot": self.root, "canonicalHead": "a" * 40}
        correct = ["a" * 40, "a" * 40, "master", ""]
        for index, bad in enumerate(("b" * 40, "b" * 40, "task", "?? extra")):
            with self.subTest(index=index), patch.object(ro, "git", side_effect=correct[:index] + [bad]), \
                 self.assertRaisesRegex(RuntimeError, "CANONICAL_IDENTITY_DRIFT"):
                ro.canonical(config)


class CurrentStateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.value = self.fixture.state("PENDING", job_id="opening-capture-20260910")
        self.epoch = ro.recovery.prospective_epoch(floor=datetime(2026, 9, 9, 13, 41, tzinfo=timezone.utc),
            first_session="2026-09-10", manifest_sha256="a" * 64, corrupt_sha256="b" * 64)
        self.value.prospective_epoch = self.epoch
        self.value.recovery_floor_at = self.epoch["boundaryAt"]
        self.config = {"statePath": str(self.fixture.path), "epoch": self.epoch}
        self.fixture.store().save(self.value)

    def test_current_state_is_nonmutating(self):
        before = {p: p.read_bytes() for p in self.fixture.root.rglob("*") if p.is_file()}
        result = ro.state(self.config)
        self.assertEqual("CURRENT", result["recovery"]["recovery_source"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.fixture.root.rglob("*") if p.is_file()})

    def test_corrupt_current_does_not_silently_recover(self):
        self.fixture.path.write_bytes(b"{")
        before = self.fixture.path.read_bytes()
        with self.assertRaises((ValueError, RuntimeError)):
            ro.state(self.config)
        self.assertEqual(before, self.fixture.path.read_bytes())

    def test_unexpected_execution_or_historical_receipt_rejected(self):
        receipt = self.value.jobs["opening-capture-20260910"]
        receipt.status = "RUNNING"
        receipt.started_at = fixtures.NOW.isoformat()
        self.fixture.store().save(self.value)
        with self.assertRaises((ValueError, RuntimeError)):
            ro.state(self.config)

    def test_pending_with_started_timestamp_is_not_pristine(self):
        self.value.jobs["opening-capture-20260910"].started_at = fixtures.NOW.isoformat()
        self.fixture.store().save(self.value)
        with self.assertRaises((ValueError, RuntimeError)):
            ro.state(self.config)

    def test_epoch_change_is_not_repaired(self):
        altered = deepcopy(self.config)
        altered["epoch"]["epochId"] = "other"
        with self.assertRaisesRegex(RuntimeError, "EPOCH_DRIFT"):
            ro.state(altered)


if __name__ == "__main__":
    unittest.main()
