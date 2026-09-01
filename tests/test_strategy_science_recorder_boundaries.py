from __future__ import annotations

import ast
import inspect
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path, PurePath

from momentum_hunter.strategy_science_recorder import (
    RecorderCustodyError,
    RecorderRecoveryError,
    StrategyScienceRecorder,
    owner_identity,
)
from momentum_hunter.windows_writer_storage import (
    WriterOwnershipConflictError,
    WriterPhysicalStorageError,
)
from tests.test_strategy_science_recorder_contract import (
    SESSION_ID,
    SOURCE_ROOT_IDENTITY,
    FixedClock,
    discovery_payload,
    export_envelope,
    health_payload,
    source_final_envelope,
    start_envelope,
)


class RecorderBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "science"

    def recorder(self, writer: str = "boundaries") -> StrategyScienceRecorder:
        return StrategyScienceRecorder(
            self.root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id=writer,
            clock=FixedClock(),
        )

    def test_constructor_requires_explicit_root_identity_writer_and_clock(self) -> None:
        signature = inspect.signature(StrategyScienceRecorder)
        self.assertIs(inspect.Parameter.empty, signature.parameters["science_root"].default)
        for name in ("source_root_identity", "writer_instance_id", "clock"):
            self.assertIs(inspect.Parameter.empty, signature.parameters[name].default)
        with self.assertRaises((RecorderCustodyError, ValueError)):
            StrategyScienceRecorder(
                self.root,
                source_root_identity="not-a-root-hash",
                writer_instance_id="bad",
                clock=FixedClock(),
            )

    def test_no_provider_runtime_account_order_service_or_scheduler_imports(self) -> None:
        package = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "strategy_science_recorder"
        )
        forbidden_modules = {
            "requests",
            "httpx",
            "socket",
            "alpaca",
            "schwab",
            "broker",
            "scheduler",
            "subprocess",
        }
        imports: set[str] = set()
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".", 1)[0])
        self.assertTrue(forbidden_modules.isdisjoint(imports), imports)
        custody_source = (package / "custody.py").read_text(encoding="utf-8")
        self.assertIn("momentum_hunter.windows_writer_storage", custody_source)
        self.assertNotIn("momentum_hunter.continuous_", custody_source)
        self.assertNotIn("momentum_hunter.app", custody_source)

    def test_start_is_required_and_single_writer_ownership_is_enforced(self) -> None:
        recorder = self.recorder("first")
        discovery = export_envelope(
            "DISCOVERY_CYCLE",
            discovery_payload(),
            stream_id="discovery-stream",
            event_id="discovery-1",
        )
        with self.assertRaises(RecorderCustodyError):
            recorder.accept(discovery)
        with self.assertRaises(WriterOwnershipConflictError):
            self.recorder("second")
        recorder.close()

    def test_source_final_is_required_and_closes_all_append_surfaces(self) -> None:
        recorder = self.recorder()
        start_raw = start_envelope()
        recorder.accept(start_raw)
        with self.assertRaises(RecorderCustodyError):
            recorder.finalize(SESSION_ID)
        final_raw = source_final_envelope(recorder, start_raw)
        recorder.accept(final_raw)
        later = export_envelope(
            "PROVIDER_HEALTH",
            health_payload(),
            stream_id="health-stream",
            event_id="health-late",
        )
        with self.assertRaises(RecorderCustodyError):
            recorder.accept(later)
        recorder.close()
        for path in self.root.rglob("*"):
            self.assertTrue(path.resolve().is_relative_to(self.root.resolve()))

    def test_recorder_rejects_traversal_absolute_foreign_and_wrong_partition_inputs(self) -> None:
        recorder = self.recorder("path-probes")
        try:
            with self.assertRaises(RecorderRecoveryError):
                recorder._files(PurePath("..", "foreign"), ".json")
            with self.assertRaises(RecorderRecoveryError):
                recorder._files(PurePath("C:\\foreign"), ".json")
            foreign = Path(self.temporary.name) / "foreign" / "evidence.json"
            foreign.parent.mkdir()
            foreign.write_text("{}", encoding="utf-8")
            with self.assertRaises(RecorderRecoveryError):
                recorder._relative(foreign)

            recorder.accept(start_envelope())
            foreign_session = owner_identity(
                "SESSION_ID", "fixture-owner", "foreign-session"
            )
            wrong_partition = export_envelope(
                "PROVIDER_HEALTH",
                health_payload(),
                stream_id="foreign-stream",
                event_id="foreign-event",
                session_id=foreign_session,
            )
            with self.assertRaises(RecorderCustodyError):
                recorder.accept(wrong_partition)
            self.assertEqual("SCIENCE_CUSTODY_OWNER_PROFILE_V1", recorder.owner_evidence["profile"])
            self.assertFalse(recorder.owner_evidence["continuous_runtime_owner"])
        finally:
            recorder.close()

    def test_hardlink_alias_is_rejected_by_recorder_verification(self) -> None:
        recorder = self.recorder("hardlink-source")
        recorder.accept(start_envelope())
        recorder.close()
        payload = next(self.root.rglob("*.payload.json"))
        alias = payload.with_name("foreign-alias.payload.json")
        os.link(payload, alias)
        reopened = self.recorder("hardlink-verify")
        try:
            with self.assertRaises(RecorderRecoveryError):
                reopened.verify(SESSION_ID)
        finally:
            reopened.close()

    def test_reparse_alias_is_rejected_when_platform_can_create_probe(self) -> None:
        recorder = self.recorder("reparse-source")
        recorder.accept(start_envelope())
        recorder.close()
        payload = next(self.root.rglob("*.payload.json"))
        alias = payload.with_name("foreign-reparse.payload.json")
        try:
            os.symlink(payload, alias)
        except OSError:
            reopened = self.recorder("reparse-error-propagation")
            try:
                with mock.patch.object(
                    reopened._storage,
                    "iter_files",
                    side_effect=WriterPhysicalStorageError("synthetic reparse entry"),
                ), self.assertRaises(RecorderRecoveryError):
                    reopened._files(PurePath("sessions"), ".payload.json")
            finally:
                reopened.close()
            return
        reopened = self.recorder("reparse-verify")
        try:
            with self.assertRaises(RecorderRecoveryError):
                reopened.verify(SESSION_ID)
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
