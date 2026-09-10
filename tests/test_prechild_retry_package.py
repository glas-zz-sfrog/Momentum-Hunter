import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


spec = importlib.util.spec_from_file_location("prechild_package", Path(__file__).resolve().parents[1] / "tools/package_prechild_retry.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PrechildPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / "stage"
        (self.stage / "source").mkdir(parents=True)
        self.payload = self.stage / "source/fixture.py"
        self.payload.write_bytes(b"# harmless offline fixture\n")
        package.write(self.stage / "CANDIDATE.json", {"head": "a" * 40, "tree": "b" * 40})
        package.write(self.stage / "SOURCE-BYTE-INVENTORY.json", [{"path": "fixture.py", "sha256": package.digest(self.payload.read_bytes())}])
        self.archive = self.root / "review.zip"

    def test_roundtrip_exact_manifest_and_bytes(self):
        result = package.seal(self.stage, self.archive)
        extracted = self.root / "extracted"
        package.extract(self.archive, extracted)
        proof = package.verify(extracted)
        self.assertEqual("PASS", proof["status"])
        self.assertEqual(result["fileCount"], proof["files"])
        self.assertEqual(self.payload.read_bytes(), (extracted / "source/fixture.py").read_bytes())

    def test_frozen_source_change_rejected(self):
        self.payload.write_bytes(b"drift")
        with self.assertRaisesRegex(ValueError, "FROZEN_SOURCE_BYTES_CHANGED"):
            package.seal(self.stage, self.archive)
        self.assertFalse(self.archive.exists())

    def test_manifest_tamper_rejected(self):
        package.seal(self.stage, self.archive)
        self.payload.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "MANIFEST_BYTE_MISMATCH"):
            package.verify(self.stage)

    def test_added_source_file_rejected_before_seal(self):
        (self.stage / "source/unbound.py").write_text("extra")
        with self.assertRaisesRegex(ValueError, "FROZEN_SOURCE_MEMBERSHIP_CHANGED"):
            package.seal(self.stage, self.archive)
        self.assertFalse(self.archive.exists())

    def test_additional_member_rejected(self):
        package.seal(self.stage, self.archive)
        (self.stage / "unindexed.txt").write_text("extra")
        with self.assertRaisesRegex(ValueError, "MEMBERSHIP_MISMATCH"):
            package.verify(self.stage)

    def test_sealed_package_cannot_be_overwritten(self):
        package.seal(self.stage, self.archive)
        before = self.archive.read_bytes()
        with self.assertRaisesRegex(ValueError, "WRITE_ONCE"):
            package.seal(self.stage, self.archive)
        self.assertEqual(before, self.archive.read_bytes())

    def test_sanitization_failure_prevents_zip(self):
        (self.stage / "credential.key").write_text("synthetic prohibited file")
        with self.assertRaisesRegex(ValueError, "SANITIZATION_BLOCKED"):
            package.seal(self.stage, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertEqual("FAIL", json.loads((self.stage / "SANITIZATION.json").read_text())["status"])

    def test_path_traversal_rejected_before_extraction(self):
        with zipfile.ZipFile(self.archive, "x") as out:
            out.writestr("../outside.txt", "bad")
        with self.assertRaisesRegex(ValueError, "UNSAFE_PACKAGE_PATH"):
            package.extract(self.archive, self.root / "extract")
        self.assertFalse((self.root / "outside.txt").exists())

    def test_token_value_is_not_released(self):
        package.write(self.stage / "secret.json", {"access_" + "token": "X" * 48})
        with self.assertRaisesRegex(ValueError, "SANITIZATION_BLOCKED"):
            package.seal(self.stage, self.archive)
        self.assertFalse(self.archive.exists())

    def test_case_aliases_rejected(self):
        with zipfile.ZipFile(self.archive, "x") as out:
            out.writestr("A.txt", "one")
            out.writestr("a.txt", "two")
        with self.assertRaisesRegex(ValueError, "DUPLICATE_PACKAGE_PATH"):
            package.extract(self.archive, self.root / "extract")

    def test_symlink_rejected(self):
        with zipfile.ZipFile(self.archive, "x") as out:
            entry = zipfile.ZipInfo("link")
            entry.external_attr = (0o120777 << 16)
            out.writestr(entry, "outside")
        with self.assertRaisesRegex(ValueError, "SYMLINK_REJECTED"):
            package.extract(self.archive, self.root / "extract")


if __name__ == "__main__":
    unittest.main()
