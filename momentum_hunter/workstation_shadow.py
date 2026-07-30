from __future__ import annotations

"""Engine-host bridge for prospective, nontransmitting Shadow Trading."""

import math
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol, Sequence

from momentum_hunter.config import DATA_DIR
from momentum_hunter.monitor_targets import latest_trade_report_path
from momentum_hunter.opportunity_alerts import OPPORTUNITY_OBSERVATIONS_PATH, PriceObservation, load_price_observations
from momentum_hunter.shadow_trading import (
    SHADOW_MODE,
    SHADOW_STATE_PATH,
    ShadowQuote,
    ShadowStateStore,
    ShadowTradingService,
    shadow_trade_to_dict,
)
from momentum_hunter.shadow_selection import (
    AutomaticShadowSelector,
    no_report_result,
)
from momentum_hunter.shadow_market_validity import (
    EASTERN_TZ,
    PersistedObservationQuoteSource,
    ShadowMarketValidityPolicy,
    entry_window_findings,
    is_offset_aware,
    stable_hash,
)
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import parse_datetime


@dataclass(frozen=True)
class ShadowWorkspacePaths:
    reports_dir: Path
    observations_path: Path
    state_path: Path

    @classmethod
    def from_data_dir(cls, data_dir: Path = DATA_DIR) -> "ShadowWorkspacePaths":
        return cls(
            reports_dir=data_dir / "reports",
            observations_path=data_dir / OPPORTUNITY_OBSERVATIONS_PATH.name,
            state_path=data_dir / "shadow-trading" / SHADOW_STATE_PATH.name,
        )


class ShadowQuoteSource(Protocol):
    def quote(
        self,
        symbol: str,
        *,
        decision_at: datetime,
    ) -> dict[str, Any] | None: ...


class ShadowBatchQuoteSource(Protocol):
    def quotes(
        self,
        symbols: Sequence[str],
        *,
        decision_at: datetime,
    ) -> dict[str, dict[str, Any]]: ...


