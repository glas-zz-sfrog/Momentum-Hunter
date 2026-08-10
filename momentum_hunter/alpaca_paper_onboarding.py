from __future__ import annotations

"""Paper-only Alpaca credential onboarding and read-only account proof."""

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

import requests

from momentum_hunter.schwab_setup import (
    LocalSecretStore,
    SchwabSetupError,
    WindowsDpapiProtector,
)


ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_BASE_URL = "https://api.alpaca.markets"
ALPACA_PAPER_ACCOUNT_URL = f"{ALPACA_PAPER_BASE_URL}/v2/account"
ALPACA_PAPER_ENVIRONMENT = "PAPER_ONLY"
ALPACA_PAPER_CREDENTIAL_SCHEMA = "ALPACA_PAPER_CREDENTIALS_V1"
DEFAULT_ALPACA_PAPER_SECRET_DIRECTORY = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "MomentumHunter"
    / "Alpaca"
)
HTTP_TIMEOUT = (5.0, 15.0)
MAX_ACCOUNT_RESPONSE_BYTES = 64 * 1024
REPLACE_CANARY_CREDENTIALS_CONFIRMATION = (
    "REPLACE CANARY_REALISTIC PAPER CREDENTIALS"
)


class AlpacaPaperLane(str, Enum):
    CANARY_REALISTIC = "CANARY_REALISTIC"
    STRATEGY_RESEARCH = "STRATEGY_RESEARCH"

    @property
    def credential_filename(self) -> str:
        if self is AlpacaPaperLane.CANARY_REALISTIC:
            return "canary-realistic-paper-credentials.bin"
        return "strategy-research-paper-credentials.bin"

    @property
    def dpapi_entropy(self) -> bytes:
        return f"MomentumHunter.Alpaca.Paper.{self.value}.v1".encode("ascii")

    @property
    def statistics_domain(self) -> str:
        if self is AlpacaPaperLane.CANARY_REALISTIC:
            return "OFFICIAL_CANARY_REALISTIC"
        return "RESEARCH_ONLY_STRATEGY"

    @property
    def operator_label(self) -> str:
        if self is AlpacaPaperLane.CANARY_REALISTIC:
            return "Canary $100 Paper"
        return "$100,000 Strategy Research Paper"


class AlpacaPaperError(RuntimeError):
    pass


class AlpacaPaperCredentialError(AlpacaPaperError):
    pass


class AlpacaPaperEndpointError(AlpacaPaperError):
    pass


class AlpacaPaperNetworkError(AlpacaPaperError):
    pass


