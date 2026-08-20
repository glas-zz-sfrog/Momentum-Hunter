from __future__ import annotations

"""Secure Schwab application credential and OAuth onboarding.

This module can authorize the registered application and store tokens locally. It
intentionally contains no account endpoint and no order-transmission method.
"""

import argparse
import json
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth

from momentum_hunter.schwab_loopback_certificate import (
    WindowsLoopbackCertificateManager,
)
from momentum_hunter.schwab_auth_lock import SchwabAuthStateLock
from momentum_hunter.schwab_oauth_listener import (
    OneShotOAuthCallbackListener,
    REGISTERED_CALLBACK_URL,
)
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    EXPECTED_ACCOUNT_TYPE,
    SchwabAccountBinding,
    normalize_last_four,
)
from momentum_hunter.schwab_setup import (
    DEFAULT_SECRET_PATH,
    LocalSecretStore,
    SchwabApplicationCredentials,
    SchwabSetupError,
    generate_oauth_state,
    read_application_credentials,
)


SCHWAB_AUTHORIZATION_URL = "https://api.schwabapi.com/v1/oauth/authorize"
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
ONBOARDING_SCHEMA_VERSION = "SCHWAB_OAUTH_ONBOARDING_V1"
ACCOUNT_BINDING_SCHEMA_VERSION = "SCHWAB_ACCOUNT_BINDING_V1"
DEFAULT_ACCOUNT_BINDING_PATH = DEFAULT_SECRET_PATH.with_name("account-binding.bin")
DELETE_LOCAL_AUTH_CONFIRMATION = "DELETE LOCAL SCHWAB AUTH"
HTTP_TIMEOUT = (5.0, 30.0)
MAX_TOKEN_RESPONSE_BYTES = 64 * 1024


class SchwabOAuthError(SchwabSetupError):
    pass


class SchwabOAuthNetworkError(SchwabOAuthError):
    pass


class SchwabOAuthResponseError(SchwabOAuthError):
    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


@dataclass(frozen=True, repr=False)
class SchwabOAuthTokens:
    access_token: str
    refresh_token: str
    token_type: str
    scope: str
    issued_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            "SchwabOAuthTokens(access_token='[redacted]', refresh_token='[redacted]', "
            f"token_type={self.token_type!r}, scope='[redacted]', "
            f"issued_at={self.issued_at.isoformat()!r}, expires_at={self.expires_at.isoformat()!r})"
        )

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


