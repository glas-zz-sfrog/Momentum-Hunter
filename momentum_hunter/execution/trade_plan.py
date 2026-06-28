from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class TradePlanMode(str, Enum):
    DISPLAY = "display"
    SIMULATION = "simulation"
    PAPER = "paper"
    LIVE_PREVIEW = "live-preview"
    LIVE = "live"


class ApprovalStatus(str, Enum):
    DRAFT = "draft"
    SIMULATION_APPROVED = "simulation-approved"
    STEVEN_REVIEW_REQUIRED = "steven-review-required"
    STEVEN_APPROVED = "steven-approved"
    LOCKED = "locked"


@dataclass(frozen=True)
class TradePlanValidationIssue:
    field: str
    status: str
    message: str


@dataclass
class TradePlan:
    ticker: str
    direction: str
    setup_type: str = ""
    entry_trigger: str = ""
    entry_limit: float | None = None
    stop_price: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    target_3: float | None = None
    trailing_stop_rule: str = ""
    position_size: int | float | None = None
    max_dollar_risk: float | None = None
    risk_reward: float | None = None
    manual_override: bool = False
    mode: TradePlanMode | str = TradePlanMode.DISPLAY
    source: str = "argus-machine"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approval_status: ApprovalStatus | str = ApprovalStatus.DRAFT
    plan_id: str = field(default_factory=lambda: f"tp-{uuid4().hex}")

    def __post_init__(self) -> None:
        self.ticker = self.ticker.strip().upper()
        self.direction = self.direction.strip().lower()
        self.setup_type = self.setup_type.strip()
        self.entry_trigger = self.entry_trigger.strip()
        self.trailing_stop_rule = self.trailing_stop_rule.strip()
        self.source = self.source.strip()
        self.mode = coerce_trade_plan_mode(self.mode)
        self.approval_status = coerce_approval_status(self.approval_status)
        if self.created_at.tzinfo is None:
            self.created_at = self.created_at.replace(tzinfo=timezone.utc)

    @property
    def has_entry(self) -> bool:
        return bool(self.entry_trigger) or self.entry_limit is not None

    @property
    def has_targets(self) -> bool:
        return self.target_1 is not None or self.target_2 is not None or self.target_3 is not None

    @property
    def is_live_mode(self) -> bool:
        return self.mode in {TradePlanMode.LIVE, TradePlanMode.LIVE_PREVIEW}

    def validation_issues(self) -> list[TradePlanValidationIssue]:
        issues: list[TradePlanValidationIssue] = []
        if not self.ticker:
            issues.append(TradePlanValidationIssue("ticker", "BLOCK", "Ticker is required."))
        if not self.direction:
            issues.append(TradePlanValidationIssue("direction", "BLOCK", "Direction is required."))
        if not self.has_entry:
            issues.append(TradePlanValidationIssue("entry", "BLOCK", "Entry trigger or entry limit is required."))
        if self.stop_price is None:
            issues.append(TradePlanValidationIssue("stop_price", "BLOCK", "Stop is required before risk approval."))
        if self.position_size is None:
            issues.append(TradePlanValidationIssue("position_size", "BLOCK", "Position size is required."))
        elif self.position_size < 0:
            issues.append(TradePlanValidationIssue("position_size", "BLOCK", "Position size must be nonnegative."))
        if self.max_dollar_risk is None:
            issues.append(TradePlanValidationIssue("max_dollar_risk", "BLOCK", "Max dollar risk is required."))
        elif self.max_dollar_risk < 0:
            issues.append(TradePlanValidationIssue("max_dollar_risk", "BLOCK", "Max dollar risk must be nonnegative."))
        if self.is_live_mode:
            issues.append(TradePlanValidationIssue("mode", "LOCKED", "Live modes are locked by default."))
        if self.manual_override:
            issues.append(
                TradePlanValidationIssue(
                    "manual_override",
                    "WARN",
                    "Manual override requires Risk Governor re-check before advancement.",
                )
            )
        return issues

    def to_ladder_rows(self) -> list[tuple[str, str]]:
        return [
            ("Ticker", self.ticker),
            ("Setup type", self.setup_type),
            ("Direction", self.direction),
            ("Entry trigger", self.entry_trigger),
            ("Entry/limit", format_optional_number(self.entry_limit)),
            ("Stop/invalidation", format_optional_number(self.stop_price)),
            ("Target 1", format_optional_number(self.target_1)),
            ("Target 2", format_optional_number(self.target_2)),
            ("Target 3", format_optional_number(self.target_3)),
            ("Trailing rule", self.trailing_stop_rule),
            ("Position size", format_optional_number(self.position_size)),
            ("Max dollar risk", format_optional_number(self.max_dollar_risk)),
            ("Risk/reward", format_optional_number(self.risk_reward)),
            ("Manual override state", "Requires re-check" if self.manual_override else "None"),
            ("Mode", self.mode.value),
            ("Approval status", self.approval_status.value),
        ]

    def to_ladder_dict(self) -> dict[str, str]:
        return dict(self.to_ladder_rows())


def coerce_trade_plan_mode(value: TradePlanMode | str) -> TradePlanMode:
    if isinstance(value, TradePlanMode):
        return value
    normalized = str(value).strip().lower().replace("_", "-")
    for mode in TradePlanMode:
        if mode.value == normalized:
            return mode
    raise ValueError(f"Unknown TradePlan mode: {value!r}")


def coerce_approval_status(value: ApprovalStatus | str) -> ApprovalStatus:
    if isinstance(value, ApprovalStatus):
        return value
    normalized = str(value).strip().lower().replace("_", "-")
    for status in ApprovalStatus:
        if status.value == normalized:
            return status
    raise ValueError(f"Unknown TradePlan approval status: {value!r}")


def format_optional_number(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
