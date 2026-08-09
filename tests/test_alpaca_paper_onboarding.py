from __future__ import annotations

import ast
import io
import inspect
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import requests

from momentum_hunter.alpaca_paper_onboarding import (
    ALPACA_LIVE_BASE_URL,
    ALPACA_PAPER_BASE_URL,
    ALPACA_PAPER_CREDENTIAL_SCHEMA,
    ALPACA_PAPER_ENVIRONMENT,
    REPLACE_CANARY_CREDENTIALS_CONFIRMATION,
    AlpacaPaperCredentialError,
    AlpacaPaperCredentialRepository,
    AlpacaPaperCredentials,
    AlpacaPaperEndpointError,
    AlpacaPaperNetworkError,
    AlpacaPaperReadonlyCanary,
    AlpacaPaperReadonlyTransport,
    AlpacaPaperResponseError,
    AlpacaPaperLane,
    main,
    onboard_paper_credentials,
    parse_paper_account,
    read_paper_credentials,
    replace_canary_credentials,
)
from momentum_hunter.schwab_setup import LocalSecretStore, WindowsDpapiProtector


KEY_ID = "SYNTHETIC-PAPER-KEY-ID"
SECRET_KEY = "SYNTHETIC-PAPER-SECRET-KEY"


class _XorProtector:
    def protect(self, plaintext: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in plaintext)

    def unprotect(self, ciphertext: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in ciphertext)


class _Response:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        redirect: bool = False,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.is_redirect = redirect
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> object:
        return self._payload


class _Session:
    def __init__(self, response: _Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _account_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "SYNTHETIC-ACCOUNT-ID-MUST-NOT-LEAK",
        "account_number": "SYNTHETIC-ACCOUNT-NUMBER-MUST-NOT-LEAK",
        "status": "ACTIVE",
        "cash": "100.00",
        "buying_power": "200.00",
        "account_blocked": False,
        "trading_blocked": False,
        "trade_suspended_by_user": False,
    }
    payload.update(overrides)
    return payload


def _repository(
    path: Path,
    lane: AlpacaPaperLane = AlpacaPaperLane.CANARY_REALISTIC,
) -> AlpacaPaperCredentialRepository:
    return AlpacaPaperCredentialRepository(
        lane=lane,
        store=LocalSecretStore(
            path=path,
            protector=_XorProtector(),
            permission_hardener=lambda _path: None,
        )
    )


