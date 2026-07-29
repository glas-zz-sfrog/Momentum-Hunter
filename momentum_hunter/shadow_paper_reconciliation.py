from __future__ import annotations

"""Write-once evidence for manual thinkorswim paperMoney reconciliation.

This module reads frozen Shadow Trading state and writes a separate evidence record.
It has no broker client, account selector, credential access, or order action.
"""

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_trading import (
    SHADOW_MODE,
    SHADOW_STATE_PATH,
    ShadowStateError,
    ShadowTrade,
    canonical_json,
    shadow_state_from_dict,
    stable_id,
)
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import parse_datetime


PAPER_RECONCILIATION_SCHEMA_VERSION = 2
PAPER_RECONCILIATION_MODE = (
    "MANUAL THINKORSWIM PAPERMONEY RECONCILIATION / NONTRANSMITTING"
)
PAPER_RECONCILIATIONS_DIR = (
    DATA_DIR / "shadow-trading" / "paper-reconciliations"
)
MAX_SHADOW_STATE_BYTES = 16 * 1024 * 1024
MAX_RECONCILIATION_BYTES = 1024 * 1024
MAX_TICKET_TEXT_LENGTH = 8192
MAX_NOTE_LENGTH = 8192
MAX_SHORT_TEXT_LENGTH = 512
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PAPER_RESULTS_REQUIRING_FILL = frozenset({"FILLED", "PARTIALLY_FILLED"})
PAPER_RESULTS_WITHOUT_FILL = frozenset(
    {"NOT_FILLED", "REJECTED", "CANCELLED", "EXPIRED", "NOT_SUBMITTED"}
)
PAPER_RESULTS = PAPER_RESULTS_REQUIRING_FILL | PAPER_RESULTS_WITHOUT_FILL


@dataclass(frozen=True)
class PaperMoneyReconciliationRecord:
    schema_version: int
    reconciliation_id: str
    request_fingerprint: str
    recorded_at: str
    mode: str
    transmitting: bool
    broker_request_performed: bool
    order_action_performed: bool
    source_state_path: str
    source_state_sha256: str
    shadow_trade_id: str
    shadow_order_id: str
    symbol: str
    trade_plan_id: str
    risk_decision_id: str
    evidence_snapshot_id: str
    plan_fingerprint: str
    sample_version: str
    strategy_configuration_fingerprint: str
    fill_model_version: str
    evidence_schema_version: int
    selection_policy_version: str
    selection_policy_fingerprint: str
    selector_arm_id: str
    constitution_hash: str
    decision_cycle_id: str
    opportunity_id: str
    exact_ticket_entered: str
    operator_modifications: str
    paper_money_result: str
    paper_money_filled_quantity: int
    paper_money_fill_price: float | None
    paper_money_exit_price: float | None
    paper_money_exit: str
    paper_money_outcome: str
    reconciliation_notes: str
    ticket_quantity: int
    ticket_side: str
    planned_entry_price: float
    fakebroker_order_status: str
    fakebroker_filled_quantity: int
    fakebroker_fill_price: float | None
    fakebroker_exit_price: float | None
    fakebroker_executable_pnl: float | None
    fakebroker_executable_pnl_per_share: float | None
    comparison_status: str
    paper_minus_fake_entry_price: float | None
    paper_minus_fake_entry_bps: float | None
    paper_minus_fake_exit_price: float | None
    paper_money_estimated_pnl: float | None
    paper_money_estimated_pnl_per_share: float | None
    paper_minus_fake_executable_pnl: float | None
    paper_minus_fake_pnl_per_share: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaperMoneyReconciliationResult:
    record: PaperMoneyReconciliationRecord
    path: Path
    created: bool
    source_state_unchanged: bool


def load_paper_money_reconciliation(
    path: Path,
) -> PaperMoneyReconciliationRecord:
    """Load and fully validate one persisted reconciliation artifact."""

    resolved = path.expanduser().resolve()
    record = _load_existing_record(resolved)
    if record is None:
        raise FileNotFoundError(
            f"paperMoney reconciliation does not exist: {resolved}"
        )
    return record


