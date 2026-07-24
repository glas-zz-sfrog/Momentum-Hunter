from __future__ import annotations

"""Engine-host bridge for prospective, nontransmitting Shadow Trading."""

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

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


class ShadowWorkspaceService:
    def __init__(
        self,
        *,
        paths: ShadowWorkspacePaths | None = None,
        service: ShadowTradingService | None = None,
    ) -> None:
        self.paths = paths or ShadowWorkspacePaths.from_data_dir()
        self.service = service or ShadowTradingService(store=ShadowStateStore(self.paths.state_path))

    def snapshot(self) -> dict[str, Any]:
        return self.service.snapshot()

    def start(self, symbol: str, simulation_command_id: str) -> dict[str, Any]:
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

    def advance_observations(self, *, received_at: datetime | None = None) -> dict[str, Any]:
        received_at = received_at or now_central()
        observations = sorted(
            load_price_observations(self.paths.observations_path),
            key=lambda item: (item.timestamp, item.symbol, item.source_report),
        )
        active_symbols = {
            trade["symbol"]
            for trade in self.service.snapshot()["trades"]
            if trade["status"] in {"pending_entry", "partially_filled", "open"}
        }
        relevant = [item for item in observations if item.symbol in active_symbols]
        for observation in relevant:
            if observation.bid is None or observation.ask is None:
                self.service.process_missing_quote(observation.symbol, observed_at=received_at)
                continue
            self.service.process_quote(
                quote_from_price_observation(observation),
                received_at=received_at,
            )
        snapshot = self.service.snapshot()
        return {
            "mode": SHADOW_MODE,
            "observationsSeen": len(observations),
            "observationsRelevant": len(relevant),
            "activeTradeCount": sum(
                1
                for trade in snapshot["trades"]
                if trade["status"] in {"pending_entry", "partially_filled", "open"}
            ),
            "completedTradeCount": snapshot["metrics"]["completedTradeCount"],
            "snapshot": snapshot,
        }


def quote_from_price_observation(observation: PriceObservation) -> ShadowQuote:
    return ShadowQuote(
        symbol=observation.symbol,
        timestamp=observation.timestamp,
        bid=observation.bid,
        ask=observation.ask,
        last=observation.price,
        volume=observation.volume,
        session=session_for_timestamp(observation.timestamp),
        trading_state="tradable",
        source=observation.source_report or "opportunity_price_observation",
    )


def session_for_timestamp(timestamp: str) -> str:
    observed_at = parse_datetime(timestamp)
    if observed_at is None:
        return "unknown"
    current = observed_at.timetz().replace(tzinfo=None)
    return "regular" if time(8, 30) <= current < time(15, 0) else "extended"
