from __future__ import annotations

"""One-use HTTPS loopback receiver for credential-free Schwab OAuth proof."""

import ssl
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from momentum_hunter.schwab_setup import (
    CallbackTimeoutError,
    OAuthCallback,
    SchwabSetupError,
    parse_oauth_callback,
)


REGISTERED_CALLBACK_HOST = "127.0.0.1"
REGISTERED_CALLBACK_PORT = 8182
REGISTERED_CALLBACK_PATH = "/oauth/callback"
REGISTERED_CALLBACK_URL = (
    f"https://{REGISTERED_CALLBACK_HOST}:{REGISTERED_CALLBACK_PORT}{REGISTERED_CALLBACK_PATH}"
)

_SUCCESS_BODY = (
    b"Momentum Hunter received the local authorization response. "
    b"You may close this browser tab."
)
_REJECTED_BODY = (
    b"Momentum Hunter rejected the local authorization response. "
    b"Return to the workstation."
)
_NOT_FOUND_BODY = b"This local authorization path is not available."
_METHOD_BODY = b"This local authorization endpoint accepts GET only."


class OAuthCallbackRejectedError(SchwabSetupError):
    pass


@dataclass(frozen=True)
class LoopbackListenerConfig:
    certificate_file: Path
    private_key_file: Path
    host: str = REGISTERED_CALLBACK_HOST
    port: int = REGISTERED_CALLBACK_PORT
    path: str = REGISTERED_CALLBACK_PATH
    timeout_seconds: float = 120.0
    test_only_allow_ephemeral_port: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "certificate_file", Path(self.certificate_file))
        object.__setattr__(self, "private_key_file", Path(self.private_key_file))
        if self.host != REGISTERED_CALLBACK_HOST:
            raise SchwabSetupError("The OAuth listener must bind only to 127.0.0.1.")
        if self.path != REGISTERED_CALLBACK_PATH:
            raise SchwabSetupError("The OAuth listener path must match the registered callback exactly.")
        if self.port != REGISTERED_CALLBACK_PORT:
            if not (self.test_only_allow_ephemeral_port and self.port == 0):
                raise SchwabSetupError("The OAuth listener port must match the registered callback exactly.")
        if self.timeout_seconds <= 0:
            raise CallbackTimeoutError("OAuth callback timeout must be positive.")


class _LoopbackHttpServer(HTTPServer):
    allow_reuse_address = False
    request_queue_size = 1

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        tls_context: ssl.SSLContext,
        connection_timeout_seconds: float,
        request_error_callback: Callable[[], None],
    ) -> None:
        self._tls_context = tls_context
        self._connection_timeout_seconds = connection_timeout_seconds
        self._request_error_callback = request_error_callback
        super().__init__(server_address, handler_class)

    def get_request(self) -> tuple[ssl.SSLSocket, tuple[str, int]]:
        raw_socket, address = self.socket.accept()
        raw_socket.settimeout(self._connection_timeout_seconds)
        try:
            secure_socket = self._tls_context.wrap_socket(
                raw_socket,
                server_side=True,
            )
        except (OSError, ssl.SSLError):
            raw_socket.close()
            raise
        secure_socket.settimeout(self._connection_timeout_seconds)
        return secure_socket, address

    def handle_error(
        self,
        _request: object,
        _client_address: tuple[str, int],
    ) -> None:
        self._request_error_callback()