class AlpacaPaperResponseError(AlpacaPaperError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


@dataclass(frozen=True, repr=False)
class AlpacaPaperCredentials:
    key_id: str
    secret_key: str

    def __repr__(self) -> str:
        return "AlpacaPaperCredentials(key_id='[redacted]', secret_key='[redacted]')"


@dataclass(frozen=True)
class AlpacaPaperAccount:
    status: str
    cash: Decimal
    buying_power: Decimal
    account_blocked: bool
    trading_blocked: bool
    trade_suspended_by_user: bool
    equity: Decimal | None = None
    last_equity: Decimal | None = None

    @property
    def usable(self) -> bool:
        return (
            self.status == "ACTIVE"
            and not self.account_blocked
            and not self.trading_blocked
            and not self.trade_suspended_by_user
        )


class AlpacaPaperCredentialRepository:
    """Write-once DPAPI storage bound to one explicit Alpaca Paper lane."""

    def __init__(
        self,
        *,
        lane: AlpacaPaperLane,
        store: LocalSecretStore | None = None,
    ) -> None:
        self.lane = lane
        self.store = store or LocalSecretStore(
            path=DEFAULT_ALPACA_PAPER_SECRET_DIRECTORY / lane.credential_filename,
            protector=WindowsDpapiProtector(
                entropy=lane.dpapi_entropy,
                description=f"Momentum Hunter Alpaca Paper {lane.value} credentials",
            ),
        )

    @property
    def exists(self) -> bool:
        return self.store.path.is_file()

    def save_new(self, credentials: AlpacaPaperCredentials) -> Path:
        _validate_credentials(credentials)
        if self.exists:
            raise AlpacaPaperCredentialError(
                "Alpaca Paper credentials already exist locally; silent replacement is forbidden."
            )
        return self._save(credentials)

    def replace_existing(
        self,
        credentials: AlpacaPaperCredentials,
        *,
        confirmation: str,
    ) -> Path:
        if self.lane is not AlpacaPaperLane.CANARY_REALISTIC:
            raise AlpacaPaperCredentialError(
                "Credential replacement is not enabled for the research Paper lane."
            )
        if confirmation != REPLACE_CANARY_CREDENTIALS_CONFIRMATION:
            raise AlpacaPaperCredentialError(
                "The exact local Canary credential replacement confirmation was not provided."
            )
        if not self.exists:
            raise AlpacaPaperCredentialError(
                "No local Canary credential store exists; use first-time onboarding instead."
            )
        _validate_credentials(credentials)
        return self._save(credentials)

    def _save(self, credentials: AlpacaPaperCredentials) -> Path:
        try:
            return self.store.save(
                {
                    "schema_version": ALPACA_PAPER_CREDENTIAL_SCHEMA,
                    "environment": ALPACA_PAPER_ENVIRONMENT,
                    "endpoint": ALPACA_PAPER_BASE_URL,
                    "lane": self.lane.value,
                    "statistics_domain": self.lane.statistics_domain,
                    "key_id": credentials.key_id,
                    "secret_key": credentials.secret_key,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except SchwabSetupError:
            raise AlpacaPaperCredentialError(
                "Alpaca Paper credentials could not be protected in the local Windows store."
            ) from None

    def load(self) -> AlpacaPaperCredentials:
        if not self.exists:
            raise AlpacaPaperCredentialError(
                "Alpaca Paper credentials are not stored on this Windows account."
            )
        try:
            payload = self.store.load()
        except SchwabSetupError:
            raise AlpacaPaperCredentialError(
                "The local Alpaca Paper credential store could not be loaded."
            ) from None
        if (
            payload.get("schema_version") != ALPACA_PAPER_CREDENTIAL_SCHEMA
            or payload.get("environment") != ALPACA_PAPER_ENVIRONMENT
            or payload.get("endpoint") != ALPACA_PAPER_BASE_URL
            or payload.get("lane") != self.lane.value
            or payload.get("statistics_domain") != self.lane.statistics_domain
        ):
            raise AlpacaPaperCredentialError(
                "The local Alpaca Paper credential store has an invalid lane or environment binding."
            )
        credentials = AlpacaPaperCredentials(
            key_id=payload.get("key_id", ""),
            secret_key=payload.get("secret_key", ""),
        )
        _validate_credentials(credentials)
        return credentials

    def binding_fingerprint(self) -> str:
        """Return a stable account-slot binding without exposing credential material."""

        credentials = self.load()
        payload = "|".join(
            (
                "alpaca-paper-binding-v1",
                self.lane.value,
                ALPACA_PAPER_BASE_URL,
                credentials.key_id,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()

    def status(self) -> dict[str, object]:
        return {
            "lane": self.lane.value,
            "accountRole": self.lane.operator_label,
            "statisticsDomain": self.lane.statistics_domain,
            "mode": ALPACA_PAPER_ENVIRONMENT,
            "endpoint": ALPACA_PAPER_BASE_URL,
            "credentialsStored": self.exists,
            "persistence": "ENCRYPTED_DPAPI_CURRENT_USER",
            "liveEndpointReachable": False,
            "orderCapability": "UNAVAILABLE",
        }


class AlpacaPaperReadonlyTransport:
    """One exact-host GET transport with no position or order methods."""

    def __init__(
        self,
        *,
        base_url: str = ALPACA_PAPER_BASE_URL,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = HTTP_TIMEOUT,
    ) -> None:
        _require_exact_paper_endpoint(base_url)
        self.base_url = base_url
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.timeout = timeout

    def get_account(
        self,
        credentials: AlpacaPaperCredentials,
    ) -> tuple[AlpacaPaperAccount, bool]:
        _validate_credentials(credentials)
        _require_exact_paper_endpoint(self.base_url)
        try:
            response = self.session.get(
                ALPACA_PAPER_ACCOUNT_URL,
                headers={
                    "Accept": "application/json",
                    "APCA-API-KEY-ID": credentials.key_id,
                    "APCA-API-SECRET-KEY": credentials.secret_key,
                    "Cache-Control": "no-store",
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise AlpacaPaperNetworkError(
                "The read-only Alpaca Paper canary could not reach the exact Paper endpoint."
            ) from None
        if response.is_redirect:
            raise AlpacaPaperEndpointError(
                "The read-only Alpaca Paper canary refused an HTTP redirect."
            )
        if response.status_code != 200:
            raise AlpacaPaperResponseError(
                f"Alpaca Paper authentication failed safely with HTTP {response.status_code}."
            )
        if len(response.content) > MAX_ACCOUNT_RESPONSE_BYTES:
            raise AlpacaPaperResponseError(
                "The Alpaca Paper account response exceeded the size limit."
            )
        try:
            payload = response.json()
        except ValueError:
            raise AlpacaPaperResponseError(
                "The Alpaca Paper account response was not valid JSON."
            ) from None
        account = parse_paper_account(payload)
        return account, bool(response.headers.get("X-Request-ID"))


class AlpacaPaperReadonlyCanary:
    """Loads local Paper credentials and performs exactly one account GET."""

    def __init__(
        self,
        *,
        lane: AlpacaPaperLane,
        credentials: AlpacaPaperCredentialRepository | None = None,
        transport: AlpacaPaperReadonlyTransport | None = None,
    ) -> None:
        self.lane = lane
        self.credentials = credentials or AlpacaPaperCredentialRepository(lane=lane)
        if self.credentials.lane is not lane:
            raise AlpacaPaperCredentialError(
                "The read-only canary credential repository belongs to another Paper lane."
            )
        self.transport = transport or AlpacaPaperReadonlyTransport()

    def run(self) -> dict[str, object]:
        account, request_id_present = self.transport.get_account(
            self.credentials.load()
        )
        return {
            "lane": self.lane.value,
            "accountRole": self.lane.operator_label,
            "statisticsDomain": self.lane.statistics_domain,
            "mode": "ALPACA_PAPER_ACCOUNT_CANARY_READ_ONLY",
            "environment": ALPACA_PAPER_ENVIRONMENT,
            "endpoint": ALPACA_PAPER_BASE_URL,
            "requestMethod": "GET",
            "requestPath": "/v2/account",
            "requestCount": 1,
            "authentication": "SUCCEEDED",
            "paperAccountValidated": True,
            "paperAccountProof": "AUTHENTICATED_EXACT_PAPER_ENDPOINT",
            "accountStatus": account.status,
            "accountUsable": account.usable,
            "cash": _decimal_text(account.cash),
            "buyingPower": _decimal_text(account.buying_power),
            "accountBlocked": account.account_blocked,
            "tradingBlocked": account.trading_blocked,
            "tradeSuspendedByUser": account.trade_suspended_by_user,
            "requestIdPresent": request_id_present,
            "positionsRequested": False,
            "ordersRequested": False,
            "mutatingRequestAttempted": False,
            "liveEndpointReachable": False,
            "orderCapability": "UNAVAILABLE",
            "credentialValuesIncluded": False,
        }


def read_paper_credentials(
    *,
    lane: AlpacaPaperLane,
    reader: Callable[[str], str] | None = None,
) -> AlpacaPaperCredentials:
    if reader is None:
        return _read_paper_credentials_gui(lane)
    hidden_reader = reader
    label = lane.operator_label
    key_id = hidden_reader(f"{label} API Key (hidden): ").strip()
    secret_key = hidden_reader(f"{label} Secret Key (hidden): ").strip()
    credentials = AlpacaPaperCredentials(key_id=key_id, secret_key=secret_key)
    _validate_credentials(credentials)
    return credentials


def onboard_paper_credentials(
    *,
    lane: AlpacaPaperLane,
    repository: AlpacaPaperCredentialRepository | None = None,
    credential_reader: Callable[[str], str] | None = None,
) -> dict[str, object]:
    selected = repository or AlpacaPaperCredentialRepository(lane=lane)
    if selected.lane is not lane:
        raise AlpacaPaperCredentialError(
            "The onboarding credential repository belongs to another Paper lane."
        )
    if selected.exists:
        raise AlpacaPaperCredentialError(
            "Alpaca Paper credentials already exist locally; silent replacement is forbidden."
        )
    selected.save_new(
        read_paper_credentials(lane=lane, reader=credential_reader)
    )
    return {
        **selected.status(),
        "credentialEntry": "HIDDEN_LOCAL_INTERACTIVE",
        "networkRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "nextStep": "RUN_READ_ONLY_ACCOUNT_CANARY",
    }


def replace_canary_credentials(
    repository: AlpacaPaperCredentialRepository | None = None,
    *,
    confirmation_reader: Callable[[str], str] = input,
    credential_reader: Callable[[str], str] | None = None,
) -> dict[str, object]:
    selected = repository or AlpacaPaperCredentialRepository(
        lane=AlpacaPaperLane.CANARY_REALISTIC
    )
    if selected.lane is not AlpacaPaperLane.CANARY_REALISTIC:
        raise AlpacaPaperCredentialError(
            "Credential replacement is enabled only for the Canary Paper lane."
        )
    if not selected.exists:
        raise AlpacaPaperCredentialError(
            "No local Canary credential store exists; use first-time onboarding instead."
        )
    confirmation = confirmation_reader(
        "Type REPLACE CANARY_REALISTIC PAPER CREDENTIALS to replace the local "
        "encrypted Canary slot: "
    )
    selected.replace_existing(
        read_paper_credentials(
            lane=AlpacaPaperLane.CANARY_REALISTIC,
            reader=credential_reader,
        ),
        confirmation=confirmation,
    )
    return {
        **selected.status(),
        "credentialEntry": "HIDDEN_LOCAL_INTERACTIVE_SINGLE_ENTRY",
        "credentialsReplaced": True,
        "networkRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "nextStep": "RUN_READ_ONLY_ACCOUNT_CANARY",
    }


def parse_paper_account(payload: object) -> AlpacaPaperAccount:
    if not isinstance(payload, Mapping):
        raise AlpacaPaperResponseError(
            "The Alpaca Paper account response had an invalid shape."
        )
    status = payload.get("status")
    if not isinstance(status, str) or not status.strip():
        raise AlpacaPaperResponseError(
            "The Alpaca Paper account response omitted account status."
        )
    return AlpacaPaperAccount(
        status=status.strip().upper(),
        cash=_required_decimal(payload, "cash"),
        buying_power=_required_decimal(payload, "buying_power"),
        account_blocked=_required_bool(payload, "account_blocked"),
        trading_blocked=_required_bool(payload, "trading_blocked"),
        trade_suspended_by_user=_required_bool(
            payload,
            "trade_suspended_by_user",
        ),
        equity=_optional_decimal(payload, "equity"),
        last_equity=_optional_decimal(payload, "last_equity"),
    )


def _required_decimal(payload: Mapping[object, object], field: str) -> Decimal:
    value = payload.get(field)
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise AlpacaPaperResponseError(
            f"The Alpaca Paper account response omitted normalized {field}."
        )
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AlpacaPaperResponseError(
            f"The Alpaca Paper account response contained invalid {field}."
        ) from None
    if not normalized.is_finite() or not math.isfinite(float(normalized)):
        raise AlpacaPaperResponseError(
            f"The Alpaca Paper account response contained non-finite {field}."
        )
    return normalized


def _optional_decimal(
    payload: Mapping[object, object],
    field: str,
) -> Decimal | None:
    if field not in payload or payload.get(field) in {None, ""}:
        return None
    return _required_decimal(payload, field)


def _required_bool(payload: Mapping[object, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise AlpacaPaperResponseError(
            f"The Alpaca Paper account response omitted boolean {field}."
        )
    return value


def _validate_credentials(credentials: AlpacaPaperCredentials) -> None:
    if not credentials.key_id or not credentials.secret_key:
        raise AlpacaPaperCredentialError(
            "Both hidden Alpaca Paper credential fields are required."
        )
    if len(credentials.key_id) > 4096 or len(credentials.secret_key) > 4096:
        raise AlpacaPaperCredentialError(
            "An Alpaca Paper credential field exceeded the local safety limit."
        )
    if any(
        not value.isascii()
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
        for value in (credentials.key_id, credentials.secret_key)
    ):
        raise AlpacaPaperCredentialError(
            "An Alpaca Paper credential contained whitespace or control characters; "
            "nothing was stored."
        )


def _read_paper_credentials_gui(
    lane: AlpacaPaperLane,
) -> AlpacaPaperCredentials:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        raise AlpacaPaperCredentialError(
            "The local masked credential-entry window is unavailable."
        ) from None

    result: dict[str, str] = {}
    root: object | None = None
    try:
        root = tk.Tk()
        root.title("Momentum Hunter - Alpaca Paper Credential Entry")
        root.geometry("620x330")
        root.resizable(False, False)
        root.configure(bg="#101820")
        root.attributes("-topmost", True)

        title = tk.Label(
            root,
            text="ALPACA PAPER CREDENTIAL ENTRY",
            bg="#101820",
            fg="#f2f5f7",
            font=("Segoe UI", 15, "bold"),
        )
        title.pack(anchor="w", padx=24, pady=(20, 2))
        detail = tk.Label(
            root,
            text=(
                f"{lane.operator_label} | {lane.value}\n"
                f"{ALPACA_PAPER_BASE_URL} | PAPER ONLY | orders unavailable"
            ),
            bg="#101820",
            fg="#41d6c3",
            justify="left",
            font=("Segoe UI", 10),
        )
        detail.pack(anchor="w", padx=24, pady=(0, 16))

        form = tk.Frame(root, bg="#101820")
        form.pack(fill="x", padx=24)

        def add_field(row: int, label_text: str) -> tuple[object, object]:
            label = tk.Label(
                form,
                text=label_text,
                bg="#101820",
                fg="#d9e2e8",
                anchor="w",
                font=("Segoe UI", 10),
            )
            label.grid(row=row, column=0, sticky="w", pady=7)
            entry = tk.Entry(
                form,
                show="*",
                width=43,
                bg="#172733",
                fg="#ffffff",
                insertbackground="#ffffff",
                relief="solid",
                borderwidth=1,
                font=("Consolas", 11),
            )
            entry.grid(row=row, column=1, sticky="ew", padx=(12, 8), pady=7, ipady=6)
            button = tk.Button(
                form,
                text="Paste",
                width=9,
                bg="#243a49",
                fg="#ffffff",
                activebackground="#31556b",
                activeforeground="#ffffff",
            )
            button.grid(row=row, column=2, pady=7)

            def paste_value() -> None:
                try:
                    value = root.clipboard_get().strip()
                except tk.TclError:
                    messagebox.showerror(
                        "Clipboard unavailable",
                        "Copy the matching Alpaca credential, then click Paste.",
                        parent=root,
                    )
                    return
                entry.delete(0, tk.END)
                entry.insert(0, value)

            button.configure(command=paste_value)
            return entry, button

        key_entry, _key_paste = add_field(0, "Canary API Key")
        secret_entry, _secret_paste = add_field(1, "Canary Secret Key")
        form.columnconfigure(1, weight=1)

        note = tk.Label(
            root,
            text=(
                "Copy each value from Alpaca and click its Paste button. "
                "Values remain masked and are never printed."
            ),
            bg="#101820",
            fg="#a9bac5",
            wraplength=570,
            justify="left",
            font=("Segoe UI", 9),
        )
        note.pack(anchor="w", padx=24, pady=(12, 10))

        controls = tk.Frame(root, bg="#101820")
        controls.pack(fill="x", padx=24)

        def cancel() -> None:
            result.clear()
            root.destroy()

        def accept() -> None:
            credentials = AlpacaPaperCredentials(
                key_id=key_entry.get().strip(),
                secret_key=secret_entry.get().strip(),
            )
            try:
                _validate_credentials(credentials)
            except AlpacaPaperCredentialError as exc:
                messagebox.showerror("Credential entry stopped", str(exc), parent=root)
                return
            result["key_id"] = credentials.key_id
            result["secret_key"] = credentials.secret_key
            try:
                clipboard_value = root.clipboard_get()
                if clipboard_value.strip() in {
                    credentials.key_id,
                    credentials.secret_key,
                }:
                    root.clipboard_clear()
                    root.update()
            except tk.TclError:
                pass
            root.destroy()

        cancel_button = tk.Button(
            controls,
            text="Cancel",
            command=cancel,
            width=12,
            bg="#24313a",
            fg="#ffffff",
        )
        cancel_button.pack(side="right")
        store_button = tk.Button(
            controls,
            text="Store Encrypted Credentials",
            command=accept,
            width=25,
            bg="#197a6e",
            fg="#ffffff",
            activebackground="#239b8c",
            activeforeground="#ffffff",
        )
        store_button.pack(side="right", padx=(0, 10))
        root.protocol("WM_DELETE_WINDOW", cancel)
        key_entry.focus_set()
        root.mainloop()
    except Exception as exc:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        if isinstance(exc, AlpacaPaperCredentialError):
            raise
        raise AlpacaPaperCredentialError(
            "The local masked credential-entry window failed safely."
        ) from None
    if not result:
        raise AlpacaPaperCredentialError(
            "Local Alpaca Paper credential entry was cancelled; nothing was stored."
        )
    return AlpacaPaperCredentials(
        key_id=result["key_id"],
        secret_key=result["secret_key"],
    )


def _require_exact_paper_endpoint(base_url: str) -> None:
    if base_url != ALPACA_PAPER_BASE_URL:
        raise AlpacaPaperEndpointError(
            "Alpaca Paper is locked to the exact approved Paper endpoint."
        )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def main(argv: list[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Secure local onboarding and read-only proof for Alpaca Paper."
    )
    parser.add_argument(
        "command",
        choices=(
            "status",
            "onboard-canary",
            "replace-canary",
            "canary-canary",
        ),
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            report = {
                "mode": ALPACA_PAPER_ENVIRONMENT,
                "endpoint": ALPACA_PAPER_BASE_URL,
                "lanes": {
                    lane.value: AlpacaPaperCredentialRepository(lane=lane).status()
                    for lane in AlpacaPaperLane
                },
                "researchOnboarding": "RESERVED_NOT_ENABLED_IN_THIS_TASK",
                "liveEndpointReachable": False,
                "orderCapability": "UNAVAILABLE",
            }
        elif args.command == "onboard-canary":
            report = onboard_paper_credentials(
                lane=AlpacaPaperLane.CANARY_REALISTIC
            )
        elif args.command == "replace-canary":
            report = replace_canary_credentials()
        else:
            report = AlpacaPaperReadonlyCanary(
                lane=AlpacaPaperLane.CANARY_REALISTIC
            ).run()
            if not report["accountUsable"]:
                print(json.dumps(report, indent=2, sort_keys=True))
                return 2
    except AlpacaPaperError as exc:
        print(f"Alpaca Paper onboarding stopped safely: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
