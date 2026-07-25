from __future__ import annotations

import inspect
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import requests

from momentum_hunter.schwab_onboarding import (
    ACCOUNT_BINDING_SCHEMA_VERSION,
    DELETE_LOCAL_AUTH_CONFIRMATION,
    ONBOARDING_SCHEMA_VERSION,
    SCHWAB_AUTHORIZATION_URL,
    SCHWAB_TOKEN_URL,
    EncryptedSchwabAccountBindingStore,
    SchwabOAuthError,
    SchwabOAuthNetworkError,
    SchwabOAuthOnboarding,
    SchwabOAuthResponseError,
    SchwabOAuthSecretRepository,
    SchwabOAuthTokens,
    SchwabOAuthTransport,
    build_authorization_url,
    main,
)
from momentum_hunter.schwab_oauth_listener import OAuthCallback, REGISTERED_CALLBACK_URL
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    EXPECTED_ACCOUNT_TYPE,
    SchwabAccountBinding,
)
from momentum_hunter.schwab_setup import (
    LocalSecretStore,
    SchwabApplicationCredentials,
    SchwabSetupError,
)


APP_ID = "SYNTHETIC-APP-ID"
APP_SECRET = "SYNTHETIC-APP-SECRET"
ACCESS_TOKEN = "SYNTHETIC-ACCESS-TOKEN"
REFRESH_TOKEN = "SYNTHETIC-REFRESH-TOKEN"
ACCOUNT_HASH = "SYNTHETIC-OPAQUE-ACCOUNT-HASH"


class _XorProtector:
    def protect(self, plaintext: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in plaintext)

    def unprotect(self, ciphertext: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in ciphertext)


class _FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        is_redirect: bool = False,
        content: bytes | None = None,
        json_error: bool = False,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.is_redirect = is_redirect
        self.content = content if content is not None else json.dumps(payload).encode("utf-8")
        self.json_error = json_error

    def json(self) -> object:
        if self.json_error:
            raise ValueError("synthetic invalid JSON")
        return self.payload