class OneShotOAuthCallbackListener:
    """Accept exactly one terminal OAuth callback over loopback-only TLS."""

    def __init__(self, config: LoopbackListenerConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._terminal = threading.Event()
        self._closed = threading.Event()
        self._stop_requested = threading.Event()
        self._server: _LoopbackHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._expected_state = ""
        self._callback_url = ""
        self._result: OAuthCallback | None = None
        self._error: SchwabSetupError | None = None
        self._started = False

    @property
    def callback_url(self) -> str:
        if not self._callback_url:
            raise SchwabSetupError("The OAuth callback listener has not started.")
        return self._callback_url

    @property
    def is_running(self) -> bool:
        return self._started and not self._closed.is_set()

    @property
    def bound_port(self) -> int:
        parsed = urlsplit(self.callback_url)
        if parsed.port is None:
            raise SchwabSetupError("The OAuth callback listener did not expose a bound port.")
        return parsed.port

    def start(self, *, expected_state: str) -> str:
        if not expected_state:
            raise SchwabSetupError("A non-empty OAuth state is required before opening the listener.")
        tls_context = self._build_tls_context()
        with self._lock:
            if self._started:
                raise SchwabSetupError("The OAuth callback listener is one-use and has already started.")
            self._started = True
            self._expected_state = expected_state

        handler_class = self._build_handler_class()
        server: _LoopbackHttpServer | None = None
        try:
            server = _LoopbackHttpServer(
                (self.config.host, self.config.port),
                handler_class,
                tls_context=tls_context,
                connection_timeout_seconds=min(1.0, self.config.timeout_seconds),
                request_error_callback=self._record_request_error,
            )
        except (OSError, ssl.SSLError) as exc:
            if server is not None:
                server.server_close()
            self._closed.set()
            raise SchwabSetupError("The local HTTPS OAuth listener could not start.") from exc

        actual_port = int(server.server_address[1])
        self._callback_url = f"https://{self.config.host}:{actual_port}{self.config.path}"
        self._server = server
        self._thread = threading.Thread(
            target=self._serve,
            name="SchwabOAuthLoopback",
            daemon=True,
        )
        self._thread.start()
        return self._callback_url

    def wait(self, *, timeout_seconds: float | None = None) -> OAuthCallback:
        if not self._started:
            raise SchwabSetupError("The OAuth callback listener has not started.")
        wait_seconds = (
            self.config.timeout_seconds + 1.0
            if timeout_seconds is None
            else timeout_seconds
        )
        if wait_seconds <= 0 or not self._closed.wait(wait_seconds):
            raise CallbackTimeoutError("The local OAuth listener did not shut down in time.")
        if self._thread is not None:
            self._thread.join(timeout=0.2)
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise SchwabSetupError("The OAuth callback listener closed without a result.")
        return self._result

    def close(self) -> None:
        if not self._started or self._closed.is_set():
            return
        self._record_terminal(
            error=SchwabSetupError("The local OAuth listener was closed before authorization completed.")
        )
        self._stop_requested.set()
        self._closed.wait(1.0)
        if self._thread is not None:
            self._thread.join(timeout=0.2)

    def _build_tls_context(self) -> ssl.SSLContext:
        if not self.config.certificate_file.is_file() or not self.config.private_key_file.is_file():
            raise SchwabSetupError(
                "The local HTTPS OAuth listener requires an explicit certificate and private key."
            )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            context.load_cert_chain(
                certfile=str(self.config.certificate_file),
                keyfile=str(self.config.private_key_file),
            )
        except (OSError, ssl.SSLError) as exc:
            raise SchwabSetupError(
                "The local HTTPS OAuth certificate or private key could not be loaded."
            ) from exc
        return context

    def _build_handler_class(self) -> type[BaseHTTPRequestHandler]:
        listener = self

        class OAuthCallbackHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "MomentumHunterLoopback"
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                listener._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                listener._handle_unsupported_method(self)

            def log_message(self, _format: str, *args: object) -> None:
                _ = args

        return OAuthCallbackHandler

    def _serve(self) -> None:
        server = self._server
        if server is None:
            self._closed.set()
            return
        deadline = time.monotonic() + self.config.timeout_seconds
        try:
            while not self._terminal.is_set() and not self._stop_requested.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._record_terminal(
                        error=CallbackTimeoutError(
                            "OAuth callback did not arrive before the local listener timeout."
                        )
                    )
                    break
                server.timeout = min(0.05, remaining)
                server.handle_request()
        except Exception:
            self._record_terminal(
                error=SchwabSetupError("The local HTTPS OAuth listener failed safely.")
            )
        finally:
            server.server_close()
            self._closed.set()

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        target = urlsplit(handler.path)
        if target.scheme or target.netloc or target.path != self.config.path:
            self._write_response(handler, 404, _NOT_FOUND_BODY)
            return

        expected_host = f"{self.config.host}:{self.bound_port}"
        if handler.headers.get("Host", "") != expected_host:
            self._record_terminal(
                error=SchwabSetupError(
                    "OAuth callback host did not match the registered loopback callback."
                )
            )
            self._write_response(handler, 400, _REJECTED_BODY)
            return

        if self._terminal.is_set():
            self._write_response(handler, 409, _REJECTED_BODY)
            return

        try:
            callback = parse_oauth_callback(
                f"https://{expected_host}{handler.path}",
                expected_state=self._expected_state,
            )
            if callback.error:
                raise OAuthCallbackRejectedError(
                    "Schwab authorization was not completed; the callback was rejected."
                )
        except SchwabSetupError as exc:
            self._record_terminal(error=exc)
            self._write_response(handler, 400, _REJECTED_BODY)
            return

        if not self._record_terminal(result=callback):
            self._write_response(handler, 409, _REJECTED_BODY)
            return
        self._write_response(handler, 200, _SUCCESS_BODY)

    def _handle_unsupported_method(self, handler: BaseHTTPRequestHandler) -> None:
        target = urlsplit(handler.path)
        if target.scheme or target.netloc or target.path != self.config.path:
            self._write_response(handler, 404, _NOT_FOUND_BODY)
            return
        self._record_terminal(
            error=SchwabSetupError("The OAuth callback used an unsupported HTTP method.")
        )
        self._write_response(handler, 405, _METHOD_BODY)

    def _record_request_error(self) -> None:
        self._record_terminal(
            error=SchwabSetupError("The local HTTPS OAuth listener rejected a malformed request.")
        )

    def _record_terminal(
        self,
        *,
        result: OAuthCallback | None = None,
        error: SchwabSetupError | None = None,
    ) -> bool:
        with self._lock:
            if self._terminal.is_set():
                return False
            self._result = result
            self._error = error
            self._terminal.set()
            return True

    @staticmethod
    def _write_response(
        handler: BaseHTTPRequestHandler,
        status: int,
        body: bytes,
    ) -> None:
        try:
            handler.close_connection = True
            handler.send_response(status)
            handler.send_header("Content-Type", "text/plain; charset=utf-8")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Pragma", "no-cache")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.write(body)
            handler.wfile.flush()
        except OSError:
            return
