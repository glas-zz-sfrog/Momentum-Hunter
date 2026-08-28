from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from tools import run_stat_data_002_canary as canary


class StatData002CanaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_write_once_is_idempotent_and_conflicts_fail_closed(self) -> None:
        path = self.root / "evidence.json"
        value = {"status": "PASS", "authority": "RESEARCH_ONLY"}

        canary._write_once(path, value)
        original = path.read_bytes()
        canary._write_once(path, value)

        self.assertEqual(original, path.read_bytes())
        with self.assertRaises(canary.StatDataCanaryError):
            canary._write_once(path, {"status": "FAIL"})

    def test_manifest_verification_detects_tamper(self) -> None:
        payload = self.root / "payload.json"
        payload.write_text('{"safe":true}\n', encoding="ascii")
        canary._write_once(self.root / "MANIFEST.json", canary._manifest(self.root))

        self.assertEqual("PASS", canary._verify_manifest(self.root))
        payload.write_text('{"safe":false}\n', encoding="ascii")
        self.assertEqual("FAIL", canary._verify_manifest(self.root))

    def test_secret_scan_and_terminal_message_redaction(self) -> None:
        safe = self.root / "safe.json"
        safe.write_text(json.dumps({"authority": "RESEARCH_ONLY"}), encoding="ascii")
        self.assertEqual("PASS", canary._secret_scan(self.root)["status"])

        unsafe = self.root / "unsafe.txt"
        unsafe.write_text("Bearer " + "A" * 30, encoding="ascii")
        result = canary._secret_scan(self.root)
        self.assertEqual("FAIL", result["status"])
        self.assertEqual("BEARER_TOKEN", result["findings"][0]["pattern"])

        message = canary._sanitized_message(
            "identity 1234 key PK" + "A" * 22,
            "1234",
        )
        self.assertNotIn("1234", message)
        self.assertNotIn("PK" + "A" * 22, message)

        assignment = canary._sanitized_message(
            "refresh_token=" + "S" * 32,
            "1234",
        )
        self.assertNotIn("S" * 32, assignment)

    def test_live_launch_is_restricted_to_regular_session(self) -> None:
        eastern = ZoneInfo("America/New_York")
        accepted = canary._assert_regular_session(
            datetime(2026, 8, 28, 9, 32, tzinfo=eastern)
        )
        self.assertIn("2026-08-28T09:32:00", accepted)
        for observed in (
            datetime(2026, 8, 28, 9, 29, tzinfo=eastern),
            datetime(2026, 8, 28, 16, 0, tzinfo=eastern),
            datetime(2026, 8, 29, 10, 0, tzinfo=eastern),
        ):
            with self.subTest(observed=observed):
                with self.assertRaises(canary.StatDataCanaryError):
                    canary._assert_regular_session(observed)

    def test_run_all_packages_terminal_failure_even_when_verification_raises(self) -> None:
        evidence = self.root / "terminal-failure"

        def prepare_root(**kwargs):
            kwargs["evidence_root"].mkdir()
            return {"status": "PASS"}

        arguments = (
            "run-all",
            "--task-root",
            str(self.root),
            "--production-root",
            str(self.root),
            "--evidence-root",
            str(evidence),
            "--session-date",
            "2026-08-28",
            "--python-executable",
            str(Path(__file__)),
        )
        with (
            mock.patch.object(canary, "prepare", side_effect=prepare_root),
            mock.patch.object(canary, "execute", return_value={"status": "FAIL"}),
            mock.patch.object(
                canary,
                "verify",
                side_effect=canary.StatDataCanaryError("verification failed"),
            ),
            mock.patch.object(
                canary,
                "package",
                return_value={"status": "PASS", "zipPath": "safe.zip"},
            ) as package,
            mock.patch("builtins.print"),
        ):
            return_code = canary.main(arguments)

        self.assertEqual(1, return_code)
        package.assert_called_once()
        failure = json.loads(
            (evidence / "verification-failure.json").read_text(encoding="ascii")
        )
        self.assertEqual("FAIL", failure["status"])


if __name__ == "__main__":
    unittest.main()