class _FakeSession:
    def __init__(
        self,
        response: _FakeResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeCertificateManager:
    def __init__(self, active_file: Path, events: list[str]) -> None:
        self.active_file = active_file
        self.events = events

    def listener_config(
        self,
        version_id: str,
        *,
        require_windows_trust: bool,
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.events.append("certificate")
        if version_id != "synthetic-version" or not require_windows_trust:
            raise AssertionError("Unexpected certificate request")
        return {"timeout": timeout_seconds}


class _FakeListener:
    def __init__(self, config: object, events: list[str]) -> None:
        self.config = config
        self.events = events
        self.state = ""
        self.closed = False
        self.wait_timeout_seconds: float | None = None

    def start(self, *, expected_state: str) -> str:
        self.events.append("listener-start")
        self.state = expected_state
        return REGISTERED_CALLBACK_URL

    def wait(self, *, timeout_seconds: float) -> OAuthCallback:
        self.events.append("listener-wait")
        self.wait_timeout_seconds = timeout_seconds
        if timeout_seconds <= 0:
            raise AssertionError("Timeout must be positive")
        return OAuthCallback("SYNTHETIC-AUTHORIZATION-CODE", self.state)

    def close(self) -> None:
        self.events.append("listener-close")
        self.closed = True


class _FakeTransport:
    def __init__(self, events: list[str], tokens: SchwabOAuthTokens) -> None:
        self.events = events
        self.tokens = tokens

    def exchange_authorization_code(
        self,
        credentials: SchwabApplicationCredentials,
        authorization_code: str,
    ) -> SchwabOAuthTokens:
        self.events.append("token-exchange")
        if credentials.application_secret != APP_SECRET:
            raise AssertionError("Credentials were not loaded")
        if authorization_code != "SYNTHETIC-AUTHORIZATION-CODE":
            raise AssertionError("Unexpected authorization code")
        return self.tokens


def _secret_store(path: Path) -> LocalSecretStore:
    return LocalSecretStore(
        path=path,
        protector=_XorProtector(),
        permission_hardener=lambda _path: None,
    )


def _tokens() -> SchwabOAuthTokens:
    issued_at = datetime.now(timezone.utc)
    return SchwabOAuthTokens(
        access_token=ACCESS_TOKEN,
        refresh_token=REFRESH_TOKEN,
        token_type="Bearer",
        scope="synthetic",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=30),
    )


class SchwabOAuthTransportTests(unittest.TestCase):
    def test_authorization_url_uses_only_exact_registered_contract(self) -> None:
        credentials = SchwabApplicationCredentials(APP_ID, APP_SECRET)
        url = build_authorization_url(credentials, state="synthetic-random-state")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(SCHWAB_AUTHORIZATION_URL, f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
        self.assertEqual([APP_ID], query["client_id"])
        self.assertEqual([REGISTERED_CALLBACK_URL], query["redirect_uri"])
        self.assertEqual(["code"], query["response_type"])
        self.assertEqual(["synthetic-random-state"], query["state"])
        self.assertNotIn(APP_SECRET, url)

    def test_code_exchange_uses_exact_token_endpoint_basic_auth_and_no_redirect(self) -> None:
        response = _FakeResponse(
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "token_type": "Bearer",
                "scope": "synthetic",
                "expires_in": 1800,
            }
        )
        session = _FakeSession(response)
        transport = SchwabOAuthTransport(session=session)
        tokens = transport.exchange_authorization_code(
            SchwabApplicationCredentials(APP_ID, APP_SECRET),
            "SYNTHETIC-CODE",
        )

        self.assertEqual(ACCESS_TOKEN, tokens.access_token)
        self.assertNotIn(ACCESS_TOKEN, repr(tokens))
        self.assertNotIn(REFRESH_TOKEN, repr(tokens))
        self.assertEqual(1, len(session.calls))
        call = session.calls[0]
        self.assertEqual(SCHWAB_TOKEN_URL, call["url"])
        self.assertEqual(False, call["allow_redirects"])
        self.assertEqual(("SYNTHETIC-APP-ID", "SYNTHETIC-APP-SECRET"), (call["auth"].username, call["auth"].password))
        self.assertEqual("authorization_code", call["data"]["grant_type"])
        self.assertEqual(REGISTERED_CALLBACK_URL, call["data"]["redirect_uri"])

    def test_refresh_preserves_existing_refresh_token_when_schwab_omits_rotation(self) -> None:
        response = _FakeResponse(
            {
                "access_token": "SYNTHETIC-NEW-ACCESS",
                "token_type": "Bearer",
                "expires_in": 1800,
            }
        )
        session = _FakeSession(response)
        refreshed = SchwabOAuthTransport(session=session).refresh(
            SchwabApplicationCredentials(APP_ID, APP_SECRET),
            _tokens(),
        )
        self.assertEqual(REFRESH_TOKEN, refreshed.refresh_token)
        self.assertEqual("refresh_token", session.calls[0]["data"]["grant_type"])

    def test_network_status_redirect_shape_and_secret_body_fail_without_leak(self) -> None:
        failures = [
            (
                _FakeSession(error=requests.ConnectionError(f"failed {APP_SECRET}")),
                SchwabOAuthNetworkError,
            ),
            (
                _FakeSession(_FakeResponse({}, status_code=302, is_redirect=True)),
                SchwabOAuthResponseError,
            ),
            (
                _FakeSession(
                    _FakeResponse(
                        {"error": APP_SECRET},
                        status_code=401,
                        content=APP_SECRET.encode("utf-8"),
                    )
                ),
                SchwabOAuthResponseError,
            ),
            (
                _FakeSession(_FakeResponse({}, json_error=True)),
                SchwabOAuthResponseError,
            ),
            (
                _FakeSession(_FakeResponse(["not", "a", "mapping"])),
                SchwabOAuthResponseError,
            ),
        ]
        for session, expected in failures:
            with self.subTest(expected=expected.__name__):
                with self.assertRaises(expected) as captured:
                    SchwabOAuthTransport(session=session).exchange_authorization_code(
                        SchwabApplicationCredentials(APP_ID, APP_SECRET),
                        "SYNTHETIC-CODE",
                    )
                self.assertNotIn(APP_SECRET, str(captured.exception))

    def test_missing_tokens_wrong_type_and_unsafe_lifetime_fail(self) -> None:
        payloads = [
            {"refresh_token": REFRESH_TOKEN, "expires_in": 1800},
            {"access_token": ACCESS_TOKEN, "expires_in": 1800},
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "token_type": "MAC",
                "expires_in": 1800,
            },
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "expires_in": 0,
            },
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "expires_in": 999_999,
            },
        ]
        for payload in payloads:
            with self.subTest(payload=sorted(payload)):
                with self.assertRaises(SchwabOAuthResponseError):
                    SchwabOAuthTransport(
                        session=_FakeSession(_FakeResponse(payload))
                    ).exchange_authorization_code(
                        SchwabApplicationCredentials(APP_ID, APP_SECRET),
                        "SYNTHETIC-CODE",
                    )


