from __future__ import annotations

"""Prospective, persistent Shadow Trading using supplied evidence and FakeBroker rules.

This module never fetches market data and never connects to a broker. Callers freeze a
persisted TradePlan candidate, then feed later quote observations to advance the
simulated order and position.
"""

import argparse
import hashlib
import json
import math
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from momentum_hunter.autonomy.auditor import AuditFinding, AuditReport, audit_execution_ledger
from momentum_hunter.autonomy.ledger import ExecutionLedger, ExecutionLedgerEvent
from momentum_hunter.autonomy.risk_governor import RiskGovernorResult, evaluate_trade_plan
from momentum_hunter.autonomy.view_models import candidate_plan_from_report_row, stable_trade_plan_id
from momentum_hunter.config import DATA_DIR
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import TradePlan, parse_datetime


SHADOW_SCHEMA_VERSION = 1
SHADOW_MODE = "PAPER SHADOW / NONTRANSMITTING"
SHADOW_ENGINE_VERSION = "shadow_trading_v1"
SHADOW_STATE_PATH = DATA_DIR / "shadow-trading" / "shadow-trading-state.json"
SHADOW_REPORTS_DIR = DATA_DIR / "reports"
MIN_MEANINGFUL_SAMPLE_SIZE = 30
TERMINAL_TRADE_STATES = {"completed", "blocked", "entry_rejected", "cancelled", "ambiguous_exit"}
ACTIVE_TRADE_STATES = {"pending_entry", "partially_filled", "open"}
TRADABLE_STATES = {"tradable", "open"}


@dataclass(frozen=True)
class ShadowExecutionPolicy:
    slippage_bps: float = 5.0
    max_quote_age_seconds: int = 90
    minimum_fill_delay_seconds: int = 1
    allow_extended_hours: bool = False
    max_spread_percent: float = 3.0
    buying_power: float = 100_000.0
    max_open_positions: int = 3
    daily_loss_limit: float = 500.0


@dataclass(frozen=True)
class ShadowQuote:
    symbol: str
    timestamp: str
    bid: float | None
    ask: float | None
    last: float | None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    available_size: int | None = None
    session: str = "regular"
    trading_state: str = "tradable"
    source: str = "supplied_quote"


@dataclass(frozen=True)
class ShadowEvidenceSnapshot:
    evidence_snapshot_id: str
    candidate_id: str
    decision_timestamp: str
    source_path: str
    source_sha256: str
    source_generated_at: str
    source_capture_path: str
    source_capture_time: str
    candidate_json: str
    source_report_json: str

    def candidate_payload(self) -> dict[str, Any]:
        payload = json.loads(self.candidate_json)
        return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class ShadowOrder:
    order_id: str
    shadow_trade_id: str
    symbol: str
    side: str
    quantity: int
    remaining_quantity: int
    order_type: str
    limit_price: float
    status: str
    submitted_at: str
    filled_quantity: int = 0
    average_fill_price: float | None = None
    last_update_at: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ShadowPosition:
    position_id: str
    shadow_trade_id: str
    symbol: str
    quantity: int
    average_entry_price: float
    opened_at: str
    stop_price: float
    target_price: float
    highest_price: float
    lowest_price: float


@dataclass(frozen=True)
class ShadowOutcome:
    outcome_id: str
    shadow_trade_id: str
    status: str
    classification: str
    exit_timestamp: str
    exit_reason: str
    exit_price: float
    gross_pnl: float
    executable_pnl: float
    r_multiple: float | None
    mfe_dollars: float
    mae_dollars: float
    mfe_percent: float
    mae_percent: float
    duration_seconds: int


@dataclass(frozen=True)
class ShadowOrderTicket:
    shadow_order_id: str
    generated_timestamp: str
    environment: str
    symbol: str
    side: str
    quantity: int
    order_type: str
    limit_price: float
    duration: str
    session: str
    maximum_notional: float
    trade_plan_id: str
    risk_decision: str
    evidence_snapshot_id: str
    plan_fingerprint: str
    exact_ticket_entered: str = ""
    operator_modifications: str = ""
    paper_money_result: str = ""
    paper_money_fill_price: float | None = None
    paper_money_exit: str = ""
    paper_money_outcome: str = ""
    reconciliation_notes: str = ""


@dataclass(frozen=True)
class ShadowTrade:
    shadow_trade_id: str
    simulation_command_id: str
    candidate_id: str
    evidence_snapshot_id: str
    trade_plan_id: str
    risk_decision_id: str
    outcome_id: str
    symbol: str
    candidate_rank: int
    candidate_score: int
    setup_type: str
    catalyst: str
    market_regime: str
    decision_timestamp: str
    plan_fingerprint: str
    trade_plan_json: str
    risk_result_json: str
    evidence: ShadowEvidenceSnapshot
    status: str
    data_quality_state: str
    risk_rejection_reasons: tuple[str, ...] = ()
    order: ShadowOrder | None = None
    position: ShadowPosition | None = None
    outcome: ShadowOutcome | None = None
    ticket: ShadowOrderTicket | None = None
    ledger_events: tuple[ExecutionLedgerEvent, ...] = ()
    processed_observation_ids: tuple[str, ...] = ()
    last_observation_timestamp: str = ""
    last_reason: str = ""

    def trade_plan(self) -> TradePlan:
        return TradePlan(**json.loads(self.trade_plan_json))

    def risk_result_payload(self) -> dict[str, Any]:
        payload = json.loads(self.risk_result_json)
        return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class ShadowCommandReceipt:
    command_id: str
    request_fingerprint: str
    shadow_trade_id: str


@dataclass(frozen=True)
class ShadowTradingState:
    schema_version: int = SHADOW_SCHEMA_VERSION
    engine_version: str = SHADOW_ENGINE_VERSION
    updated_at: str = ""
    trades: tuple[ShadowTrade, ...] = ()
    command_receipts: tuple[ShadowCommandReceipt, ...] = ()


class ShadowStateError(RuntimeError):
    pass


class ShadowStateStore:
    def __init__(self, path: Path = SHADOW_STATE_PATH) -> None:
        self.path = path

    def load(self) -> ShadowTradingState:
        if not self.path.exists():
            return ShadowTradingState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShadowStateError(f"Shadow state cannot be loaded: {type(exc).__name__}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != SHADOW_SCHEMA_VERSION:
            raise ShadowStateError("Shadow state has an unsupported or missing schema version.")
        return shadow_state_from_dict(payload)

    def save(self, state: ShadowTradingState) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = shadow_state_to_dict(replace(state, updated_at=now_central().isoformat()))
        temporary = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)
        return self.path