def record_paper_money_reconciliation(
    *,
    state_path: Path = SHADOW_STATE_PATH,
    output_dir: Path = PAPER_RECONCILIATIONS_DIR,
    shadow_trade_id: str,
    exact_ticket_entered: str,
    paper_money_result: str,
    paper_money_filled_quantity: int | None = None,
    paper_money_fill_price: float | None = None,
    paper_money_exit_price: float | None = None,
    operator_modifications: str = "",
    paper_money_exit: str = "",
    paper_money_outcome: str = "",
    reconciliation_notes: str = "",
    recorded_at: datetime | None = None,
) -> PaperMoneyReconciliationResult:
    source_path = _resolve_source_state_path(state_path)
    source_bytes, source_sha256, state = _read_state_snapshot(source_path)
    trade = next(
        (item for item in state.trades if item.shadow_trade_id == shadow_trade_id),
        None,
    )
    if trade is None:
        raise ValueError("The requested Shadow Trade does not exist.")
    _validate_frozen_ticket(trade)

    result = _normalize_result(paper_money_result)
    fill_price = _validate_fill_price(result, paper_money_fill_price)
    exit_price = _validate_exit_price(result, fill_price, paper_money_exit_price)
    ticket_text = _bounded_text(
        exact_ticket_entered,
        "Exact ticket entered",
        MAX_TICKET_TEXT_LENGTH,
        required=True,
    )
    modifications = _bounded_text(
        operator_modifications,
        "Operator modifications",
        MAX_NOTE_LENGTH,
    )
    exit_text = _bounded_text(
        paper_money_exit,
        "paperMoney exit",
        MAX_NOTE_LENGTH,
    )
    outcome = _bounded_text(
        paper_money_outcome,
        "paperMoney outcome",
        MAX_SHORT_TEXT_LENGTH,
    )
    notes = _bounded_text(
        reconciliation_notes,
        "Reconciliation notes",
        MAX_NOTE_LENGTH,
    )
    timestamp = recorded_at or now_central()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Reconciliation timestamp must include a UTC offset.")

    ticket = trade.ticket
    assert ticket is not None
    filled_quantity = _validate_filled_quantity(
        result,
        paper_money_filled_quantity,
        ticket.quantity,
    )
    decision_at = parse_datetime(trade.decision_timestamp)
    ticket_at = parse_datetime(ticket.generated_timestamp)
    if decision_at is None or ticket_at is None:
        raise ValueError("Frozen Shadow decision and ticket timestamps must be valid.")
    if timestamp < decision_at or timestamp < ticket_at:
        raise ValueError(
            "Reconciliation timestamp cannot precede the frozen decision or ticket."
        )
    comparison = _build_comparison(
        trade,
        paper_money_filled_quantity=filled_quantity,
        paper_money_fill_price=fill_price,
        paper_money_exit_price=exit_price,
    )
    record = PaperMoneyReconciliationRecord(
        schema_version=PAPER_RECONCILIATION_SCHEMA_VERSION,
        reconciliation_id="",
        request_fingerprint="",
        recorded_at=timestamp.isoformat(),
        mode=PAPER_RECONCILIATION_MODE,
        transmitting=False,
        broker_request_performed=False,
        order_action_performed=False,
        source_state_path=str(source_path),
        source_state_sha256=source_sha256,
        shadow_trade_id=trade.shadow_trade_id,
        shadow_order_id=ticket.shadow_order_id,
        symbol=trade.symbol,
        trade_plan_id=trade.trade_plan_id,
        risk_decision_id=trade.risk_decision_id,
        evidence_snapshot_id=trade.evidence_snapshot_id,
        plan_fingerprint=trade.plan_fingerprint,
        sample_version=trade.sample_metadata.sample_version,
        strategy_configuration_fingerprint=(
            trade.sample_metadata.strategy_configuration_fingerprint
        ),
        fill_model_version=trade.sample_metadata.fill_model_version,
        evidence_schema_version=trade.sample_metadata.evidence_schema_version,
        selection_policy_version=trade.selection_policy_version,
        selection_policy_fingerprint=trade.selection_policy_fingerprint,
        selector_arm_id=trade.selector_arm_id,
        constitution_hash=trade.constitution_hash,
        decision_cycle_id=trade.decision_cycle_id,
        opportunity_id=trade.opportunity_id,
        exact_ticket_entered=ticket_text,
        operator_modifications=modifications,
        paper_money_result=result,
        paper_money_filled_quantity=filled_quantity,
        paper_money_fill_price=fill_price,
        paper_money_exit_price=exit_price,
        paper_money_exit=exit_text,
        paper_money_outcome=outcome,
        reconciliation_notes=notes,
        **comparison,
    )
    request_fingerprint = hashlib.sha256(
        canonical_json(_request_payload_from_record(record)).encode("utf-8")
    ).hexdigest()
    record = replace(
        record,
        reconciliation_id=stable_id(
            "paper-reconciliation",
            trade.shadow_trade_id,
            request_fingerprint,
        ),
        request_fingerprint=request_fingerprint,
    )
    _validate_record(record)

    destination = _reconciliation_path(output_dir, trade.shadow_trade_id)
    if destination == source_path:
        raise ValueError("Reconciliation output cannot replace Shadow Trading state.")
    existing = _load_existing_record(destination)
    if existing is not None:
        if existing.reconciliation_id != record.reconciliation_id:
            raise ValueError(
                "A different write-once paperMoney reconciliation already exists "
                "for this Shadow Trade."
            )
        source_unchanged = _source_matches(
            source_path,
            source_bytes,
            source_sha256,
        )
        if not source_unchanged:
            raise ShadowStateError(
                "Shadow Trading state changed while existing reconciliation "
                "evidence was verified."
            )
        return PaperMoneyReconciliationResult(
            record=existing,
            path=destination,
            created=False,
            source_state_unchanged=True,
        )

    if not _source_matches(source_path, source_bytes, source_sha256):
        raise ShadowStateError(
            "Shadow Trading state changed while reconciliation evidence was prepared."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            {
                "schema_version": PAPER_RECONCILIATION_SCHEMA_VERSION,
                "reconciliation": record.to_dict(),
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    )
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        existing = _load_existing_record(destination)
        if existing is None or existing.reconciliation_id != record.reconciliation_id:
            raise ValueError(
                "A different write-once paperMoney reconciliation already exists "
                "for this Shadow Trade."
            ) from None
        record = existing
        created = False
    else:
        created = True

    source_unchanged = _source_matches(source_path, source_bytes, source_sha256)
    if not source_unchanged:
        raise ShadowStateError(
            "Shadow Trading state changed while reconciliation evidence was written; "
            "preserve both artifacts for review."
        )
    return PaperMoneyReconciliationResult(
        record=record,
        path=destination,
        created=created,
        source_state_unchanged=True,
    )


def _resolve_source_state_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Shadow Trading state does not exist: {resolved}")
    if not resolved.is_file():
        raise ValueError("Shadow Trading state path must identify a regular file.")
    return resolved


def _read_state_snapshot(
    path: Path,
) -> tuple[bytes, str, Any]:
    before = path.stat()
    if before.st_size > MAX_SHADOW_STATE_BYTES:
        raise ShadowStateError("Shadow Trading state exceeds the reconciliation read limit.")
    raw = path.read_bytes()
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(raw) != after.st_size
    ):
        raise ShadowStateError("Shadow Trading state changed while it was being read.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowStateError(
            f"Shadow Trading state cannot be loaded: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, dict):
        raise ShadowStateError("Shadow Trading state must contain an object.")
    state = shadow_state_from_dict(payload)
    return raw, hashlib.sha256(raw).hexdigest(), state


def _validate_frozen_ticket(trade: ShadowTrade) -> None:
    ticket = trade.ticket
    if ticket is None or trade.order is None:
        raise ValueError("The requested Shadow Trade has no nontransmitting ticket.")
    if ticket.environment != SHADOW_MODE:
        raise ValueError("The Shadow ticket is not in the nontransmitting environment.")
    bindings = {
        "order identifier": (ticket.shadow_order_id, trade.order.order_id),
        "symbol": (ticket.symbol, trade.symbol),
        "side": (ticket.side.strip().lower(), trade.order.side.strip().lower()),
        "quantity": (ticket.quantity, trade.order.quantity),
        "order type": (
            ticket.order_type.strip().lower(),
            trade.order.order_type.strip().lower(),
        ),
        "limit price": (ticket.limit_price, trade.order.limit_price),
        "TradePlan identifier": (ticket.trade_plan_id, trade.trade_plan_id),
        "evidence snapshot identifier": (
            ticket.evidence_snapshot_id,
            trade.evidence_snapshot_id,
        ),
        "plan fingerprint": (ticket.plan_fingerprint, trade.plan_fingerprint),
    }
    for label, (ticket_value, trade_value) in bindings.items():
        if not ticket_value or ticket_value != trade_value:
            raise ValueError(f"The frozen ticket {label} does not match Shadow state.")
    if any(
        (
            ticket.exact_ticket_entered,
            ticket.operator_modifications,
            ticket.paper_money_result,
            ticket.paper_money_exit,
            ticket.paper_money_outcome,
            ticket.reconciliation_notes,
        )
    ) or ticket.paper_money_fill_price is not None:
        raise ValueError(
            "Shadow state contains embedded paperMoney reconciliation data; "
            "preserve it and review before creating a separate record."
        )


def _normalize_result(value: str) -> str:
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized not in PAPER_RESULTS:
        allowed = ", ".join(sorted(PAPER_RESULTS))
        raise ValueError(f"paperMoney result must be one of: {allowed}.")
    return normalized


def _validate_fill_price(result: str, value: float | None) -> float | None:
    if result in PAPER_RESULTS_REQUIRING_FILL:
        if value is None:
            raise ValueError(
                "A finite positive paperMoney fill price is required for filled results."
            )
        try:
            return _finite_number(
                value,
                "paperMoney fill price",
                positive=True,
            )
        except ValueError as exc:
            raise ValueError(
                "A finite positive paperMoney fill price is required for filled results."
            ) from exc
    if value is not None:
        raise ValueError(
            "paperMoney fill price must be omitted when the result is not filled."
        )
    return None


def _validate_filled_quantity(
    result: str,
    value: int | None,
    ticket_quantity: int,
) -> int:
    if (
        isinstance(ticket_quantity, bool)
        or not isinstance(ticket_quantity, int)
        or ticket_quantity <= 0
    ):
        raise ValueError("Frozen ticket quantity must be positive.")
    if result == "FILLED":
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value != ticket_quantity
        ):
            raise ValueError(
                "A FILLED paperMoney result must use the complete frozen ticket quantity."
            )
        return ticket_quantity
    if result == "PARTIALLY_FILLED":
        if (
            value is None
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value >= ticket_quantity
        ):
            raise ValueError(
                "PARTIALLY_FILLED requires a quantity between one and "
                "the frozen ticket quantity minus one."
            )
        return value
    if value not in (None, 0):
        raise ValueError(
            "paperMoney filled quantity must be omitted when the result is not filled."
        )
    return 0


