from __future__ import annotations

import ast
import io
import socket
import ssl
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from http.client import HTTPSConnection
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

import momentum_hunter.schwab_oauth_listener as listener_module
from momentum_hunter.schwab_oauth_listener import (
    REGISTERED_CALLBACK_HOST,
    REGISTERED_CALLBACK_PATH,
    REGISTERED_CALLBACK_PORT,
    REGISTERED_CALLBACK_URL,
    LoopbackListenerConfig,
    OAuthCallbackRejectedError,
    OneShotOAuthCallbackListener,
)
from momentum_hunter.schwab_setup import (
    CallbackTimeoutError,
    OAuthStateError,
    SchwabSetupError,
    generate_oauth_state,
)


# Public test-only material. It is never used outside a temporary test directory.
SYNTHETIC_CERTIFICATE = """-----BEGIN CERTIFICATE-----
MIICyDCCAbCgAwIBAgIIbXhvDaDCl/kwDQYJKoZIhvcNAQELBQAwFDESMBAGA1UEAxMJMTI3LjAu
MC4xMB4XDTI2MDcyMzIzNTYzMloXDTM2MDcyNDIzNTYzMlowFDESMBAGA1UEAxMJMTI3LjAuMC4x
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwQ2KkxpgycNZColdv3TR3rNCrPlGqiU9
K+aAfNIx3nznMFmqduyTn9QUZJDYdU2FfoBGVu/KZ2yvpt3iLP45Rt7XNilEl2/UZ2APyO22pYE9
eOtcPeDORJnr1SS63Wh7+rWtxb3uVP/QkAuCKsdOg3fZ2ofjSVoGPl4lGchC0gHTTKPw9in42+u1
mKc2fcInCpZvuaGMwdF/C5WVk/xHwdeMiu/POJ7S85ic5/Q2tNHCg7KK+t6jRGgCgr94GUDljii+
OIAP1L6Sh1e5rMDTd+4iNSHnxMMQTva0Nfnle7NFtYFoH+jZ3mnthaurPIWTccdD1pPwn0pmyken
dHVXIQIDAQABox4wHDAaBgNVHREEEzARhwR/AAABgglsb2NhbGhvc3QwDQYJKoZIhvcNAQELBQAD
ggEBALdC6gkocHoYwm18Z4rxXV0s4MeNSVtwQgL7ilKaqeRen5C0s6NaJoWvbYLdamZoy4OBmrKE
P0eyY7ufE0cI4fWrV/q3MOpeRiNIrwezvxebmcUALx73PvJNDPdbvSdpxn868e/rd7Lfb5nhNuNY
m9VTwwjxK7La2t/ch6RgTihMgqmO4W2/F296ZzZTgLywKr6eotedxJnvIF35ZEf2YB/iQhNOpwgs
/oFz98k2rnqlrmf20507fNXqr3cSl3tP6C6udfWD8mZbg/Z4QUe2+6DhO0yW2T3a1GVimnwi+83D
IwDqW4Cg5qaGF6Dbf7mGpGgZalDYfu/mmC2T3zxbuBM=
-----END CERTIFICATE-----
"""