class ProspectiveFakeBroker:
    """Conservative quote-driven FakeBroker rules for Shadow Trading only."""

    def __init__(self, policy: ShadowExecutionPolicy) -> None:
        self.policy = policy

    def validate_quote(self, quote: ShadowQuote, *, received_at: datetime) -> str:
        observed_at = parse_datetime(quote.timestamp)
        if observed_at is None:
            return "Quote timestamp is missing or invalid."
        if observed_at > received_at:
            return "Quote timestamp is later than the receiving clock."
        age_seconds = (received_at - observed_at).total_seconds()
        if age_seconds > self.policy.max_quote_age_seconds:
            return f"Quote is stale by {int(age_seconds)} seconds."
        if quote.trading_state.lower() not in TRADABLE_STATES:
            return f"Trading state is unavailable: {quote.trading_state or 'unknown'}."
        if quote.session.lower() != "regular" and not self.policy.allow_extended_hours:
            return f"Session is not eligible for Shadow Trading: {quote.session or 'unknown'}."
        if quote.bid is None or quote.ask is None:
            return "Quote is missing bid or ask."
        if quote.bid <= 0 or quote.ask <= 0 or quote.ask < quote.bid:
            return "Quote bid/ask values are invalid or crossed."
        spread_percent = (quote.ask - quote.bid) / quote.ask * 100
        if spread_percent > self.policy.max_spread_percent:
            return f"Quote spread {spread_percent:.2f}% exceeds the Shadow Trading limit."
        return ""

    def fill_entry(
        self,
        order: ShadowOrder,
        quote: ShadowQuote,
        *,
        received_at: datetime,
        committed_notional: float,
        open_position_count: int,
        realized_pnl_today: float,
    ) -> tuple[ShadowOrder, ShadowPosition | None, str]:
        reason = self.validate_quote(quote, received_at=received_at)
        if reason:
            return order, None, reason
        quote_time = require_datetime(quote.timestamp, "quote timestamp")
        submitted_at = require_datetime(order.submitted_at, "order timestamp")
        if (quote_time - submitted_at).total_seconds() < self.policy.minimum_fill_delay_seconds:
            return order, None, "Waiting for the configured prospective fill delay."
        if realized_pnl_today <= -abs(self.policy.daily_loss_limit):
            rejected = replace(order, status="rejected", last_update_at=quote.timestamp, reason="Daily loss limit reached.")
            return rejected, None, rejected.reason
        if open_position_count >= self.policy.max_open_positions:
            rejected = replace(order, status="rejected", last_update_at=quote.timestamp, reason="Position concurrency limit reached.")
            return rejected, None, rejected.reason
        required_notional = order.remaining_quantity * order.limit_price
        if committed_notional + required_notional > self.policy.buying_power:
            rejected = replace(order, status="rejected", last_update_at=quote.timestamp, reason="Shadow buying power is insufficient.")
            return rejected, None, rejected.reason
        assert quote.ask is not None
        if quote.ask > order.limit_price:
            return order, None, "Limit order remains unfilled because the executable ask is above the limit."
        executable_price = apply_basis_points(quote.ask, self.policy.slippage_bps)
        if executable_price > order.limit_price:
            return order, None, "Limit order remains unfilled after applying simulated slippage."
        available = order.remaining_quantity if quote.available_size is None else max(0, quote.available_size)
        fill_quantity = min(order.remaining_quantity, available)
        if fill_quantity <= 0:
            return order, None, "Limit order remains unfilled because no executable size is available."
        total_filled = order.filled_quantity + fill_quantity
        previous_cost = (order.average_fill_price or 0.0) * order.filled_quantity
        average_fill = round_price((previous_cost + executable_price * fill_quantity) / total_filled)
        remaining = order.quantity - total_filled
        status = "filled" if remaining == 0 else "partially_filled"
        updated_order = replace(
            order,
            remaining_quantity=remaining,
            status=status,
            filled_quantity=total_filled,
            average_fill_price=average_fill,
            last_update_at=quote.timestamp,
            reason="Prospective FakeBroker fill from executable ask with configured slippage.",
        )
        position = ShadowPosition(
            position_id=stable_id("shadow-position", order.shadow_trade_id),
            shadow_trade_id=order.shadow_trade_id,
            symbol=order.symbol,
            quantity=total_filled,
            average_entry_price=average_fill,
            opened_at=quote.timestamp,
            stop_price=0.0,
            target_price=0.0,
            highest_price=average_fill,
            lowest_price=average_fill,
        )
        return updated_order, position, ""

    def executable_exit_price(self, quote: ShadowQuote, *, reason: str) -> float:
        assert quote.bid is not None
        return max(0.0, apply_basis_points(quote.bid, -self.policy.slippage_bps))