def _validate_exit_price(
    result: str,
    fill_price: float | None,
    value: float | None,
) -> float | None:
    if value is None:
        return None
    if result not in PAPER_RESULTS_REQUIRING_FILL or fill_price is None:
        raise ValueError(
            "paperMoney exit price requires a filled or partially filled result."
        )
    return _finite_number(
        value,
        "paperMoney exit price",
        positive=True,
    )


def _build_comparison(
    trade: ShadowTrade,
    *,
    paper_money_filled_quantity: int,
    paper_money_fill_price: float | None,
    paper_money_exit_price: float | None,
) -> dict[str, Any]:
    ticket = trade.ticket
    order = trade.order
    assert ticket is not None and order is not None

    planned_entry = _finite_number(
        ticket.limit_price,
        "Frozen planned entry price",
        positive=True,
    )
    fake_fill = _optional_finite_number(
        order.average_fill_price,
        "FakeBroker fill price",
        positive=True,
    )
    fake_exit = _optional_finite_number(
        trade.outcome.exit_price if trade.outcome is not None else None,
        "FakeBroker exit price",
        positive=True,
    )
    fake_pnl = _optional_finite_number(
        trade.outcome.executable_pnl if trade.outcome is not None else None,
        "FakeBroker executable P&L",
    )
    return _comparison_values(
        ticket_quantity=ticket.quantity,
        ticket_side=ticket.side,
        planned_entry_price=planned_entry,
        fakebroker_order_status=order.status,
        fakebroker_filled_quantity=order.filled_quantity,
        fakebroker_fill_price=fake_fill,
        fakebroker_exit_price=fake_exit,
        fakebroker_executable_pnl=fake_pnl,
        paper_money_filled_quantity=paper_money_filled_quantity,
        paper_money_fill_price=paper_money_fill_price,
        paper_money_exit_price=paper_money_exit_price,
    )


