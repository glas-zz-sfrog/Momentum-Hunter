from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.review import CandidateIdentity
from momentum_hunter.time_utils import now_central


ENTRY_PLANS_PATH = DATA_DIR / "entry-plans.json"
ENTRY_PLAN_SCHEMA_VERSION = 1
REQUIRED_PLAN_FIELDS = {
    "trigger": "missing trigger",
    "stop": "missing stop",
    "invalidation": "missing invalidation",
    "max_loss": "missing max loss",
}


@dataclass
class EntryPlan:
    identity: CandidateIdentity
    trigger: str = ""
    stop: str = ""
    thesis: str = ""
    invalidation: str = ""
    max_loss: str = ""
    position_size: str = ""
    planned_hold_time: str = ""
    notes: str = ""
    plan_complete: bool = False
    updated_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)


def load_entry_plans(path: Path | None = None) -> dict[str, EntryPlan]:
    path = path or ENTRY_PLANS_PATH
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    plans = payload.get("plans", payload if isinstance(payload, dict) else {})
    return {
        key: entry_plan_from_dict(item)
        for key, item in plans.items()
        if isinstance(item, dict) and item.get("identity")
    }


def save_entry_plans(plans: dict[str, EntryPlan], path: Path | None = None) -> Path:
    path = path or ENTRY_PLANS_PATH
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ENTRY_PLAN_SCHEMA_VERSION,
        "updated_at": now_central().isoformat(),
        "plans": {key: entry_plan_to_dict(value) for key, value in sorted(plans.items())},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def upsert_entry_plan(
    plans: dict[str, EntryPlan],
    identity: CandidateIdentity,
    *,
    trigger: str = "",
    stop: str = "",
    thesis: str = "",
    invalidation: str = "",
    max_loss: str = "",
    position_size: str = "",
    planned_hold_time: str = "",
    notes: str = "",
    plan_complete: bool | None = None,
    updated_at: datetime | None = None,
    path: Path | None = None,
) -> EntryPlan:
    updated_at = updated_at or now_central()
    plan = EntryPlan(
        identity=identity,
        trigger=trigger.strip(),
        stop=stop.strip(),
        thesis=thesis.strip(),
        invalidation=invalidation.strip(),
        max_loss=max_loss.strip(),
        position_size=position_size.strip(),
        planned_hold_time=planned_hold_time.strip(),
        notes=notes.strip(),
        updated_at=updated_at,
    )
    plan.warnings = entry_plan_warnings(plan)
    plan.plan_complete = not plan.warnings if plan_complete is None else bool(plan_complete)
    if plan.plan_complete and plan.warnings:
        plan.plan_complete = False
    plans[identity.key] = plan
    save_entry_plans(plans, path=path)
    return plan


def entry_plan_warnings(plan: EntryPlan) -> list[str]:
    warnings = []
    for field_name, warning in REQUIRED_PLAN_FIELDS.items():
        if not getattr(plan, field_name).strip():
            warnings.append(warning)
    return warnings


def entry_plan_to_dict(plan: EntryPlan) -> dict:
    return {
        "identity": asdict(plan.identity),
        "trigger": plan.trigger,
        "stop": plan.stop,
        "thesis": plan.thesis,
        "invalidation": plan.invalidation,
        "max_loss": plan.max_loss,
        "position_size": plan.position_size,
        "planned_hold_time": plan.planned_hold_time,
        "notes": plan.notes,
        "plan_complete": plan.plan_complete,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        "warnings": list(plan.warnings or entry_plan_warnings(plan)),
    }


def entry_plan_from_dict(payload: dict) -> EntryPlan:
    identity_payload = payload["identity"]
    updated_at = payload.get("updated_at")
    plan = EntryPlan(
        identity=CandidateIdentity(
            capture_id=identity_payload.get("capture_id", ""),
            capture_date=identity_payload.get("capture_date", ""),
            session=identity_payload.get("session", ""),
            provider=identity_payload.get("provider", ""),
            scanner=identity_payload.get("scanner", ""),
            ticker=identity_payload.get("ticker", ""),
        ),
        trigger=payload.get("trigger", ""),
        stop=payload.get("stop", ""),
        thesis=payload.get("thesis", ""),
        invalidation=payload.get("invalidation", ""),
        max_loss=payload.get("max_loss", ""),
        position_size=payload.get("position_size", ""),
        planned_hold_time=payload.get("planned_hold_time", ""),
        notes=payload.get("notes", ""),
        plan_complete=bool(payload.get("plan_complete", False)),
        updated_at=datetime.fromisoformat(updated_at) if updated_at else None,
        warnings=list(payload.get("warnings", [])),
    )
    plan.warnings = entry_plan_warnings(plan)
    if plan.warnings:
        plan.plan_complete = False
    return plan