class SchwabOAuthSecretRepository:
    """Atomic DPAPI storage for application credentials and OAuth tokens."""

    def __init__(self, *, store: LocalSecretStore | None = None) -> None:
        self.store = store or LocalSecretStore(path=DEFAULT_SECRET_PATH)

    @property
    def exists(self) -> bool:
        return self.store.path.is_file()

    def save_new_credentials(self, credentials: SchwabApplicationCredentials) -> Path:
        with self.refresh_ownership():
            if self.exists:
                raise SchwabOAuthError(
                    "Local Schwab authorization material already exists; delete it explicitly before replacing credentials."
                )
            return self.store.save(
                {
                    "schema_version": ONBOARDING_SCHEMA_VERSION,
                    "application_id": credentials.application_id,
                    "application_secret": credentials.application_secret,
                    "created_at": _utc_now().isoformat(),
                }
            )

    def load_credentials(self) -> SchwabApplicationCredentials:
        payload = self._load()
        application_id = payload.get("application_id", "")
        application_secret = payload.get("application_secret", "")
        if not application_id or not application_secret:
            raise SchwabOAuthError("Stored Schwab application credentials are incomplete.")
        return SchwabApplicationCredentials(application_id, application_secret)

    def save_tokens(self, tokens: SchwabOAuthTokens) -> Path:
        with self.refresh_ownership():
            return self.save_tokens_under_ownership(tokens)

    def save_tokens_under_ownership(self, tokens: SchwabOAuthTokens) -> Path:
        payload = self._load()
        payload.update(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "scope": tokens.scope,
                "issued_at": tokens.issued_at.isoformat(),
                "expires_at": tokens.expires_at.isoformat(),
            }
        )
        return self.store.save(payload)

    def refresh_ownership(
        self,
        *,
        timeout_seconds: float = 45.0,
    ) -> SchwabAuthStateLock:
        return SchwabAuthStateLock(
            self.store.path,
            timeout_seconds=timeout_seconds,
        )

    def load_tokens(self) -> SchwabOAuthTokens:
        payload = self._load()
        try:
            issued_at = _parse_utc(payload["issued_at"])
            expires_at = _parse_utc(payload["expires_at"])
            tokens = SchwabOAuthTokens(
                access_token=payload["access_token"],
                refresh_token=payload["refresh_token"],
                token_type=payload["token_type"],
                scope=payload.get("scope", ""),
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (KeyError, ValueError) as exc:
            raise SchwabOAuthError("Stored Schwab OAuth tokens are incomplete.") from exc
        _validate_tokens(tokens)
        return tokens

    def delete(self) -> bool:
        with self.refresh_ownership():
            return self.store.delete()

    def status(self) -> dict[str, object]:
        if not self.exists:
            return {
                "credentialsStored": False,
                "oauthAuthorized": False,
                "tokenState": "MISSING",
            }
        payload = self._load()
        authorized = all(
            payload.get(key)
            for key in ("access_token", "refresh_token", "issued_at", "expires_at")
        )
        token_state = "NOT_AUTHORIZED"
        expires_at = ""
        if authorized:
            tokens = self.load_tokens()
            token_state = "EXPIRED" if tokens.expired else "ACTIVE"
            expires_at = tokens.expires_at.isoformat()
        return {
            "credentialsStored": bool(
                payload.get("application_id") and payload.get("application_secret")
            ),
            "oauthAuthorized": authorized,
            "tokenState": token_state,
            "tokenExpiresAt": expires_at,
        }

    def _load(self) -> dict[str, str]:
        if not self.exists:
            raise SchwabOAuthError("Local Schwab application credentials are not stored.")
        payload = self.store.load()
        if payload.get("schema_version") != ONBOARDING_SCHEMA_VERSION:
            raise SchwabOAuthError("The local Schwab authorization store has an unsupported schema.")
        return payload


class EncryptedSchwabAccountBindingStore:
    """Persist one immutable account binding without exposing its account hash."""

    def __init__(self, *, store: LocalSecretStore | None = None) -> None:
        self.store = store or LocalSecretStore(path=DEFAULT_ACCOUNT_BINDING_PATH)

    @property
    def exists(self) -> bool:
        return self.store.path.is_file()

    def save_new(self, binding: SchwabAccountBinding) -> Path:
        if self.exists:
            raise AccountIsolationError(
                "A Schwab canary account is already bound; silent account replacement is forbidden."
            )
        _validate_binding(binding)
        return self.store.save(
            {
                "schema_version": ACCOUNT_BINDING_SCHEMA_VERSION,
                "account_hash": binding.account_hash,
                "account_number_last_four": binding.account_number_last_four,
                "account_type": binding.account_type,
                "bound_at": _utc_now().isoformat(),
            }
        )

    def load(self) -> SchwabAccountBinding:
        if not self.exists:
            raise AccountIsolationError("No Schwab canary account is bound.")
        payload = self.store.load()
        if payload.get("schema_version") != ACCOUNT_BINDING_SCHEMA_VERSION:
            raise AccountIsolationError("The Schwab account binding has an unsupported schema.")
        try:
            binding = SchwabAccountBinding(
                account_hash=payload["account_hash"],
                account_number_last_four=payload["account_number_last_four"],
                account_type=payload["account_type"],
            )
        except KeyError as exc:
            raise AccountIsolationError("The Schwab account binding is incomplete.") from exc
        _validate_binding(binding)
        return binding

    def delete(self) -> bool:
        return self.store.delete()


class SchwabOAuthTransport:
    """Exact-host OAuth token transport; it has no account or order endpoints."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = HTTP_TIMEOUT,
    ) -> None:
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.timeout = timeout

    def exchange_authorization_code(
        self,
        credentials: SchwabApplicationCredentials,
        authorization_code: str,
    ) -> SchwabOAuthTokens:
        if not authorization_code:
            raise SchwabOAuthError("Schwab authorization did not return a usable code.")
        payload = self._post_token(
            credentials,
            {
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": REGISTERED_CALLBACK_URL,
            },
        )
        return _tokens_from_payload(payload, require_refresh_token=True)

    def refresh(
        self,
        credentials: SchwabApplicationCredentials,
        current_tokens: SchwabOAuthTokens,
    ) -> SchwabOAuthTokens:
        _validate_tokens(current_tokens)
        payload = self._post_token(
            credentials,
            {
                "grant_type": "refresh_token",
                "refresh_token": current_tokens.refresh_token,
            },
        )
        if not payload.get("refresh_token"):
            payload["refresh_token"] = current_tokens.refresh_token
        return _tokens_from_payload(payload, require_refresh_token=True)

    def _post_token(
        self,
        credentials: SchwabApplicationCredentials,
        data: Mapping[str, str],
    ) -> dict[str, object]:
        try:
            response = self.session.post(
                SCHWAB_TOKEN_URL,
                data=dict(data),
                auth=HTTPBasicAuth(
                    credentials.application_id,
                    credentials.application_secret,
                ),
                headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-store",
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise SchwabOAuthNetworkError(
                "Schwab OAuth token exchange could not reach the exact configured endpoint."
            ) from None
        if response.is_redirect:
            raise SchwabOAuthResponseError("Schwab OAuth token exchange refused an HTTP redirect.")
        if response.status_code != 200:
            raise SchwabOAuthResponseError(
                f"Schwab OAuth token exchange failed safely with HTTP {response.status_code}.",
                http_status=response.status_code,
            )
        if len(response.content) > MAX_TOKEN_RESPONSE_BYTES:
            raise SchwabOAuthResponseError("Schwab OAuth token response exceeded the size limit.")
        try:
            payload = response.json()
        except ValueError:
            raise SchwabOAuthResponseError("Schwab OAuth token response was not valid JSON.") from None
        if not isinstance(payload, dict):
            raise SchwabOAuthResponseError("Schwab OAuth token response had an invalid shape.")
        return payload


class SchwabOAuthOnboarding:
    def __init__(
        self,
        *,
        secrets_repository: SchwabOAuthSecretRepository | None = None,
        binding_store: EncryptedSchwabAccountBindingStore | None = None,
        transport: SchwabOAuthTransport | None = None,
        certificate_manager: WindowsLoopbackCertificateManager | None = None,
        listener_factory: Callable[[object], OneShotOAuthCallbackListener] = OneShotOAuthCallbackListener,
        browser_open: Callable[[str], bool] = webbrowser.open,
    ) -> None:
        self.secrets = secrets_repository or SchwabOAuthSecretRepository()
        self.bindings = binding_store or EncryptedSchwabAccountBindingStore()
        self.transport = transport or SchwabOAuthTransport()
        self.certificates = certificate_manager or WindowsLoopbackCertificateManager()
        self.listener_factory = listener_factory
        self.browser_open = browser_open

    def store_credentials(self, credentials: SchwabApplicationCredentials) -> dict[str, object]:
        self.secrets.save_new_credentials(credentials)
        return self.status()

    def authorize(self, *, callback_timeout_seconds: float = 600.0) -> dict[str, object]:
        credentials = self.secrets.load_credentials()
        version_id = self._active_certificate_version()
        config = self.certificates.listener_config(
            version_id,
            require_windows_trust=True,
            timeout_seconds=callback_timeout_seconds,
        )
        listener = self.listener_factory(config)
        state = generate_oauth_state()
        listener.start(expected_state=state)
        authorization_url = build_authorization_url(credentials, state=state)
        try:
            if not self.browser_open(authorization_url):
                raise SchwabOAuthError("The Schwab authorization browser could not be opened.")
            callback = listener.wait(timeout_seconds=callback_timeout_seconds + 1.0)
            if callback.error:
                raise SchwabOAuthError("Schwab authorization was not granted.")
            tokens = self.transport.exchange_authorization_code(
                credentials,
                callback.authorization_code,
            )
            self.secrets.save_tokens(tokens)
        finally:
            listener.close()
        return self.status()

    def refresh(self) -> dict[str, object]:
        if self.bindings.exists:
            raise AccountIsolationError(
                "Token refresh is locked until the pinned Schwab account can be revalidated."
            )
        credentials = self.secrets.load_credentials()
        current_tokens = self.secrets.load_tokens()
        refreshed = self.transport.refresh(credentials, current_tokens)
        self.secrets.save_tokens(refreshed)
        return self.status()

    def delete_local_auth(self, *, confirmation: str) -> dict[str, object]:
        if confirmation != DELETE_LOCAL_AUTH_CONFIRMATION:
            raise SchwabOAuthError("Deleting local Schwab authorization requires the exact confirmation phrase.")
        self.bindings.delete()
        self.secrets.delete()
        return self.status()

    def status(self) -> dict[str, object]:
        status = self.secrets.status()
        account_ending = ""
        if self.bindings.exists:
            account_ending = self.bindings.load().account_number_last_four
        status.update(
            {
                "registeredCallbackUrl": REGISTERED_CALLBACK_URL,
                "accountBinding": "PINNED" if account_ending else "NOT_BOUND",
                "accountEnding": account_ending,
                "authenticatedAccountRequests": "LOCKED_PENDING_SEPARATE_APPROVAL",
                "orderTransmission": "UNAVAILABLE",
            }
        )
        return status

    def _active_certificate_version(self) -> str:
        try:
            payload = json.loads(self.certificates.active_file.read_text(encoding="utf-8"))
            version_id = str(payload["version_id"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SchwabOAuthError(
                "A trusted active loopback certificate is required before Schwab authorization."
            ) from exc
        if not version_id:
            raise SchwabOAuthError(
                "A trusted active loopback certificate is required before Schwab authorization."
            )
        return version_id


def build_authorization_url(
    credentials: SchwabApplicationCredentials,
    *,
    state: str,
) -> str:
    if not credentials.application_id or not state:
        raise SchwabOAuthError("Schwab authorization requires an application ID and random state.")
    return (
        SCHWAB_AUTHORIZATION_URL
        + "?"
        + urlencode(
            {
                "client_id": credentials.application_id,
                "redirect_uri": REGISTERED_CALLBACK_URL,
                "response_type": "code",
                "state": state,
            }
        )
    )


def _tokens_from_payload(
    payload: Mapping[str, object],
    *,
    require_refresh_token: bool,
) -> SchwabOAuthTokens:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    token_type = payload.get("token_type", "Bearer")
    scope = payload.get("scope", "")
    expires_in = payload.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        raise SchwabOAuthResponseError("Schwab OAuth token response omitted the access token.")
    if require_refresh_token and (not isinstance(refresh_token, str) or not refresh_token):
        raise SchwabOAuthResponseError("Schwab OAuth token response omitted the refresh token.")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise SchwabOAuthResponseError("Schwab OAuth token response used an unsupported token type.")
    if not isinstance(scope, str):
        raise SchwabOAuthResponseError("Schwab OAuth token response used an invalid scope.")
    try:
        lifetime = int(expires_in)
    except (TypeError, ValueError):
        raise SchwabOAuthResponseError("Schwab OAuth token response omitted a valid lifetime.") from None
    if lifetime <= 0 or lifetime > 86_400:
        raise SchwabOAuthResponseError("Schwab OAuth token response used an unsafe lifetime.")
    issued_at = _utc_now()
    tokens = SchwabOAuthTokens(
        access_token=access_token,
        refresh_token=str(refresh_token),
        token_type="Bearer",
        scope=scope,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=lifetime),
    )
    _validate_tokens(tokens)
    return tokens


def _validate_tokens(tokens: SchwabOAuthTokens) -> None:
    if (
        not tokens.access_token
        or not tokens.refresh_token
        or tokens.token_type.lower() != "bearer"
        or tokens.expires_at <= tokens.issued_at
    ):
        raise SchwabOAuthError("Schwab OAuth token material is invalid.")


def _validate_binding(binding: SchwabAccountBinding) -> None:
    if not binding.account_hash.strip():
        raise AccountIsolationError("A Schwab account binding requires an opaque account hash.")
    normalize_last_four(binding.account_number_last_four)
    if binding.account_type != EXPECTED_ACCOUNT_TYPE:
        raise AccountIsolationError(
            f"Only an {EXPECTED_ACCOUNT_TYPE} canary account may be persisted."
        )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp is missing a timezone.")
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = _RedactedArgumentParser(description="Secure Schwab OAuth onboarding.")
    parser.add_argument(
        "command",
        choices=("status", "credentials", "authorize", "delete-local-auth"),
    )
    args = parser.parse_args(argv)
    onboarding = SchwabOAuthOnboarding()
    try:
        if args.command == "credentials":
            print(
                "Enter Schwab application credentials only.\n"
                "Never enter your Schwab username, password, or MFA code here."
            )
            status = onboarding.store_credentials(read_application_credentials())
        elif args.command == "authorize":
            status = onboarding.authorize()
        elif args.command == "delete-local-auth":
            confirmation = input(
                f"Type {DELETE_LOCAL_AUTH_CONFIRMATION!r} to remove local credentials, tokens, and account binding: "
            )
            status = onboarding.delete_local_auth(confirmation=confirmation)
        else:
            status = onboarding.status()
    except SchwabSetupError as exc:
        print(f"Schwab onboarding stopped safely: {exc}")
        return 1
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