def _comparison_values(
    *,
    ticket_quantity: int,
    ticket_side: str,
    planned_entry_price: float,
    fakebroker_order_status: str,
    fakebroker_filled_quantity: int,
    fakebroker_fill_price: float | None,
    fakebroker_exit_price: float | None,
    fakebroker_executable_pnl: float | None,
    paper_money_filled_quantity: int,
    paper_money_fill_price: float | None,
    paper_money_exit_price: float | None,
) -> dict[str, Any]:
    normalized_side = ticket_side.strip().upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError("Frozen ticket side must be BUY or SELL.")
    if (
        fakebroker_filled_quantity > 0
        and fakebroker_fill_price is None
    ) or (
        fakebroker_filled_quantity == 0
        and fakebroker_fill_price is not None
    ):
        raise ValueError("FakeBroker filled quantity and fill price are inconsistent.")
    if (fakebroker_exit_price is None) != (fakebroker_executable_pnl is None):
        raise ValueError("FakeBroker exit and executable P&L are inconsistent.")

    entry_delta = (
        round(paper_money_fill_price - fakebroker_fill_price, 6)
        if paper_money_fill_price is not None
        and fakebroker_fill_price is not None
        else None
    )
    entry_delta_bps = (
        round(entry_delta / fakebroker_fill_price * 10_000, 4)
        if entry_delta is not None and fakebroker_fill_price
        else None
    )
    exit_delta = (
        round(paper_money_exit_price - fakebroker_exit_price, 6)
        if paper_money_exit_price is not None
        and fakebroker_exit_price is not None
        else None
    )
    paper_pnl = (
        round(
            (paper_money_exit_price - paper_money_fill_price)
            * paper_money_filled_quantity,
            2,
        )
        if paper_money_exit_price is not None
        and paper_money_fill_price is not None
        and paper_money_filled_quantity > 0
        else None
    )
    if paper_pnl is not None and normalized_side == "SELL":
        paper_pnl = -paper_pnl
    fake_pnl_per_share = (
        round(fakebroker_executable_pnl / fakebroker_filled_quantity, 6)
        if fakebroker_executable_pnl is not None
        and fakebroker_filled_quantity > 0
        else None
    )
    paper_pnl_per_share = (
        round(paper_pnl / paper_money_filled_quantity, 6)
        if paper_pnl is not None and paper_money_filled_quantity > 0
        else None
    )
    pnl_delta = (
        round(paper_pnl - fakebroker_executable_pnl, 2)
        if paper_pnl is not None
        and fakebroker_executable_pnl is not None
        and paper_money_filled_quantity == fakebroker_filled_quantity
        else None
    )
    pnl_per_share_delta = (
        round(paper_pnl_per_share - fake_pnl_per_share, 6)
        if paper_pnl_per_share is not None and fake_pnl_per_share is not None
        else None
    )

    if paper_money_fill_price is None:
        comparison_status = "UNAVAILABLE_NO_PAPER_FILL"
    elif fakebroker_fill_price is None:
        comparison_status = "PAPER_FILL_ONLY"
    elif (
        paper_money_exit_price is not None
        and fakebroker_exit_price is not None
        and fakebroker_executable_pnl is not None
    ):
        comparison_status = (
            "FULL_LIFECYCLE_COMPARISON"
            if paper_money_filled_quantity == fakebroker_filled_quantity
            else "FULL_LIFECYCLE_QUANTITY_MISMATCH"
        )
    elif paper_money_exit_price is not None or fakebroker_exit_price is not None:
        comparison_status = "PARTIAL_LIFECYCLE_COMPARISON"
    else:
        comparison_status = "ENTRY_COMPARISON"

    return {
        "ticket_quantity": ticket_quantity,
        "ticket_side": normalized_side,
        "planned_entry_price": planned_entry_price,
        "fakebroker_order_status": fakebroker_order_status,
        "fakebroker_filled_quantity": fakebroker_filled_quantity,
        "fakebroker_fill_price": fakebroker_fill_price,
        "fakebroker_exit_price": fakebroker_exit_price,
        "fakebroker_executable_pnl": fakebroker_executable_pnl,
        "fakebroker_executable_pnl_per_share": fake_pnl_per_share,
        "comparison_status": comparison_status,
        "paper_minus_fake_entry_price": entry_delta,
        "paper_minus_fake_entry_bps": entry_delta_bps,
        "paper_minus_fake_exit_price": exit_delta,
        "paper_money_estimated_pnl": paper_pnl,
        "paper_money_estimated_pnl_per_share": paper_pnl_per_share,
        "paper_minus_fake_executable_pnl": pnl_delta,
        "paper_minus_fake_pnl_per_share": pnl_per_share_delta,
    }


