"""Bounded canonical-candle readiness for opening TradePlan production."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.automatic_candle_backfill import (
    DEFAULT_AUTOMATION_MANIFEST_PATH,
    expected_account_ending_from_manifest,
)
from momentum_hunter.canonical_candle_evidence import (
    CanonicalCandleEvidenceError,
    CanonicalMinuteBar,
    load_canonical_minute_bars,
)
from momentum_hunter.schwab_candle_backfill import (
    CandleBackfillOptions,
    SchwabHistoricalCandleBackfiller,
)
from momentum_hunter.schwab_candle_collector import CandleSymbolUniverse
from momentum_hunter.schwab_candle_contract import EASTERN_TZ, normalize_symbols
from momentum_hunter.schwab_candle_observer import SchwabCandleHttpTransport
from momentum_hunter.schwab_candle_store import SCHWAB_CANDLE_STORE_ROOT, SchwabCandleStore
from momentum_hunter.schwab_daily_candle_store import (
    SCHWAB_DAILY_CANDLE_STORE_ROOT,
    SchwabDailyCandleStore,
)
from momentum_hunter.time_normalized_rvol import (
    TimeNormalizedRvolEvidence,
    calculate_time_normalized_rvol,
    unavailable_rvol_evidence,
)


OPENING_CANDLE_READINESS_SCHEMA_VERSION = 1
OPENING_CANDLE_READINESS_PROFILE = "opening-candle-readiness-v1"
OPENING_CANDLE_READY = "READY"
OPENING_CANDLE_TIMEOUT = "CANONICAL_CANDLE_READINESS_TIMEOUT"
OPENING_CANDLE_BACKFILL_FAILED = "CANONICAL_CANDLE_BACKFILL_FAILED"
MAX_OPENING_SYMBOLS = 5
REQUIRED_OPENING_BARS = 5
OPENING_HISTORY_HTTP_TIMEOUT = (3.0, 8.0)


@dataclass(frozen=True)
class OpeningCandleReadinessResult:
    status: str
    evidence_as_of: str
    attempts: tuple[Mapping[str, object], ...]
    symbol_evidence: Mapping[str, Mapping[str, object]]
    findings: tuple[str, ...]
    bars_by_symbol: Mapping[str, tuple[CanonicalMinuteBar, ...]]
    rvol_by_symbol: Mapping[str, TimeNormalizedRvolEvidence]

    @property
    def ready(self) -> bool:
        return self.status == OPENING_CANDLE_READY

    def to_evidence(self) -> dict[str, object]:
        return {
            "schemaVersion": OPENING_CANDLE_READINESS_SCHEMA_VERSION,
            "profile": OPENING_CANDLE_READINESS_PROFILE,
            "status": self.status,
            "evidenceAsOf": self.evidence_as_of,
            "attemptCount": len(self.attempts),
            "attempts": [dict(item) for item in self.attempts],
            "symbols": {
                symbol: dict(self.symbol_evidence[symbol])
                for symbol in sorted(self.symbol_evidence)
            },
            "findings": list(self.findings),
            "networkBounded": True,
            "sourceCaptureMutated": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }


class OpeningCandleReadinessCoordinator:
    """Backfill and inspect a fixed opening evidence window with finite retries."""

    def __init__(
        self,
        *,
        run_backfill: Callable[[], Mapping[str, object]],
        inspect_store: Callable[
            [tuple[str, ...], datetime],
            tuple[
                Mapping[str, tuple[CanonicalMinuteBar, ...]],
                Mapping[str, TimeNormalizedRvolEvidence],
                Mapping[str, Mapping[str, object]],
                tuple[str, ...],
            ],
        ],
        sleep: Callable[[float], None] = time.sleep,
        maximum_attempts: int = 3,
        retry_delays: Sequence[float] = (10.0, 25.0),
    ) -> None:
        if not 1 <= maximum_attempts <= 3:
            raise ValueError("Opening candle readiness allows one to three attempts.")
        if any(float(value) < 0 for value in retry_delays):
            raise ValueError("Opening candle readiness retry delays cannot be negative.")
        self.run_backfill = run_backfill
        self.inspect_store = inspect_store
        self.sleep = sleep
        self.maximum_attempts = maximum_attempts
        self.retry_delays = tuple(float(value) for value in retry_delays)

    def prepare(
        self,
        symbols: Sequence[str],
        *,
        evidence_as_of: datetime,
    ) -> OpeningCandleReadinessResult:
        normalized = tuple(normalize_symbols(tuple(symbols)))
        if not normalized or len(normalized) > MAX_OPENING_SYMBOLS:
            raise ValueError("Opening candle readiness requires one to five symbols.")
        _require_aware(evidence_as_of)

        attempts: list[Mapping[str, object]] = []
        failures: list[str] = []
        snapshot = self.inspect_store(normalized, evidence_as_of)
        if _snapshot_ready(snapshot[2]):
            return _result(
                OPENING_CANDLE_READY,
                evidence_as_of,
                attempts,
                snapshot,
                ("CANONICAL_OPENING_EVIDENCE_ALREADY_READY",),
            )

        for attempt_number in range(1, self.maximum_attempts + 1):
            try:
                backfill = self.run_backfill()
                backfill_status = str(backfill.get("status", "UNKNOWN"))
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "status": backfill_status,
                        "resultFingerprint": str(backfill.get("resultFingerprint", "")),
                        "findings": list(backfill.get("findings", [])),
                    }
                )
            except Exception as exc:  # The opening decision remains fail-closed.
                failure = f"BACKFILL_ATTEMPT_FAILED:{type(exc).__name__}"
                failures.append(failure)
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "status": "FAILED",
                        "error": type(exc).__name__,
                    }
                )

            snapshot = self.inspect_store(normalized, evidence_as_of)
            if _snapshot_ready(snapshot[2]):
                return _result(
                    OPENING_CANDLE_READY,
                    evidence_as_of,
                    attempts,
                    snapshot,
                    ("CANONICAL_OPENING_EVIDENCE_READY",),
                )
            if attempt_number < self.maximum_attempts:
                delay_index = min(attempt_number - 1, len(self.retry_delays) - 1)
                delay = self.retry_delays[delay_index] if self.retry_delays else 0.0
                self.sleep(delay)

        terminal_status = (
            OPENING_CANDLE_BACKFILL_FAILED
            if len(failures) == self.maximum_attempts
            else OPENING_CANDLE_TIMEOUT
        )
        return _result(
            terminal_status,
            evidence_as_of,
            attempts,
            snapshot,
            tuple([*failures, terminal_status]),
        )


def prepare_opening_candle_readiness(
    symbols: Sequence[str],
    *,
    evidence_as_of: datetime,
    manifest_path: Path = DEFAULT_AUTOMATION_MANIFEST_PATH,
    minute_store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
    daily_store_root: Path = SCHWAB_DAILY_CANDLE_STORE_ROOT,
    sleep: Callable[[float], None] = time.sleep,
) -> OpeningCandleReadinessResult:
    """Use the guarded Schwab history path to make opening evidence available."""

    normalized = tuple(normalize_symbols(tuple(symbols)))
    if not normalized or len(normalized) > MAX_OPENING_SYMBOLS:
        raise ValueError("Opening candle readiness requires one to five symbols.")
    ending = expected_account_ending_from_manifest(manifest_path)
    universe = CandleSymbolUniverse(
        symbols=normalized,
        sources_by_symbol={symbol: ("OPENING_CANDIDATE",) for symbol in normalized},
        excluded_symbols=(),
        warnings=(),
        input_fingerprints={},
    )
    backfiller = SchwabHistoricalCandleBackfiller(
        minute_store=SchwabCandleStore(minute_store_root),
        daily_store=SchwabDailyCandleStore(daily_store_root),
        http_transport=SchwabCandleHttpTransport(
            timeout=OPENING_HISTORY_HTTP_TIMEOUT,
        ),
        sleep=sleep,
    )
    options = CandleBackfillOptions(
        expected_account_ending=ending,
        history_attempts=1,
    )
    coordinator = OpeningCandleReadinessCoordinator(
        run_backfill=lambda: backfiller.backfill(universe, options),
        inspect_store=lambda wanted, as_of: inspect_opening_candle_store(
            wanted,
            evidence_as_of=as_of,
            minute_store_root=minute_store_root,
        ),
        sleep=sleep,
    )
    return coordinator.prepare(normalized, evidence_as_of=evidence_as_of)


def failed_opening_candle_readiness(
    symbols: Sequence[str],
    *,
    evidence_as_of: datetime,
    finding: str,
) -> OpeningCandleReadinessResult:
    """Create explicit ineligible evidence when readiness setup fails."""

    normalized = tuple(normalize_symbols(tuple(symbols)))
    if not normalized or len(normalized) > MAX_OPENING_SYMBOLS:
        raise ValueError("Opening candle readiness requires one to five symbols.")
    _require_aware(evidence_as_of)
    rvol = {
        symbol: unavailable_rvol_evidence(
            symbol,
            as_of=evidence_as_of,
            finding=finding,
        )
        for symbol in normalized
    }
    symbol_evidence = {
        symbol: {
            "status": "INVALID",
            "openingBarCount": 0,
            "requiredOpeningBarCount": REQUIRED_OPENING_BARS,
            "rvolStatus": evidence.status,
            "currentBarCount": evidence.current_bar_count,
            "expectedCurrentBarCount": evidence.expected_current_bar_count,
            "baselineSessionCount": evidence.baseline_session_count,
            "minimumBaselineSessions": evidence.minimum_baseline_sessions,
            "findings": list(evidence.findings),
        }
        for symbol, evidence in rvol.items()
    }
    return OpeningCandleReadinessResult(
        status=OPENING_CANDLE_BACKFILL_FAILED,
        evidence_as_of=evidence_as_of.isoformat(),
        attempts=(),
        symbol_evidence=symbol_evidence,
        findings=(finding, OPENING_CANDLE_BACKFILL_FAILED),
        bars_by_symbol={symbol: () for symbol in normalized},
        rvol_by_symbol=rvol,
    )


def inspect_opening_candle_store(
    symbols: Sequence[str],
    *,
    evidence_as_of: datetime,
    minute_store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
) -> tuple[
    Mapping[str, tuple[CanonicalMinuteBar, ...]],
    Mapping[str, TimeNormalizedRvolEvidence],
    Mapping[str, Mapping[str, object]],
    tuple[str, ...],
]:
    normalized = tuple(normalize_symbols(tuple(symbols)))
    _require_aware(evidence_as_of)
    try:
        loaded = load_canonical_minute_bars(
            store_root=minute_store_root,
            symbols=list(normalized),
        )
    except CanonicalCandleEvidenceError:
        return {}, {}, {
            symbol: {
                "status": "INVALID",
                "openingBarCount": 0,
                "requiredOpeningBarCount": REQUIRED_OPENING_BARS,
                "rvolStatus": "EXECUTION_INELIGIBLE",
                "findings": ["CANONICAL_CANDLE_EVIDENCE_INVALID"],
            }
            for symbol in normalized
        }, ("CANONICAL_CANDLE_EVIDENCE_INVALID",)

    eastern = evidence_as_of.astimezone(EASTERN_TZ)
    session_date = eastern.date().isoformat()
    expected_minutes = {
        eastern.replace(hour=9, minute=30 + offset, second=0, microsecond=0).isoformat()
        for offset in range(REQUIRED_OPENING_BARS)
    }
    bars_by_symbol: dict[str, tuple[CanonicalMinuteBar, ...]] = {}
    rvol_by_symbol: dict[str, TimeNormalizedRvolEvidence] = {}
    symbol_evidence: dict[str, Mapping[str, object]] = {}
    aggregate_findings: list[str] = []
    for symbol in normalized:
        bars = tuple(loaded.get(symbol, ()))
        bars_by_symbol[symbol] = bars
        opening_minutes = {
            datetime.fromisoformat(bar.timestamp).astimezone(EASTERN_TZ).isoformat()
            for bar in bars
            if bar.session_date == session_date
            and datetime.fromisoformat(bar.timestamp).astimezone(EASTERN_TZ).isoformat()
            in expected_minutes
        }
        rvol = calculate_time_normalized_rvol(
            symbol,
            bars,
            as_of=evidence_as_of,
        )
        rvol_by_symbol[symbol] = rvol
        findings = list(rvol.findings)
        if opening_minutes != expected_minutes:
            findings.append("OPENING_RANGE_FIVE_COMPLETED_BARS_REQUIRED")
        status = (
            OPENING_CANDLE_READY
            if len(opening_minutes) == REQUIRED_OPENING_BARS and rvol.execution_eligible
            else "WAITING"
        )
        symbol_evidence[symbol] = {
            "status": status,
            "openingBarCount": len(opening_minutes),
            "requiredOpeningBarCount": REQUIRED_OPENING_BARS,
            "rvolStatus": rvol.status,
            "currentBarCount": rvol.current_bar_count,
            "expectedCurrentBarCount": rvol.expected_current_bar_count,
            "baselineSessionCount": rvol.baseline_session_count,
            "minimumBaselineSessions": rvol.minimum_baseline_sessions,
            "findings": sorted(set(findings)),
        }
        aggregate_findings.extend(f"{symbol}:{item}" for item in findings)
    return (
        bars_by_symbol,
        rvol_by_symbol,
        symbol_evidence,
        tuple(sorted(set(aggregate_findings))),
    )


def _snapshot_ready(symbol_evidence: Mapping[str, Mapping[str, object]]) -> bool:
    return bool(symbol_evidence) and all(
        str(item.get("status")) == OPENING_CANDLE_READY
        for item in symbol_evidence.values()
    )


def _result(
    status: str,
    evidence_as_of: datetime,
    attempts: Sequence[Mapping[str, object]],
    snapshot: tuple[
        Mapping[str, tuple[CanonicalMinuteBar, ...]],
        Mapping[str, TimeNormalizedRvolEvidence],
        Mapping[str, Mapping[str, object]],
        tuple[str, ...],
    ],
    findings: Sequence[str],
) -> OpeningCandleReadinessResult:
    bars, rvol, symbol_evidence, snapshot_findings = snapshot
    return OpeningCandleReadinessResult(
        status=status,
        evidence_as_of=evidence_as_of.isoformat(),
        attempts=tuple(dict(item) for item in attempts),
        symbol_evidence=dict(symbol_evidence),
        findings=tuple(sorted(set([*findings, *snapshot_findings]))),
        bars_by_symbol=dict(bars),
        rvol_by_symbol=dict(rvol),
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Opening candle readiness time must include a UTC offset.")
