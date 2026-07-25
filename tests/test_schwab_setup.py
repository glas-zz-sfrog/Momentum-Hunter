from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from momentum_hunter.schwab_setup import (
    CallbackTimeoutError,
    LocalSecretStore,
    OAuthStateError,
    SETUP_NOTICE,
    SchwabApplicationCredentials,
    SchwabSetupError,
    WindowsDpapiProtector,
    callback_recommendation,
    generate_oauth_state,
    main,
    parse_oauth_callback,
    read_application_credentials,
    redacted_setup_status,
    wait_for_callback,
)


class SchwabSetupSecurityTests(unittest.TestCase):
    def test_application_secret_uses_masked_reader_and_never_appears_in_repr(self) -> None:
        prompts: list[str] = []

        def app_reader(prompt: str) -> str:
            prompts.append(prompt)
            return "SYNTHETIC-APP-ID"

        def secret_reader(prompt: str) -> str:
            prompts.append(prompt)
            return "SYNTHETIC-APP-SECRET"

        credentials = read_application_credentials(
            application_id_reader=app_reader,
            application_secret_reader=secret_reader,
        )
        self.assertEqual("SYNTHETIC-APP-SECRET", credentials.application_secret)
        self.assertNotIn("SYNTHETIC-APP-ID", repr(credentials))
        self.assertNotIn("SYNTHETIC-APP-SECRET", repr(credentials))
        self.assertIn("secret", prompts[1].lower())

    def test_oauth_state_is_random_and_mismatch_fails(self) -> None:
        first = generate_oauth_state()
        second = generate_oauth_state()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 32)
        callback = parse_oauth_callback(
            f"http://127.0.0.1/callback?code=SYNTHETIC-CODE&state={first}",
            expected_state=first,
        )
        self.assertEqual("SYNTHETIC-CODE", callback.authorization_code)
        self.assertNotIn("SYNTHETIC-CODE", repr(callback))
        self.assertNotIn(first, repr(callback))
        with self.assertRaises(OAuthStateError):
            parse_oauth_callback(
                "http://127.0.0.1/callback?code=SYNTHETIC-CODE&state=wrong",
                expected_state=first,
            )

    def test_nonlocal_callback_and_missing_code_fail(self) -> None:
        state = generate_oauth_state()
        with self.assertRaisesRegex(SchwabSetupError, "local"):
            parse_oauth_callback(f"https://example.com/callback?code=x&state={state}", expected_state=state)
        with self.assertRaisesRegex(SchwabSetupError, "authorization code"):
            parse_oauth_callback(f"http://localhost/callback?state={state}", expected_state=state)
        with self.assertRaisesRegex(SchwabSetupError, "HTTP"):
            parse_oauth_callback(f"file://localhost/callback?code=x&state={state}", expected_state=state)
        with self.assertRaisesRegex(SchwabSetupError, "duplicate state"):
            parse_oauth_callback(
                f"http://localhost/callback?code=x&state={state}&state={state}",
                expected_state=state,
            )

    def test_callback_timeout_fails_safely(self) -> None:
        ticks = iter([0.0, 0.0, 0.1, 0.2])
        with self.assertRaises(CallbackTimeoutError):
            wait_for_callback(
                lambda: None,
                expected_state="synthetic-state",
                timeout_seconds=0.1,
                monotonic=lambda: next(ticks, 1.0),
                sleep=lambda _seconds: None,
            )

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI proof runs on Windows only.")
    def test_dpapi_round_trip_and_local_store_hide_fake_tokens(self) -> None:
        protector = WindowsDpapiProtector()
        plaintext = b'{"access_token":"SYNTHETIC-ACCESS","refresh_token":"SYNTHETIC-REFRESH"}'
        protected = protector.protect(plaintext)
        self.assertNotEqual(plaintext, protected)
        self.assertEqual(plaintext, protector.unprotect(protected))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.bin"
            store = LocalSecretStore(path=path, protector=protector)
            store.save(
                {"access_token": "SYNTHETIC-ACCESS", "refresh_token": "SYNTHETIC-REFRESH"}
            )
            raw = path.read_bytes()
            self.assertNotIn(b"SYNTHETIC-ACCESS", raw)
            self.assertEqual("SYNTHETIC-REFRESH", store.load()["refresh_token"])
            self.assertTrue(store.delete())
            self.assertFalse(path.exists())

    def test_redacted_status_hides_fake_credentials_and_tokens(self) -> None:
        status = redacted_setup_status(
            {
                "client_secret": "SYNTHETIC-SECRET",
                "refresh_token": "SYNTHETIC-REFRESH",
                "state": "LOCKED",
            }
        )
        rendered = json.dumps(status)
        self.assertNotIn("SYNTHETIC-SECRET", rendered)
        self.assertNotIn("SYNTHETIC-REFRESH", rendered)
        self.assertIn("LOCKED", rendered)

    def test_cli_is_credential_free_and_reports_registered_callback(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--show-callback-recommendation"])
        rendered = output.getvalue()
        self.assertEqual(0, result)
        self.assertIn(SETUP_NOTICE, rendered)
        self.assertIn("locked", rendered)
        recommendation = callback_recommendation()
        self.assertEqual("127.0.0.1", recommendation["host"])
        self.assertEqual(
            "https://127.0.0.1:8182/oauth/callback",
            recommendation["registeredCallbackUrl"],
        )
        self.assertEqual(
            "SYNTHETIC_LISTENER_IMPLEMENTED_REAL_ONBOARDING_LOCKED",
            recommendation["status"],
        )
