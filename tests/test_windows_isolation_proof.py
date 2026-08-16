from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.continuous_runtime import (
    WRITER_ACCEPTED,
    WRITER_DUPLICATE,
    WRITER_UNAVAILABLE,
)
from momentum_hunter.windows_isolation_proof import (
    crash_restart_matrix,
    current_identity,
    duplicate_writer_process_proof,
    handle_inheritance_matrix,
    ipc_attack_matrix,
    reparse_attack_matrix,
    run_non_elevated_proof,
    runtime_restart_replay_proof,
    same_sid_handle_duplication,
    same_sid_ransom_proof,
)


ROOT = Path(__file__).parents[1]


@unittest.skipUnless(__import__("os").name == "nt", "Windows physical proof")
class WindowsIsolationProofTests(unittest.TestCase):
    def test_current_identity_is_physical_windows_token(self) -> None:
        identity = current_identity()
        self.assertTrue(str(identity["sid"]).startswith("S-1-"))
        self.assertIn(identity["integrity"], {"LOW", "MEDIUM", "HIGH", "SYSTEM"})
        self.assertGreater(identity["processId"], 0)

    def test_handle_inheritance_requires_inheritance_or_explicit_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = handle_inheritance_matrix(Path(temporary))
        self.assertFalse(result["inheritanceDisabled"]["sha256Matches"])
        self.assertTrue(result["inheritanceEnabled"]["sha256Matches"])
        self.assertTrue(result["explicitAllowedList"]["sha256Matches"])
        self.assertFalse(result["explicitUnrelatedList"]["sha256Matches"])

    def test_same_sid_can_open_process_duplicate_handle_and_read_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = same_sid_handle_duplication(Path(temporary))
        self.assertTrue(result["openProcess"])
        self.assertTrue(result["duplicateHandle"])
        self.assertTrue(result["sha256Matches"])

    def test_ipc_attack_matrix_fails_closed(self) -> None:
        result = ipc_attack_matrix()
        self.assertTrue(result)
        self.assertTrue(all(result.values()))

    def test_two_physical_writers_expose_missing_process_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = duplicate_writer_process_proof(Path(temporary))
        self.assertTrue(result["bothAccepted"])
        self.assertEqual(2, result["recordFiles"])
        self.assertTrue(result["restartValidationFailed"])

    def test_physical_writer_and_runtime_restart_replay_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            crashes = crash_restart_matrix(root / "crashes")
            runtime = runtime_restart_replay_proof(root / "runtime")
        self.assertEqual(4, len(crashes))
        for phase, result in crashes.items():
            with self.subTest(phase=phase):
                self.assertEqual(86, result["crashExitCode"])
                self.assertEqual(0, result["restartExitCode"])
                self.assertIn(
                    result["restartStatus"],
                    {WRITER_ACCEPTED, WRITER_DUPLICATE},
                )
                self.assertEqual(1, result["recordCount"])
                self.assertEqual(0, result["partialCount"])
        self.assertEqual(86, runtime["crashExitCode"])
        self.assertEqual(0, runtime["replayExitCode"])
        self.assertEqual(WRITER_DUPLICATE, runtime["replayStatus"])
        self.assertEqual(1, runtime["recordCount"])

    def test_same_sid_root_and_partial_reparse_attacks_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = reparse_attack_matrix(Path(temporary))
        self.assertTrue(result["rootSubstitution"]["writeRejected"])
        self.assertEqual(0, result["rootSubstitution"]["escapedRecordCount"])
        self.assertTrue(result["recordShardRedirect"]["rejected"])
        self.assertEqual(0, result["recordShardRedirect"]["escapedRecordCount"])
        self.assertEqual(WRITER_UNAVAILABLE, result["partialRedirect"]["writerStatus"])
        self.assertEqual(1, result["partialRedirect"]["escapedTemporaryCount"])

    def test_same_sid_can_overwrite_and_delete_committed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = same_sid_ransom_proof(Path(temporary))
        self.assertTrue(result["overwriteAllowed"])
        self.assertTrue(result["deleteAllowed"])

    def test_aggregate_non_elevated_proof_is_write_once_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proof.json"
            result = run_non_elevated_proof(output)
            persisted = json.loads(output.read_text(encoding="ascii"))
        self.assertEqual("TEST_ONLY_NO_RUNTIME_AUTHORITY", result["authority"])
        self.assertEqual(0, result["providerBrokerOrderCalls"])
        self.assertFalse(result["productionContacted"])
        self.assertEqual("continuous-windows-isolation-proof-v1", persisted["profile"])
        self.assertRegex(persisted["fingerprint"], r"^[a-f0-9]{64}$")

    def test_harness_has_no_provider_broker_order_or_service_control_import(self) -> None:
        source = ROOT / "momentum_hunter" / "windows_isolation_proof.py"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden = (
            "alpaca",
            "schwab",
            "finviz",
            "broker",
            "automation_supervisor",
            "servicecontroller",
        )
        self.assertFalse(
            any(any(part in item.casefold() for part in forbidden) for item in imports)
        )

    def test_powershell_harnesses_parse(self) -> None:
        for relative in (
            "tools/windows_isolation_actor.ps1",
            "tools/run_windows_isolation_elevated.ps1",
            "tools/run_continuous_windows_isolation_proof.ps1",
        ):
            with self.subTest(path=relative):
                command = (
                    "$t=$null;$e=$null;"
                    f"[Management.Automation.Language.Parser]::ParseFile('{(ROOT / relative).as_posix()}',"
                    "[ref]$t,[ref]$e)|Out-Null;"
                    "if($e.Count){$e|%{$_.Message};exit 1}"
                )
                completed = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", command],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_distinct_principal_seed_files_are_protected_before_actor_launch(self) -> None:
        source = (
            ROOT / "tools" / "run_windows_isolation_elevated.ps1"
        ).read_text(encoding="utf-8")
        proof_body = source.index("try {", source.index("function Invoke-DuplicateTask"))
        acl_install = source.index("$result.acl = [ordered]@{", proof_body)
        seed_creation = source.index("New-SeedRoot -Path $path", proof_body)
        writer_launch = source.index("$writerActor = Invoke-AccessTask", proof_body)
        self.assertLess(seed_creation, acl_install)
        self.assertLess(acl_install, writer_launch)

    def test_distinct_principal_children_keep_root_acl_inheritance(self) -> None:
        source = (
            ROOT / "tools" / "run_windows_isolation_elevated.ps1"
        ).read_text(encoding="utf-8")
        for root, failure in (
            ("$testRoot", "Test root ACL configuration failed."),
            ("$toolRoot", "Test tool ACL configuration failed."),
            ("$controlRoot", "Test control ACL configuration failed."),
        ):
            with self.subTest(root=root):
                start = source.index(f"& icacls.exe {root} /inheritance:r")
                end = source.index(failure, start)
                self.assertNotIn("/T", source[start:end])

    def test_service_actor_uses_encoded_disposable_payload(self) -> None:
        source = (
            ROOT / "tools" / "run_windows_isolation_elevated.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Get-ActorInvocationPrefix", source)
        self.assertIn("-EncodedCommand $encoded", source)
        self.assertNotIn("-File $actorPath", source)


if __name__ == "__main__":
    unittest.main()