class ShadowWorkspaceService:
    def __init__(
        self,
        *,
        paths: ShadowWorkspacePaths | None = None,
        service: ShadowTradingService | None = None,
        quote_source: ShadowQuoteSource | ShadowBatchQuoteSource | None = None,
    ) -> None:
        production_defaults = paths is None and service is None
        self.paths = paths or ShadowWorkspacePaths.from_data_dir()
        self.service = service or ShadowTradingService(store=ShadowStateStore(self.paths.state_path))
        self._lock = threading.RLock()
        if quote_source is not None:
            self.quote_source = quote_source
        elif production_defaults:
            from momentum_hunter.schwab_market_data import (
                SchwabMarketDataQuoteSource,
            )

            self.quote_source = SchwabMarketDataQuoteSource()
        else:
            self.quote_source = PersistedObservationQuoteSource(
                self.paths.observations_path
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.service.snapshot()

    def start(self, symbol: str, simulation_command_id: str) -> dict[str, Any]:
        with self._lock:
            report_path = latest_trade_report_path(self.paths.reports_dir)
            if report_path is None:
                raise ValueError("No persisted trade-planning report is available for Shadow Trading.")
            trade = self.service.start_trade(
                report_path,
                symbol=symbol,
                simulation_command_id=simulation_command_id,
            )
            return {
                "mode": SHADOW_MODE,
                "state": trade.status,
                "summary": trade.last_reason,
                "trade": shadow_trade_to_dict(trade),
            }

    def select_automatic(self) -> dict[str, Any]:
        with self._lock:
            report_path = latest_scheduled_trade_report_path(self.paths.reports_dir)
            if report_path is None:
                return no_report_result().to_dict()
            return AutomaticShadowSelector(
                self.service,
                quote_source=self.quote_source,
            ).select(report_path).to_dict()

    def record_collection_attempt(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = observed_at or now_central()
        if (
            self.service.sample_activation is None
            or not self.service.selector_is_armed()
        ):
            return {"recorded": False, "status": "CONSTITUTION_NOT_ARMED"}
        if entry_window_findings(observed_at):
            return {"recorded": False, "status": "OUTSIDE_SAMPLE_WINDOW"}

        policy = ShadowMarketValidityPolicy()
        store = self.service.decision_cycle_store
        attempts = [
            item
            for item in store.load().cycles
            if item.get("cycle_kind") == "COLLECTION_ATTEMPT"
        ]
        arm = self.service.selector_arm_record()
        assert arm is not None
        baseline = (
            max(
                parse_datetime(str(item.get("decision_at", "")))
                for item in attempts
                if parse_datetime(str(item.get("decision_at", ""))) is not None
            )
            if attempts
            else parse_datetime(arm.armed_at)
        )
        assert baseline is not None
        interval = timedelta(seconds=policy.expected_cycle_interval_seconds)
        missed_at = baseline + interval
        while missed_at + interval <= observed_at:
            if not entry_window_findings(missed_at, policy):
                store.save_cycle(
                    collection_attempt_cycle(
                        missed_at,
                        arm_id=arm.arm_id,
                        constitution_hash=arm.constitution_hash,
                        status="SYSTEM_DOWNTIME",
                        reason=(
                            "No Engine Host collection attempt was recorded for "
                            "this expected in-window cycle."
                        ),
                    )
                )
            missed_at += interval

        attempt = collection_attempt_cycle(
            observed_at,
            arm_id=arm.arm_id,
            constitution_hash=arm.constitution_hash,
            status="COLLECTION_STARTED",
            reason="The Engine Host began an expected in-window collection cycle.",
        )
        store.save_cycle(attempt)
        return {
            "recorded": True,
            "status": attempt["status"],
            "cycleId": attempt["cycle_id"],
        }

    def record_collection_outcome(
        self,
        attempt_id: str,
        selection: dict[str, Any],
    ) -> dict[str, Any]:
        attempt = self.service.decision_cycle_store.get(attempt_id)
        if attempt is None or attempt.get("cycle_kind") != "COLLECTION_ATTEMPT":
            return {"recorded": False, "status": "ATTEMPT_NOT_FOUND"}
        status = str(selection.get("status") or "COLLECTION_COMPLETED")
        updated = {
            **attempt,
            "updated_at": now_central().isoformat(),
            "capture_succeeded": True,
            "report_sha256": str(selection.get("reportSha256") or ""),
            "linked_decision_cycle_id": str(
                selection.get("decisionCycleId") or ""
            ),
            "status": status,
            "reason": str(selection.get("reason") or "Collection completed."),
        }
        self.service.decision_cycle_store.save_cycle(updated)
        return {"recorded": True, "status": status, "cycleId": attempt_id}

    def record_collection_failure(
        self,
        reason: str,
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = observed_at or now_central()
        if self.service.sample_activation is None or not self.service.selector_is_armed():
            return {"recorded": False, "status": "CONSTITUTION_NOT_ARMED"}
        arm = self.service.selector_arm_record()
        assert arm is not None
        pending = [
            item
            for item in self.service.decision_cycle_store.load().cycles
            if item.get("cycle_kind") == "COLLECTION_ATTEMPT"
            and item.get("status") == "COLLECTION_STARTED"
        ]
        cycle = (
            {
                **max(pending, key=lambda item: str(item.get("decision_at", ""))),
                "updated_at": observed_at.isoformat(),
                "status": "COLLECTION_FAILED",
                "reason": reason,
            }
            if pending
            else collection_attempt_cycle(
                observed_at,
                arm_id=arm.arm_id,
                constitution_hash=arm.constitution_hash,
                status="COLLECTION_FAILED",
                reason=reason,
            )
        )
        self.service.decision_cycle_store.save_cycle(cycle)
        return {
            "recorded": True,
            "status": "COLLECTION_FAILED",
            "cycleId": cycle["cycle_id"],
        }

    def advance_observations(self, *, received_at: datetime | None = None) -> dict[str, Any]:
        with self._lock:
            return self._advance_observations_unlocked(received_at=received_at)

    def _advance_observations_unlocked(
        self,
        *,
        received_at: datetime | None = None,
    ) -> dict[str, Any]:
        received_at = received_at or now_central()
        active_symbols = {
            trade["symbol"]
            for trade in self.service.snapshot()["trades"]
            if trade["status"] in {"pending_entry", "partially_filled", "open"}
        }
        batch_loader = getattr(self.quote_source, "quotes", None)
        if callable(batch_loader):
            tracked_symbols = tracked_shadow_symbols(
                self.service,
                received_at=received_at,
                active_symbols=active_symbols,
            )
            quotes = (
                batch_loader(
                    tracked_symbols,
                    decision_at=received_at,
                )
                if tracked_symbols
                else {}
            )
            return self._advance_provider_quotes(
                quotes,
                received_at=received_at,
                active_symbols=active_symbols,
                requested_symbols=set(tracked_symbols),
            )
        observations = sorted(
            load_price_observations(self.paths.observations_path),
            key=lambda item: (item.timestamp, item.symbol, item.source_report),
        )
        trusted_observations: list[PriceObservation] = []
        for item in observations:
            quote_timestamp = trusted_quote_timestamp(item)
            if quote_timestamp is not None and quote_timestamp <= received_at:
                trusted_observations.append(item)
        self.service.decision_cycle_store.append_observations(
            {
                "symbol": item.symbol,
                "timestamp": item.quote_timestamp,
                "bid": item.bid,
                "ask": item.ask,
                "last": item.price,
                "volume": item.volume,
                "source": item.quote_source,
            }
            for item in trusted_observations
        )
        relevant_by_symbol: dict[str, PriceObservation] = {}
        for observation in trusted_observations:
            symbol = observation.symbol.upper()
            if symbol not in active_symbols:
                continue
            current = relevant_by_symbol.get(symbol)
            observation_timestamp = trusted_quote_timestamp(observation)
            current_timestamp = (
                trusted_quote_timestamp(current)
                if current is not None
                else None
            )
            if (
                current is None
                or (
                    observation_timestamp is not None
                    and current_timestamp is not None
                    and observation_timestamp > current_timestamp
                )
            ):
                relevant_by_symbol[symbol] = observation
        missing_quote_symbols: list[str] = []
        for symbol in sorted(active_symbols):
            observation = relevant_by_symbol.get(symbol)
            if observation is None:
                missing_quote_symbols.append(symbol)
                self.service.process_missing_quote(symbol, observed_at=received_at)
                continue
            if observation.bid is None or observation.ask is None:
                missing_quote_symbols.append(symbol)
                self.service.process_missing_quote(symbol, observed_at=received_at)
                continue
            self.service.process_quote(
                quote_from_price_observation(observation),
                received_at=received_at,
            )
        state = self.service.store.load()
        for trade in state.trades:
            if (
                trade.status == "completed"
                and trade.outcome is not None
                and trade.decision_cycle_id
            ):
                self.service.decision_cycle_store.finalize_counterfactuals(
                    trade.decision_cycle_id,
                    horizon_at=trade.outcome.exit_timestamp,
                )
        snapshot = self.service.snapshot()
        return {
            "mode": SHADOW_MODE,
            "observationsSeen": len(observations),
            "trustedObservationsSeen": len(trusted_observations),
            "observationsRelevant": len(relevant_by_symbol),
            "missingQuoteSymbols": missing_quote_symbols,
            "activeTradeCount": sum(
                1
                for trade in snapshot["trades"]
                if trade["status"] in {"pending_entry", "partially_filled", "open"}
            ),
            "completedTradeCount": snapshot["metrics"]["completedTradeCount"],
            "snapshot": snapshot,
        }

    def active_official_symbols(self) -> tuple[str, ...]:
        with self._lock:
            return self._active_official_symbols_unlocked()

    def _active_official_symbols_unlocked(self) -> tuple[str, ...]:
        state = self.service.store.load()
        definition = self.service.sample_definition
        return tuple(
            sorted(
                {
                    trade.symbol
                    for trade in state.trades
                    if trade.status
                    in {"pending_entry", "partially_filled", "open"}
                    and trade.sample_metadata == definition
                    and trade.sample_metadata.official_sample_authorized
                    and trade.order is not None
                }
            )
        )

    def advance_active_marks(
        self,
        *,
        received_at: datetime | None = None,
    ) -> dict[str, Any]:
        request_at = received_at or now_central()
        with self._lock:
            active_symbols = self._active_official_symbols_unlocked()
            if not active_symbols:
                return {
                    "mode": SHADOW_MODE,
                    "polled": False,
                    "providerRequestCount": 0,
                    "requestedSymbols": [],
                    "reason": (
                        "No official working FakeBroker order or active "
                        "position requires a quote."
                    ),
                    "snapshot": self.service.snapshot(),
                }
        batch_loader = getattr(self.quote_source, "quotes", None)
        if not callable(batch_loader):
            raise RuntimeError(
                "Active Shadow marking requires the canonical batch "
                "Schwab quote transport."
            )
        quotes = batch_loader(active_symbols, decision_at=request_at)
        receipt_at = received_at or now_central()
        with self._lock:
            return self._advance_active_provider_quotes(
                quotes,
                received_at=receipt_at,
                active_symbols=set(active_symbols),
            )

    def _advance_active_provider_quotes(
        self,
        quotes: dict[str, dict[str, Any]],
        *,
        received_at: datetime,
        active_symbols: set[str],
    ) -> dict[str, Any]:
        from momentum_hunter.schwab_market_data import SCHWAB_QUOTE_SOURCE

        normalized: dict[str, dict[str, Any]] = {}
        invalid_symbols: list[str] = []
        for symbol, quote in quotes.items():
            normalized_symbol = str(symbol).strip().upper()
            quote_timestamp = (
                parse_datetime(str(quote.get("timestamp", "")))
                if isinstance(quote, dict)
                else None
            )
            if (
                normalized_symbol not in active_symbols
                or not isinstance(quote, dict)
                or str(quote.get("symbol", "")).strip().upper()
                != normalized_symbol
                or str(quote.get("source", "")).strip()
                != SCHWAB_QUOTE_SOURCE
                or not is_offset_aware(quote_timestamp)
                or quote.get("bid") is None
                or quote.get("ask") is None
                or not is_finite_optional_number(quote.get("bid"))
                or not is_finite_optional_number(quote.get("ask"))
            ):
                if normalized_symbol:
                    invalid_symbols.append(normalized_symbol)
                continue
            normalized[normalized_symbol] = dict(quote)

        missing_symbols: list[str] = []
        for symbol in sorted(active_symbols):
            quote = normalized.get(symbol)
            if quote is None:
                missing_symbols.append(symbol)
                self.service.process_missing_quote(
                    symbol,
                    observed_at=received_at,
                )
                continue
            self.service.process_quote(
                shadow_quote_from_mapping(quote),
                received_at=received_at,
            )

        state = self.service.store.load()
        for trade in state.trades:
            if (
                trade.status == "completed"
                and trade.outcome is not None
                and trade.decision_cycle_id
            ):
                self.service.decision_cycle_store.finalize_counterfactuals(
                    trade.decision_cycle_id,
                    horizon_at=trade.outcome.exit_timestamp,
                )
        snapshot = self.service.snapshot()
        return {
            "mode": SHADOW_MODE,
            "polled": True,
            "providerRequestCount": 1,
            "requestedSymbols": sorted(active_symbols),
            "validQuoteSymbols": sorted(normalized),
            "missingQuoteSymbols": missing_symbols,
            "invalidQuoteSymbols": sorted(set(invalid_symbols)),
            "activeTradeCount": sum(
                1
                for trade in snapshot["trades"]
                if trade["status"]
                in {"pending_entry", "partially_filled", "open"}
            ),
            "snapshot": snapshot,
        }

    def _advance_provider_quotes(
        self,
        quotes: dict[str, dict[str, Any]],
        *,
        received_at: datetime,
        active_symbols: set[str],
        requested_symbols: set[str],
    ) -> dict[str, Any]:
        normalized: dict[str, dict[str, Any]] = {}
        invalid_quote_symbols: list[str] = []
        for symbol, quote in quotes.items():
            normalized_symbol = str(symbol).strip().upper()
            if (
                not normalized_symbol
                or normalized_symbol not in requested_symbols
                or not isinstance(quote, dict)
                or str(quote.get("symbol", "")).strip().upper()
                != normalized_symbol
                or not str(quote.get("source", "")).strip()
                or not is_offset_aware(
                    parse_datetime(str(quote.get("timestamp", "")))
                )
                or any(
                    not is_finite_optional_number(quote.get(field_name))
                    for field_name in ("bid", "ask", "last", "volume")
                )
            ):
                if normalized_symbol:
                    invalid_quote_symbols.append(normalized_symbol)
                continue
            normalized[normalized_symbol] = dict(quote)
        self.service.decision_cycle_store.append_observations(
            provider_observation(quote)
            for quote in normalized.values()
        )
        missing_quote_symbols: list[str] = []
        relevant_count = 0
        for symbol in sorted(active_symbols):
            quote = normalized.get(symbol)
            if quote is None:
                missing_quote_symbols.append(symbol)
                self.service.process_missing_quote(
                    symbol,
                    observed_at=received_at,
                )
                continue
            relevant_count += 1
            if quote.get("bid") is None or quote.get("ask") is None:
                missing_quote_symbols.append(symbol)
                self.service.process_missing_quote(
                    symbol,
                    observed_at=received_at,
                )
                continue
            self.service.process_quote(
                shadow_quote_from_mapping(quote),
                received_at=received_at,
            )
        state = self.service.store.load()
        for trade in state.trades:
            if (
                trade.status == "completed"
                and trade.outcome is not None
                and trade.decision_cycle_id
            ):
                self.service.decision_cycle_store.finalize_counterfactuals(
                    trade.decision_cycle_id,
                    horizon_at=trade.outcome.exit_timestamp,
                )
        snapshot = self.service.snapshot()
        return {
            "mode": SHADOW_MODE,
            "observationsSeen": len(normalized),
            "trustedObservationsSeen": len(normalized),
            "observationsRelevant": relevant_count,
            "missingQuoteSymbols": missing_quote_symbols,
            "invalidQuoteSymbols": sorted(set(invalid_quote_symbols)),
            "activeTradeCount": sum(
                1
                for trade in snapshot["trades"]
                if trade["status"] in {"pending_entry", "partially_filled", "open"}
            ),
            "completedTradeCount": snapshot["metrics"]["completedTradeCount"],
            "snapshot": snapshot,
        }


def quote_from_price_observation(observation: PriceObservation) -> ShadowQuote:
    observed_at = trusted_quote_timestamp(observation)
    if observed_at is None:
        raise ValueError(
            "A provider quote timestamp and provider source are required for Shadow Trading."
        )
    return ShadowQuote(
        symbol=observation.symbol,
        timestamp=observation.quote_timestamp,
        bid=observation.bid,
        ask=observation.ask,
        last=observation.price,
        volume=observation.volume,
        session=session_for_timestamp(observation.quote_timestamp),
        trading_state="tradable",
        source=observation.quote_source,
    )


def trusted_quote_timestamp(observation: PriceObservation) -> datetime | None:
    if not observation.quote_source.strip():
        return None
    observed_at = parse_datetime(observation.quote_timestamp)
    return observed_at if is_offset_aware(observed_at) else None


def tracked_shadow_symbols(
    service: ShadowTradingService,
    *,
    received_at: datetime,
    active_symbols: set[str],
) -> tuple[str, ...]:
    symbols = set(active_symbols)
    received_date = received_at.astimezone(EASTERN_TZ).date()
    for cycle in service.decision_cycle_store.load().cycles:
        if cycle.get("cycle_kind") != "DECISION":
            continue
        decision_at = parse_datetime(str(cycle.get("decision_at", "")))
        if (
            not is_offset_aware(decision_at)
            or decision_at.astimezone(EASTERN_TZ).date() != received_date
        ):
            continue
        symbols.update(
            str(item.get("symbol", "")).strip().upper()
            for item in cycle.get("candidate_assessments", [])
            if isinstance(item, dict) and item.get("eligible") is True
        )
        symbols.update(
            str(item).strip().upper()
            for item in cycle.get("benchmark_symbols", [])
        )
    return tuple(sorted(symbol for symbol in symbols if symbol))


def provider_observation(quote: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(quote.get("symbol", "")).strip().upper(),
        "timestamp": str(quote.get("timestamp", "")),
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "last": quote.get("last"),
        "volume": quote.get("volume"),
        "source": str(quote.get("source", "")),
    }


def shadow_quote_from_mapping(quote: dict[str, Any]) -> ShadowQuote:
    return ShadowQuote(
        symbol=str(quote.get("symbol", "")).strip().upper(),
        timestamp=str(quote.get("timestamp", "")),
        bid=quote.get("bid"),
        ask=quote.get("ask"),
        last=quote.get("last"),
        volume=quote.get("volume"),
        session=str(quote.get("session", "")),
        trading_state=str(quote.get("trading_state", "")),
        source=str(quote.get("source", "")),
        provider_quote_timestamp=str(
            quote.get("provider_quote_timestamp", "")
        ),
        provider_bid_timestamp=str(
            quote.get("provider_bid_timestamp", "")
        ),
        provider_ask_timestamp=str(
            quote.get("provider_ask_timestamp", "")
        ),
        realtime=(
            quote.get("realtime")
            if isinstance(quote.get("realtime"), bool)
            else None
        ),
        security_status=str(quote.get("security_status", "")),
    )


def is_finite_optional_number(value: object) -> bool:
    return (
        value is None
        or (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    )


def collection_attempt_cycle(
    observed_at: datetime,
    *,
    arm_id: str,
    constitution_hash: str,
    status: str,
    reason: str,
) -> dict[str, Any]:
    cycle_id = stable_hash(
        "shadow-collection-attempt-v1",
        observed_at.isoformat(),
    )
    return {
        "schema_version": 1,
        "cycle_kind": "COLLECTION_ATTEMPT",
        "cycle_id": cycle_id,
        "decision_at": observed_at.isoformat(),
        "updated_at": observed_at.isoformat(),
        "capture_succeeded": status not in {
            "COLLECTION_STARTED",
            "COLLECTION_FAILED",
            "SYSTEM_DOWNTIME",
        },
        "report_path": "",
        "report_sha256": "",
        "source_capture_path": "",
        "source_capture_time": "",
        "report_generated_at": "",
        "selector_arm_id": arm_id,
        "constitution_hash": constitution_hash,
        "candidate_assessments": [],
        "eligible_candidate_count": 0,
        "benchmark_symbols": ["SPY", "IWM"],
        "benchmark_baselines": {},
        "market_observations": [],
        "counterfactual_marks": [],
        "selected_symbol": None,
        "selected_rank": None,
        "opportunity_id": None,
        "selection_quote": None,
        "linked_decision_cycle_id": "",
        "status": status,
        "reason": reason,
        "shadow_trade_id": None,
    }


def session_for_timestamp(timestamp: str) -> str:
    observed_at = parse_datetime(timestamp)
    if observed_at is None:
        return "unknown"
    current = observed_at.astimezone(EASTERN_TZ).timetz().replace(tzinfo=None)
    return "regular" if time(9, 30) <= current < time(16, 0) else "extended"


def latest_scheduled_trade_report_path(reports_dir: Path) -> Path | None:
    if not reports_dir.exists():
        return None
    reports = list(reports_dir.glob("trade-plan-briefing-*.json"))
    if not reports:
        return None
    return max(reports, key=lambda path: path.stat().st_mtime)
