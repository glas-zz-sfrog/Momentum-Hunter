from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import uuid4

from momentum_hunter.time_utils import now_central


@dataclass(frozen=True)
class ExecutionLedgerEvent:
    event_id: str
    timestamp: str
    event_type: str
    mode: str
    ticker: str
    trade_plan_id: str
    risk_result_id: str
    broker_adapter: str
    approval_state: str
    requested_action: str
    result: str
    actor: str
    source: str
    reason: str = ""
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ExecutionLedgerEvent":
        return cls(
            event_id=str(payload.get("event_id", "")),
            timestamp=str(payload.get("timestamp", "")),
            event_type=str(payload.get("event_type", "")),
            mode=str(payload.get("mode", "")),
            ticker=str(payload.get("ticker", "")),
            trade_plan_id=str(payload.get("trade_plan_id", "")),
            risk_result_id=str(payload.get("risk_result_id", "")),
            broker_adapter=str(payload.get("broker_adapter", "")),
            approval_state=str(payload.get("approval_state", "")),
            requested_action=str(payload.get("requested_action", "")),
            result=str(payload.get("result", "")),
            actor=str(payload.get("actor", "")),
            source=str(payload.get("source", "")),
            reason=str(payload.get("reason", "")),
            payload=dict(payload.get("payload", {})) if isinstance(payload.get("payload"), dict) else {},
        )


class ExecutionLedger:
    def __init__(self, events: list[ExecutionLedgerEvent] | None = None) -> None:
        self._events = list(events or [])

    @property
    def events(self) -> list[ExecutionLedgerEvent]:
        return list(self._events)

    def append(self, event: ExecutionLedgerEvent) -> ExecutionLedgerEvent:
        self._events.append(event)
        return event

    def record(
        self,
        *,
        event_type: str,
        mode: str,
        ticker: str = "",
        trade_plan_id: str = "",
        risk_result_id: str = "",
        broker_adapter: str = "",
        approval_state: str = "simulation-only",
        requested_action: str,
        result: str,
        actor: str = "Argus Machine",
        source: str = "Argus Machine Console",
        reason: str = "",
        payload: dict[str, object] | None = None,
        timestamp: datetime | None = None,
    ) -> ExecutionLedgerEvent:
        event = ExecutionLedgerEvent(
            event_id=f"ledger-{uuid4().hex[:12]}",
            timestamp=(timestamp or now_central()).isoformat(),
            event_type=event_type,
            mode=mode,
            ticker=ticker,
            trade_plan_id=trade_plan_id,
            risk_result_id=risk_result_id,
            broker_adapter=broker_adapter,
            approval_state=approval_state,
            requested_action=requested_action,
            result=result,
            actor=actor,
            source=source,
            reason=reason,
            payload=dict(payload or {}),
        )
        return self.append(event)

    def to_dicts(self) -> list[dict[str, object]]:
        return [event.to_dict() for event in self._events]

    @classmethod
    def from_dicts(cls, rows: list[dict[str, object]]) -> "ExecutionLedger":
        return cls([ExecutionLedgerEvent.from_dict(row) for row in rows])


def render_machine_log(events: list[ExecutionLedgerEvent], *, limit: int = 8) -> str:
    if not events:
        return "Argus Machine loaded in Simulation Lab. No events recorded yet."
    lines = [render_event_line(event) for event in events[-limit:]]
    return "\n".join(lines)


def render_event_line(event: ExecutionLedgerEvent) -> str:
    ticker = f" | {event.ticker}" if event.ticker else ""
    reason = f" | {event.reason}" if event.reason else ""
    return (
        f"{event.timestamp} | {event.mode}{ticker} | "
        f"{event.requested_action} -> {event.result}{reason}"
    )

