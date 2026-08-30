"""Read-only provider boundary backed by accepted preserved market evidence."""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from momentum_hunter.broad_discovery import DiscoverySnapshot
from momentum_hunter.continuous_tradeplan_producer import CurrentMarketEvidence


PROFILE = "OFFLINE_PRESERVED_PROVIDER_REPLAY"
EXPECTED_PACKAGE_SHA256 = (
    "DAB6F1159893EFAD8F80669A8FCF7759B4473AD1E8252F27261634E3DBC9C831"
)
INNER_PACKAGE_ENTRY = (
    "inputs/ARGUS-CONTINUOUS-PRODUCER-001D-FORENSIC-CANARY-20260827-"
    "REGULAR-FBA8781-SECOND-EYE.zip"
)
FINVIZ_PREFIX = "evidence/runtime-artifacts/source-evidence/finviz/"
SCHWAB_PREFIX = "evidence/runtime-artifacts/source-evidence/schwab/"
MINUTE_PREFIX = "evidence/runtime-artifacts/market-data/minute/"
DAILY_PREFIX = "evidence/runtime-artifacts/market-data/daily/"


class PreservedProviderReplayError(ValueError):
    pass


def _parsed(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PreservedProviderReplayError("Preserved timestamp must be timezone-aware.")
    return parsed


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


class ReplayClock:
    """Monotonic virtual clock that can only advance through preserved chronology."""

    def __init__(self, launch_at: datetime) -> None:
        if launch_at.tzinfo is None or launch_at.utcoffset() is None:
            raise PreservedProviderReplayError("Replay launch time must be timezone-aware.")
        self._launch_at = launch_at
        self._now = launch_at
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def monotonic(self) -> float:
        with self._lock:
            return (self._now - self._launch_at).total_seconds()

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise PreservedProviderReplayError("Replay clock cannot move backward.")
        with self._lock:
            self._now += timedelta(seconds=seconds)

    def advance_to(self, value: str | datetime) -> datetime:
        target = _parsed(value) if isinstance(value, str) else value
        if target.tzinfo is None or target.utcoffset() is None:
            raise PreservedProviderReplayError("Replay timestamp must be timezone-aware.")
        with self._lock:
            if target > self._now:
                self._now = target
            return self._now


class PreservedFinvizProvider:
    def __init__(
        self,
        *,
        clock: ReplayClock,
        snapshots: tuple[DiscoverySnapshot, ...],
    ) -> None:
        if not snapshots:
            raise PreservedProviderReplayError("Replay omitted Finviz discovery snapshots.")
        self.clock = clock
        self.snapshots = snapshots
        self.index = 0
        self.receipts: list[dict[str, object]] = []

    def discover_paginated(self, *_args, **_kwargs) -> DiscoverySnapshot:
        snapshot = self.snapshots[min(self.index, len(self.snapshots) - 1)]
        self.index += 1
        requested = self.clock.now().isoformat()
        self.clock.advance_to(snapshot.received_at)
        self.receipts.append(
            {
                "requestedAt": requested,
                "snapshotId": snapshot.snapshot_id,
                "snapshotFingerprint": snapshot.fingerprint,
                "providerRequestedAt": snapshot.requested_at.isoformat(),
                "providerReceivedAt": snapshot.received_at.isoformat(),
            }
        )
        return snapshot


class PreservedSchwabBoundary:
    def __init__(
        self,
        *,
        clock: ReplayClock,
        admissions: Mapping[
            str,
            tuple[tuple[CurrentMarketEvidence, datetime], ...],
        ],
        minute_files: Mapping[str, bytes],
        daily_files: Mapping[str, bytes],
    ) -> None:
        self.clock = clock
        self.admissions = dict(admissions)
        self.minute_files = dict(minute_files)
        self.daily_files = dict(daily_files)
        self.quote_receipts: list[dict[str, object]] = []
        self.backfill_receipts: list[dict[str, object]] = []
        self._last_decision_cutoff: datetime | None = None

    def auth_health(self) -> dict[str, object]:
        return {
            "mode": PROFILE,
            "networkRequested": False,
            "credentialStateRequested": False,
        }

    def current_evidence(
        self,
        symbol: str,
        cutoff: datetime,
    ) -> CurrentMarketEvidence:
        candidates = self.admissions.get(symbol, ())
        selected = next(
            (
                item
                for item in candidates
                if item[1] >= cutoff
            ),
            None,
        )
        if selected is None:
            raise PreservedProviderReplayError(
                f"Preserved Schwab evidence omitted a current quote for {symbol}."
            )
        evidence, decision_cutoff = selected
        self._last_decision_cutoff = decision_cutoff
        self.quote_receipts.append(
            {
                "symbol": symbol,
                "requestCutoff": cutoff.isoformat(),
                "decisionCutoff": decision_cutoff.isoformat(),
                "providerTimestamp": evidence.provider_timestamp,
                "receiptTimestamp": evidence.receipt_timestamp,
                "evidenceId": evidence.evidence_id,
                "evidenceFingerprint": evidence.evidence_fingerprint,
            }
        )
        return evidence

    def decision_cutoff(self) -> datetime:
        if self._last_decision_cutoff is None:
            raise PreservedProviderReplayError(
                "Preserved Schwab decision cutoff was requested before evidence."
            )
        return self._last_decision_cutoff

    def backfill(
        self,
        symbols: tuple[str, ...],
        *,
        minute_store_root: Path,
        daily_store_root: Path,
    ) -> dict[str, object]:
        results: list[dict[str, object]] = []
        for symbol in symbols:
            minute_rows = self._copy_symbol_files(
                symbol,
                source=self.minute_files,
                destination=minute_store_root,
                daily=False,
            )
            daily_rows = self._copy_symbol_files(
                symbol,
                source=self.daily_files,
                destination=daily_store_root,
                daily=True,
            )
            if minute_rows == 0 or daily_rows == 0:
                raise PreservedProviderReplayError(
                    f"Preserved Schwab history omitted required stores for {symbol}."
                )
            results.append(
                {
                    "symbol": symbol,
                    "minute": {"rows": minute_rows, "error": None},
                    "daily": {"rows": daily_rows, "error": None},
                }
            )
        receipt = {
            "status": "COMPLETE",
            "symbols": results,
            "networkRequested": False,
            "accountValuesRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }
        self.backfill_receipts.append(receipt)
        return receipt

    def _copy_symbol_files(
        self,
        symbol: str,
        *,
        source: Mapping[str, bytes],
        destination: Path,
        daily: bool,
    ) -> int:
        suffix = f"/{symbol}.json"
        selected = sorted(
            (name, content) for name, content in source.items() if name.endswith(suffix)
        )
        row_count = 0
        received_at: list[datetime] = []
        for name, content in selected:
            payload = json.loads(content.decode("ascii"))
            bars = payload.get("bars")
            if not isinstance(bars, list):
                raise PreservedProviderReplayError("Preserved candle store is malformed.")
            row_count += len(bars)
            for bar in bars:
                if not isinstance(bar, Mapping):
                    continue
                for family in ("historyVersions", "streamVersions"):
                    versions = bar.get(family)
                    if not isinstance(versions, list):
                        continue
                    for version in versions:
                        if isinstance(version, Mapping) and version.get("firstReceivedAt"):
                            received_at.append(_parsed(str(version["firstReceivedAt"])))
            target = (
                destination
                / (Path(name).name if daily else Path(name).parent.name)
                / Path(name).name
            )
            if daily:
                target = destination / Path(name).name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != content:
                    raise PreservedProviderReplayError(
                        "Replay attempted to replace nonmatching candle-store bytes."
                    )
            else:
                with target.open("xb") as handle:
                    handle.write(content)
        return row_count


@dataclass(frozen=True)
class PreservedProviderReplay:
    package_path: Path
    package_sha256: str
    inner_package_sha256: str
    source_fingerprint: str
    launch_at: datetime
    activation_at: datetime
    session_date: str
    clock: ReplayClock
    discovery_provider: PreservedFinvizProvider
    market_boundary: PreservedSchwabBoundary
    selected_entries: tuple[dict[str, object], ...]

    @property
    def mode(self) -> str:
        return PROFILE

    def receipt(self) -> dict[str, object]:
        return {
            "mode": PROFILE,
            "packageSha256": self.package_sha256,
            "innerPackageSha256": self.inner_package_sha256,
            "sourceFingerprint": self.source_fingerprint,
            "sessionDate": self.session_date,
            "launchAt": self.launch_at.isoformat(),
            "activationAt": self.activation_at.isoformat(),
            "selectedEntries": list(self.selected_entries),
            "discoveryReceipts": list(self.discovery_provider.receipts),
            "quoteReceipts": list(self.market_boundary.quote_receipts),
            "backfillReceipts": list(self.market_boundary.backfill_receipts),
            "networkRequested": False,
            "accountValuesRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "countsAsNewProspectiveLiveEvidence": False,
        }


def load_preserved_provider_replay(path: Path) -> PreservedProviderReplay:
    package_path = path.resolve(strict=True)
    package_bytes = package_path.read_bytes()
    package_sha = _sha256(package_bytes)
    if package_sha != EXPECTED_PACKAGE_SHA256:
        raise PreservedProviderReplayError(
            "Preserved provider package identity differs from the accepted V4 packet."
        )
    with zipfile.ZipFile(io.BytesIO(package_bytes)) as outer:
        try:
            inner_bytes = outer.read(INNER_PACKAGE_ENTRY)
        except KeyError as exc:
            raise PreservedProviderReplayError(
                "Accepted V4 packet omitted its reviewed 001D provider package."
            ) from exc
    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
        names = tuple(entry.filename for entry in inner.infolist() if not entry.is_dir())
        finviz_files = {
            name: inner.read(name)
            for name in names
            if name.startswith(FINVIZ_PREFIX) and name.endswith(".json")
        }
        schwab_files = {
            name: inner.read(name)
            for name in names
            if name.startswith(SCHWAB_PREFIX) and name.endswith(".json")
        }
        minute_files = {
            name: inner.read(name)
            for name in names
            if name.startswith(MINUTE_PREFIX) and name.endswith(".json")
        }
        daily_files = {
            name: inner.read(name)
            for name in names
            if name.startswith(DAILY_PREFIX) and name.endswith(".json")
        }
    snapshots = tuple(
        sorted(
            (
                DiscoverySnapshot.from_dict(json.loads(content.decode("ascii")))
                for content in finviz_files.values()
            ),
            key=lambda item: _parsed(item.evaluated_at),
        )
    )
    admissions: dict[str, list[tuple[CurrentMarketEvidence, datetime]]] = {}
    for content in schwab_files.values():
        payload = json.loads(content.decode("ascii"))
        current = payload.get("currentMarketEvidence")
        if not isinstance(current, Mapping):
            continue
        historical = payload.get("historicalContext")
        if not isinstance(historical, Mapping) or historical.get("status") != "READY":
            continue
        evidence = CurrentMarketEvidence(**dict(current))
        decision_cutoff = _parsed(str(historical.get("evidence_cutoff", "")))
        admissions.setdefault(evidence.symbol, []).append(
            (evidence, decision_cutoff)
        )
    ordered_admissions = {
        symbol: tuple(sorted(items, key=lambda item: item[1]))
        for symbol, items in admissions.items()
    }
    if not snapshots or not ordered_admissions or not minute_files or not daily_files:
        raise PreservedProviderReplayError(
            "Accepted provider packet omitted required discovery, quote, or candle evidence."
        )
    launch_at = _parsed(snapshots[0].evaluated_at)
    clock = ReplayClock(launch_at)
    selected = tuple(
        {
            "path": name,
            "size": len(content),
            "sha256": _sha256(content),
        }
        for name, content in sorted(
            {
                **finviz_files,
                **schwab_files,
                **minute_files,
                **daily_files,
            }.items()
        )
    )
    identity_payload = json.dumps(
        selected,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return PreservedProviderReplay(
        package_path=package_path,
        package_sha256=package_sha,
        inner_package_sha256=_sha256(inner_bytes),
        source_fingerprint=_sha256(identity_payload),
        launch_at=launch_at,
        activation_at=launch_at - timedelta(seconds=1),
        session_date=launch_at.date().isoformat(),
        clock=clock,
        discovery_provider=PreservedFinvizProvider(
            clock=clock,
            snapshots=snapshots,
        ),
        market_boundary=PreservedSchwabBoundary(
            clock=clock,
            admissions=ordered_admissions,
            minute_files=minute_files,
            daily_files=daily_files,
        ),
        selected_entries=selected,
    )