def _finite_number(
    value: float,
    label: str,
    *,
    positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric.")
    numeric = float(value)
    if not math.isfinite(numeric) or (positive and numeric <= 0):
        qualifier = "finite and positive" if positive else "finite"
        raise ValueError(f"{label} must be {qualifier}.")
    return round(numeric, 6)


def _optional_finite_number(
    value: float | None,
    label: str,
    *,
    positive: bool = False,
) -> float | None:
    return None if value is None else _finite_number(value, label, positive=positive)


def _bounded_text(
    value: str,
    label: str,
    maximum_length: int,
    *,
    required: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{label} is required.")
    if "\x00" in normalized:
        raise ValueError(f"{label} cannot contain a null character.")
    if len(normalized) > maximum_length:
        raise ValueError(f"{label} exceeds the {maximum_length}-character limit.")
    return normalized


def _reconciliation_path(output_dir: Path, shadow_trade_id: str) -> Path:
    if not SAFE_IDENTIFIER_PATTERN.fullmatch(shadow_trade_id):
        raise ValueError("Shadow Trade identifier is not safe for an evidence filename.")
    directory = output_dir.expanduser().resolve()
    if directory.exists() and not directory.is_dir():
        raise ValueError("Reconciliation output path must identify a directory.")
    return directory / f"paper-reconciliation-{shadow_trade_id}.json"


def _load_existing_record(
    path: Path,
) -> PaperMoneyReconciliationRecord | None:
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_RECONCILIATION_BYTES:
        raise ValueError("Existing reconciliation artifact is not a bounded regular file.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"Existing reconciliation artifact cannot be loaded: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("Existing reconciliation artifact must contain an object.")
    if payload.get("schema_version") != PAPER_RECONCILIATION_SCHEMA_VERSION:
        raise ValueError("Existing reconciliation artifact has an unsupported schema.")
    raw_record = payload.get("reconciliation")
    if not isinstance(raw_record, dict):
        raise ValueError("Existing reconciliation artifact has no record object.")
    try:
        record = PaperMoneyReconciliationRecord(**raw_record)
        _validate_record(record)
    except (TypeError, ValueError) as exc:
        raise ValueError("Existing reconciliation artifact is malformed.") from exc
    return record


def _validate_record(record: PaperMoneyReconciliationRecord) -> None:
    if record.schema_version != PAPER_RECONCILIATION_SCHEMA_VERSION:
        raise ValueError("Paper reconciliation record has an unsupported schema.")
    if record.mode != PAPER_RECONCILIATION_MODE:
        raise ValueError("Paper reconciliation record has an invalid mode.")
    if (
        record.transmitting
        or record.broker_request_performed
        or record.order_action_performed
    ):
        raise ValueError("Paper reconciliation record cannot claim broker activity.")
    if not SAFE_IDENTIFIER_PATTERN.fullmatch(record.shadow_trade_id):
        raise ValueError("Paper reconciliation record has an invalid Shadow Trade ID.")
    if not re.fullmatch(r"[0-9a-f]{64}", record.source_state_sha256):
        raise ValueError("Paper reconciliation record has an invalid source hash.")
    if not re.fullmatch(r"[0-9a-f]{64}", record.request_fingerprint):
        raise ValueError("Paper reconciliation record has an invalid request fingerprint.")
    if not record.reconciliation_id.startswith("paper-reconciliation-"):
        raise ValueError("Paper reconciliation record has an invalid identifier.")
    recorded_at = parse_datetime(record.recorded_at)
    if (
        recorded_at is None
        or recorded_at.tzinfo is None
        or recorded_at.utcoffset() is None
    ):
        raise ValueError("Paper reconciliation record timestamp must include an offset.")
    normalized_result = _normalize_result(record.paper_money_result)
    if normalized_result != record.paper_money_result:
        raise ValueError("Paper reconciliation result must use its canonical label.")
    validated_fill = _validate_fill_price(
        record.paper_money_result,
        record.paper_money_fill_price,
    )
    if validated_fill != record.paper_money_fill_price:
        raise ValueError("Paper reconciliation fill price is not normalized.")
    validated_quantity = _validate_filled_quantity(
        record.paper_money_result,
        record.paper_money_filled_quantity,
        record.ticket_quantity,
    )
    if validated_quantity != record.paper_money_filled_quantity:
        raise ValueError("Paper reconciliation filled quantity is inconsistent.")
    validated_exit = _validate_exit_price(
        record.paper_money_result,
        record.paper_money_fill_price,
        record.paper_money_exit_price,
    )
    if validated_exit != record.paper_money_exit_price:
        raise ValueError("Paper reconciliation exit price is not normalized.")
    if (
        isinstance(record.fakebroker_filled_quantity, bool)
        or not isinstance(record.fakebroker_filled_quantity, int)
        or record.fakebroker_filled_quantity < 0
        or record.fakebroker_filled_quantity > record.ticket_quantity
    ):
        raise ValueError("FakeBroker filled quantity is inconsistent.")
    planned_entry = _finite_number(
        record.planned_entry_price,
        "Frozen planned entry price",
        positive=True,
    )
    fake_fill = _optional_finite_number(
        record.fakebroker_fill_price,
        "FakeBroker fill price",
        positive=True,
    )
    fake_exit = _optional_finite_number(
        record.fakebroker_exit_price,
        "FakeBroker exit price",
        positive=True,
    )
    fake_pnl = _optional_finite_number(
        record.fakebroker_executable_pnl,
        "FakeBroker executable P&L",
    )
    expected_comparison = _comparison_values(
        ticket_quantity=record.ticket_quantity,
        ticket_side=record.ticket_side,
        planned_entry_price=planned_entry,
        fakebroker_order_status=record.fakebroker_order_status,
        fakebroker_filled_quantity=record.fakebroker_filled_quantity,
        fakebroker_fill_price=fake_fill,
        fakebroker_exit_price=fake_exit,
        fakebroker_executable_pnl=fake_pnl,
        paper_money_filled_quantity=record.paper_money_filled_quantity,
        paper_money_fill_price=record.paper_money_fill_price,
        paper_money_exit_price=record.paper_money_exit_price,
    )
    for field_name, expected_value in expected_comparison.items():
        if getattr(record, field_name) != expected_value:
            raise ValueError(
                f"Paper reconciliation comparison field {field_name!r} is inconsistent."
            )
    expected_fingerprint = hashlib.sha256(
        canonical_json(_request_payload_from_record(record)).encode("utf-8")
    ).hexdigest()
    if record.request_fingerprint != expected_fingerprint:
        raise ValueError("Paper reconciliation record fingerprint does not match its content.")
    expected_id = stable_id(
        "paper-reconciliation",
        record.shadow_trade_id,
        expected_fingerprint,
    )
    if record.reconciliation_id != expected_id:
        raise ValueError("Paper reconciliation record identifier does not match its content.")


def _request_payload_from_record(
    record: PaperMoneyReconciliationRecord,
) -> dict[str, Any]:
    payload = record.to_dict()
    for field_name in ("reconciliation_id", "request_fingerprint", "recorded_at"):
        payload.pop(field_name)
    return payload


def _source_matches(path: Path, expected: bytes, expected_sha256: str) -> bool:
    try:
        if path.stat().st_size > MAX_SHADOW_STATE_BYTES:
            return False
        current = path.read_bytes()
    except OSError:
        return False
    return (
        current == expected
        and hashlib.sha256(current).hexdigest() == expected_sha256
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record write-once manual thinkorswim paperMoney evidence without "
            "contacting a broker or changing Shadow Trading state, then refresh "
            "read-only experiment evidence."
        )
    )
    parser.add_argument("--state-path", type=Path, default=SHADOW_STATE_PATH)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PAPER_RECONCILIATIONS_DIR,
    )
    parser.add_argument("--decision-cycles-path", type=Path)
    parser.add_argument("--experiments-dir", type=Path)
    parser.add_argument("--studies-dir", type=Path)
    parser.add_argument("--automation-receipts-dir", type=Path)
    parser.add_argument("--trade-id", required=True)
    parser.add_argument("--exact-ticket-entered", required=True)
    parser.add_argument("--result", required=True, choices=sorted(PAPER_RESULTS))
    parser.add_argument("--filled-quantity", type=int)
    parser.add_argument("--fill-price", type=float)
    parser.add_argument("--exit-price", type=float)
    parser.add_argument("--operator-modifications", default="")
    parser.add_argument("--exit", dest="paper_money_exit", default="")
    parser.add_argument("--outcome", dest="paper_money_outcome", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    from momentum_hunter.shadow_paper_reconciliation_workflow import (
        record_and_refresh_paper_money_evidence,
    )

    workflow = record_and_refresh_paper_money_evidence(
        state_path=args.state_path,
        output_dir=args.output_dir,
        decision_cycles_path=args.decision_cycles_path,
        experiments_dir=args.experiments_dir,
        studies_dir=args.studies_dir,
        automation_receipts_dir=args.automation_receipts_dir,
        shadow_trade_id=args.trade_id,
        exact_ticket_entered=args.exact_ticket_entered,
        paper_money_result=args.result,
        paper_money_filled_quantity=args.filled_quantity,
        paper_money_fill_price=args.fill_price,
        paper_money_exit_price=args.exit_price,
        operator_modifications=args.operator_modifications,
        paper_money_exit=args.paper_money_exit,
        paper_money_outcome=args.paper_money_outcome,
        reconciliation_notes=args.notes,
    )
    result = workflow.reconciliation
    print(
        json.dumps(
            {
                "artifactPath": str(result.path),
                "created": result.created,
                "sourceStateUnchanged": result.source_state_unchanged,
                "transmitting": result.record.transmitting,
                "brokerRequestPerformed": result.record.broker_request_performed,
                "orderActionPerformed": result.record.order_action_performed,
                "reconciliation": result.record.to_dict(),
                "experimentEvidence": (
                    workflow.experiment_evidence.to_dict()
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
