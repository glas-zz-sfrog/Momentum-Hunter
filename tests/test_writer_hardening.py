from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path, PurePath
from unittest.mock import patch
from momentum_hunter import windows_writer_storage as storage_module

from momentum_hunter.windows_writer_storage import (
    OWNER_LEASE_NAME,
    PHYSICAL_STORAGE_PROFILE,
    WriterOwnershipConflictError,
    WriterPhysicalStorage,
    WriterPhysicalStorageError,
)


TOPOLOGY = "a" * 64


@unittest.skipUnless(os.name == "nt", "Windows writer hardening")
class WriterHardeningTests(unittest.TestCase):
    def storage(self, root: Path, instance: str) -> WriterPhysicalStorage:
        return WriterPhysicalStorage(
            root,
            writer_instance_id=instance,
            topology_fingerprint=TOPOLOGY,
            topology_version=2,
        )

    def test_owner_is_root_scoped_fail_fast_and_observable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root_x = Path(temporary) / "root-x"
            root_y = Path(temporary) / "root-y"
            first = self.storage(root_x, "writer-a")
            independent = self.storage(root_y, "writer-y")
            try:
                started = time.perf_counter()
                with self.assertRaises(WriterOwnershipConflictError):
                    self.storage(root_x, "writer-b")
                self.assertLess(time.perf_counter() - started, 1.0)
                owner = first.owner_evidence
                self.assertEqual("writer-a", owner.writer_instance_id)
                self.assertEqual(os.getpid(), owner.process_id)
                self.assertEqual(2, owner.topology_version)
                self.assertEqual(TOPOLOGY, owner.topology_fingerprint)
                self.assertEqual(PHYSICAL_STORAGE_PROFILE, owner.storage_profile)
                self.assertRegex(owner.root_identity, r"^[a-f0-9]{64}$")
                self.assertRegex(owner.lease_identity, r"^[a-f0-9]{64}$")
                self.assertNotEqual(owner.root_identity, independent.owner_evidence.root_identity)
            finally:
                independent.close()
                first.close()

    def test_close_and_stale_owner_file_do_not_block_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "evidence"
            first = self.storage(root, "writer-a")
            first_identity = first.owner_evidence.lease_identity
            first.close()

            stale_path = root / OWNER_LEASE_NAME
            stale = json.loads(stale_path.read_text(encoding="ascii"))
            self.assertEqual("writer-a", stale["writer_instance_id"])

            second = self.storage(root, "writer-c")
            try:
                self.assertEqual(first_identity, second.owner_evidence.lease_identity)
                self.assertEqual("writer-c", second.owner_evidence.writer_instance_id)
            finally:
                second.close()

    def test_path_components_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = self.storage(Path(temporary) / "evidence", "writer-a")
            try:
                for relative in (
                    PurePath("..", "escape.json"),
                    PurePath("records", "CON"),
                    PurePath("records", "alternate:stream"),
                    PurePath("records", "trailing."),
                    PurePath("records", "unicode-K.json"),
                ):
                    with self.subTest(relative=relative):
                        with self.assertRaises(WriterPhysicalStorageError):
                            storage.atomic_create(relative, b"evidence\n")
            finally:
                storage.close()

    def test_read_committed_uses_pinned_parent_and_rejects_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "evidence"
            storage = self.storage(root, "writer-read-proof")
            relative = PurePath("records", "test", "record.json")
            try:
                self.assertTrue(storage.atomic_create(relative, b"durable\n"))
                self.assertEqual(b"durable\n", storage.read_committed(relative))
                for invalid in (PurePath("..", "outside"), PurePath("uncreated", "record.json")):
                    with self.assertRaises(WriterPhysicalStorageError):
                        storage.read_committed(invalid)
                self.assertFalse((root / "uncreated").exists())
                os.link(root / relative, base / "alias.json")
                with self.assertRaisesRegex(WriterPhysicalStorageError, "alias"):
                    storage.read_committed(relative)
            finally:
                storage.close()
            with self.assertRaises(WriterPhysicalStorageError):
                storage.read_committed(relative)

    def test_read_rejects_opened_object_redirection_before_consuming_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            storage = self.storage(base / "evidence", "reader-target-proof")
            relative = PurePath("records", "target.json")
            outside = base / "outside.json"
            outside.write_bytes(b"outside-must-not-be-read")
            try:
                storage.atomic_create(relative, b"durable")
                wrong = storage_module._create_file_handle(outside,
                    desired_access=storage_module._FILE_READ_ATTRIBUTES,
                    share_mode=7, creation_disposition=storage_module._OPEN_EXISTING,
                    flags=storage_module._FILE_FLAG_OPEN_REPARSE_POINT)
                with patch.object(storage._backend,"_open_existing_file",return_value=wrong), \
                        patch.object(storage_module,"_read_handle",side_effect=AssertionError("Read before identity validation")):
                    with self.assertRaises(WriterPhysicalStorageError):
                        storage.read_committed(relative)
                self.assertTrue(wrong.closed)
                self.assertEqual(b"outside-must-not-be-read", outside.read_bytes())
            finally:
                storage.close()

    def test_readback_handles_are_bounded_and_replaced_path_is_not_cached_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence'
            storage=self.storage(root,'readback-bound')
            retained=[]
            try:
                for sequence in range(10):
                    relative=PurePath('records',f'{sequence}.json')
                    storage.atomic_create(relative,str(sequence).encode())
                    self.assertEqual(str(sequence).encode(),storage.read_committed(relative))
                    retained.append(storage._backend._readback_handles[tuple(relative.parts)])
                    self.assertLessEqual(len(storage._backend._readback_handles),2)
                self.assertTrue(all(item.closed for item in retained[:-2]))
                self.assertEqual(b'0',storage.read_committed(PurePath('records','0.json')))
                relative=PurePath('records','9.json')
                (root/relative).unlink()
                (root/relative).write_bytes(b'9')
                with self.assertRaisesRegex(WriterPhysicalStorageError,'no longer identifies'):
                    storage.read_committed(relative)
            finally:
                storage.close()
            self.assertTrue(all(item.closed for item in retained))

    def test_external_hard_link_alias_is_rejected_without_outside_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "evidence"
            outside = base / "outside.json"
            data = b'{"evidence":"outside"}\n'
            storage = self.storage(root, "writer-a")
            try:
                target_parent = root / "records" / "test"
                target_parent.mkdir(parents=True)
                outside.write_bytes(data)
                target = target_parent / "record.json"
                os.link(outside, target)
                before = outside.read_bytes()
                with self.assertRaisesRegex(
                    WriterPhysicalStorageError,
                    "hard-link alias",
                ):
                    storage.atomic_create(
                        PurePath("records", "test", "record.json"),
                        data,
                    )
                self.assertEqual(before, outside.read_bytes())
                self.assertEqual(2, outside.stat().st_nlink)
            finally:
                storage.close()

    def test_owner_lock_hard_link_alias_is_rejected_before_diagnostic_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "evidence"
            root.mkdir()
            outside = base / "outside-owner.txt"
            outside.write_text("outside-owner\n", encoding="ascii")
            os.link(outside, root / OWNER_LEASE_NAME)
            before = outside.read_bytes()
            with self.assertRaisesRegex(
                WriterPhysicalStorageError,
                "owner lease has an external hard-link alias",
            ):
                self.storage(root, "writer-a")
            self.assertEqual(before, outside.read_bytes())


if __name__ == "__main__":
    unittest.main()
