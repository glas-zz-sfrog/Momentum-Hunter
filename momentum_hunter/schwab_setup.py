from __future__ import annotations

"""Credential-free secure setup primitives for future Schwab OAuth onboarding.

The registered callback is known, but the CLI cannot contact Schwab and intentionally
refuses credential onboarding, token exchange, account access, or order activity.
"""

import argparse
import base64
import ctypes
import getpass
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse


SETUP_NOTICE = (
    "Enter Schwab application credentials only.\n"
    "Never enter your Schwab username, password, or MFA code here."
)
DEFAULT_SECRET_PATH = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "MomentumHunter"
    / "Schwab"
    / "secrets.bin"
)
DPAPI_ENTROPY = b"MomentumHunter.Schwab.Setup.v1"


class SchwabSetupError(RuntimeError):
    pass


class OAuthStateError(SchwabSetupError):
    pass


class CallbackTimeoutError(SchwabSetupError):
    pass


@dataclass(frozen=True, repr=False)
class SchwabApplicationCredentials:
    application_id: str
    application_secret: str

    def __repr__(self) -> str:
        return "SchwabApplicationCredentials(application_id='[redacted]', application_secret='[redacted]')"


@dataclass(frozen=True, repr=False)
class OAuthCallback:
    authorization_code: str
    state: str
    error: str = ""

    def __repr__(self) -> str:
        return (
            "OAuthCallback(authorization_code='[redacted]', "
            "state='[redacted]', error='[redacted]')"
        )


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDpapiProtector:
    """Windows-current-user encryption without third-party packages."""

    def __init__(
        self,
        *,
        entropy: bytes = DPAPI_ENTROPY,
        description: str = "Momentum Hunter Schwab setup",
    ) -> None:
        if not entropy or not isinstance(entropy, bytes):
            raise SchwabSetupError("Windows DPAPI entropy must be nonempty bytes.")
        if not description or not isinstance(description, str):
            raise SchwabSetupError("Windows DPAPI description must be nonempty text.")
        self._entropy = entropy
        self._description = description

    def protect(self, plaintext: bytes) -> bytes:
        self._require_windows()
        input_blob, input_buffer = self._blob(plaintext)
        entropy_blob, entropy_buffer = self._blob(self._entropy)
        output_blob = _DataBlob()
        result = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            self._description,
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
        _ = (input_buffer, entropy_buffer)
        if not result:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)

    def unprotect(self, ciphertext: bytes) -> bytes:
        self._require_windows()
        input_blob, input_buffer = self._blob(ciphertext)
        entropy_blob, entropy_buffer = self._blob(self._entropy)
        output_blob = _DataBlob()
        result = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
        _ = (input_buffer, entropy_buffer)
        if not result:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, object]:
        buffer = (ctypes.c_byte * len(data)).from_buffer_copy(data)
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise SchwabSetupError("Windows DPAPI is available only on Windows.")


class LocalSecretStore:
    def __init__(
        self,
        *,
        path: Path = DEFAULT_SECRET_PATH,
        protector: WindowsDpapiProtector | None = None,
        permission_hardener: Callable[[Path], None] | None = None,
    ) -> None:
        self.path = path
        self.protector = protector or WindowsDpapiProtector()
        self.permission_hardener = permission_hardener or harden_current_user_secret_file

    def save(self, payload: dict[str, str]) -> Path:
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in payload.items()
        ):
            raise SchwabSetupError("The local Schwab secret payload has an invalid shape.")
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        protected = self.protector.protect(encoded)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        replaced = False
        try:
            temporary.write_bytes(base64.b64encode(protected))
            self.permission_hardener(temporary)
            temporary.replace(self.path)
            replaced = True
            self.permission_hardener(self.path)
        except Exception:
            temporary.unlink(missing_ok=True)
            if replaced:
                self.path.unlink(missing_ok=True)
            raise
        return self.path

    def save_fake_or_future_values(self, payload: dict[str, str]) -> Path:
        return self.save(payload)

    def load(self) -> dict[str, str]:
        try:
            protected = base64.b64decode(self.path.read_bytes(), validate=True)
            payload = json.loads(self.protector.unprotect(protected))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SchwabSetupError("The local Schwab secret store cannot be loaded.") from exc
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in payload.items()
        ):
            raise SchwabSetupError("The local Schwab secret store has an invalid shape.")
        return payload

    def delete(self) -> bool:
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


