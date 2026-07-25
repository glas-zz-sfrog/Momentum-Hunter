from __future__ import annotations

import ast
import io
import json
import os
import socket
import ssl
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

import momentum_hunter.schwab_loopback_certificate as certificate_module
from momentum_hunter.schwab_loopback_certificate import (
    INSTALL_TRUST_CONFIRMATION,
    REMOVE_TRUST_CONFIRMATION,
    BrowserCertificateProof,
    LoopbackCertificateError,
    WindowsLoopbackCertificateManager,
    main,
    run_browser_certificate_proof,
)
from momentum_hunter.schwab_oauth_listener import OneShotOAuthCallbackListener
from momentum_hunter.schwab_setup import WindowsDpapiProtector, generate_oauth_state


@unittest.skipUnless(os.name == "nt", "Windows certificate proof runs on Windows only.")
class WindowsLoopbackCertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.root_directory = Path(cls.temporary_directory.name) / "oauth-loopback"
        cls.manager = WindowsLoopbackCertificateManager(root_directory=cls.root_directory)
        cls.material = cls.manager.stage()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_stage_generates_encrypted_versioned_material_without_trust(self) -> None:
        material = self.material
        self.assertEqual("127.0.0.1", material.metadata.host)
        self.assertEqual("localhost", material.metadata.dns_name)
        self.assertEqual("STAGED_UNTRUSTED", material.metadata.trust_status)
        self.assertTrue(material.certificate_chain_file.is_file())
        self.assertTrue(material.root_certificate_file.is_file())
        self.assertTrue(material.private_key_file.is_file())
        self.assertTrue(material.secret_store_file.is_file())
        key_text = material.private_key_file.read_text(encoding="ascii")
        self.assertIn("BEGIN ENCRYPTED PRIVATE KEY", key_text)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", key_text)
        self.assertFalse(self.manager.is_trusted(material.metadata.version_id))

    def test_dpapi_secret_does_not_expose_private_key_password(self) -> None:
        material = self.material
        protector = WindowsDpapiProtector()
        protected_file = material.secret_store_file.read_bytes()
        decoded = self.manager._load_secret(material)
        password = decoded["private_key_password"]
        self.assertNotIn(password.encode("utf-8"), protected_file)
        self.assertNotIn(password, repr(material))
        self.assertGreaterEqual(len(password), 48)
        self.assertNotEqual(protected_file, protector.protect(password.encode("utf-8")))

    def test_staged_certificate_passes_chain_hostname_key_and_tls_proof(self) -> None:
        verification = self.manager.verify(
            self.material.metadata.version_id,
            require_windows_trust=False,
        )
        self.assertEqual("STAGED_VERIFIED_UNTRUSTED", verification.status)
        self.assertFalse(verification.windows_trusted)
        self.assertTrue(verification.private_key_encrypted)
        self.assertTrue(verification.tls_handshake_passed)
        self.assertTrue(verification.acl_hardened)
        self.assertGreaterEqual(verification.days_remaining, 360)

    def test_encrypted_material_runs_one_use_listener_without_trust_install(self) -> None:
        config = self.manager.listener_config(
            self.material.metadata.version_id,
            require_windows_trust=False,
            timeout_seconds=1.0,
            test_only_allow_ephemeral_port=True,
        )
        self.assertNotIn(
            self.manager._load_secret(self.material)["private_key_password"],
            repr(config),
        )
        listener = OneShotOAuthCallbackListener(config)
        state = generate_oauth_state()
        callback_url = listener.start(expected_state=state)
        client_context = ssl.create_default_context(
            cafile=str(self.material.root_certificate_file)
        )
        opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=client_context),
        )
        try:
            with opener.open(
                f"{callback_url}?code=SYNTHETIC-CODE&state={state}",
                timeout=2.0,
            ) as response:
                self.assertEqual(200, response.status)
                response.read()
            callback = listener.wait(timeout_seconds=2.0)
        finally:
            listener.close()
        self.assertEqual("SYNTHETIC-CODE", callback.authorization_code)
        self.assertFalse(listener.is_running)
        self.assertFalse(self.manager.is_trusted(self.material.metadata.version_id))

    def test_listener_config_refuses_untrusted_material_by_default(self) -> None:
        with self.assertRaisesRegex(LoopbackCertificateError, "not trusted"):
            self.manager.listener_config(self.material.metadata.version_id)

    def test_browser_certificate_proof_runs_synthetic_callback_and_closes(self) -> None:
        opened_urls: list[str] = []
        response_bodies: list[str] = []
        client_context = ssl.create_default_context(
            cafile=str(self.material.root_certificate_file)
        )
        opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=client_context),
        )

        def open_local_proof(url: str) -> bool:
            opened_urls.append(url)
            with opener.open(url, timeout=2.0) as response:
                self.assertEqual(200, response.status)
                response_bodies.append(response.read().decode("utf-8"))
            return True

        proof = run_browser_certificate_proof(
            self.manager,
            self.material.metadata.version_id,
            browser_opener=open_local_proof,
            timeout_seconds=2.0,
            require_windows_trust=False,
            test_only_allow_ephemeral_port=True,
        )
        self.assertEqual("BROWSER_TRUST_PROOF_PASSED", proof.status)
        self.assertTrue(proof.listener_closed)
        self.assertFalse(proof.credentials_loaded)
        self.assertFalse(proof.oauth_attempted)
        self.assertFalse(proof.broker_connected)
        self.assertEqual(1, len(opened_urls))
        query = parse_qs(urlsplit(opened_urls[0]).query)
        self.assertEqual(["LOCAL-CERTIFICATE-PROOF"], query["code"])
        self.assertEqual(1, len(query["state"]))
        self.assertNotIn(query["state"][0], response_bodies[0])
        self.assertNotIn("LOCAL-CERTIFICATE-PROOF", response_bodies[0])
        self.assertFalse(self.manager.is_trusted(self.material.metadata.version_id))
        with self.assertRaises(OSError):
            socket.create_connection((proof.host, proof.port), timeout=0.2)

    def test_browser_certificate_proof_requires_windows_trust_by_default(self) -> None:
        browser_opener = mock.Mock(return_value=True)
        with self.assertRaisesRegex(LoopbackCertificateError, "not trusted"):
            run_browser_certificate_proof(
                self.manager,
                self.material.metadata.version_id,
                browser_opener=browser_opener,
                timeout_seconds=1.0,
                test_only_allow_ephemeral_port=True,
            )
        browser_opener.assert_not_called()

    def test_browser_certificate_proof_closes_if_browser_cannot_open(self) -> None:
        opened_urls: list[str] = []

        def refuse_browser(url: str) -> bool:
            opened_urls.append(url)
            return False

        with self.assertRaisesRegex(LoopbackCertificateError, "could not open"):
            run_browser_certificate_proof(
                self.manager,
                self.material.metadata.version_id,
                browser_opener=refuse_browser,
                timeout_seconds=1.0,
                require_windows_trust=False,
                test_only_allow_ephemeral_port=True,
            )
        self.assertEqual(1, len(opened_urls))
        parsed = urlsplit(opened_urls[0])
        self.assertIsNotNone(parsed.port)
        with self.assertRaises(OSError):
            socket.create_connection((str(parsed.hostname), int(parsed.port)), timeout=0.2)

    def test_trust_mutation_requires_exact_confirmation(self) -> None:
        version_id = self.material.metadata.version_id
        with self.assertRaisesRegex(LoopbackCertificateError, "confirmation"):
            self.manager.install_trust(version_id, confirmation="")
        with self.assertRaisesRegex(LoopbackCertificateError, "confirmation"):
            self.manager.remove_trust(version_id, confirmation="")
        self.assertFalse(self.manager.is_trusted(version_id))

    def test_cli_status_and_stage_output_never_imply_oauth_or_broker_access(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--status", "--root", str(self.root_directory)])
        payload = json.loads(output.getvalue())
        self.assertEqual(0, result)
        self.assertFalse(payload["credentials_loaded"])
        self.assertFalse(payload["oauth_attempted"])
        self.assertFalse(payload["broker_connected"])
        self.assertEqual(1, len(payload["versions"]))
        self.assertEqual("STAGED_UNTRUSTED", payload["versions"][0]["trust_status"])

    def test_cli_browser_proof_output_is_sanitized(self) -> None:
        proof = BrowserCertificateProof(
            status="BROWSER_TRUST_PROOF_PASSED",
            version_id=self.material.metadata.version_id,
            host="127.0.0.1",
            port=8182,
            listener_closed=True,
        )
        output = io.StringIO()
        with mock.patch.object(
            certificate_module,
            "run_browser_certificate_proof",
            return_value=proof,
        ):
            with redirect_stdout(output):
                result = main(
                    [
                        "--browser-proof",
                        self.material.metadata.version_id,
                        "--root",
                        str(self.root_directory),
                    ]
                )
        payload = json.loads(output.getvalue())
        self.assertEqual(0, result)
        self.assertTrue(payload["listener_closed"])
        self.assertFalse(payload["credentials_loaded"])
        self.assertFalse(payload["oauth_attempted"])
        self.assertFalse(payload["broker_connected"])
        self.assertNotIn("code", payload)
        self.assertNotIn("state", payload)

    def test_version_identity_rejects_path_traversal(self) -> None:
        for version_id in ("../outside", "..", "bad/name", "bad\\name"):
            with self.subTest(version_id=version_id):
                with self.assertRaises(LoopbackCertificateError):
                    self.manager.load(version_id)

    def test_module_has_no_provider_broker_account_or_order_client_imports(self) -> None:
        source = Path(certificate_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        momentum_hunter_imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("momentum_hunter")
        }
        self.assertEqual(
            {
                "momentum_hunter.schwab_oauth_listener",
                "momentum_hunter.schwab_setup",
            },
            momentum_hunter_imports,
        )
        for forbidden in (
            "requests",
            "httpx",
            "submit_order",
            "replace_order",
            "cancel_order",
            "account_hash",
            "authorization_endpoint",
            "token_endpoint",
        ):
            self.assertNotIn(forbidden, source)

    def test_private_key_password_uses_stdin_not_process_arguments_or_errors(self) -> None:
        password = "SYNTHETIC-PRIVATE-KEY-PASSWORD-MUST-NOT-LEAK"
        manager = WindowsLoopbackCertificateManager(
            root_directory=self.root_directory,
            powershell_executable="pwsh.exe",
        )
        completed = SimpleNamespace(
            returncode=0,
            stdout='{"status":"ok"}\n',
            stderr="",
        )
        with mock.patch.object(certificate_module.subprocess, "run", return_value=completed) as run:
            result = manager._run_powershell(
                "Write-Output '{}'",
                {"private_key_password": password},
            )
        args, kwargs = run.call_args
        rendered_arguments = json.dumps(args[0])
        self.assertNotIn(password, rendered_arguments)
        self.assertIn(password, str(kwargs["input"]))
        self.assertEqual("ok", result["status"])

        failed = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=f"provider wrote {password}",
        )
        with mock.patch.object(certificate_module.subprocess, "run", return_value=failed):
            with self.assertRaises(LoopbackCertificateError) as caught:
                manager._run_powershell(
                    "throw 'failed'",
                    {"private_key_password": password},
                )
        self.assertNotIn(password, str(caught.exception))

    def test_failed_generation_removes_partial_version_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "failed-stage"

            def fail_generation(
                _script: str,
                _payload: dict[str, object],
            ) -> dict[str, object]:
                raise LoopbackCertificateError("synthetic generation failure")

            manager = WindowsLoopbackCertificateManager(
                root_directory=root,
                powershell_runner=fail_generation,
            )
            with self.assertRaisesRegex(LoopbackCertificateError, "synthetic"):
                manager.stage()
            self.assertEqual((), manager.list_versions())
            versions = root / "versions"
            self.assertFalse(versions.exists() and any(versions.iterdir()))

    def test_explicit_trust_lifecycle_contract_is_reversible_with_fake_store(self) -> None:
        calls: list[str] = []

        def fake_runner(script: str, payload: dict[str, object]) -> dict[str, object]:
            if "AreAccessRulesProtected" in script or "SetAccessControl" in script:
                return self.manager._run_powershell(script, payload)
            if "store.Add" in script:
                calls.append("install")
                return {"installed": True}
            if "store.Remove" in script:
                calls.append("remove")
                return {"removed": 1}
            calls.append("status")
            return {"trusted": "install" in calls and "remove" not in calls, "match_count": 1}

        manager = WindowsLoopbackCertificateManager(
            root_directory=self.root_directory,
            protector=WindowsDpapiProtector(),
            powershell_runner=fake_runner,
        )
        version_id = self.material.metadata.version_id
        verification = manager.install_trust(
            version_id,
            confirmation=INSTALL_TRUST_CONFIRMATION,
        )
        self.assertTrue(verification.windows_trusted)
        self.assertTrue(manager.active_file.is_file())
        self.assertIn("install", calls)

        removed = manager.remove_trust(
            version_id,
            confirmation=REMOVE_TRUST_CONFIRMATION,
        )
        self.assertTrue(removed)
        self.assertFalse(manager.active_file.exists())
        self.assertIn("remove", calls)
        restored_metadata = read_trust_status(self.material.metadata_file)
        self.assertEqual("STAGED_UNTRUSTED", restored_metadata)

    def test_failed_trust_install_attempts_exact_rollback(self) -> None:
        calls: list[str] = []

        def failing_runner(script: str, payload: dict[str, object]) -> dict[str, object]:
            if "AreAccessRulesProtected" in script or "SetAccessControl" in script:
                return self.manager._run_powershell(script, payload)
            if "store.Add" in script:
                calls.append("install-failed-after-add")
                raise LoopbackCertificateError("synthetic post-add failure")
            if "store.Remove" in script:
                calls.append("rollback-remove")
                return {"removed": 1}
            return {"trusted": False, "match_count": 0}

        manager = WindowsLoopbackCertificateManager(
            root_directory=self.root_directory,
            protector=WindowsDpapiProtector(),
            powershell_runner=failing_runner,
        )
        version_id = self.material.metadata.version_id
        with self.assertRaisesRegex(LoopbackCertificateError, "post-add"):
            manager.install_trust(
                version_id,
                confirmation=INSTALL_TRUST_CONFIRMATION,
            )
        self.assertEqual(
            ["install-failed-after-add", "rollback-remove"],
            calls,
        )
        self.assertFalse(manager.active_file.exists())
        metadata = json.loads(self.material.metadata_file.read_text(encoding="utf-8"))
        self.assertEqual("STAGED_UNTRUSTED", metadata["trust_status"])


def read_trust_status(metadata_file: Path) -> str:
    payload = json.loads(metadata_file.read_text(encoding="utf-8"))
    return str(payload["trust_status"])