class ShadowTradingService:
    def __init__(
        self,
        *,
        store: ShadowStateStore | None = None,
        policy: ShadowExecutionPolicy | None = None,
    ) -> None:
        self.store = store or ShadowStateStore()
        self.policy = policy or ShadowExecutionPolicy()
        self.fake_broker = ProspectiveFakeBroker(self.policy)

    def start_trade(
        self,
        report_path: Path,
        *,
        symbol: str,
        simulation_command_id: str,
        decision_at: datetime | None = None,
    ) -> ShadowTrade:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("A non-empty symbol is required.")
        if not simulation_command_id.strip():
            raise ValueError("A stable simulation command ID is required.")
        source_bytes = report_path.read_bytes()
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        try:
            source_report_json = source_bytes.decode("utf-8")
            report = json.loads(source_report_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("The trade-planning report is not valid JSON.") from exc
        if not isinstance(report, dict):
            raise ValueError("The trade-planning report must contain an object.")
        rows = report.get("candidates") or report.get("top_5_for_capital") or []
        matches = [(index, row) for index, row in enumerate(rows, 1) if isinstance(row, dict) and str(row.get("symbol", "")).upper() == normalized_symbol]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one persisted candidate row for {normalized_symbol}; found {len(matches)}.")
        rank, row = matches[0]
        metadata = report.get("metadata", {}) if isinstance(report.get("metadata"), dict) else {}
        candidate = candidate_plan_from_report_row(
            row,
            rank=rank,
            source_name=report_path.name,
            source_path=str(report_path),
            source_generated_at=str(metadata.get("generated_at", "")),
        )
        if candidate is None:
            raise ValueError(f"{normalized_symbol} does not contain a valid persisted TradePlan.")
        decision_at = decision_at or now_central()
        canonical_candidate = canonical_json(row)
        source_capture_key = "|".join(
            [
                str(metadata.get("source_capture_path", "")),
                str(metadata.get("source_capture_time", "")),
                normalized_symbol,
                str(rank),
            ]
        )
        candidate_id = stable_id("candidate", source_capture_key, source_sha, canonical_candidate)
        evidence_snapshot_id = stable_id("evidence", source_sha, canonical_candidate, decision_at.isoformat())
        plan_payload = asdict(candidate.trade_plan)
        plan_json = canonical_json(plan_payload)
        plan_fingerprint = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
        trade_plan_id = stable_trade_plan_id(normalized_symbol, candidate.trade_plan)
        risk_seed = stable_id("risk", evidence_snapshot_id, trade_plan_id)
        evaluated_risk = evaluate_trade_plan(
            candidate.trade_plan,
            ticker=normalized_symbol,
            trade_plan_id=trade_plan_id,
            checked_at=decision_at,
        )
        risk = replace(evaluated_risk, result_id=risk_seed)
        risk_json = canonical_json(risk_result_to_dict(risk))
        request_fingerprint = stable_id("shadow-request", source_sha, normalized_symbol, plan_fingerprint)
        state = self.store.load()
        existing_receipt = next((item for item in state.command_receipts if item.command_id == simulation_command_id), None)
        if existing_receipt is not None:
            if existing_receipt.request_fingerprint != request_fingerprint:
                raise ValueError("Simulation command ID was reused with different evidence or arguments.")
            existing = next((item for item in state.trades if item.shadow_trade_id == existing_receipt.shadow_trade_id), None)
            if existing is None:
                raise ShadowStateError("A command receipt references a missing Shadow Trade.")
            return existing

        shadow_trade_id = stable_id("shadow-trade", simulation_command_id, evidence_snapshot_id)
        outcome_id = stable_id("shadow-outcome", shadow_trade_id)
        evidence = ShadowEvidenceSnapshot(
            evidence_snapshot_id=evidence_snapshot_id,
            candidate_id=candidate_id,
            decision_timestamp=decision_at.isoformat(),
            source_path=str(report_path),
            source_sha256=source_sha,
            source_generated_at=str(metadata.get("generated_at", "")),
            source_capture_path=str(metadata.get("source_capture_path", "")),
            source_capture_time=str(metadata.get("source_capture_time", "")),
            candidate_json=canonical_candidate,
            source_report_json=source_report_json,
        )
        risk_event = make_ledger_event(
            shadow_trade_id,
            index=0,
            timestamp=decision_at.isoformat(),
            event_type="risk_gate_evaluated",
            symbol=normalized_symbol,
            trade_plan_id=trade_plan_id,
            risk_result_id=risk.result_id,
            requested_action="risk_gate_evaluated",
            result=risk.status,
            reason=" | ".join(risk.reasons),
            payload={
                "candidate_id": candidate_id,
                "evidence_snapshot_id": evidence_snapshot_id,
                "simulation_command_id": simulation_command_id,
            },
        )
        quantity = int(candidate.trade_plan.estimated_shares_for_500 or 0)
        can_start = (
            risk.allows_simulation
            and quantity > 0
            and candidate.trade_plan.bullish_entry is not None
            and candidate.trade_plan.bullish_stop is not None
            and candidate.trade_plan.bullish_target_1 is not None
        )
        if can_start:
            entry = float(candidate.trade_plan.bullish_entry)
            order = ShadowOrder(
                order_id=stable_id("shadow-order", shadow_trade_id),
                shadow_trade_id=shadow_trade_id,
                symbol=normalized_symbol,
                side="buy",
                quantity=quantity,
                remaining_quantity=quantity,
                order_type="limit",
                limit_price=entry,
                status="accepted",
                submitted_at=decision_at.isoformat(),
                last_update_at=decision_at.isoformat(),
                reason="FakeBroker order intent accepted; waiting for a later executable quote.",
            )
            ticket = ShadowOrderTicket(
                shadow_order_id=order.order_id,
                generated_timestamp=decision_at.isoformat(),
                environment=SHADOW_MODE,
                symbol=normalized_symbol,
                side="BUY",
                quantity=quantity,
                order_type="LIMIT",
                limit_price=entry,
                duration="DAY",
                session="REGULAR",
                maximum_notional=round(quantity * entry, 2),
                trade_plan_id=trade_plan_id,
                risk_decision=f"{risk.status} ({risk.result_id})",
                evidence_snapshot_id=evidence_snapshot_id,
                plan_fingerprint=plan_fingerprint,
            )
            preview_event = make_ledger_event(
                shadow_trade_id,
                index=1,
                timestamp=decision_at.isoformat(),
                event_type="simulated_order_created",
                symbol=normalized_symbol,
                trade_plan_id=trade_plan_id,
                risk_result_id=risk.result_id,
                requested_action="simulated_order_previewed",
                result="previewed",
                reason="Nontransmitting Shadow Order Ticket created.",
                payload={"order_id": order.order_id, "quantity": quantity, "limit_price": entry},
            )
            submit_event = make_ledger_event(
                shadow_trade_id,
                index=2,
                timestamp=decision_at.isoformat(),
                event_type="fake_order_submitted",
                symbol=normalized_symbol,
                trade_plan_id=trade_plan_id,
                risk_result_id=risk.result_id,
                requested_action="fake_order_submitted",
                result="accepted",
                reason=order.reason,
                payload={"order_id": order.order_id, "quantity": quantity, "filled_quantity": 0},
            )
            status = "pending_entry"
            events = (risk_event, preview_event, submit_event)
            rejection_reasons: tuple[str, ...] = ()
            last_reason = order.reason
        else:
            order = None
            ticket = None
            reason = (
                " | ".join(risk.reasons)
                if not risk.allows_simulation
                else "TradePlan lacks a positive simulation quantity, entry, stop, or target 1."
            )
            block_event = make_ledger_event(
                shadow_trade_id,
                index=1,
                timestamp=decision_at.isoformat(),
                event_type="execution_blocked",
                symbol=normalized_symbol,
                trade_plan_id=trade_plan_id,
                risk_result_id=risk.result_id,
                requested_action="simulation_blocked",
                result="blocked",
                reason=reason,
                payload={"candidate_id": candidate_id, "evidence_snapshot_id": evidence_snapshot_id},
            )
            status = "blocked"
            events = (risk_event, block_event)
            rejection_reasons = tuple(risk.reasons) if not risk.allows_simulation else (reason,)
            last_reason = reason
        scoring = row.get("scoring", {}) if isinstance(row.get("scoring"), dict) else {}
        setup_type = str(scoring.get("catalyst_cluster") or candidate.setup_label or "unknown")
        catalyst = str(scoring.get("catalyst_summary") or "unknown")
        warnings = list(candidate.trade_plan.warnings) + list(candidate.trade_plan.blocking_reasons)
        data_quality_state = "PARTIAL" if warnings else "COMPLETE"
        trade = ShadowTrade(
            shadow_trade_id=shadow_trade_id,
            simulation_command_id=simulation_command_id,
            candidate_id=candidate_id,
            evidence_snapshot_id=evidence_snapshot_id,
            trade_plan_id=trade_plan_id,
            risk_decision_id=risk.result_id,
            outcome_id=outcome_id,
            symbol=normalized_symbol,
            candidate_rank=rank,
            candidate_score=int(scoring.get("composite_score") or 0),
            setup_type=setup_type,
            catalyst=catalyst,
            market_regime=str(metadata.get("market_regime") or "unknown"),
            decision_timestamp=decision_at.isoformat(),
            plan_fingerprint=plan_fingerprint,
            trade_plan_json=plan_json,
            risk_result_json=risk_json,
            evidence=evidence,
            status=status,
            data_quality_state=data_quality_state,
            risk_rejection_reasons=rejection_reasons,
            order=order,
            ticket=ticket,
            ledger_events=events,
            last_reason=last_reason,
        )
        updated_state = replace(
            state,
            trades=(*state.trades, trade),
            command_receipts=(
                *state.command_receipts,
                ShadowCommandReceipt(simulation_command_id, request_fingerprint, shadow_trade_id),
            ),
        )
        self.store.save(updated_state)
        return trade

    def process_quote(self, quote: ShadowQuote, *, received_at: datetime | None = None) -> list[ShadowTrade]:
        received_at = received_at or now_central()
        normalized_quote = replace(quote, symbol=quote.symbol.strip().upper())
        if not normalized_quote.symbol:
            raise ValueError("A quote symbol is required.")
        observation_id = stable_id(
            "shadow-observation",
            normalized_quote.symbol,
            normalized_quote.timestamp,
            normalized_quote.source,
            canonical_json(asdict(normalized_quote)),
        )
        state = self.store.load()
        updated: list[ShadowTrade] = []
        changed = False
        for trade in state.trades:
            if (
                trade.symbol != normalized_quote.symbol
                or trade.status not in ACTIVE_TRADE_STATES
                or observation_id in trade.processed_observation_ids
            ):
                updated.append(trade)
                continue
            next_trade = self._apply_quote(
                trade,
                normalized_quote,
                observation_id=observation_id,
                received_at=received_at,
                all_trades=state.trades,
            )
            updated.append(next_trade)
            changed = changed or next_trade != trade
        if changed:
            self.store.save(replace(state, trades=tuple(updated)))
        return [trade for trade in updated if trade.symbol == normalized_quote.symbol]

    def process_missing_quote(self, symbol: str, *, observed_at: datetime | None = None) -> list[ShadowTrade]:
        observed_at = observed_at or now_central()
        normalized_symbol = symbol.strip().upper()
        observation_id = stable_id("shadow-missing-observation", normalized_symbol, observed_at.isoformat())
        state = self.store.load()
        changed = False
        trades: list[ShadowTrade] = []
        for trade in state.trades:
            if (
                trade.symbol != normalized_symbol
                or trade.status not in ACTIVE_TRADE_STATES
                or observation_id in trade.processed_observation_ids
            ):
                trades.append(trade)
                continue
            event = append_trade_event(
                replace(trade, processed_observation_ids=(*trade.processed_observation_ids, observation_id)),
                timestamp=observed_at.isoformat(),
                event_type="quote_rejected",
                requested_action="shadow_quote_rejected",
                result="blocked",
                reason="No quote was available; Shadow Trading did not fill or exit.",
            )
            trades.append(replace(event, last_reason="No quote was available; Shadow Trading did not fill or exit."))
            changed = True
        if changed:
            self.store.save(replace(state, trades=tuple(trades)))
        return [trade for trade in trades if trade.symbol == normalized_symbol]

    def snapshot(self) -> dict[str, Any]:
        state = self.store.load()
        audits = {trade.shadow_trade_id: audit_shadow_trade(trade) for trade in state.trades}
        return {
            "schemaVersion": SHADOW_SCHEMA_VERSION,
            "mode": SHADOW_MODE,
            "engineVersion": SHADOW_ENGINE_VERSION,
            "transmitting": False,
            "summary": "Prospective Shadow Trading uses supplied evidence and FakeBroker execution only.",
            "trades": [shadow_trade_to_dict(trade) for trade in state.trades],
            "metrics": shadow_metrics(state.trades),
            "audits": {
                trade_id: {
                    "status": report.status,
                    "findings": [asdict(finding) for finding in report.findings],
                }
                for trade_id, report in audits.items()
            },
        }

    def write_ticket(
        self,
        shadow_trade_id: str,
        *,
        output_dir: Path = SHADOW_REPORTS_DIR,
    ) -> dict[str, Path]:
        state = self.store.load()
        trade = next((item for item in state.trades if item.shadow_trade_id == shadow_trade_id), None)
        if trade is None or trade.ticket is None:
            raise ValueError("The requested Shadow Trade has no nontransmitting ticket.")
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"shadow-order-ticket-{shadow_trade_id}.json"
        md_path = output_dir / f"shadow-order-ticket-{shadow_trade_id}.md"
        payload = {"schema_version": 1, "ticket": asdict(trade.ticket)}
        atomic_write_json(json_path, payload)
        md_path.write_text(render_shadow_ticket_markdown(trade.ticket), encoding="utf-8")
        return {"json": json_path, "markdown": md_path}

    def _apply_quote(
        self,
        trade: ShadowTrade,
        quote: ShadowQuote,
        *,
        observation_id: str,
        received_at: datetime,
        all_trades: tuple[ShadowTrade, ...],
    ) -> ShadowTrade:
        quote_time = parse_datetime(quote.timestamp)
        decision_time = require_datetime(trade.decision_timestamp, "decision timestamp")
        if quote_time is None or quote_time <= decision_time:
            reason = "Quote is not later than the frozen decision timestamp."
            return append_trade_event(
                replace(trade, processed_observation_ids=(*trade.processed_observation_ids, observation_id)),
                timestamp=received_at.isoformat(),
                event_type="quote_rejected",
                requested_action="shadow_quote_rejected",
                result="blocked",
                reason=reason,
            )
        last_observation_time = parse_datetime(trade.last_observation_timestamp)
        if last_observation_time is not None and quote_time <= last_observation_time:
            reason = "Quote is not later than the last processed market observation."
            return append_trade_event(
                replace(trade, processed_observation_ids=(*trade.processed_observation_ids, observation_id)),
                timestamp=received_at.isoformat(),
                event_type="quote_rejected",
                requested_action="shadow_quote_rejected",
                result="blocked",
                reason=reason,
            )
        processed_trade = replace(
            trade,
            processed_observation_ids=(*trade.processed_observation_ids, observation_id),
            last_observation_timestamp=quote.timestamp,
        )
        if trade.status == "partially_filled" and trade.order is not None and trade.position is not None:
            validation_reason = self.fake_broker.validate_quote(quote, received_at=received_at)
            if validation_reason:
                return append_trade_event(
                    replace(processed_trade, last_reason=validation_reason),
                    timestamp=quote.timestamp,
                    event_type="quote_rejected",
                    requested_action="shadow_quote_rejected",
                    result="blocked",
                    reason=validation_reason,
                )
            position = update_position_excursions(trade.position, quote)
            stop_executable, target_executable = position_exit_flags(position, quote)
            if stop_executable or target_executable:
                cancelled_order = replace(
                    trade.order,
                    status="cancelled",
                    last_update_at=quote.timestamp,
                    reason="Unfilled entry remainder cancelled before the filled quantity exited.",
                )
                cancelled_trade = append_trade_event(
                    replace(processed_trade, order=cancelled_order, position=position),
                    timestamp=quote.timestamp,
                    event_type="fake_order_cancelled",
                    requested_action="fake_entry_remainder_cancelled",
                    result="cancelled",
                    reason=cancelled_order.reason,
                    payload={
                        "order_id": cancelled_order.order_id,
                        "cancelled_quantity": cancelled_order.remaining_quantity,
                    },
                )
                return self._close_position(
                    cancelled_trade,
                    quote,
                    position,
                    stop_executable=stop_executable,
                    target_executable=target_executable,
                )
            processed_trade = replace(processed_trade, position=position)
        if trade.status in {"pending_entry", "partially_filled"} and trade.order is not None:
            committed = committed_notional(all_trades, excluding_trade_id=trade.shadow_trade_id)
            if trade.position is not None:
                committed += trade.position.quantity * trade.position.average_entry_price
            open_positions = sum(
                1
                for item in all_trades
                if item.shadow_trade_id != trade.shadow_trade_id and item.position is not None and item.outcome is None
            )
            realized_today = realized_pnl_for_date(all_trades, quote_time.date().isoformat())
            updated_order, candidate_position, reason = self.fake_broker.fill_entry(
                trade.order,
                quote,
                received_at=received_at,
                committed_notional=committed,
                open_position_count=open_positions,
                realized_pnl_today=realized_today,
            )
            if updated_order.status == "rejected":
                rejected = replace(
                    processed_trade,
                    status="entry_rejected",
                    order=updated_order,
                    last_reason=updated_order.reason,
                )
                return append_trade_event(
                    rejected,
                    timestamp=quote.timestamp,
                    event_type="fake_order_rejected",
                    requested_action="fake_order_rejected",
                    result="rejected",
                    reason=updated_order.reason,
                    payload={"order_id": updated_order.order_id},
                )
            if candidate_position is None:
                waiting = replace(processed_trade, order=updated_order, last_reason=reason)
                return append_trade_event(
                    waiting,
                    timestamp=quote.timestamp,
                    event_type="fake_order_unfilled",
                    requested_action="fake_order_unfilled",
                    result="unfilled",
                    reason=reason,
                    payload={"order_id": updated_order.order_id},
                )
            plan = trade.trade_plan()
            assert plan.bullish_stop is not None and plan.bullish_target_1 is not None
            previous_position = processed_trade.position
            if previous_position is None:
                position = replace(
                    candidate_position,
                    stop_price=float(plan.bullish_stop),
                    target_price=float(plan.bullish_target_1),
                )
            else:
                position = replace(
                    previous_position,
                    quantity=updated_order.filled_quantity,
                    average_entry_price=float(updated_order.average_fill_price or previous_position.average_entry_price),
                )
            fill_event_trade = replace(
                processed_trade,
                status="open" if updated_order.status == "filled" else "partially_filled",
                order=updated_order,
                position=position,
                last_reason=updated_order.reason,
            )
            return append_trade_event(
                fill_event_trade,
                timestamp=quote.timestamp,
                event_type="fake_order_filled",
                requested_action="fake_order_filled",
                result=updated_order.status,
                reason=updated_order.reason,
                payload={
                    "order_id": updated_order.order_id,
                    "filled_quantity": updated_order.filled_quantity,
                    "average_fill_price": updated_order.average_fill_price,
                    "spread_percent": quote_spread_percent(quote),
                    "slippage_bps": self.policy.slippage_bps,
                },
            )
        if trade.position is None or trade.outcome is not None:
            return processed_trade
        validation_reason = self.fake_broker.validate_quote(quote, received_at=received_at)
        if validation_reason:
            return append_trade_event(
                replace(processed_trade, last_reason=validation_reason),
                timestamp=quote.timestamp,
                event_type="quote_rejected",
                requested_action="shadow_quote_rejected",
                result="blocked",
                reason=validation_reason,
            )
        position = update_position_excursions(trade.position, quote)
        stop_executable, target_executable = position_exit_flags(position, quote)
        if not stop_executable and not target_executable:
            return replace(processed_trade, position=position, last_reason="Position remains open.")
        return self._close_position(
            processed_trade,
            quote,
            position,
            stop_executable=stop_executable,
            target_executable=target_executable,
        )

    def _close_position(
        self,
        trade: ShadowTrade,
        quote: ShadowQuote,
        position: ShadowPosition,
        *,
        stop_executable: bool,
        target_executable: bool,
    ) -> ShadowTrade:
        if stop_executable and target_executable:
            reason = "The same observation makes both stop and target executable; exit order is ambiguous."
            ambiguous = replace(
                trade,
                status="ambiguous_exit",
                position=position,
                last_reason=reason,
            )
            return append_trade_event(
                ambiguous,
                timestamp=quote.timestamp,
                event_type="ambiguous_order_state",
                requested_action="shadow_exit_ambiguous",
                result="unknown",
                reason=reason,
            )
        exit_reason = "stop" if stop_executable else "target_1"
        exit_price = self.fake_broker.executable_exit_price(quote, reason=exit_reason)
        outcome = build_shadow_outcome(trade, position, quote.timestamp, exit_reason, exit_price)
        completed = replace(
            trade,
            status="completed",
            position=position,
            outcome=outcome,
            last_reason=f"Shadow position closed by {exit_reason}.",
        )
        completed = append_trade_event(
            completed,
            timestamp=quote.timestamp,
            event_type="fake_position_closed",
            requested_action="shadow_position_closed",
            result=exit_reason,
            reason=completed.last_reason,
            payload={"exit_price": exit_price, "quantity": position.quantity},
        )
        return append_trade_event(
            completed,
            timestamp=quote.timestamp,
            event_type="shadow_outcome_recorded",
            requested_action="shadow_outcome_recorded",
            result=outcome.classification,
            reason=f"Executable P&L {outcome.executable_pnl:.2f}; R {outcome.r_multiple}.",
            payload=asdict(outcome),
        )


def build_shadow_outcome(
    trade: ShadowTrade,
    position: ShadowPosition,
    exit_timestamp: str,
    exit_reason: str,
    exit_price: float,
) -> ShadowOutcome:
    plan = trade.trade_plan()
    quantity = position.quantity
    executable_pnl = round((exit_price - position.average_entry_price) * quantity, 2)
    ideal_entry = float(plan.bullish_entry or position.average_entry_price)
    ideal_exit = float(plan.bullish_stop if exit_reason == "stop" else plan.bullish_target_1 or exit_price)
    gross_pnl = round((ideal_exit - ideal_entry) * quantity, 2)
    risk_per_share = position.average_entry_price - position.stop_price
    initial_risk = risk_per_share * quantity
    r_multiple = round(executable_pnl / initial_risk, 4) if initial_risk > 0 else None
    mfe_dollars = round((position.highest_price - position.average_entry_price) * quantity, 2)
    mae_dollars = round((position.lowest_price - position.average_entry_price) * quantity, 2)
    mfe_percent = round((position.highest_price - position.average_entry_price) / position.average_entry_price * 100, 4)
    mae_percent = round((position.lowest_price - position.average_entry_price) / position.average_entry_price * 100, 4)
    opened_at = require_datetime(position.opened_at, "position open timestamp")
    exited_at = require_datetime(exit_timestamp, "exit timestamp")
    duration_seconds = max(0, int((exited_at - opened_at).total_seconds()))
    classification = "WIN" if executable_pnl > 0 else "LOSS" if executable_pnl < 0 else "FLAT"
    return ShadowOutcome(
        outcome_id=trade.outcome_id,
        shadow_trade_id=trade.shadow_trade_id,
        status="COMPLETED",
        classification=classification,
        exit_timestamp=exit_timestamp,
        exit_reason=exit_reason,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        executable_pnl=executable_pnl,
        r_multiple=r_multiple,
        mfe_dollars=mfe_dollars,
        mae_dollars=mae_dollars,
        mfe_percent=mfe_percent,
        mae_percent=mae_percent,
        duration_seconds=duration_seconds,
    )


def update_position_excursions(position: ShadowPosition, quote: ShadowQuote) -> ShadowPosition:
    high_candidates = [value for value in (quote.high, quote.bid, quote.last) if value is not None]
    low_candidates = [value for value in (quote.low, quote.bid, quote.last) if value is not None]
    return replace(
        position,
        highest_price=max([position.highest_price, *high_candidates]),
        lowest_price=min([position.lowest_price, *low_candidates]),
    )


def position_exit_flags(position: ShadowPosition, quote: ShadowQuote) -> tuple[bool, bool]:
    assert quote.bid is not None
    stop_executable = quote.bid <= position.stop_price or (
        quote.open is not None and quote.open <= position.stop_price
    )
    target_executable = quote.bid >= position.target_price
    return stop_executable, target_executable


def audit_shadow_trade(trade: ShadowTrade) -> AuditReport:
    findings: list[AuditFinding] = []
    required = {
        "shadow_trade_id": trade.shadow_trade_id,
        "simulation_command_id": trade.simulation_command_id,
        "candidate_id": trade.candidate_id,
        "evidence_snapshot_id": trade.evidence_snapshot_id,
        "trade_plan_id": trade.trade_plan_id,
        "risk_decision_id": trade.risk_decision_id,
        "outcome_id": trade.outcome_id,
        "plan_fingerprint": trade.plan_fingerprint,
    }
    for field_name, value in required.items():
        if not value.strip():
            findings.append(AuditFinding(trade.shadow_trade_id, field_name, f"Missing Shadow Trading identifier: {field_name}"))
    if hashlib.sha256(trade.trade_plan_json.encode("utf-8")).hexdigest() != trade.plan_fingerprint:
        findings.append(AuditFinding(trade.shadow_trade_id, "plan_fingerprint", "Frozen TradePlan fingerprint does not match."))
    if trade.evidence.evidence_snapshot_id != trade.evidence_snapshot_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "evidence_snapshot_id", "Evidence identity does not match the trade."))
    if hashlib.sha256(trade.evidence.source_report_json.encode("utf-8")).hexdigest() != trade.evidence.source_sha256:
        findings.append(AuditFinding(trade.shadow_trade_id, "source_sha256", "Frozen source report does not match its hash."))
    ledger_report = audit_execution_ledger(ExecutionLedger(list(trade.ledger_events)))
    findings.extend(ledger_report.findings)
    actions = [event.requested_action for event in trade.ledger_events]
    if "risk_gate_evaluated" not in actions:
        findings.append(AuditFinding(trade.shadow_trade_id, "risk_decision_id", "Missing Risk Governor evidence."))
    if trade.order is not None:
        if "simulated_order_previewed" not in actions or "fake_order_submitted" not in actions:
            findings.append(AuditFinding(trade.shadow_trade_id, "order", "Missing preview or submit evidence."))
    if trade.position is not None and "fake_order_filled" not in actions:
        findings.append(AuditFinding(trade.shadow_trade_id, "position", "Position exists without fill evidence."))
    if trade.status == "completed":
        if trade.outcome is None:
            findings.append(AuditFinding(trade.shadow_trade_id, "outcome", "Completed trade is missing its outcome."))
        if "shadow_position_closed" not in actions or "shadow_outcome_recorded" not in actions:
            findings.append(AuditFinding(trade.shadow_trade_id, "outcome", "Completed trade is missing close/outcome chronology."))
    if len({event.event_id for event in trade.ledger_events}) != len(trade.ledger_events):
        findings.append(AuditFinding(trade.shadow_trade_id, "event_id", "Duplicate ledger event identifier."))
    return AuditReport("PASS" if not findings else "FAIL", findings)


