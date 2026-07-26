from __future__ import annotations

"""Engine-host bridge for prospective, nontransmitting Shadow Trading."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
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
from momentum_hunter.shadow_selection import (
    AutomaticShadowSelector,
    no_report_result,
)
from momentum_hunter.shadow_market_validity import (
    EASTERN_TZ,
    PersistedObservationQuoteSource,
    ShadowMarketValidityPolicy,
    entry_window_findings,
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


class ShadowWorkspaceService:
    def __init__(
        self,
        *,
        paths: ShadowWorkspacePaths | None = None,
        service: ShadowTradingService | None = None,
    ) -> None:
        self.paths = paths or ShadowWorkspacePaths.from_data_dir()
        self.service = service or ShadowTradingService(store=ShadowStateStore(self.paths.state_path))
        self.quote_source = PersistedObservationQuoteSource(
            self.paths.observations_path
        )

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

    def select_automatic(self) -> dict[str, Any]:
        report_path = latest_scheduled_trade_report_path(self.paths.reports_dir)
        if report_path is None:
            result = no_report_result()
            if self.service.sample_activation is not None and self.service.selector_is_armed():
                decision_at = now_central()
                self.service.decision_cycle_store.save_cycle(
                    {
                        "schema_version": 1,
                        "cycle_kind": "DECISION",
                        "cycle_id": stable_hash(
                            "shadow-missing-report-cycle-v1",
                            decision_at.isoformat(),
                        ),
                        "decision_at": decision_at.isoformat(),
                        "updated_at": decision_at.isoformat(),
                        "capture_succeeded": True,
                        "report_path": "",
                        "report_sha256": "",
                        "source_capture_path": "",
                        "source_capture_time": "",
                        "report_generated_at": "",
                        "selector_arm_id": (
                            self.service.selector_arm_record().arm_id
                        ),
                        "candidate_assessments": [],
                        "eligible_candidate_count": 0,
                        "benchmark_symbols": ["SPY", "IWM"],
                        "benchmark_baselines": {},
                        "market_observations": [],
                        "selected_symbol": None,
                        "selected_rank": None,
                        "opportunity_id": None,
                        "selection_quote": None,
                        "status": "NO_REPORT",
                        "reason": result.reason,
                        "shadow_trade_id": None,
                    }
                )
            return result.to_dict()
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
        received_at = received_at or now_central()
        observations = sorted(
            load_price_observations(self.paths.observations_path),
            key=lambda item: (item.timestamp, item.symbol, item.source_report),
        )
        self.service.decision_cycle_store.append_observations(
            {
                "symbol": item.symbol,
                "timestamp": item.timestamp,
                "bid": item.bid,
                "ask": item.ask,
                "last": item.price,
                "volume": item.volume,
                "source": item.source_report,
            }
            for item in observations
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
