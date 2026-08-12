from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
import subprocess

from momentum_hunter.session_fidelity import fingerprint
from momentum_hunter.session_fidelity_premarket_retry import (
    CHECKPOINTS,
    TASK_ID,
    PremarketRetryError,
    load_existing_retry,
    program_context,
    require_checkpoint_start,
)


class SessionFidelityPremarketRetryTests(unittest.TestCase):
    @staticmethod
    def _load_runner() -> object:
        path = (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "run_session_fidelity_premarket_retry.py"
        )
        spec = importlib.util.spec_from_file_location("premarket_retry_test_runner", path)
        assert spec is not None and spec.loader is not None
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        return runner

    def test_retry_matrix_is_fixed_alpaca_only_and_prospective(self) -> None:
        self.assertEqual(TASK_ID, "SESSION-FIDELITY-003")
        self.assertEqual(tuple(CHECKPOINTS), ("A", "B", "C"))
        self.assertEqual(
            tuple(row.target_central.isoformat() for row in CHECKPOINTS.values()),
            (
                "2026-08-12T03:05:00-05:00",
                "2026-08-12T05:55:00-05:00",
                "2026-08-12T06:05:00-05:00",
            ),
        )
        for checkpoint in CHECKPOINTS.values():
            self.assertFalse(checkpoint.schwab)
            self.assertTrue(checkpoint.alpaca)
            self.assertEqual(checkpoint.duration_seconds, 300)

    def test_retry_window_fails_closed(self) -> None:
        target = CHECKPOINTS["A"].target_central
        self.assertEqual(require_checkpoint_start("A", target).code, "A")
        with self.assertRaises(PremarketRetryError):
            require_checkpoint_start("A", target - timedelta(microseconds=1))
        with self.assertRaises(PremarketRetryError):
            require_checkpoint_start("A", target + timedelta(minutes=6, microseconds=1))
        with self.assertRaises(PremarketRetryError):
            require_checkpoint_start("A", target.replace(tzinfo=None))

    def test_program_context_preserves_failed_source_without_reuse(self) -> None:
        context = program_context("B")
        self.assertEqual(context["retryTaskId"], TASK_ID)
        self.assertEqual(context["sourceTaskId"], "SESSION-FIDELITY-001")
        self.assertEqual(context["sourceCheckpoint"], "B")
        self.assertFalse(context["sourceEvidenceMutationAuthorized"])
        self.assertFalse(context["historicalSchwabEvidenceReused"])
        self.assertFalse(context["strategyAuthorityGranted"])
        self.assertFalse(context["executionAuthorityGranted"])

    def test_existing_exact_retry_is_verified_without_provider_replay(self) -> None:
        checkpoint = CHECKPOINTS["A"]
        result = {
            "taskId": TASK_ID,
            "mode": "READ_ONLY_NONPERSISTING_SESSION_FIDELITY",
            "provider": "ALPACA",
            "symbols": ["SPY", "QQQ", "NVDA"],
            "checkpoint": checkpoint.evidence(),
            "programContext": dict(program_context("A")),
            "adjudication": {"classification": "USEFUL_WITH_LIMITATIONS"},
            "accountRequested": False,
            "accountValuesIncluded": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "previewsRequested": False,
            "mutatingRequestAttempted": False,
            "strategyAuthorityGranted": False,
            "executionAuthorityGranted": False,
            "productionPersistence": False,
            "credentialMaterialIncluded": False,
            "liveEndpointReachable": False,
            "orderTransmission": "UNAVAILABLE",
        }
        result["evidenceFingerprint"] = fingerprint(result)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint-a-alpaca.json"
            path.write_text(json.dumps(result), encoding="utf-8")
            self.assertEqual(load_existing_retry(path, checkpoint_code="A"), result)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = self._load_runner().main(
                    [
                        "--checkpoint",
                        "A",
                        "--project-root",
                        str(Path(temporary) / "unavailable-project"),
                        "--source-root",
                        str(Path(temporary) / "unavailable-provider"),
                        "--output",
                        str(path),
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "DUPLICATE_VERIFIED")
            result["ordersRequested"] = True
            result["evidenceFingerprint"] = fingerprint(result)
            path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaises(PremarketRetryError):
                load_existing_retry(path, checkpoint_code="A")

    def test_retry_runner_passes_exact_identity_to_repaired_adapter(self) -> None:
        runner = self._load_runner()
        calls: list[dict[str, object]] = []

        class Adapter:
            def _run_checkpoint_observation(
                self, checkpoint: object, **kwargs: object
            ) -> dict[str, object]:
                calls.append({"checkpoint": checkpoint, **kwargs})
                return {"taskId": kwargs["task_id"], "adjudication": {"classification": "STALE"}}

        target = CHECKPOINTS["C"].target_central
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = runner.run_retry(
                "C",
                project_root=root,
                source_root=root,
                now=target,
                sleeper=lambda _seconds: None,
                adapter=Adapter(),
            )
        self.assertEqual(result["taskId"], TASK_ID)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["task_id"], TASK_ID)
        self.assertEqual(calls[0]["program_context"], program_context("C"))

    def test_scripts_are_one_time_read_only_and_have_no_order_routes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = (
            root / "momentum_hunter" / "session_fidelity_premarket_retry.py",
            root / "tools" / "run_session_fidelity_premarket_retry.py",
            root / "tools" / "run_session_fidelity_premarket_retry.ps1",
            root / "tools" / "install_session_fidelity_premarket_retry_tasks.ps1",
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for forbidden in (
            "api.alpaca.markets",
            "paper-api.alpaca.markets",
            "/v2/orders",
            "/v2/positions",
            "submit_order",
            "cancel_order",
            "replace_order",
            "preview_order",
        ):
            self.assertNotIn(forbidden, combined)
        installer = paths[-1].read_text(encoding="utf-8")
        self.assertNotIn("New-ScheduledTaskTrigger -Daily", installer)
        self.assertIn("StartWhenAvailable", installer)
        self.assertIn('@($common[0..4]) + "-Checkpoint', installer)
        self.assertNotIn('@($common[0..3]) + "-Checkpoint', installer)
        self.assertIn('providerScope = "ALPACA_ONLY"', installer)
        self.assertIn('orderTransmission = "UNAVAILABLE"', installer)

    def test_powershell_scripts_parse(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in (
            "run_session_fidelity_premarket_retry.ps1",
            "install_session_fidelity_premarket_retry_tasks.ps1",
        ):
            path = root / "tools" / name
            command = (
                "$ErrorActionPreference='Stop'; "
                f"[void][scriptblock]::Create((Get-Content -LiteralPath '{path}' -Raw));"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_powershell_wrapper_logs_preflight_failure_before_python(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "tools" / "run_session_fidelity_premarket_retry.ps1"
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = Path(temporary) / "diagnostics"
            missing = Path(temporary) / "missing-project"
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Checkpoint",
                    "B",
                    "-ProjectRoot",
                    str(missing),
                    "-PythonRoot",
                    str(root),
                    "-AlpacaRoot",
                    str(root),
                    "-DiagnosticDirectory",
                    str(diagnostic),
                    "-ExpectedGitCommit",
                    "0" * 40,
                    "-ExpectedRetryModuleSha256",
                    "0" * 64,
                    "-ExpectedRetryRunnerSha256",
                    "0" * 64,
                    "-ExpectedAdapterSha256",
                    "0" * 64,
                    "-ExpectedAlpacaCommit",
                    "0" * 40,
                    "-ExpectedAlpacaModuleSha256",
                    "0" * 64,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            log = diagnostic / "checkpoint-b-wrapper.log"
            self.assertTrue(log.is_file())
            content = log.read_text(encoding="utf-8")
            self.assertIn("wrapper.start", content)
            self.assertIn("wrapper.failed", content)
            self.assertIn("Premarket retry worktree is unavailable", content)
            self.assertNotIn("provider.start", content)


if __name__ == "__main__":
    unittest.main()