def shadow_metrics(trades: Iterable[ShadowTrade]) -> dict[str, Any]:
    items = list(trades)
    completed = sorted(
        [trade for trade in items if trade.outcome is not None and trade.outcome.status == "COMPLETED"],
        key=lambda trade: trade.outcome.exit_timestamp if trade.outcome else "",
    )
    wins = [trade.outcome.executable_pnl for trade in completed if trade.outcome and trade.outcome.executable_pnl > 0]
    losses = [trade.outcome.executable_pnl for trade in completed if trade.outcome and trade.outcome.executable_pnl < 0]
    pnl_values = [trade.outcome.executable_pnl for trade in completed if trade.outcome]
    ideal_values = [trade.outcome.gross_pnl for trade in completed if trade.outcome]
    r_values = [trade.outcome.r_multiple for trade in completed if trade.outcome and trade.outcome.r_multiple is not None]
    meaningful = len(completed) >= MIN_MEANINGFUL_SAMPLE_SIZE
    profit_factor = None
    if meaningful and losses:
        profit_factor = round(sum(wins) / abs(sum(losses)), 4)
    return {
        "sampleStatus": "MEANINGFUL" if meaningful else "INSUFFICIENT_SAMPLE",
        "minimumMeaningfulSample": MIN_MEANINGFUL_SAMPLE_SIZE,
        "candidateCount": len(items),
        "validTradePlanCount": sum(1 for trade in items if trade.status != "blocked"),
        "riskRejectedCount": sum(1 for trade in items if trade.status == "blocked"),
        "simulatedEntryCount": sum(1 for trade in items if trade.position is not None),
        "unfilledOrderCount": sum(1 for trade in items if trade.status == "pending_entry"),
        "completedTradeCount": len(completed),
        "winRatePercent": rounded_ratio(len(wins), len(completed)),
        "averageWin": rounded_mean(wins),
        "averageLoss": rounded_mean(losses),
        "expectancy": rounded_mean(pnl_values),
        "averageR": rounded_mean(r_values),
        "maximumDrawdown": maximum_drawdown(pnl_values),
        "profitFactor": profit_factor,
        "idealPnl": round(sum(ideal_values), 2),
        "executablePnl": round(sum(pnl_values), 2),
        "idealVsExecutableGap": round(sum(ideal_values) - sum(pnl_values), 2),
        "resultsBySetup": grouped_shadow_results(completed, lambda trade: trade.setup_type),
        "resultsByCatalyst": grouped_shadow_results(completed, lambda trade: trade.catalyst),
        "resultsByMarketRegime": grouped_shadow_results(completed, lambda trade: trade.market_regime),
        "resultsByTimeOfDay": grouped_shadow_results(completed, trade_time_bucket),
        "conclusion": (
            "Sample supports descriptive aggregate evidence only."
            if meaningful
            else "Too few completed Shadow Trades for best/worst or strategy conclusions."
        ),
    }