class AlpacaPaperOnboardingTests(unittest.TestCase):
    def test_hidden_entry_requires_each_value_once(self) -> None:
        prompts: list[str] = []
        values = iter([KEY_ID, SECRET_KEY])

        def reader(prompt: str) -> str:
            prompts.append(prompt)
            return next(values)

        credentials = read_paper_credentials(
            lane=AlpacaPaperLane.CANARY_REALISTIC,
            reader=reader,
        )
        self.assertEqual(KEY_ID, credentials.key_id)
        self.assertEqual(SECRET_KEY, credentials.secret_key)
        self.assertEqual(2, len(prompts))
        self.assertTrue(all("hidden" in prompt.lower() for prompt in prompts))
        self.assertNotIn(KEY_ID, repr(credentials))
        self.assertNotIn(SECRET_KEY, repr(credentials))

    def test_empty_hidden_entry_is_rejected(self) -> None:
        values = iter([KEY_ID, ""])
        with self.assertRaisesRegex(AlpacaPaperCredentialError, "required"):
            read_paper_credentials(
                lane=AlpacaPaperLane.CANARY_REALISTIC,
                reader=lambda _prompt: next(values),
            )

    def test_control_character_paste_is_rejected(self) -> None:
        values = iter(["\x16", "\x16"])
        with self.assertRaisesRegex(AlpacaPaperCredentialError, "control"):
            read_paper_credentials(
                lane=AlpacaPaperLane.CANARY_REALISTIC,
                reader=lambda _prompt: next(values),
            )

    def test_credentials_are_write_once_and_bound_to_paper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _repository(Path(directory) / "paper.bin")
            repository.save_new(AlpacaPaperCredentials(KEY_ID, SECRET_KEY))
            loaded = repository.load()
            self.assertEqual(KEY_ID, loaded.key_id)
            self.assertEqual(SECRET_KEY, loaded.secret_key)
            status = repository.status()
            self.assertEqual(ALPACA_PAPER_ENVIRONMENT, status["mode"])
            self.assertEqual(ALPACA_PAPER_BASE_URL, status["endpoint"])
            self.assertEqual("CANARY_REALISTIC", status["lane"])
            self.assertEqual("OFFICIAL_CANARY_REALISTIC", status["statisticsDomain"])
            self.assertFalse(status["liveEndpointReachable"])
            with self.assertRaisesRegex(AlpacaPaperCredentialError, "replacement"):
                repository.save_new(AlpacaPaperCredentials(KEY_ID, SECRET_KEY))

    def test_ciphertext_does_not_contain_synthetic_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.bin"
            repository = _repository(path)
            repository.save_new(AlpacaPaperCredentials(KEY_ID, SECRET_KEY))
            raw = path.read_bytes()
            self.assertNotIn(KEY_ID.encode(), raw)
            self.assertNotIn(SECRET_KEY.encode(), raw)

    def test_invalid_store_environment_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.bin"
            store = LocalSecretStore(
                path=path,
                protector=_XorProtector(),
                permission_hardener=lambda _path: None,
            )
            store.save(
                {
                    "schema_version": ALPACA_PAPER_CREDENTIAL_SCHEMA,
                    "environment": "LIVE",
                    "endpoint": ALPACA_LIVE_BASE_URL,
                    "key_id": KEY_ID,
                    "secret_key": SECRET_KEY,
                }
            )
            with self.assertRaisesRegex(AlpacaPaperCredentialError, "environment"):
                AlpacaPaperCredentialRepository(
                    lane=AlpacaPaperLane.CANARY_REALISTIC,
                    store=store,
                ).load()

    def test_onboarding_has_no_network_and_no_credential_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _repository(Path(directory) / "paper.bin")
            values = iter([KEY_ID, SECRET_KEY])
            with patch(
                "requests.Session",
                side_effect=AssertionError("network forbidden"),
            ):
                report = onboard_paper_credentials(
                    lane=AlpacaPaperLane.CANARY_REALISTIC,
                    repository=repository,
                    credential_reader=lambda _prompt: next(values),
                )
            rendered = json.dumps(report)
            self.assertNotIn(KEY_ID, rendered)
            self.assertNotIn(SECRET_KEY, rendered)
            self.assertFalse(report["networkRequested"])
            self.assertFalse(report["ordersRequested"])

    def test_replacement_requires_exact_confirmation_and_one_hidden_entry_each(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _repository(Path(directory) / "paper.bin")
            repository.save_new(AlpacaPaperCredentials(KEY_ID, SECRET_KEY))
            original = repository.store.path.read_bytes()
            with self.assertRaisesRegex(AlpacaPaperCredentialError, "exact"):
                repository.replace_existing(
                    AlpacaPaperCredentials("SYNTHETIC-NEW-KEY", "SYNTHETIC-NEW-SECRET"),
                    confirmation="replace",
                )
            self.assertEqual(original, repository.store.path.read_bytes())

            prompts: list[str] = []
            values = iter(["SYNTHETIC-NEW-KEY", "SYNTHETIC-NEW-SECRET"])

            def hidden_reader(prompt: str) -> str:
                prompts.append(prompt)
                return next(values)

            report = replace_canary_credentials(
                repository,
                confirmation_reader=lambda _prompt: (
                    REPLACE_CANARY_CREDENTIALS_CONFIRMATION
                ),
                credential_reader=hidden_reader,
            )
            self.assertEqual(2, len(prompts))
            self.assertTrue(report["credentialsReplaced"])
            self.assertFalse(report["networkRequested"])
            loaded = repository.load()
            self.assertEqual("SYNTHETIC-NEW-KEY", loaded.key_id)
            self.assertEqual("SYNTHETIC-NEW-SECRET", loaded.secret_key)

    def test_research_lane_credentials_cannot_be_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _repository(
                Path(directory) / "research.bin",
                AlpacaPaperLane.STRATEGY_RESEARCH,
            )
            repository.save_new(AlpacaPaperCredentials(KEY_ID, SECRET_KEY))
            with self.assertRaisesRegex(AlpacaPaperCredentialError, "research"):
                repository.replace_existing(
                    AlpacaPaperCredentials("SYNTHETIC-NEW-KEY", "SYNTHETIC-NEW-SECRET"),
                    confirmation=REPLACE_CANARY_CREDENTIALS_CONFIRMATION,
                )

    def test_exact_paper_endpoint_is_required(self) -> None:
        for endpoint in (
            ALPACA_LIVE_BASE_URL,
            "http://paper-api.alpaca.markets",
            f"{ALPACA_PAPER_BASE_URL}/",
            "https://example.com",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(
                AlpacaPaperEndpointError
            ):
                AlpacaPaperReadonlyTransport(base_url=endpoint)

    def test_account_canary_uses_one_exact_get_and_redacts_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _repository(Path(directory) / "paper.bin")
            repository.save_new(AlpacaPaperCredentials(KEY_ID, SECRET_KEY))
            session = _Session(
                _Response(_account_payload(), headers={"X-Request-ID": "synthetic-request"})
            )
            report = AlpacaPaperReadonlyCanary(
                lane=AlpacaPaperLane.CANARY_REALISTIC,
                credentials=repository,
                transport=AlpacaPaperReadonlyTransport(session=session),
            ).run()
            self.assertEqual(1, len(session.calls))
            url, kwargs = session.calls[0]
            self.assertEqual(f"{ALPACA_PAPER_BASE_URL}/v2/account", url)
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(KEY_ID, kwargs["headers"]["APCA-API-KEY-ID"])
            self.assertEqual(SECRET_KEY, kwargs["headers"]["APCA-API-SECRET-KEY"])
            self.assertTrue(report["paperAccountValidated"])
            self.assertTrue(report["accountUsable"])
            self.assertEqual("CANARY_REALISTIC", report["lane"])
            self.assertEqual("OFFICIAL_CANARY_REALISTIC", report["statisticsDomain"])
            self.assertEqual("100.00", report["cash"])
            self.assertEqual("200.00", report["buyingPower"])
            self.assertFalse(report["positionsRequested"])
            self.assertFalse(report["ordersRequested"])
            self.assertFalse(report["mutatingRequestAttempted"])
            rendered = json.dumps(report)
            self.assertNotIn(KEY_ID, rendered)
            self.assertNotIn(SECRET_KEY, rendered)
            self.assertNotIn("SYNTHETIC-ACCOUNT-ID", rendered)
            self.assertNotIn("SYNTHETIC-ACCOUNT-NUMBER", rendered)

    def test_redirect_is_rejected(self) -> None:
        session = _Session(_Response({}, status_code=302, redirect=True))
        with self.assertRaisesRegex(AlpacaPaperEndpointError, "redirect"):
            AlpacaPaperReadonlyTransport(session=session).get_account(
                AlpacaPaperCredentials(KEY_ID, SECRET_KEY)
            )

    def test_non_200_does_not_echo_credentials_or_response(self) -> None:
        response = _Response(
            {"message": f"bad {KEY_ID} {SECRET_KEY}"},
            status_code=401,
        )
        with self.assertRaises(AlpacaPaperResponseError) as observed:
            AlpacaPaperReadonlyTransport(session=_Session(response)).get_account(
                AlpacaPaperCredentials(KEY_ID, SECRET_KEY)
            )
        rendered = str(observed.exception)
        self.assertNotIn(KEY_ID, rendered)
        self.assertNotIn(SECRET_KEY, rendered)
        self.assertNotIn("message", rendered)

    def test_network_error_is_redacted(self) -> None:
        error = requests.ConnectionError(f"synthetic {KEY_ID} {SECRET_KEY}")
        with self.assertRaises(AlpacaPaperNetworkError) as observed:
            AlpacaPaperReadonlyTransport(session=_Session(error)).get_account(
                AlpacaPaperCredentials(KEY_ID, SECRET_KEY)
            )
        self.assertNotIn(KEY_ID, str(observed.exception))
        self.assertNotIn(SECRET_KEY, str(observed.exception))

    def test_account_parser_blocks_missing_or_invalid_authority_fields(self) -> None:
        invalid = (
            [],
            _account_payload(status=""),
            _account_payload(cash="NaN"),
            _account_payload(buying_power="Infinity"),
            _account_payload(account_blocked="false"),
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(
                AlpacaPaperResponseError
            ):
                parse_paper_account(payload)

    def test_blocked_or_nonactive_account_is_not_usable(self) -> None:
        for changes in (
            {"status": "SUBMITTED"},
            {"account_blocked": True},
            {"trading_blocked": True},
            {"trade_suspended_by_user": True},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(parse_paper_account(_account_payload(**changes)).usable)

    def test_cli_has_no_credential_arguments_and_status_is_sanitized(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch(
            "momentum_hunter.alpaca_paper_onboarding.DEFAULT_ALPACA_PAPER_SECRET_DIRECTORY",
            Path(directory),
        ), redirect_stdout(output):
            self.assertEqual(0, main(["status"]))
        rendered = output.getvalue()
        self.assertIn(ALPACA_PAPER_BASE_URL, rendered)
        self.assertIn('"credentialsStored": false', rendered)
        self.assertNotIn("key_id", rendered.lower())
        self.assertNotIn("secret_key", rendered.lower())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["onboard-canary", "--key", KEY_ID])

    def test_lanes_use_distinct_files_entropy_and_statistics_domains(self) -> None:
        canary = AlpacaPaperLane.CANARY_REALISTIC
        research = AlpacaPaperLane.STRATEGY_RESEARCH
        self.assertNotEqual(canary.credential_filename, research.credential_filename)
        self.assertNotEqual(canary.dpapi_entropy, research.dpapi_entropy)
        self.assertNotEqual(canary.statistics_domain, research.statistics_domain)

    def test_credential_payload_cannot_cross_paper_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalSecretStore(
                path=Path(directory) / "paper.bin",
                protector=_XorProtector(),
                permission_hardener=lambda _path: None,
            )
            AlpacaPaperCredentialRepository(
                lane=AlpacaPaperLane.CANARY_REALISTIC,
                store=store,
            ).save_new(AlpacaPaperCredentials(KEY_ID, SECRET_KEY))
            with self.assertRaisesRegex(AlpacaPaperCredentialError, "lane"):
                AlpacaPaperCredentialRepository(
                    lane=AlpacaPaperLane.STRATEGY_RESEARCH,
                    store=store,
                ).load()

    def test_canary_rejects_repository_from_other_lane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _repository(
                Path(directory) / "research.bin",
                AlpacaPaperLane.STRATEGY_RESEARCH,
            )
            with self.assertRaisesRegex(AlpacaPaperCredentialError, "another"):
                AlpacaPaperReadonlyCanary(
                    lane=AlpacaPaperLane.CANARY_REALISTIC,
                    credentials=repository,
                )

    def test_cli_does_not_enable_research_credential_onboarding(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["onboard-research"])

    def test_readonly_surface_contains_no_order_or_position_method(self) -> None:
        public = {
            name
            for name in dir(AlpacaPaperReadonlyTransport)
            if not name.startswith("_")
        }
        self.assertEqual({"get_account"}, public)

    def test_readonly_transport_has_no_mutating_http_call(self) -> None:
        tree = ast.parse(inspect.getsource(AlpacaPaperReadonlyTransport))
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(called_attributes.isdisjoint({"post", "put", "patch", "delete"}))
        source = inspect.getsource(AlpacaPaperReadonlyTransport).lower()
        self.assertNotIn("/orders", source)
        self.assertNotIn("/positions", source)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI proof runs on Windows only.")
    def test_alpaca_dpapi_domain_cannot_be_opened_by_schwab_default(self) -> None:
        alpaca = WindowsDpapiProtector(
            entropy=AlpacaPaperLane.CANARY_REALISTIC.dpapi_entropy,
            description="Momentum Hunter Alpaca Paper CANARY_REALISTIC credentials",
        )
        research = WindowsDpapiProtector(
            entropy=AlpacaPaperLane.STRATEGY_RESEARCH.dpapi_entropy,
            description="Momentum Hunter Alpaca Paper STRATEGY_RESEARCH credentials",
        )
        schwab = WindowsDpapiProtector()
        protected = alpaca.protect(b"SYNTHETIC-ALPACA-PAPER-VALUE")
        self.assertEqual(b"SYNTHETIC-ALPACA-PAPER-VALUE", alpaca.unprotect(protected))
        with self.assertRaises(OSError):
            research.unprotect(protected)
        with self.assertRaises(OSError):
            schwab.unprotect(protected)


if __name__ == "__main__":
    unittest.main()