class SchwabSecurePersistenceTests(unittest.TestCase):
    def test_credentials_and_tokens_are_encrypted_redacted_and_not_silently_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oauth.bin"
            repository = SchwabOAuthSecretRepository(store=_secret_store(path))
            repository.save_new_credentials(SchwabApplicationCredentials(APP_ID, APP_SECRET))
            self.assertNotIn(APP_ID.encode("utf-8"), path.read_bytes())
            self.assertNotIn(APP_SECRET.encode("utf-8"), path.read_bytes())
            with self.assertRaisesRegex(SchwabOAuthError, "already exists"):
                repository.save_new_credentials(
                    SchwabApplicationCredentials("OTHER-ID", "OTHER-SECRET")
                )

            repository.save_tokens(_tokens())
            raw = path.read_bytes()
            self.assertNotIn(ACCESS_TOKEN.encode("utf-8"), raw)
            self.assertNotIn(REFRESH_TOKEN.encode("utf-8"), raw)
            self.assertEqual(APP_SECRET, repository.load_credentials().application_secret)
            self.assertEqual(ACCESS_TOKEN, repository.load_tokens().access_token)
            status = repository.status()
            self.assertEqual(True, status["credentialsStored"])
            self.assertEqual(True, status["oauthAuthorized"])
            self.assertEqual("ACTIVE", status["tokenState"])
            self.assertNotIn(APP_ID, str(status))
            self.assertNotIn(APP_SECRET, str(status))
            self.assertNotIn(ACCESS_TOKEN, str(status))

    def test_wrong_schema_and_incomplete_store_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oauth.bin"
            store = _secret_store(path)
            store.save({"schema_version": "WRONG", "application_id": APP_ID, "application_secret": APP_SECRET})
            with self.assertRaisesRegex(SchwabOAuthError, "unsupported"):
                SchwabOAuthSecretRepository(store=store).load_credentials()
            store.save({"schema_version": ONBOARDING_SCHEMA_VERSION, "application_id": APP_ID})
            with self.assertRaisesRegex(SchwabOAuthError, "incomplete"):
                SchwabOAuthSecretRepository(store=store).load_credentials()

    def test_one_account_binding_is_encrypted_immutable_and_type_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binding.bin"
            store = EncryptedSchwabAccountBindingStore(store=_secret_store(path))
            binding = SchwabAccountBinding(
                account_hash=ACCOUNT_HASH,
                account_number_last_four="4321",
                account_type=EXPECTED_ACCOUNT_TYPE,
            )
            store.save_new(binding)
            self.assertNotIn(ACCOUNT_HASH.encode("utf-8"), path.read_bytes())
            self.assertEqual(binding, store.load())
            with self.assertRaisesRegex(AccountIsolationError, "replacement"):
                store.save_new(binding)

            invalid_path = Path(directory) / "invalid.bin"
            invalid_store = EncryptedSchwabAccountBindingStore(
                store=_secret_store(invalid_path)
            )
            with self.assertRaises(AccountIsolationError):
                invalid_store.save_new(
                    SchwabAccountBinding(
                        account_hash=ACCOUNT_HASH,
                        account_number_last_four="4321",
                        account_type="MARGIN",
                    )
                )
            self.assertFalse(invalid_path.exists())

    def test_binding_schema_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binding.bin"
            secret_store = _secret_store(path)
            secret_store.save(
                {
                    "schema_version": ACCOUNT_BINDING_SCHEMA_VERSION,
                    "account_hash": ACCOUNT_HASH,
                    "account_number_last_four": "4321",
                    "account_type": EXPECTED_ACCOUNT_TYPE,
                }
            )
            self.assertEqual(
                ACCOUNT_HASH,
                EncryptedSchwabAccountBindingStore(store=secret_store).load().account_hash,
            )