def grouped_shadow_results(
    trades: list[ShadowTrade],
    key_fn,
) -> list[dict[str, Any]]:
    groups: dict[str, list[float]] = {}
    for trade in trades:
        key = str(key_fn(trade) or "unknown")
        assert trade.outcome is not None
        groups.setdefault(key, []).append(trade.outcome.executable_pnl)
    return [
        {
            "group": key,
            "count": len(values),
            "wins": sum(1 for value in values if value > 0),
            "winRatePercent": rounded_ratio(sum(1 for value in values if value > 0), len(values)),
            "averageExecutablePnl": rounded_mean(values),
        }
        for key, values in sorted(groups.items())
    ]


def render_shadow_ticket_markdown(ticket: ShadowOrderTicket) -> str:
    return "\n".join(
        [
            "# Momentum Hunter Shadow Order Ticket",
            "",
            f"**{ticket.environment}**",
            "",
            f"- Shadow Order ID: `{ticket.shadow_order_id}`",
            f"- Generated: {ticket.generated_timestamp}",
            f"- Symbol: {ticket.symbol}",
            f"- Side: {ticket.side}",
            f"- Quantity: {ticket.quantity}",
            f"- Order: {ticket.order_type} at {ticket.limit_price:.4f}",
            f"- Duration/session: {ticket.duration} / {ticket.session}",
            f"- Maximum notional: {ticket.maximum_notional:.2f}",
            f"- TradePlan ID: `{ticket.trade_plan_id}`",
            f"- Risk decision: {ticket.risk_decision}",
            f"- Evidence snapshot ID: `{ticket.evidence_snapshot_id}`",
            f"- Plan fingerprint: `{ticket.plan_fingerprint}`",
            "",
            "## Manual paperMoney Reconciliation",
            "",
            f"- Exact ticket entered: {ticket.exact_ticket_entered or 'Pending'}",
            f"- Operator modifications: {ticket.operator_modifications or 'None recorded'}",
            f"- paperMoney result: {ticket.paper_money_result or 'Pending'}",
            f"- Fill price: {ticket.paper_money_fill_price if ticket.paper_money_fill_price is not None else 'Pending'}",
            f"- Exit: {ticket.paper_money_exit or 'Pending'}",
            f"- Outcome: {ticket.paper_money_outcome or 'Pending'}",
            f"- Notes: {ticket.reconciliation_notes or 'None'}",
            "",
            "This ticket is nontransmitting. Enter it manually only in thinkorswim paperMoney.",
            "",
        ]
    )


