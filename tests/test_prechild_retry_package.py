import importlib.util
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
import zipfile


spec = importlib.util.spec_from_file_location("prechild_package", Path(__file__).resolve().parents[1] / "tools/package_prechild_retry.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PrechildPackageTests(unittest.TestCase):
    def install_reviewed_fixture(self):
        name = "test_schwab_oauth_listener.py"
        path = self.stage / "source/tests" / name
        path.parent.mkdir(parents=True)
        path.write_bytes((Path(__file__).parent / name).read_bytes())
        return path

    def test_reviewed_public_fixture_requires_exact_path_rule_and_bytes(self):
        self.install_reviewed_fixture()
        report = package.scan(self.stage)
        self.assertEqual("PASS", report["status"])
        self.assertEqual(1, len(report["reviewedPublicTestFixtures"]))

    def test_reviewed_fixture_with_added_bytes_fails_closed(self):
        path = self.install_reviewed_fixture()
        path.write_bytes(path.read_bytes() + b"\n# changed fixture\n")
        self.assertEqual("FAIL", package.scan(self.stage)["status"])

    def test_reviewed_fixture_at_another_path_is_not_exempt(self):
        path = self.install_reviewed_fixture()
        path.rename(self.stage / "unreviewed.py")
        self.assertEqual("FAIL", package.scan(self.stage)["status"])

    def test_other_secret_still_blocks_with_reviewed_fixture_present(self):
        self.install_reviewed_fixture()
        package.write(self.stage / "secret.json", {"access_" + "token": "X" * 48})
        report = package.scan(self.stage)
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(any(row["path"] == "secret.json" for row in report["findings"]))

    def test_prepare_binds_raw_git_blob_and_exact_physical_checkout(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout.decode().strip()
        git("init", "--quiet")
        git("config", "core.autocrlf", "true")
        raw = b"# offline source fixture\n"
        physical = raw.replace(b"\n", b"\r\n")
        (repo / "fixture.py").write_bytes(physical)
        git("add", "fixture.py")
        git("-c", "user.name=Offline Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        head = git("rev-parse", "HEAD")
        binary = self.root / "binary-fixture"
        binary.mkdir()
        (binary / "MomentumHunter.AutomationService.exe").write_bytes(b"NOT_EXECUTABLE_OFFLINE_PACKAGE_FIXTURE")
        target = self.root / "prepared"
        package.prepare(repo, target, head, head, binary, {})
        proof = json.loads((target / "GIT-CHECKOUT-BYTE-BINDING.json").read_text())["files"][0]
        self.assertEqual(package.digest(raw), proof["gitBlobSha256"])
        self.assertEqual(package.digest(physical), proof["physicalSha256"])
        self.assertEqual(physical, (target / "source/fixture.py").read_bytes())
        self.assertEqual("EXACT_GIT_WINDOWS_CRLF_CHECKOUT", proof["representation"])

    def test_checkout_representation_is_exact_and_narrow(self):
        self.assertEqual("EXACT_GIT_BLOB", package.checkout_representation(b"a\nb\n", b"a\nb\n"))
        self.assertEqual("EXACT_GIT_WINDOWS_CRLF_CHECKOUT", package.checkout_representation(b"a\nb\n", b"a\r\nb\r\n"))
        for changed in (b"a\r\nc\r\n", b"a\r\nb\n", b"a \r\nb\r\n"):
            with self.assertRaisesRegex(ValueError, "PHYSICAL_SOURCE_NOT_EXACT"):
                package.checkout_representation(b"a\nb\n", changed)
        with self.assertRaisesRegex(ValueError, "PHYSICAL_SOURCE_NOT_EXACT"):
            package.checkout_representation(b"\0binary\n", b"\0binary\r\n")

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