class SchwabOAuthOrchestrationTests(unittest.TestCase):
    def _onboarding(self, directory: str) -> tuple[SchwabOAuthOnboarding, list[str], _FakeListener]:
        root = Path(directory)
        events: list[str] = []
        secrets_repository = SchwabOAuthSecretRepository(
            store=_secret_store(root / "oauth.bin")
        )
        secrets_repository.save_new_credentials(
            SchwabApplicationCredentials(APP_ID, APP_SECRET)
        )
        binding_store = EncryptedSchwabAccountBindingStore(
            store=_secret_store(root / "binding.bin")
        )
        active_file = root / "active.json"
        active_file.write_text(
            json.dumps({"version_id": "synthetic-version"}),
            encoding="utf-8",
        )
        certificate_manager = _FakeCertificateManager(active_file, events)
        listener_holder: list[_FakeListener] = []

        def listener_factory(config: object) -> _FakeListener:
            listener = _FakeListener(config, events)
            listener_holder.append(listener)
            return listener

        def open_browser(url: str) -> bool:
            events.append("browser")
            self.assertEqual(SCHWAB_AUTHORIZATION_URL, url.split("?", 1)[0])
            self.assertNotIn(APP_SECRET, url)
            return True

        onboarding = SchwabOAuthOnboarding(
            secrets_repository=secrets_repository,
            binding_store=binding_store,
            transport=_FakeTransport(events, _tokens()),
            certificate_manager=certificate_manager,
            listener_factory=listener_factory,
            browser_open=open_browser,
        )
        return onboarding, events, listener_holder

    def test_listener_starts_before_browser_and_tokens_persist_after_callback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            onboarding, events, listeners = self._onboarding(directory)
            status = onboarding.authorize(callback_timeout_seconds=5)
            self.assertEqual(
                [
                    "certificate",
                    "listener-start",
                    "browser",
                    "listener-wait",
                    "token-exchange",
                    "listener-close",
                ],
                events,
            )
            self.assertTrue(listeners[0].closed)
            self.assertEqual(True, status["oauthAuthorized"])
            self.assertEqual("NOT_BOUND", status["accountBinding"])
            self.assertEqual(
                "LOCKED_PENDING_SEPARATE_APPROVAL",
                status["authenticatedAccountRequests"],
            )
            self.assertEqual("UNAVAILABLE", status["orderTransmission"])

    def test_default_authorization_window_allows_manual_schwab_login(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            onboarding, _events, listeners = self._onboarding(directory)

            onboarding.authorize()

            self.assertEqual({"timeout": 600.0}, listeners[0].config)
            self.assertEqual(601.0, listeners[0].wait_timeout_seconds)

    def test_browser_failure_closes_listener_and_stores_no_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            onboarding, events, listeners = self._onboarding(directory)
            onboarding.browser_open = lambda _url: False
            with self.assertRaisesRegex(SchwabOAuthError, "browser"):
                onboarding.authorize(callback_timeout_seconds=5)
            self.assertTrue(listeners[0].closed)
            self.assertEqual(False, onboarding.secrets.status()["oauthAuthorized"])
            self.assertNotIn("token-exchange", events)

    def test_missing_active_certificate_blocks_before_listener_or_browser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            onboarding, events, _listeners = self._onboarding(directory)
            onboarding.certificates.active_file.unlink()
            with self.assertRaisesRegex(SchwabOAuthError, "trusted active"):
                onboarding.authorize()
            self.assertEqual([], events)

    def test_local_auth_deletion_requires_exact_confirmation_and_removes_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            onboarding, _events, _listeners = self._onboarding(directory)
            onboarding.bindings.save_new(
                SchwabAccountBinding(
                    account_hash=ACCOUNT_HASH,
                    account_number_last_four="4321",
                    account_type=EXPECTED_ACCOUNT_TYPE,
                )
            )
            with self.assertRaisesRegex(SchwabOAuthError, "exact confirmation"):
                onboarding.delete_local_auth(confirmation="delete")
            self.assertTrue(onboarding.secrets.exists)
            self.assertTrue(onboarding.bindings.exists)
            status = onboarding.delete_local_auth(
                confirmation=DELETE_LOCAL_AUTH_CONFIRMATION
            )
            self.assertFalse(onboarding.secrets.exists)
            self.assertFalse(onboarding.bindings.exists)
            self.assertEqual(False, status["credentialsStored"])

    def test_token_refresh_locks_when_any_account_binding_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            onboarding, events, _listeners = self._onboarding(directory)
            onboarding.secrets.save_tokens(_tokens())
            onboarding.bindings.save_new(
                SchwabAccountBinding(
                    account_hash=ACCOUNT_HASH,
                    account_number_last_four="4321",
                    account_type=EXPECTED_ACCOUNT_TYPE,
                )
            )
            with self.assertRaisesRegex(AccountIsolationError, "revalidated"):
                onboarding.refresh()
            self.assertNotIn("token-exchange", events)


class SchwabOnboardingBoundaryTests(unittest.TestCase):
    def test_module_contains_no_account_endpoint_or_transmitting_method(self) -> None:
        import momentum_hunter.schwab_onboarding as module

        source = inspect.getsource(module)
        self.assertNotIn("/trader/", source)
        self.assertNotIn("/accounts", source)
        for forbidden in (
            "submit_order",
            "place_order",
            "replace_order",
            "cancel_order",
            "transfer_money",
            "withdraw",
        ):
            self.assertNotIn(forbidden, source)
            self.assertFalse(hasattr(SchwabOAuthTransport, forbidden))

    def test_cli_accepts_no_credential_or_token_arguments(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit):
            main(["status", "--client-secret", APP_SECRET])
        self.assertNotIn(APP_SECRET, stderr.getvalue())

    def test_status_cli_is_redacted_and_locked_without_local_material(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secrets_repository = SchwabOAuthSecretRepository(
                store=_secret_store(Path(directory) / "missing-oauth.bin")
            )
            binding_store = EncryptedSchwabAccountBindingStore(
                store=_secret_store(Path(directory) / "missing-binding.bin")
            )
            fake = SchwabOAuthOnboarding(
                secrets_repository=secrets_repository,
                binding_store=binding_store,
            )
            output = io.StringIO()
            with patch(
                "momentum_hunter.schwab_onboarding.SchwabOAuthOnboarding",
                return_value=fake,
            ), redirect_stdout(output):
                self.assertEqual(0, main(["status"]))
            rendered = output.getvalue()
            self.assertIn("LOCKED_PENDING_SEPARATE_APPROVAL", rendered)
            self.assertIn('"orderTransmission": "UNAVAILABLE"', rendered)
            self.assertNotIn(APP_SECRET, rendered)

    def test_local_secret_store_hardens_ciphertext_before_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret.bin"
            observed: list[tuple[Path, bool]] = []

            def hardener(candidate: Path) -> None:
                observed.append((candidate, candidate.is_file()))

            LocalSecretStore(
                path=path,
                protector=_XorProtector(),
                permission_hardener=hardener,
            ).save({"schema_version": "SYNTHETIC"})
            self.assertEqual(2, len(observed))
            self.assertTrue(all(existed for _candidate, existed in observed))
            self.assertNotEqual(path, observed[0][0])
            self.assertEqual(path, observed[1][0])
            self.assertTrue(path.is_file())

    def test_local_secret_store_removes_final_file_if_acl_verification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret.bin"
            calls = 0

            def hardener(_candidate: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise SchwabSetupError("synthetic final ACL failure")

            with self.assertRaisesRegex(SchwabSetupError, "synthetic final ACL"):
                LocalSecretStore(
                    path=path,
                    protector=_XorProtector(),
                    permission_hardener=hardener,
                ).save({"schema_version": "SYNTHETIC"})
            self.assertFalse(path.exists())

    def test_no_live_values_or_secret_schema_are_present_in_repository_fixture(self) -> None:
        payload = {
            "schema_version": ONBOARDING_SCHEMA_VERSION,
            "application_id": APP_ID,
            "application_secret": APP_SECRET,
        }
        self.assertTrue(
            all(
                value.startswith("SYNTHETIC")
                for value in payload.values()
                if value != ONBOARDING_SCHEMA_VERSION
            )
        )
        with self.assertRaises(SchwabSetupError):
            LocalSecretStore(
                path=Path("unused"),
                protector=_XorProtector(),
                permission_hardener=lambda _path: None,
            ).save({"invalid": 1})  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