def shadow_state_to_dict(state: ShadowTradingState) -> dict[str, Any]:
    return {
        "schema_version": state.schema_version,
        "engine_version": state.engine_version,
        "updated_at": state.updated_at,
        "trades": [shadow_trade_to_dict(trade) for trade in state.trades],
        "command_receipts": [asdict(receipt) for receipt in state.command_receipts],
    }


def shadow_state_from_dict(payload: dict[str, Any]) -> ShadowTradingState:
    raw_trades = payload.get("trades", [])
    raw_receipts = payload.get("command_receipts", [])
    if not isinstance(raw_trades, list) or not isinstance(raw_receipts, list):
        raise ShadowStateError("Shadow state contains invalid trade or command collections.")
    if any(not isinstance(item, dict) for item in raw_trades) or any(not isinstance(item, dict) for item in raw_receipts):
        raise ShadowStateError("Shadow state contains malformed trade or command receipt entries.")
    state = ShadowTradingState(
        schema_version=int(payload.get("schema_version", 0)),
        engine_version=str(payload.get("engine_version", "")),
        updated_at=str(payload.get("updated_at", "")),
        trades=tuple(shadow_trade_from_dict(item) for item in raw_trades),
        command_receipts=tuple(
            ShadowCommandReceipt(
                command_id=str(item.get("command_id", "")),
                request_fingerprint=str(item.get("request_fingerprint", "")),
                shadow_trade_id=str(item.get("shadow_trade_id", "")),
            )
            for item in raw_receipts
        ),
    )
    validate_shadow_state(state)
    return state


