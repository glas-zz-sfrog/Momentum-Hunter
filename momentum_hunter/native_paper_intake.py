"""Engine-owned, non-upgradable disabled observations of Continuous decisions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from momentum_hunter.autonomy.ledger import ExecutionLedgerEvent
from momentum_hunter.native_paper_store import NativePaperError, NativePaperStore, encoded, fingerprint, identity


class DisabledPaperIntake:
    """No adapter, risk account, arm method, execution owner or Science input."""

    def __init__(self, *, root: Path, runtime_fingerprint: str) -> None:
        if len(runtime_fingerprint) != 64:
            raise NativePaperError("RUNTIME_BINDING_REQUIRED")
        self.binding = {"schema": 1, "runtime_fingerprint": runtime_fingerprint,
                        "root": str(root.resolve()), "mode": "DISABLED_CONTINUOUS_OBSERVATION"}
        self.store = NativePaperStore(root, binding=self.binding)

    def record(self, payload: dict, at: datetime) -> str:
        value = json.loads(encoded(payload))
        if (value.get("runtime_fingerprint") != self.binding["runtime_fingerprint"]
                or value.get("execution_authority") != "NONE"
                or value.get("state") != "DISABLED"
                or value.get("owner") != "CONTINUOUS_ENGINE_COMPOSITION"):
            raise NativePaperError("DISABLED_INTAKE_BOUNDARY_MISMATCH")
        source = value["source_identity"]
        iid = identity("disabled-paper-observation", self.binding["runtime_fingerprint"], source)
        with self.store.lease.transaction():
            state, records = self.store.load()
            previous = state["disabled_intents"].get(iid)
            if previous is not None:
                if fingerprint(previous) != fingerprint(value):
                    raise NativePaperError("DISABLED_INTAKE_SOURCE_CONFLICT")
                return iid
            state["disabled_intents"][iid] = value
            self.store.commit(state, ExecutionLedgerEvent(
                event_id=identity("disabled-paper-event", iid), timestamp=at.isoformat(),
                event_type="DISABLED_CONTINUOUS_INTENT", mode="DISABLED",
                ticker=value["request"]["symbol"], trade_plan_id=value["result"].get("plan_id") or "",
                risk_result_id="", broker_adapter="NONE", approval_state="UNARMED",
                requested_action="RECORD_ONLY", result="DISABLED", actor="ENGINE",
                source="continuous-composition", reason="NO_EXECUTION_AUTHORITY", payload=value))
        return iid