SYNTHETIC_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDBDYqTGmDJw1kKiV2/dNHes0Ks
+UaqJT0r5oB80jHefOcwWap27JOf1BRkkNh1TYV+gEZW78pnbK+m3eIs/jlG3tc2KUSXb9RnYA/I
7balgT1461w94M5EmevVJLrdaHv6ta3Fve5U/9CQC4Iqx06Dd9nah+NJWgY+XiUZyELSAdNMo/D2
Kfjb67WYpzZ9wicKlm+5oYzB0X8LlZWT/EfB14yK7884ntLzmJzn9Da00cKDsor63qNEaAKCv3gZ
QOWOKL44gA/UvpKHV7mswNN37iI1IefEwxBO9rQ1+eV7s0W1gWgf6Nneae2Fq6s8hZNxx0PWk/Cf
SmbKR6d0dVchAgMBAAECggEABRucnQPHp875XiQATP6ERwYrL3RxADN4CN9SavsMwrw/SbI1pmvg
BAySdY63i3L/ozc1pTs2+cGQbDPWtiYL0eo3e4FgBTm6Pvn1sPVJLdvbioV/rUtzabFA4iTUpOMM
1LdV37OEyM7z77u+N++KDkRviS6rPteY7rGC/cmkqvXBoxFzxuExdhfFtjcPlpGhaCbV3/+zXBO4
Qwsi34m2mXGIrwpBjVNFCEwewdNCFJfZWefJdCpIanYw67l62X+Hz90yBk+ky0yK6bMzEBQruV8x
QTE+YSSNIZEz+5JnJMZnTcnl3jydymdPT2mdBMLv/4R4DizoUVdDS+FHVwHGeQKBgQDjfSSslf5W
HaiZT/Ut1vAraWTmYSSLaGg6XPP+tkdB4jH7fM6WsFffQ4MWm/xeC1RjBXedzOVqr3WD0eepU/6l
AgNcDu4jpAKszTddOi0KNb6lPvIV3Bci1Y5OerVrtClpHe9KAMIMmE2fdfDvpiMV5YmPeW1RbtYu
GdJ2TSv+UwKBgQDZP4oRPqle76+A+SdJE0zRu7tslMlHqBbWbvEHj1+rWZLyHVhZXoXKtYYplvb5
dYhOZ1OHUXHmrovU7CIhmOl6NvWQ41gufLdv4MpTGv60EQkCqaNViu7p6dtTA9jkMsnsgiJCtyUG
s35gjo9Dpu0n2h+mZBhgQocGUxE11eweOwKBgA3ydDcokwlQlC+iGVQQI3Vl5svBFO5/HjTF0ifB
oSjG522Vv0y5zwlfKEBQm+5gH3JauXSxRTd/PmMwkVVuUuRm9THFsI/61Dcn9cb/dBd2KBQVgd4Z
Oknmce0Z1NmfmBJbxXnyBfOjus6V+omW0/vZsM9dEHi3pOX6q06ZeKMFAoGAIwj9MiTB2b6bthf4
Pu+u3tAAvNUN1NGFxVUk58w2aILMkOEso1T8DKHTnhdrgvVyYvqE3PjEfqg9grwGERcA6CW+2nvf
d7fDOXauClL7Knzo0BYdcikyuGRva2bebobGS6786XdxsC/4PIghEI72BgxGOGZCDBwOfHWe++ig
6IsCgYEAxARLLSxzqQkozd0GxmyWT0QGodzHeCoP3ssrczLxWzoCemQmfGKozYKzXNg/jvac9cZB
szOOBqgZ/fbtqFfmhEXwzgWJyV85aUhGwfWoaEpJ6kGzf1dJ2tXhwQPN+6xUEpQBRfVZa8h6MMgr
GiKGkg4ccWWu4UjFjyTBKtV40GY=
-----END PRIVATE KEY-----
"""


def tcp_port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex((REGISTERED_CALLBACK_HOST, port)) == 0


class SchwabOAuthLoopbackListenerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        directory = Path(self.temporary_directory.name)
        self.certificate_file = directory / "synthetic-loopback-cert.pem"
        self.private_key_file = directory / "synthetic-loopback-key.pem"
        self.certificate_file.write_text(SYNTHETIC_CERTIFICATE, encoding="ascii")
        self.private_key_file.write_text(SYNTHETIC_PRIVATE_KEY, encoding="ascii")
        self.listeners: list[OneShotOAuthCallbackListener] = []
        self.client_context = ssl.create_default_context(cafile=str(self.certificate_file))
        self.opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=self.client_context),
        )

    def tearDown(self) -> None:
        for listener in self.listeners:
            listener.close()
        self.temporary_directory.cleanup()

    def new_listener(
        self,
        *,
        timeout_seconds: float = 1.0,
        use_registered_port: bool = False,
    ) -> OneShotOAuthCallbackListener:
        listener = OneShotOAuthCallbackListener(
            LoopbackListenerConfig(
                certificate_file=self.certificate_file,
                private_key_file=self.private_key_file,
                port=REGISTERED_CALLBACK_PORT if use_registered_port else 0,
                timeout_seconds=timeout_seconds,
                test_only_allow_ephemeral_port=not use_registered_port,
            )
        )
        self.listeners.append(listener)
        return listener

    def get(self, url: str) -> tuple[int, bytes]:
        with self.opener.open(Request(url, method="GET"), timeout=2.0) as response:
            return response.status, response.read()

    def test_registered_https_callback_opens_once_then_closes(self) -> None:
        self.assertFalse(tcp_port_is_open(REGISTERED_CALLBACK_PORT))
        listener = self.new_listener(use_registered_port=True)
        state = generate_oauth_state()

        callback_url = listener.start(expected_state=state)

        self.assertEqual(REGISTERED_CALLBACK_URL, callback_url)
        self.assertTrue(tcp_port_is_open(REGISTERED_CALLBACK_PORT))
        status, body = self.get(f"{callback_url}?code=SYNTHETIC-CODE&state={state}")
        result = listener.wait(timeout_seconds=2.0)

        self.assertEqual(200, status)
        self.assertEqual("SYNTHETIC-CODE", result.authorization_code)
        self.assertNotIn(b"SYNTHETIC-CODE", body)
        self.assertNotIn(state.encode("ascii"), body)
        self.assertFalse(tcp_port_is_open(REGISTERED_CALLBACK_PORT))
        with self.assertRaises((URLError, OSError)):
            self.get(f"{callback_url}?code=SECOND-CODE&state={state}")

    def test_wrong_path_does_not_consume_the_registered_callback(self) -> None:
        listener = self.new_listener()
        state = generate_oauth_state()
        callback_url = listener.start(expected_state=state)

        with self.assertRaises(HTTPError) as rejected:
            self.get(callback_url.replace(REGISTERED_CALLBACK_PATH, "/wrong"))
        self.assertEqual(404, rejected.exception.code)
        self.assertTrue(listener.is_running)

        status, _body = self.get(f"{callback_url}?code=SYNTHETIC-CODE&state={state}")
        result = listener.wait(timeout_seconds=2.0)
        self.assertEqual(200, status)
        self.assertEqual("SYNTHETIC-CODE", result.authorization_code)
        self.assertFalse(tcp_port_is_open(listener.bound_port))

    def test_keep_alive_request_still_closes_immediately_after_callback(self) -> None:
        listener = self.new_listener(timeout_seconds=2.0)
        state = generate_oauth_state()
        callback_url = listener.start(expected_state=state)
        parsed = urlsplit(callback_url)
        connection = HTTPSConnection(
            parsed.hostname,
            parsed.port,
            context=self.client_context,
            timeout=2.0,
        )
        started_at = time.monotonic()
        try:
            connection.request(
                "GET",
                f"{parsed.path}?code=SYNTHETIC-CODE&state={state}",
                headers={"Connection": "keep-alive"},
            )
            response = connection.getresponse()
            response.read()
            result = listener.wait(timeout_seconds=0.5)
        finally:
            connection.close()
        self.assertEqual(200, response.status)
        self.assertEqual("SYNTHETIC-CODE", result.authorization_code)
        self.assertLess(time.monotonic() - started_at, 0.5)
        self.assertNotIn("Python", response.getheader("Server", ""))
        self.assertFalse(tcp_port_is_open(listener.bound_port))

    def test_invalid_terminal_callbacks_are_rejected_and_close(self) -> None:
        cases = (
            ("missing code", lambda state: f"?state={state}", SchwabSetupError),
            (
                "duplicate code",
                lambda state: f"?code=FIRST&code=SECOND&state={state}",
                SchwabSetupError,
            ),
            (
                "duplicate state",
                lambda state: f"?code=VALUE&state={state}&state={state}",
                SchwabSetupError,
            ),
            ("mismatched state", lambda _state: "?code=VALUE&state=wrong", OAuthStateError),
            (
                "provider error",
                lambda state: f"?error=access_denied&state={state}",
                OAuthCallbackRejectedError,
            ),
        )
        for label, query_builder, expected_error in cases:
            with self.subTest(label=label):
                listener = self.new_listener()
                state = generate_oauth_state()
                callback_url = listener.start(expected_state=state)
                with self.assertRaises(HTTPError) as rejected:
                    self.get(f"{callback_url}{query_builder(state)}")
                response_body = rejected.exception.read()
                self.assertEqual(400, rejected.exception.code)
                self.assertNotIn(state.encode("ascii"), response_body)
                self.assertNotIn(b"VALUE", response_body)
                with self.assertRaises(expected_error):
                    listener.wait(timeout_seconds=2.0)
                self.assertFalse(tcp_port_is_open(listener.bound_port))

    def test_timeout_closes_listener_without_callback(self) -> None:
        listener = self.new_listener(timeout_seconds=0.1)
        listener.start(expected_state=generate_oauth_state())
        port = listener.bound_port
        self.assertTrue(tcp_port_is_open(port))

        with self.assertRaises(CallbackTimeoutError):
            listener.wait(timeout_seconds=2.0)

        self.assertFalse(tcp_port_is_open(port))

    def test_wrong_method_is_terminal_and_does_not_expose_callback_values(self) -> None:
        listener = self.new_listener()
        state = generate_oauth_state()
        callback_url = listener.start(expected_state=state)
        request = Request(
            f"{callback_url}?code=SYNTHETIC-CODE&state={state}",
            method="POST",
        )
        with self.assertRaises(HTTPError) as rejected:
            self.opener.open(request, timeout=2.0)
        body = rejected.exception.read()
        self.assertEqual(405, rejected.exception.code)
        self.assertNotIn(b"SYNTHETIC-CODE", body)
        self.assertNotIn(state.encode("ascii"), body)
        with self.assertRaisesRegex(SchwabSetupError, "unsupported HTTP method"):
            listener.wait(timeout_seconds=2.0)
        self.assertFalse(tcp_port_is_open(listener.bound_port))

    def test_host_header_must_match_the_bound_callback_exactly(self) -> None:
        listener = self.new_listener()
        state = generate_oauth_state()
        callback_url = listener.start(expected_state=state)
        request = Request(
            f"{callback_url}?code=SYNTHETIC-CODE&state={state}",
            method="GET",
        )
        request.add_unredirected_header("Host", f"localhost:{listener.bound_port}")
        with self.assertRaises(HTTPError) as rejected:
            self.opener.open(request, timeout=2.0)
        self.assertEqual(400, rejected.exception.code)
        with self.assertRaisesRegex(SchwabSetupError, "host"):
            listener.wait(timeout_seconds=2.0)
        self.assertFalse(tcp_port_is_open(listener.bound_port))

    def test_incomplete_tls_handshake_cannot_hold_listener_open(self) -> None:
        listener = self.new_listener(timeout_seconds=0.15)
        listener.start(expected_state=generate_oauth_state())
        port = listener.bound_port
        stalled_client = socket.create_connection((REGISTERED_CALLBACK_HOST, port), timeout=0.5)
        try:
            with self.assertRaises(CallbackTimeoutError):
                listener.wait(timeout_seconds=2.0)
        finally:
            stalled_client.close()
        self.assertFalse(tcp_port_is_open(port))

    def test_unexpected_handler_error_fails_closed_without_stderr_leak(self) -> None:
        listener = self.new_listener()
        state = generate_oauth_state()
        callback_url = listener.start(expected_state=state)

        def fail_handler(_handler: object) -> None:
            raise RuntimeError("SYNTHETIC-CODE-MUST-NOT-LOG")

        listener._handle_get = fail_handler  # type: ignore[method-assign]
        captured_stderr = io.StringIO()
        with redirect_stderr(captured_stderr):
            with self.assertRaises((URLError, OSError)):
                self.get(f"{callback_url}?code=SYNTHETIC-CODE&state={state}")
            with self.assertRaisesRegex(SchwabSetupError, "malformed request"):
                listener.wait(timeout_seconds=2.0)
        self.assertNotIn("SYNTHETIC-CODE", captured_stderr.getvalue())
        self.assertNotIn(state, captured_stderr.getvalue())
        self.assertFalse(tcp_port_is_open(listener.bound_port))

    def test_configuration_enforces_registered_loopback_shape(self) -> None:
        config = LoopbackListenerConfig(
            certificate_file=self.certificate_file,
            private_key_file=self.private_key_file,
            private_key_password="SYNTHETIC-KEY-PASSWORD",
        )
        self.assertEqual(REGISTERED_CALLBACK_HOST, config.host)
        self.assertEqual(REGISTERED_CALLBACK_PORT, config.port)
        self.assertEqual(REGISTERED_CALLBACK_PATH, config.path)
        self.assertNotIn("SYNTHETIC-KEY-PASSWORD", repr(config))
        with self.assertRaisesRegex(SchwabSetupError, "127.0.0.1"):
            LoopbackListenerConfig(
                certificate_file=self.certificate_file,
                private_key_file=self.private_key_file,
                host="0.0.0.0",
            )
        with self.assertRaisesRegex(SchwabSetupError, "path"):
            LoopbackListenerConfig(
                certificate_file=self.certificate_file,
                private_key_file=self.private_key_file,
                path="/callback",
            )
        with self.assertRaisesRegex(SchwabSetupError, "port"):
            LoopbackListenerConfig(
                certificate_file=self.certificate_file,
                private_key_file=self.private_key_file,
                port=8183,
            )

    def test_listener_has_no_provider_broker_or_order_client_imports(self) -> None:
        source = Path(listener_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        momentum_hunter_imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("momentum_hunter")
        }
        self.assertEqual({"momentum_hunter.schwab_setup"}, momentum_hunter_imports)
        for forbidden in (
            "requests",
            "httpx",
            "submit_order",
            "replace_order",
            "cancel_order",
            "account_hash",
            "client_secret",
        ):
            self.assertNotIn(forbidden, source)

    def test_listener_refuses_missing_or_invalid_certificate_material(self) -> None:
        missing = Path(self.temporary_directory.name) / "missing.pem"
        listener = OneShotOAuthCallbackListener(
            LoopbackListenerConfig(
                certificate_file=missing,
                private_key_file=missing,
                port=0,
                test_only_allow_ephemeral_port=True,
            )
        )
        with self.assertRaisesRegex(SchwabSetupError, "certificate"):
            listener.start(expected_state=generate_oauth_state())
        self.assertFalse(listener.is_running)

        invalid = Path(self.temporary_directory.name) / "invalid.pem"
        invalid.write_text("not a certificate or key", encoding="ascii")
        listener = OneShotOAuthCallbackListener(
            LoopbackListenerConfig(
                certificate_file=invalid,
                private_key_file=invalid,
                port=0,
                test_only_allow_ephemeral_port=True,
            )
        )
        with self.assertRaisesRegex(SchwabSetupError, "could not be loaded"):
            listener.start(expected_state=generate_oauth_state())
        self.assertFalse(listener.is_running)