def shadow_trade_to_dict(trade: ShadowTrade) -> dict[str, Any]:
    payload = asdict(trade)
    payload["ledger_events"] = [event.to_dict() for event in trade.ledger_events]
    payload["processed_observation_ids"] = list(trade.processed_observation_ids)
    payload["risk_rejection_reasons"] = list(trade.risk_rejection_reasons)
    return payload


def shadow_trade_from_dict(payload: dict[str, Any]) -> ShadowTrade:
    evidence_payload = require_mapping(payload.get("evidence"), "evidence")
    order_payload = payload.get("order")
    position_payload = payload.get("position")
    outcome_payload = payload.get("outcome")
    ticket_payload = payload.get("ticket")
    return ShadowTrade(
        shadow_trade_id=str(payload.get("shadow_trade_id", "")),
        simulation_command_id=str(payload.get("simulation_command_id", "")),
        candidate_id=str(payload.get("candidate_id", "")),
        evidence_snapshot_id=str(payload.get("evidence_snapshot_id", "")),
        trade_plan_id=str(payload.get("trade_plan_id", "")),
        risk_decision_id=str(payload.get("risk_decision_id", "")),
        outcome_id=str(payload.get("outcome_id", "")),
        symbol=str(payload.get("symbol", "")),
        candidate_rank=int(payload.get("candidate_rank", 0)),
        candidate_score=int(payload.get("candidate_score", 0)),
        setup_type=str(payload.get("setup_type", "")),
        catalyst=str(payload.get("catalyst", "")),
        market_regime=str(payload.get("market_regime", "")),
        decision_timestamp=str(payload.get("decision_timestamp", "")),
        plan_fingerprint=str(payload.get("plan_fingerprint", "")),
        trade_plan_json=str(payload.get("trade_plan_json", "")),
        risk_result_json=str(payload.get("risk_result_json", "")),
        evidence=ShadowEvidenceSnapshot(**evidence_payload),
        status=str(payload.get("status", "")),
        data_quality_state=str(payload.get("data_quality_state", "")),
        risk_rejection_reasons=tuple(str(item) for item in payload.get("risk_rejection_reasons", [])),
        order=ShadowOrder(**order_payload) if isinstance(order_payload, dict) else None,
        position=ShadowPosition(**position_payload) if isinstance(position_payload, dict) else None,
        outcome=ShadowOutcome(**outcome_payload) if isinstance(outcome_payload, dict) else None,
        ticket=ShadowOrderTicket(**ticket_payload) if isinstance(ticket_payload, dict) else None,
        ledger_events=tuple(
            ExecutionLedgerEvent.from_dict(item)
            for item in payload.get("ledger_events", [])
            if isinstance(item, dict)
        ),
        processed_observation_ids=tuple(str(item) for item in payload.get("processed_observation_ids", [])),
        last_observation_timestamp=str(payload.get("last_observation_timestamp", "")),
        last_reason=str(payload.get("last_reason", "")),
    )