def harden_current_user_secret_file(path: Path) -> None:
    """Restrict a DPAPI ciphertext file to the current Windows user."""

    if os.name != "nt":
        return
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    whoami = system32 / "whoami.exe"
    icacls = system32 / "icacls.exe"
    if not whoami.is_file() or not icacls.is_file():
        raise SchwabSetupError("Windows account-permission tools are required to protect the local Schwab secret file.")
    try:
        identity_result = subprocess.run(
            [str(whoami)],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        identity = identity_result.stdout.strip()
        if identity_result.returncode != 0 or not identity:
            raise SchwabSetupError("The current Windows identity could not be verified.")
        resolved = str(Path(path).resolve())
        commands = (
            [str(icacls), resolved, "/inheritance:r", "/grant:r", f"{identity}:(F)"],
            [str(icacls), resolved, "/setowner", identity],
        )
        for command in commands:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                raise SchwabSetupError("The local Schwab secret file permissions could not be protected.")
        verification = subprocess.run(
            [str(icacls), resolved],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SchwabSetupError("The local Schwab secret file permissions could not be protected.") from exc
    if verification.returncode != 0:
        raise SchwabSetupError("The local Schwab secret file permissions could not be verified.")
    acl_text = verification.stdout.replace(resolved, "", 1)
    entries = [
        line.strip()
        for line in acl_text.splitlines()
        if ":(" in line
    ]
    if (
        len(entries) != 1
        or not entries[0].lower().startswith(identity.lower() + ":")
        or not entries[0].endswith("(F)")
    ):
        raise SchwabSetupError("The local Schwab secret file permissions could not be verified.")


def read_application_credentials(
    *,
    application_id_reader: Callable[[str], str] | None = None,
    application_secret_reader: Callable[[str], str] | None = None,
) -> SchwabApplicationCredentials:
    masked_id_reader = application_id_reader or getpass.getpass
    masked_secret_reader = application_secret_reader or getpass.getpass
    application_id = masked_id_reader("Schwab application ID / App Key (hidden): ").strip()
    application_secret = masked_secret_reader("Schwab application secret (hidden): ").strip()
    if not application_id or not application_secret:
        raise SchwabSetupError("Both Schwab application credential fields are required.")
    return SchwabApplicationCredentials(application_id, application_secret)


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def validate_oauth_state(expected: str, observed: str) -> None:
    if not expected or not observed or not hmac.compare_digest(expected, observed):
        raise OAuthStateError("OAuth state mismatch; authorization is rejected.")


def parse_oauth_callback(callback_url: str, *, expected_state: str) -> OAuthCallback:
    parsed = urlparse(callback_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SchwabSetupError("OAuth callback must use an HTTP or HTTPS loopback URL.")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SchwabSetupError("OAuth callback must terminate on the local computer.")
    query = parse_qs(parsed.query, keep_blank_values=True)
    state = unique_query_value(query, "state")
    validate_oauth_state(expected_state, state)
    error = unique_query_value(query, "error")
    code = unique_query_value(query, "code")
    if error:
        return OAuthCallback("", state, error)
    if not code:
        raise SchwabSetupError("OAuth callback did not contain an authorization code.")
    return OAuthCallback(code, state)


def wait_for_callback(
    poll_callback: Callable[[], str | None],
    *,
    expected_state: str,
    timeout_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> OAuthCallback:
    if timeout_seconds <= 0:
        raise CallbackTimeoutError("OAuth callback timeout must be positive.")
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        callback_url = poll_callback()
        if callback_url:
            return parse_oauth_callback(callback_url, expected_state=expected_state)
        sleep(min(0.05, max(0.0, deadline - monotonic())))
    raise CallbackTimeoutError("OAuth callback did not arrive before the local listener timeout.")


def redacted_setup_status(payload: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(marker in lowered for marker in ("secret", "token", "credential", "account", "hash")):
            result[key] = redacted(value)
        else:
            result[key] = value
    return result


def redacted(value: str, *, visible: int = 4) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8] if value else "missing"
    suffix = value[-visible:] if len(value) > visible else ""
    return f"[redacted:{digest}{':' + suffix if suffix else ''}]"


def unique_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    if len(values) > 1:
        raise SchwabSetupError(f"OAuth callback contains duplicate {key} values.")
    return values[0] if values else ""


def callback_recommendation() -> dict[str, str]:
    return {
        "registeredCallbackUrl": "https://127.0.0.1:8182/oauth/callback",
        "host": "127.0.0.1",
        "path": "/oauth/callback",
        "httpsRequirement": "Required by the registered callback",
        "certificateRequirement": (
            "Explicit local certificate and private key; "
            "browser trust must be established separately"
        ),
        "portBehavior": "Fixed registered port 8182",
        "listenerLifecycle": (
            "Bind loopback only immediately before authorization; accept one callback; "
            "validate state; close on success, error, or timeout"
        ),
        "status": "SYNTHETIC_LISTENER_IMPLEMENTED_REAL_ONBOARDING_LOCKED",
    }


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] in {"status", "credentials", "authorize", "delete-local-auth"}:
        from momentum_hunter.schwab_onboarding import main as onboarding_main

        return onboarding_main(effective_argv)
    parser = argparse.ArgumentParser(description="Credential-free Schwab setup skeleton.")
    parser.add_argument(
        "--show-callback-recommendation",
        action="store_true",
        help="Print the registered loopback callback status without contacting Schwab.",
    )
    args = parser.parse_args(effective_argv)
    print(SETUP_NOTICE)
    print("Authenticated setup is locked pending separate credential onboarding and OAuth approval.")
    if args.show_callback_recommendation:
        print(json.dumps(callback_recommendation(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