def validate_shadow_state(state: ShadowTradingState) -> None:
    trade_ids = [trade.shadow_trade_id for trade in state.trades]
    command_ids = [receipt.command_id for receipt in state.command_receipts]
    if any(not trade_id for trade_id in trade_ids):
        raise ShadowStateError("Shadow state contains a trade with a missing identifier.")
    if len(trade_ids) != len(set(trade_ids)):
        raise ShadowStateError("Shadow state contains duplicate Shadow Trade identifiers.")
    if any(not command_id for command_id in command_ids):
        raise ShadowStateError("Shadow state contains a command receipt with a missing identifier.")
    if len(command_ids) != len(set(command_ids)):
        raise ShadowStateError("Shadow state contains duplicate simulation command identifiers.")
    known_trade_ids = set(trade_ids)
    for receipt in state.command_receipts:
        if not receipt.request_fingerprint:
            raise ShadowStateError("Shadow state contains a command receipt with a missing request fingerprint.")
        if receipt.shadow_trade_id not in known_trade_ids:
            raise ShadowStateError("Shadow state contains a command receipt for an unknown Shadow Trade.")


def make_ledger_event(
    shadow_trade_id: str,
    *,
    index: int,
    timestamp: str,
    event_type: str,
    symbol: str,
    trade_plan_id: str,
    risk_result_id: str,
    requested_action: str,
    result: str,
    reason: str,
    payload: dict[str, object] | None = None,
) -> ExecutionLedgerEvent:
    return ExecutionLedgerEvent(
        event_id=stable_id("ledger", shadow_trade_id, str(index), requested_action, timestamp),
        timestamp=timestamp,
        event_type=event_type,
        mode="Simulation Lab",
        ticker=symbol,
        trade_plan_id=trade_plan_id,
        risk_result_id=risk_result_id,
        broker_adapter="FakeBrokerAdapter",
        approval_state="simulation-only",
        requested_action=requested_action,
        result=result,
        actor="Momentum Hunter Engine",
        source="Shadow Trading",
        reason=reason,
        payload=dict(payload or {}),
    )


def append_trade_event(
    trade: ShadowTrade,
    *,
    timestamp: str,
    event_type: str,
    requested_action: str,
    result: str,
    reason: str,
    payload: dict[str, object] | None = None,
) -> ShadowTrade:
    event = make_ledger_event(
        trade.shadow_trade_id,
        index=len(trade.ledger_events),
        timestamp=timestamp,
        event_type=event_type,
        symbol=trade.symbol,
        trade_plan_id=trade.trade_plan_id,
        risk_result_id=trade.risk_decision_id,
        requested_action=requested_action,
        result=result,
        reason=reason,
        payload=payload,
    )
    return replace(trade, ledger_events=(*trade.ledger_events, event), last_reason=reason)


def risk_result_to_dict(result: RiskGovernorResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "timestamp": result.timestamp,
        "ticker": result.ticker,
        "trade_plan_id": result.trade_plan_id,
        "mode": result.mode,
        "status": result.status,
        "gates": [asdict(gate) for gate in result.gates],
        "reasons": list(result.reasons),
        "allows_simulation": result.allows_simulation,
    }


def committed_notional(trades: Iterable[ShadowTrade], *, excluding_trade_id: str = "") -> float:
    total = 0.0
    for trade in trades:
        if trade.shadow_trade_id == excluding_trade_id or trade.outcome is not None:
            continue
        if trade.position is not None:
            total += trade.position.quantity * trade.position.average_entry_price
        elif trade.order is not None and trade.status in {"pending_entry", "partially_filled"}:
            total += trade.order.remaining_quantity * trade.order.limit_price
    return round(total, 2)


def realized_pnl_for_date(trades: Iterable[ShadowTrade], date_label: str) -> float:
    return round(
        sum(
            trade.outcome.executable_pnl
            for trade in trades
            if trade.outcome is not None and trade.outcome.exit_timestamp.startswith(date_label)
        ),
        2,
    )


def quote_spread_percent(quote: ShadowQuote) -> float | None:
    if quote.bid is None or quote.ask is None or quote.ask <= 0:
        return None
    return round((quote.ask - quote.bid) / quote.ask * 100, 4)


def stable_id(namespace: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join([namespace, *parts]).encode("utf-8")).hexdigest()[:20]
    return f"{namespace}-{digest}"


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def require_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ShadowStateError(f"Shadow state field '{name}' must be an object.")
    return dict(value)


def require_datetime(value: str, name: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid {name}.")
    return parsed


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def rounded_mean(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def rounded_ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def maximum_drawdown(pnl_values: list[float]) -> float | None:
    if not pnl_values:
        return None
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in pnl_values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(worst, 2)


def trade_time_bucket(trade: ShadowTrade) -> str:
    decision = parse_datetime(trade.decision_timestamp)
    if decision is None:
        return "unknown"
    if decision.hour < 10:
        return "open"
    if decision.hour < 12:
        return "morning"
    if decision.hour < 15:
        return "midday"
    return "close"


def quote_from_dict(payload: dict[str, Any]) -> ShadowQuote:
    return ShadowQuote(
        symbol=str(payload.get("symbol", "")),
        timestamp=str(payload.get("timestamp", "")),
        bid=optional_float(payload.get("bid")),
        ask=optional_float(payload.get("ask")),
        last=optional_float(payload.get("last") if "last" in payload else payload.get("price")),
        open=optional_float(payload.get("open")),
        high=optional_float(payload.get("high")),
        low=optional_float(payload.get("low")),
        volume=optional_int(payload.get("volume")),
        available_size=optional_int(payload.get("available_size")),
        session=str(payload.get("session") or "regular"),
        trading_state=str(payload.get("trading_state") or payload.get("state") or "tradable"),
        source=str(payload.get("source") or "supplied_quote"),
    )


def optional_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def optional_int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def round_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def apply_basis_points(value: float, basis_points: float) -> float:
    multiplier = Decimal("1") + Decimal(str(basis_points)) / Decimal("10000")
    adjusted = Decimal(str(value)) * multiplier
    return float(adjusted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run nontransmitting Momentum Hunter Shadow Trading.")
    parser.add_argument("--state-path", type=Path, default=SHADOW_STATE_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Freeze one persisted candidate and create a FakeBroker order intent.")
    start_parser.add_argument("--report", type=Path, required=True)
    start_parser.add_argument("--symbol", required=True)
    start_parser.add_argument("--command-id", required=True)

    quote_parser = subparsers.add_parser("quote", help="Advance active Shadow Trades from a supplied quote JSON file.")
    quote_parser.add_argument("--input", type=Path, required=True)

    subparsers.add_parser("snapshot", help="Print persisted Shadow Trading state and sample-gated metrics.")

    ticket_parser = subparsers.add_parser("ticket", help="Write a nontransmitting paperMoney ticket.")
    ticket_parser.add_argument("--trade-id", required=True)
    ticket_parser.add_argument("--output-dir", type=Path, default=SHADOW_REPORTS_DIR)

    args = parser.parse_args(argv)
    service = ShadowTradingService(store=ShadowStateStore(args.state_path))
    if args.command == "start":
        result: object = shadow_trade_to_dict(
            service.start_trade(args.report, symbol=args.symbol, simulation_command_id=args.command_id)
        )
    elif args.command == "quote":
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Quote input must contain an object.")
        result = [shadow_trade_to_dict(trade) for trade in service.process_quote(quote_from_dict(payload))]
    elif args.command == "ticket":
        result = {key: str(value) for key, value in service.write_ticket(args.trade_id, output_dir=args.output_dir).items()}
    else:
        result = service.snapshot()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
