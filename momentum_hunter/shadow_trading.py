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
import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

from momentum_hunter.autonomy.auditor import AuditFinding, AuditReport, audit_execution_ledger
from momentum_hunter.autonomy.ledger import ExecutionLedger, ExecutionLedgerEvent
from momentum_hunter.autonomy.risk_governor import RiskGovernorResult, evaluate_trade_plan
from momentum_hunter.autonomy.view_models import candidate_plan_from_report_row, stable_trade_plan_id
from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_market_validity import (
    EASTERN_TZ,
    MAX_SELECTOR_PROOF_ARTIFACT_BYTES,
    SHADOW_CONSTITUTION_VERSION,
    SHADOW_SELECTOR_ARM_CONFIRMATION,
    SHADOW_SELECTOR_ARM_REQUIRED_PROOFS,
    SHADOW_SELECTOR_ARM_SCHEMA_VERSION,
    DecisionCycleStore,
    SelectorArmRecord,
    SelectorArmStore,
    ShadowMarketValidityPolicy,
    VerifiedSelectorProofArtifacts,
    classify_warnings,
    decision_cycle_summary,
    entry_window_findings,
    forced_exit_deadline,
    hash_prerequisite_proof_artifacts,
    read_stable_selector_artifact,
    runtime_build_hash,
    selector_arm_id,
    shadow_constitution_hash,
    shadow_market_policy_definition,
    validate_arm_record,
)
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import TradePlan, parse_datetime


SHADOW_SCHEMA_VERSION = 1
SHADOW_MODE = "PAPER SHADOW / NONTRANSMITTING"
SHADOW_ENGINE_VERSION = "shadow_trading_v1"
SHADOW_STRATEGY_CONTRACT_VERSION = "tradeplan-risk-shadow-v1"
SHADOW_FILL_MODEL_VERSION = "prospective-fakebroker-v1"
SHADOW_EVIDENCE_SCHEMA_VERSION = 1
DEFAULT_SHADOW_SAMPLE_VERSION = "engineering-preflight-v1"
OFFICIAL_SHADOW_SAMPLE_VERSION = "official-shadow-v1"
SHADOW_SAMPLE_ACTIVATION_SCHEMA_VERSION = 1
SHADOW_SAMPLE_ACTIVATION_CONFIRMATION = "START OFFICIAL SHADOW SAMPLE"
SHADOW_SELECTION_POLICY_SCHEMA_VERSION = 1
SHADOW_SELECTION_POLICY_VERSION = "official-shadow-deterministic-market-validity-v1"
SHADOW_STATE_PATH = DATA_DIR / "shadow-trading" / "shadow-trading-state.json"
SHADOW_SAMPLE_ACTIVATION_PATH = (
    DATA_DIR / "shadow-trading" / "shadow-sample-activation.json"
)
SHADOW_SELECTION_POLICY_PATH = (
    DATA_DIR / "shadow-trading" / "shadow-selection-policy.json"
)
SHADOW_SELECTOR_ARM_PATH = (
    DATA_DIR / "shadow-trading" / "shadow-selector-arm.json"
)
SHADOW_DECISION_CYCLES_PATH = (
    DATA_DIR / "shadow-trading" / "shadow-decision-cycles.json"
)
SHADOW_REPORTS_DIR = DATA_DIR / "reports"
MIN_MEANINGFUL_SAMPLE_SIZE = 30
TERMINAL_TRADE_STATES = {"completed", "blocked", "entry_rejected", "cancelled", "ambiguous_exit"}
ACTIVE_TRADE_STATES = {"pending_entry", "partially_filled", "open"}
TRADABLE_STATES = {"tradable", "open"}
SAMPLE_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


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
class ShadowSampleMetadata:
    sample_version: str = ""
    strategy_configuration_fingerprint: str = ""
    strategy_configuration_json: str = ""
    fill_model_version: str = ""
    evidence_schema_version: int = 0
    official_sample_authorized: bool = False


@dataclass(frozen=True)
class ShadowSampleReadiness:
    status: str
    can_start_official_sample: bool
    sample_version: str
    strategy_configuration_fingerprint: str
    fill_model_version: str
    evidence_schema_version: int
    official_sample_authorized: bool
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowSampleActivation:
    schema_version: int
    activated_at: str
    sample_metadata: ShadowSampleMetadata


@dataclass(frozen=True)
class ShadowSelectionPolicy:
    schema_version: int
    recorded_at: str
    sample_version: str
    strategy_configuration_fingerprint: str
    selection_policy_version: str
    selection_policy_fingerprint: str
    selection_policy_json: str


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
    sample_version: str = ""
    strategy_configuration_fingerprint: str = ""
    fill_model_version: str = ""
    evidence_schema_version: int = 0
    selection_policy_recorded_at: str = ""
    selection_policy_version: str = ""
    selection_policy_fingerprint: str = ""
    selector_arm_id: str = ""
    constitution_hash: str = ""
    decision_cycle_id: str = ""
    opportunity_id: str = ""
    selection_quote_json: str = ""
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
    candidate_score: float
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
    sample_metadata: ShadowSampleMetadata = field(default_factory=ShadowSampleMetadata)
    selection_policy_recorded_at: str = ""
    selection_policy_version: str = ""
    selection_policy_fingerprint: str = ""
    selector_arm_id: str = ""
    constitution_hash: str = ""
    decision_cycle_id: str = ""
    opportunity_id: str = ""
    selection_quote_json: str = ""
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


class ShadowSampleActivationStore:
    """Write-once activation evidence for the prospective official sample."""

    def __init__(self, path: Path = SHADOW_SAMPLE_ACTIVATION_PATH) -> None:
        self.path = path

    @classmethod
    def for_state_store(cls, state_store: ShadowStateStore) -> ShadowSampleActivationStore:
        if state_store.path == SHADOW_STATE_PATH:
            return cls()
        return cls(
            state_store.path.with_name(
                f"{state_store.path.stem}-sample-activation.json"
            )
        )

    def load(self) -> ShadowSampleActivation | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShadowStateError(
                f"Shadow sample activation cannot be loaded: {type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict):
            raise ShadowStateError("Shadow sample activation must contain an object.")
        if set(payload) != {"schema_version", "activated_at", "sample_metadata"}:
            raise ShadowStateError(
                "Shadow sample activation contains missing or unsupported fields."
            )
        if (
            payload.get("schema_version")
            != SHADOW_SAMPLE_ACTIVATION_SCHEMA_VERSION
        ):
            raise ShadowStateError(
                "Shadow sample activation has an unsupported or missing schema version."
            )
        activated_at = str(payload.get("activated_at", ""))
        activated = parse_datetime(activated_at)
        if (
            activated is None
            or activated.tzinfo is None
            or activated.utcoffset() is None
        ):
            raise ShadowStateError(
                "Shadow sample activation timestamp is missing, invalid, or lacks a UTC offset."
            )
        metadata_payload = payload.get("sample_metadata")
        if not isinstance(metadata_payload, dict):
            raise ShadowStateError(
                "Shadow sample activation field 'sample_metadata' must be an object."
            )
        expected_metadata_fields = {
            "sample_version",
            "strategy_configuration_fingerprint",
            "strategy_configuration_json",
            "fill_model_version",
            "evidence_schema_version",
            "official_sample_authorized",
        }
        if set(metadata_payload) != expected_metadata_fields:
            raise ShadowStateError(
                "Shadow sample activation metadata contains missing or unsupported fields."
            )
        evidence_schema_version = metadata_payload.get("evidence_schema_version")
        if (
            not isinstance(evidence_schema_version, int)
            or isinstance(evidence_schema_version, bool)
        ):
            raise ShadowStateError(
                "Shadow sample activation evidence-schema version must be an integer."
            )
        metadata = ShadowSampleMetadata(
            sample_version=str(metadata_payload.get("sample_version", "")),
            strategy_configuration_fingerprint=str(
                metadata_payload.get("strategy_configuration_fingerprint", "")
            ),
            strategy_configuration_json=str(
                metadata_payload.get("strategy_configuration_json", "")
            ),
            fill_model_version=str(metadata_payload.get("fill_model_version", "")),
            evidence_schema_version=evidence_schema_version,
            official_sample_authorized=(
                metadata_payload.get("official_sample_authorized") is True
            ),
        )
        findings = shadow_sample_metadata_findings(
            metadata,
            require_current_contract=True,
        )
        if not metadata.official_sample_authorized:
            findings.append("Official sample authorization is false.")
        if findings:
            raise ShadowStateError(
                "Shadow sample activation is invalid: " + " | ".join(findings)
            )
        return ShadowSampleActivation(
            schema_version=SHADOW_SAMPLE_ACTIVATION_SCHEMA_VERSION,
            activated_at=activated_at,
            sample_metadata=metadata,
        )

    def save_once(
        self,
        activation: ShadowSampleActivation,
    ) -> ShadowSampleActivation:
        if (
            activation.schema_version
            != SHADOW_SAMPLE_ACTIVATION_SCHEMA_VERSION
        ):
            raise ShadowStateError(
                "Shadow sample activation has an unsupported schema version."
            )
        activated_at = parse_datetime(activation.activated_at)
        if (
            activated_at is None
            or activated_at.tzinfo is None
            or activated_at.utcoffset() is None
        ):
            raise ShadowStateError(
                "Shadow sample activation timestamp is missing, invalid, or lacks a UTC offset."
            )
        findings = shadow_sample_metadata_findings(
            activation.sample_metadata,
            require_current_contract=True,
        )
        if not activation.sample_metadata.official_sample_authorized:
            findings.append("Official sample authorization is false.")
        if findings:
            raise ShadowStateError(
                "Shadow sample activation is invalid: " + " | ".join(findings)
            )
        existing = self.load()
        if existing is not None:
            if existing.sample_metadata == activation.sample_metadata:
                return existing
            raise ShadowStateError(
                "Shadow sample activation is immutable and already exists."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": activation.schema_version,
            "activated_at": activation.activated_at,
            "sample_metadata": asdict(activation.sample_metadata),
        }
        try:
            with self.path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(payload, indent=2, sort_keys=True))
                stream.write("\n")
        except FileExistsError as exc:
            existing = self.load()
            if (
                existing is not None
                and existing.sample_metadata == activation.sample_metadata
            ):
                return existing
            raise ShadowStateError(
                "Shadow sample activation is immutable and already exists."
            ) from exc
        return activation


class ShadowSelectionPolicyStore:
    """Write-once supplement linking automatic selection to an active sample."""

    def __init__(self, path: Path = SHADOW_SELECTION_POLICY_PATH) -> None:
        self.path = path

    @classmethod
    def for_state_store(
        cls,
        state_store: ShadowStateStore,
    ) -> ShadowSelectionPolicyStore:
        if state_store.path == SHADOW_STATE_PATH:
            return cls()
        return cls(
            state_store.path.with_name(
                f"{state_store.path.stem}-selection-policy.json"
            )
        )

    def load(self) -> ShadowSelectionPolicy | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShadowStateError(
                f"Shadow selection policy cannot be loaded: {type(exc).__name__}"
            ) from exc
        expected_fields = {
            "schema_version",
            "recorded_at",
            "sample_version",
            "strategy_configuration_fingerprint",
            "selection_policy_version",
            "selection_policy_fingerprint",
            "selection_policy_json",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise ShadowStateError(
                "Shadow selection policy contains missing or unsupported fields."
            )
        try:
            policy = ShadowSelectionPolicy(
                schema_version=int(payload.get("schema_version", 0)),
                recorded_at=str(payload.get("recorded_at", "")),
                sample_version=str(payload.get("sample_version", "")),
                strategy_configuration_fingerprint=str(
                    payload.get("strategy_configuration_fingerprint", "")
                ),
                selection_policy_version=str(
                    payload.get("selection_policy_version", "")
                ),
                selection_policy_fingerprint=str(
                    payload.get("selection_policy_fingerprint", "")
                ),
                selection_policy_json=str(
                    payload.get("selection_policy_json", "")
                ),
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ShadowStateError(
                "Shadow selection policy contains invalid field values."
            ) from exc
        validate_shadow_selection_policy(policy)
        return policy

    def save_once(
        self,
        policy: ShadowSelectionPolicy,
    ) -> ShadowSelectionPolicy:
        validate_shadow_selection_policy(policy)
        existing = self.load()
        if existing is not None:
            if same_shadow_selection_policy(existing, policy):
                return existing
            raise ShadowStateError(
                "Shadow selection policy is immutable and already exists."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(asdict(policy), indent=2, sort_keys=True))
                stream.write("\n")
        except FileExistsError as exc:
            existing = self.load()
            if existing is not None and same_shadow_selection_policy(
                existing,
                policy,
            ):
                return existing
            raise ShadowStateError(
                "Shadow selection policy is immutable and already exists."
            ) from exc
        return policy


def shadow_selection_policy_definition() -> dict[str, Any]:
    return {
        "selection_policy_version": SHADOW_SELECTION_POLICY_VERSION,
        "report_scope": "canonical_scheduled_trade_plan_reports_only",
        "candidate_order": [
            "canonical_rank_ascending",
            "composite_score_descending",
            "candidate_id_or_symbol_ascending",
        ],
        "candidate_rule": "highest_ranked_market_valid_eligible_candidate",
        "required_risk_status": "Simulation-only",
        "required_data_quality": "no_fatal_warnings",
        "required_plan_values": [
            "bullish_entry",
            "bullish_stop",
            "bullish_target_1",
            "positive_estimated_shares_for_500",
        ],
        "market_validity": shadow_market_policy_definition(),
        "constitution_version": SHADOW_CONSTITUTION_VERSION,
        "constitution_hash": shadow_constitution_hash(),
        "maximum_new_trades_per_source_report": 1,
        "maximum_active_positions": 1,
        "maximum_symbol_trades_per_trading_day": 1,
        "event_monitor_reports_eligible": False,
        "execution_boundary": "ProspectiveFakeBroker",
        "order_transmission": "UNAVAILABLE",
    }


def expected_shadow_selection_policy_evidence() -> dict[str, str]:
    policy_json = canonical_json(shadow_selection_policy_definition())
    return {
        "selection_policy_version": SHADOW_SELECTION_POLICY_VERSION,
        "selection_policy_fingerprint": hashlib.sha256(
            policy_json.encode("utf-8")
        ).hexdigest(),
    }


def automatic_shadow_selector_is_armed(
    arm_store: SelectorArmStore | None = None,
) -> bool:
    """Return persisted write-once arming state; source edits cannot arm the selector."""

    store = arm_store or SelectorArmStore(SHADOW_SELECTOR_ARM_PATH)
    return store.load() is not None


def build_shadow_selection_policy(
    sample_metadata: ShadowSampleMetadata,
    *,
    recorded_at: datetime,
) -> ShadowSelectionPolicy:
    policy_json = canonical_json(shadow_selection_policy_definition())
    evidence = expected_shadow_selection_policy_evidence()
    return ShadowSelectionPolicy(
        schema_version=SHADOW_SELECTION_POLICY_SCHEMA_VERSION,
        recorded_at=recorded_at.isoformat(),
        sample_version=sample_metadata.sample_version,
        strategy_configuration_fingerprint=(
            sample_metadata.strategy_configuration_fingerprint
        ),
        selection_policy_version=evidence["selection_policy_version"],
        selection_policy_fingerprint=evidence["selection_policy_fingerprint"],
        selection_policy_json=policy_json,
    )


def validate_shadow_selection_policy(policy: ShadowSelectionPolicy) -> None:
    recorded_at = parse_datetime(policy.recorded_at)
    if (
        policy.schema_version != SHADOW_SELECTION_POLICY_SCHEMA_VERSION
        or recorded_at is None
        or recorded_at.tzinfo is None
        or recorded_at.utcoffset() is None
    ):
        raise ShadowStateError(
            "Shadow selection policy has an invalid schema or timestamp."
        )
    if not SAMPLE_VERSION_PATTERN.fullmatch(policy.sample_version):
        raise ShadowStateError("Shadow selection policy sample version is invalid.")
    if not re.fullmatch(
        r"[0-9a-f]{64}",
        policy.strategy_configuration_fingerprint,
    ):
        raise ShadowStateError(
            "Shadow selection policy strategy fingerprint is invalid."
        )
    evidence = expected_shadow_selection_policy_evidence()
    if (
        policy.selection_policy_version != evidence["selection_policy_version"]
        or policy.selection_policy_fingerprint
        != evidence["selection_policy_fingerprint"]
        or policy.selection_policy_json
        != canonical_json(shadow_selection_policy_definition())
    ):
        raise ShadowStateError(
            "Shadow selection policy does not match the frozen automatic rule."
        )


def same_shadow_selection_policy(
    left: ShadowSelectionPolicy,
    right: ShadowSelectionPolicy,
) -> bool:
    return (
        left.sample_version == right.sample_version
        and left.strategy_configuration_fingerprint
        == right.strategy_configuration_fingerprint
        and left.selection_policy_version == right.selection_policy_version
        and left.selection_policy_fingerprint
        == right.selection_policy_fingerprint
        and left.selection_policy_json == right.selection_policy_json
    )


def build_shadow_sample_metadata(
    policy: ShadowExecutionPolicy,
    *,
    sample_version: str = DEFAULT_SHADOW_SAMPLE_VERSION,
    official_sample_authorized: bool = False,
) -> ShadowSampleMetadata:
    normalized_version = sample_version.strip().lower()
    if not SAMPLE_VERSION_PATTERN.fullmatch(normalized_version):
        raise ValueError(
            "Shadow sample version must use 1-64 lowercase letters, numbers, dots, underscores, or hyphens."
        )
    configuration_json = canonical_json(shadow_strategy_configuration(policy))
    return ShadowSampleMetadata(
        sample_version=normalized_version,
        strategy_configuration_fingerprint=hashlib.sha256(configuration_json.encode("utf-8")).hexdigest(),
        strategy_configuration_json=configuration_json,
        fill_model_version=SHADOW_FILL_MODEL_VERSION,
        evidence_schema_version=SHADOW_EVIDENCE_SCHEMA_VERSION,
        official_sample_authorized=official_sample_authorized,
    )


def shadow_strategy_configuration(policy: ShadowExecutionPolicy) -> dict[str, Any]:
    return {
        "shadow_engine_version": SHADOW_ENGINE_VERSION,
        "strategy_contract_version": SHADOW_STRATEGY_CONTRACT_VERSION,
        "fill_model_version": SHADOW_FILL_MODEL_VERSION,
        "evidence_schema_version": SHADOW_EVIDENCE_SCHEMA_VERSION,
        "minimum_meaningful_sample_size": MIN_MEANINGFUL_SAMPLE_SIZE,
        "execution_policy": asdict(policy),
    }


def shadow_sample_metadata_findings(
    metadata: ShadowSampleMetadata,
    *,
    expected_policy: ShadowExecutionPolicy | None = None,
    require_current_contract: bool = False,
) -> list[str]:
    findings: list[str] = []
    if not SAMPLE_VERSION_PATTERN.fullmatch(metadata.sample_version):
        findings.append("Sample version is missing or invalid.")
    if not re.fullmatch(r"[0-9a-f]{64}", metadata.strategy_configuration_fingerprint):
        findings.append("Strategy/configuration fingerprint is missing or invalid.")
    if not metadata.fill_model_version.strip():
        findings.append("Fill-model version is missing.")
    if metadata.evidence_schema_version <= 0:
        findings.append("Evidence-schema version is missing or invalid.")
    try:
        configuration = json.loads(metadata.strategy_configuration_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        configuration = None
    if not isinstance(configuration, dict):
        findings.append("Frozen strategy/configuration evidence is not a JSON object.")
        return findings
    expected_fingerprint = hashlib.sha256(
        canonical_json(configuration).encode("utf-8")
    ).hexdigest()
    if metadata.strategy_configuration_fingerprint != expected_fingerprint:
        findings.append("Strategy/configuration fingerprint does not match its frozen configuration.")
    if configuration.get("fill_model_version") != metadata.fill_model_version:
        findings.append("Fill-model version does not match the frozen configuration.")
    if configuration.get("evidence_schema_version") != metadata.evidence_schema_version:
        findings.append("Evidence-schema version does not match the frozen configuration.")
    if expected_policy is not None:
        expected_configuration = shadow_strategy_configuration(expected_policy)
        if canonical_json(configuration) != canonical_json(expected_configuration):
            findings.append("Frozen strategy/configuration does not match the active Shadow policy.")
    if require_current_contract:
        if metadata.fill_model_version != SHADOW_FILL_MODEL_VERSION:
            findings.append("Fill-model version is not the current approved Shadow model.")
        if metadata.evidence_schema_version != SHADOW_EVIDENCE_SCHEMA_VERSION:
            findings.append("Evidence-schema version is not the current approved schema.")
    return list(dict.fromkeys(findings))


def audit_shadow_sample_readiness(
    definition: ShadowSampleMetadata,
    *,
    policy: ShadowExecutionPolicy | None = None,
    trades: Iterable[ShadowTrade] = (),
) -> ShadowSampleReadiness:
    findings = shadow_sample_metadata_findings(
        definition,
        expected_policy=policy,
        require_current_contract=True,
    )
    if not definition.official_sample_authorized:
        findings.append("Official sample collection does not have a persisted activation record.")
    matching_trades = [
        trade
        for trade in trades
        if trade.sample_metadata.sample_version == definition.sample_version
    ]
    for trade in matching_trades:
        if trade.sample_metadata != definition:
            findings.append(
                f"Shadow Trade {trade.shadow_trade_id or 'unknown'} conflicts with the active sample definition."
            )
    findings = list(dict.fromkeys(findings))
    if findings:
        status = "BLOCKED"
        can_start = False
    elif matching_trades:
        status = "IN_PROGRESS"
        can_start = False
        findings.append(
            f"Sample version already contains {len(matching_trades)} persisted trade record(s)."
        )
    else:
        status = "PASS"
        can_start = True
    return ShadowSampleReadiness(
        status=status,
        can_start_official_sample=can_start,
        sample_version=definition.sample_version,
        strategy_configuration_fingerprint=definition.strategy_configuration_fingerprint,
        fill_model_version=definition.fill_model_version,
        evidence_schema_version=definition.evidence_schema_version,
        official_sample_authorized=definition.official_sample_authorized,
        findings=tuple(findings),
    )


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
        sample_version: str = DEFAULT_SHADOW_SAMPLE_VERSION,
        official_sample_authorized: bool = False,
        activation_store: ShadowSampleActivationStore | None = None,
    ) -> None:
        self.store = store or ShadowStateStore()
        self.policy = policy or ShadowExecutionPolicy()
        self.activation_store = (
            activation_store
            or ShadowSampleActivationStore.for_state_store(self.store)
        )
        self.selection_policy_store = ShadowSelectionPolicyStore.for_state_store(
            self.store
        )
        if self.store.path == SHADOW_STATE_PATH:
            self.selector_arm_store = SelectorArmStore(SHADOW_SELECTOR_ARM_PATH)
            self.decision_cycle_store = DecisionCycleStore(
                SHADOW_DECISION_CYCLES_PATH
            )
        else:
            self.selector_arm_store = SelectorArmStore(
                self.store.path.with_name(
                    f"{self.store.path.stem}-selector-arm.json"
                )
            )
            self.decision_cycle_store = DecisionCycleStore(
                self.store.path.with_name(
                    f"{self.store.path.stem}-decision-cycles.json"
                )
            )
        requested_definition = build_shadow_sample_metadata(
            self.policy,
            sample_version=sample_version,
            official_sample_authorized=official_sample_authorized,
        )
        self.sample_activation = self.activation_store.load()
        if official_sample_authorized and self.sample_activation is None:
            raise ShadowStateError(
                "Official sample authorization requires a persisted activation record."
            )
        if self.sample_activation is not None:
            self._validate_activation_for_policy(self.sample_activation)
            if sample_version != DEFAULT_SHADOW_SAMPLE_VERSION:
                expected_active_definition = build_shadow_sample_metadata(
                    self.policy,
                    sample_version=sample_version,
                    official_sample_authorized=True,
                )
                if expected_active_definition != self.sample_activation.sample_metadata:
                    raise ShadowStateError(
                        "Requested Shadow sample definition conflicts with the persisted activation."
                    )
            self.sample_definition = self.sample_activation.sample_metadata
        else:
            self.sample_definition = requested_definition
        self.fake_broker = ProspectiveFakeBroker(self.policy)

    def activate_official_sample(
        self,
        *,
        confirmation: str,
        sample_version: str = OFFICIAL_SHADOW_SAMPLE_VERSION,
    ) -> ShadowSampleActivation:
        if confirmation != SHADOW_SAMPLE_ACTIVATION_CONFIRMATION:
            raise ValueError(
                "Exact internal Shadow sample activation confirmation was not supplied."
            )
        definition = build_shadow_sample_metadata(
            self.policy,
            sample_version=sample_version,
            official_sample_authorized=True,
        )
        existing = self.activation_store.load()
        state = self.store.load()
        if existing is not None:
            self._validate_activation_for_policy(existing)
            if existing.sample_metadata != definition:
                raise ShadowStateError(
                    "The persisted Shadow sample activation uses a different immutable definition."
                )
            self._validate_state_for_activation(definition, state, allow_existing=True)
            self.sample_activation = existing
            self.sample_definition = existing.sample_metadata
            return existing

        self._validate_state_for_activation(definition, state, allow_existing=False)
        readiness = audit_shadow_sample_readiness(
            definition,
            policy=self.policy,
            trades=state.trades,
        )
        if readiness.status != "PASS" or not readiness.can_start_official_sample:
            raise ShadowStateError(
                "Official Shadow sample prerequisites did not pass: "
                + " | ".join(readiness.findings)
            )
        activation_time = now_central()
        if (
            activation_time.tzinfo is None
            or activation_time.utcoffset() is None
        ):
            raise ValueError(
                "Official Shadow sample activation time must include a UTC offset."
            )
        activation = ShadowSampleActivation(
            schema_version=SHADOW_SAMPLE_ACTIVATION_SCHEMA_VERSION,
            activated_at=activation_time.isoformat(),
            sample_metadata=definition,
        )
        persisted_activation = self.activation_store.save_once(activation)
        self.sample_activation = persisted_activation
        self.sample_definition = persisted_activation.sample_metadata
        return persisted_activation

    def sample_activation_status(self) -> dict[str, Any]:
        self._refresh_sample_activation()
        state = self.store.load()
        readiness = audit_shadow_sample_readiness(
            self.sample_definition,
            policy=self.policy,
            trades=state.trades,
        )
        review = build_shadow_review_snapshot(
            state.trades,
            sample_definition=self.sample_definition,
            policy=self.policy,
        )
        activation_active = self.sample_activation is not None
        selector_arm = self.selector_arm_record()
        selector_armed = selector_arm is not None
        automatic_collection_enabled = (
            activation_active
            and selector_armed
            and readiness.can_start_official_sample
        )
        if not activation_active:
            collection_state = "NOT_ACTIVATED"
            next_required_gate = "SAMPLE_ACTIVATION"
        elif not selector_armed:
            collection_state = "ACTIVATED_SELECTOR_NOT_ARMED"
            next_required_gate = (
                "REGULAR_MARKET_QUOTE_PROOF_AND_SELECTOR_BUNDLE"
            )
        elif not readiness.can_start_official_sample:
            collection_state = "ARMED_BLOCKED"
            next_required_gate = "RESOLVE_SAMPLE_READINESS_FINDINGS"
        else:
            collection_state = "ARMED_AWAITING_ELIGIBLE_CYCLE"
            next_required_gate = "AWAIT_ELIGIBLE_DECISION_CYCLE"
        return {
            "mode": SHADOW_MODE,
            "transmitting": False,
            "activationState": (
                "ACTIVE" if activation_active else "NOT_ACTIVE"
            ),
            "activatedAt": (
                self.sample_activation.activated_at
                if activation_active
                else None
            ),
            "sampleDefinition": shadow_sample_metadata_to_dict(
                self.sample_definition
            ),
            "readinessScope": "SAMPLE_ACTIVATION_ONLY",
            "readiness": shadow_sample_readiness_to_dict(readiness),
            "selectorArmState": "ARMED" if selector_armed else "NOT_ARMED",
            "selectorArmId": (
                selector_arm.arm_id if selector_arm is not None else None
            ),
            "automaticCollectionEnabled": automatic_collection_enabled,
            "canCollectOfficialTrade": automatic_collection_enabled,
            "collectionState": collection_state,
            "nextRequiredGate": next_required_gate,
            "persistedTradeCount": len(state.trades),
            "eligibleCompleted": review["sample"]["eligibleCompleted"],
            "minimumRequired": MIN_MEANINGFUL_SAMPLE_SIZE,
            "orderTransmission": "UNAVAILABLE",
        }

    def freeze_automatic_selection_policy(
        self,
        *,
        recorded_at: datetime | None = None,
    ) -> ShadowSelectionPolicy:
        self._refresh_sample_activation()
        if self.sample_activation is None:
            raise ShadowStateError(
                "Automatic selection policy requires an active official sample."
            )
        policy = build_shadow_selection_policy(
            self.sample_definition,
            recorded_at=recorded_at or now_central(),
        )
        persisted = self.selection_policy_store.save_once(policy)
        self._validate_selection_policy_for_active_sample(persisted)
        return persisted

    def arm_automatic_selector(
        self,
        *,
        confirmation: str,
        prerequisite_proof_paths: Mapping[str, str | Path],
        armed_at: datetime | None = None,
    ) -> SelectorArmRecord:
        if confirmation != SHADOW_SELECTOR_ARM_CONFIRMATION:
            raise ValueError(
                "Exact internal selector-arm confirmation was not supplied."
            )
        verified_proofs, armed_at = self.verify_automatic_selector_prerequisites(
            prerequisite_proof_paths,
            verified_at=armed_at,
        )
        prerequisite_proofs = verified_proofs.hashes
        constitution_hash = shadow_constitution_hash()
        build_hash = runtime_build_hash()
        expected_policy = expected_shadow_selection_policy_evidence()
        arm_id = selector_arm_id(
            sample_version=self.sample_definition.sample_version,
            strategy_configuration_fingerprint=(
                self.sample_definition.strategy_configuration_fingerprint
            ),
            selection_policy_fingerprint=expected_policy[
                "selection_policy_fingerprint"
            ],
            constitution_hash=constitution_hash,
            build_hash=build_hash,
            prerequisite_proofs=prerequisite_proofs,
        )
        record = SelectorArmRecord(
            schema_version=SHADOW_SELECTOR_ARM_SCHEMA_VERSION,
            arm_id=arm_id,
            armed_at=armed_at.isoformat(),
            sample_version=self.sample_definition.sample_version,
            strategy_configuration_fingerprint=(
                self.sample_definition.strategy_configuration_fingerprint
            ),
            selection_policy_fingerprint=expected_policy[
                "selection_policy_fingerprint"
            ],
            constitution_version=SHADOW_CONSTITUTION_VERSION,
            constitution_hash=constitution_hash,
            build_hash=build_hash,
            prerequisite_proofs=dict(prerequisite_proofs),
            prerequisite_proof_paths=dict(verified_proofs.paths),
        )
        try:
            validate_arm_record(record)
        except ValueError as exc:
            raise ShadowStateError(str(exc)) from exc
        policy = self.freeze_automatic_selection_policy(recorded_at=armed_at)
        if (
            policy.selection_policy_fingerprint
            != record.selection_policy_fingerprint
        ):
            raise ShadowStateError(
                "Frozen selection policy does not match selector-arm evidence."
            )
        try:
            return self.selector_arm_store.save_once(record)
        except ValueError as exc:
            raise ShadowStateError(str(exc)) from exc

    def verify_automatic_selector_prerequisites(
        self,
        prerequisite_proof_paths: Mapping[str, str | Path],
        *,
        verified_at: datetime | None = None,
    ) -> tuple[VerifiedSelectorProofArtifacts, datetime]:
        """Verify selector-arm evidence without persisting policy or arm state."""

        self._refresh_sample_activation()
        if self.sample_activation is None:
            raise ShadowStateError(
                "Selector-arm verification requires an active official Shadow sample."
            )
        if self.store.load().trades:
            raise ShadowStateError(
                "Selector-arm verification requires an empty official Shadow sample."
            )
        verified_at = verified_at or now_central()
        if (
            verified_at.tzinfo is None
            or verified_at.utcoffset() is None
        ):
            raise ValueError(
                "Selector-arm verification timestamp must include a UTC offset."
            )
        constitution_hash = shadow_constitution_hash()
        build_hash = runtime_build_hash()
        activated_at = require_datetime(
            self.sample_activation.activated_at,
            "sample activation timestamp",
        )
        activation_hash = self._activation_record_hash()
        try:
            verified_proofs = hash_prerequisite_proof_artifacts(
                prerequisite_proof_paths,
                sample_version=self.sample_definition.sample_version,
                activation_hash=activation_hash,
                activated_at=activated_at,
                constitution_hash=constitution_hash,
                build_hash=build_hash,
                armed_at=verified_at,
            )
        except ValueError as exc:
            raise ShadowStateError(str(exc)) from exc
        return verified_proofs, verified_at

    def selector_arm_record(self) -> SelectorArmRecord | None:
        try:
            record = self.selector_arm_store.load()
        except ValueError as exc:
            raise ShadowStateError(str(exc)) from exc
        if record is None:
            return None
        validate_arm_record(record)
        if (
            record.sample_version != self.sample_definition.sample_version
            or record.strategy_configuration_fingerprint
            != self.sample_definition.strategy_configuration_fingerprint
            or record.constitution_hash != shadow_constitution_hash()
            or record.build_hash != runtime_build_hash()
        ):
            raise ShadowStateError(
                "Selector arm record does not match the active sample, "
                "constitution, or runtime build."
            )
        self._refresh_sample_activation()
        if self.sample_activation is None:
            raise ShadowStateError(
                "Selector arm record requires the immutable sample activation."
            )
        armed_at = require_datetime(record.armed_at, "selector-arm timestamp")
        activated_at = require_datetime(
            self.sample_activation.activated_at,
            "sample activation timestamp",
        )
        try:
            activation_hash = self._activation_record_hash()
            verified_proofs = hash_prerequisite_proof_artifacts(
                record.prerequisite_proof_paths,
                sample_version=record.sample_version,
                activation_hash=activation_hash,
                activated_at=activated_at,
                constitution_hash=record.constitution_hash,
                build_hash=record.build_hash,
                armed_at=armed_at,
            )
        except (ShadowStateError, ValueError) as exc:
            raise ShadowStateError(
                "Selector arm prerequisite artifacts failed revalidation: "
                f"{exc}"
            ) from exc
        if (
            verified_proofs.hashes != record.prerequisite_proofs
            or verified_proofs.paths != record.prerequisite_proof_paths
        ):
            raise ShadowStateError(
                "Selector arm prerequisite artifacts no longer match the "
                "immutable arm record."
            )
        policy = self.load_automatic_selection_policy()
        if (
            record.selection_policy_fingerprint
            != policy.selection_policy_fingerprint
        ):
            raise ShadowStateError(
                "Selector arm record does not match the frozen selection policy."
            )
        return record

    def _activation_record_hash(self) -> str:
        try:
            _, payload = read_stable_selector_artifact(
                self.activation_store.path,
                proof_name="sample_activation",
                artifact_role="activation",
                maximum_bytes=MAX_SELECTOR_PROOF_ARTIFACT_BYTES,
            )
        except ValueError as exc:
            raise ShadowStateError(
                "Selector arming could not hash the immutable activation record."
            ) from exc
        return hashlib.sha256(payload).hexdigest()

    def selector_is_armed(self) -> bool:
        return self.selector_arm_record() is not None

    def load_automatic_selection_policy(self) -> ShadowSelectionPolicy:
        self._refresh_sample_activation()
        if self.sample_activation is None:
            raise ShadowStateError(
                "Automatic selection policy requires an active official sample."
            )
        policy = self.selection_policy_store.load()
        if policy is None:
            raise ShadowStateError(
                "Official Shadow sample trades require a persisted automatic "
                "selection policy."
            )
        self._validate_selection_policy_for_active_sample(policy)
        return policy

    def is_prospective_official_evidence(
        self,
        metadata: dict[str, Any],
        *,
        decision_at: datetime,
    ) -> bool:
        self._refresh_sample_activation()
        if self.sample_activation is None:
            raise ShadowStateError(
                "Prospective official evidence requires an active sample."
            )
        return self._official_evidence_is_post_activation(
            metadata,
            decision_at=decision_at,
            activation=self.sample_activation,
        )

    def start_trade(
        self,
        report_path: Path,
        *,
        symbol: str,
        simulation_command_id: str,
        decision_at: datetime | None = None,
        expected_source_sha256: str | None = None,
        selection_policy_evidence: dict[str, str] | None = None,
        decision_cycle_id: str = "",
        opportunity_id: str = "",
        selector_arm_id: str = "",
        constitution_hash: str = "",
        selection_quote_json: str = "",
    ) -> ShadowTrade:
        self._refresh_sample_activation()
        active_selection_policy: ShadowSelectionPolicy | None = None
        active_selector_arm: SelectorArmRecord | None = None
        if self.sample_activation is not None:
            active_selector_arm = self.selector_arm_record()
            if active_selector_arm is None:
                raise ShadowStateError(
                    "Official automatic selection is not armed by an immutable "
                    "selector-arm record."
                )
            active_selection_policy = self.load_automatic_selection_policy()
            if selection_policy_evidence != (
                expected_shadow_selection_policy_evidence()
            ):
                raise ValueError(
                    "Official Shadow sample trades require the exact frozen "
                    "automatic selection policy evidence."
                )
            if (
                selector_arm_id != active_selector_arm.arm_id
                or constitution_hash != active_selector_arm.constitution_hash
                or not decision_cycle_id
                or not opportunity_id
                or not selection_quote_json
            ):
                raise ValueError(
                    "Official Shadow sample requires exact selector-arm, "
                    "decision-cycle, opportunity, constitution, and quote evidence."
                )
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("A non-empty symbol is required.")
        if not simulation_command_id.strip():
            raise ValueError("A stable simulation command ID is required.")
        source_bytes = report_path.read_bytes()
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        if (
            self.sample_activation is not None
            and not is_canonical_scheduled_trade_report_path(report_path)
        ):
            raise ValueError(
                "Official Shadow sample selection requires a canonical scheduled "
                "trade-planning report."
            )
        if expected_source_sha256 is not None:
            normalized_expected_sha = expected_source_sha256.strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", normalized_expected_sha):
                raise ValueError("Expected source-report SHA-256 is invalid.")
            if source_sha != normalized_expected_sha:
                raise ValueError(
                    "The source report changed after automatic candidate selection."
                )
        if (
            self.sample_activation is not None
            and simulation_command_id
            != stable_id("shadow-auto-report", source_sha)
        ):
            raise ValueError(
                "Official Shadow sample command ID must be derived from the "
                "immutable source report."
            )
        try:
            source_report_json = source_bytes.decode("utf-8")
            report = json.loads(source_report_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("The trade-planning report is not valid JSON.") from exc
        if not isinstance(report, dict):
            raise ValueError("The trade-planning report must contain an object.")
        rows = report.get("candidates") or report.get("top_5_for_capital") or []
        if not isinstance(rows, list):
            raise ValueError(
                "The trade-planning report candidate collection is invalid."
            )
        matches = [(index, row) for index, row in enumerate(rows, 1) if isinstance(row, dict) and str(row.get("symbol", "")).upper() == normalized_symbol]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one persisted candidate row for {normalized_symbol}; found {len(matches)}.")
        persisted_rank, row = matches[0]
        rank = (
            int(row.get("rank") or 0)
            if self.sample_activation is not None
            else persisted_rank
        )
        if rank <= 0:
            raise ValueError(
                "Official Shadow candidate lacks a positive canonical rank."
            )
        if self.sample_activation is not None:
            cycle = self.decision_cycle_store.get(decision_cycle_id)
            if (
                cycle is None
                or cycle.get("report_sha256") != source_sha
                or cycle.get("selected_symbol") != normalized_symbol
                or int(cycle.get("selected_rank") or 0) != rank
                or cycle.get("opportunity_id") != opportunity_id
                or canonical_json(cycle.get("selection_quote"))
                != selection_quote_json
                or cycle.get("selector_arm_id") != selector_arm_id
                or cycle.get("constitution_hash") != constitution_hash
                or cycle.get("status") != "SELECTION_PENDING"
            ):
                raise ValueError(
                    "Official Shadow decision-cycle evidence does not match the "
                    "selected candidate and immutable report."
                )
        metadata = report.get("metadata", {}) if isinstance(report.get("metadata"), dict) else {}
        decision_at = decision_at or now_central()
        if self.sample_activation is not None:
            assert active_selection_policy is not None
            policy_recorded_at = require_datetime(
                active_selection_policy.recorded_at,
                "Shadow selection policy recorded_at",
            )
            if policy_recorded_at > decision_at:
                raise ValueError(
                    "Official Shadow selection policy was recorded after the "
                    "trade decision."
                )
            self._validate_prospective_official_evidence(
                metadata,
                decision_at=decision_at,
                activation=self.sample_activation,
            )
        candidate = candidate_plan_from_report_row(
            row,
            rank=rank,
            source_name=report_path.name,
            source_path=str(report_path),
            source_generated_at=str(metadata.get("generated_at", "")),
        )
        if candidate is None:
            raise ValueError(f"{normalized_symbol} does not contain a valid persisted TradePlan.")
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
        sample_definition_json = canonical_json(asdict(self.sample_definition))
        request_fingerprint_parts = [
            "shadow-request",
            source_sha,
            normalized_symbol,
            plan_fingerprint,
            sample_definition_json,
        ]
        if active_selection_policy is not None:
            request_fingerprint_parts.append(
                active_selection_policy.selection_policy_fingerprint
            )
            request_fingerprint_parts.extend(
                [
                    decision_cycle_id,
                    opportunity_id,
                    selector_arm_id,
                    constitution_hash,
                    hashlib.sha256(
                        selection_quote_json.encode("utf-8")
                    ).hexdigest(),
                ]
            )
        request_fingerprint = stable_id(*request_fingerprint_parts)
        state = self.store.load()
        if self.sample_activation is not None:
            self._validate_state_for_activation(
                self.sample_definition,
                state,
                allow_existing=True,
            )
        existing_receipt = next((item for item in state.command_receipts if item.command_id == simulation_command_id), None)
        if existing_receipt is not None:
            if existing_receipt.request_fingerprint != request_fingerprint:
                raise ValueError("Simulation command ID was reused with different evidence or arguments.")
            existing = next((item for item in state.trades if item.shadow_trade_id == existing_receipt.shadow_trade_id), None)
            if existing is None:
                raise ShadowStateError("A command receipt references a missing Shadow Trade.")
            return existing
        if self.sample_activation is not None and any(
            item.evidence.source_sha256 == source_sha for item in state.trades
        ):
            raise ValueError(
                "The official Shadow sample permits at most one trade per source report."
            )

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
                "sample_version": self.sample_definition.sample_version,
                "strategy_configuration_fingerprint": (
                    self.sample_definition.strategy_configuration_fingerprint
                ),
                "fill_model_version": self.sample_definition.fill_model_version,
                "evidence_schema_version": self.sample_definition.evidence_schema_version,
                "selection_policy_recorded_at": (
                    active_selection_policy.recorded_at
                    if active_selection_policy is not None
                    else ""
                ),
                "selection_policy_version": (
                    active_selection_policy.selection_policy_version
                    if active_selection_policy is not None
                    else ""
                ),
                "selection_policy_fingerprint": (
                    active_selection_policy.selection_policy_fingerprint
                    if active_selection_policy is not None
                    else ""
                ),
                "selector_arm_id": selector_arm_id,
                "constitution_hash": constitution_hash,
                "decision_cycle_id": decision_cycle_id,
                "opportunity_id": opportunity_id,
                "selection_quote_sha256": (
                    hashlib.sha256(selection_quote_json.encode("utf-8")).hexdigest()
                    if selection_quote_json
                    else ""
                ),
            },
        )
        quantity = int(candidate.trade_plan.estimated_shares_for_500 or 0)
        warning_assessment = classify_warnings(
            candidate.trade_plan.warnings,
            candidate.trade_plan.blocking_reasons,
        )
        can_start = (
            risk.allows_simulation
            and quantity > 0
            and candidate.trade_plan.bullish_entry is not None
            and candidate.trade_plan.bullish_stop is not None
            and candidate.trade_plan.bullish_target_1 is not None
            and (
                self.sample_activation is None
                or not warning_assessment.fatal
            )
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
                sample_version=self.sample_definition.sample_version,
                strategy_configuration_fingerprint=(
                    self.sample_definition.strategy_configuration_fingerprint
                ),
                fill_model_version=self.sample_definition.fill_model_version,
                evidence_schema_version=self.sample_definition.evidence_schema_version,
                selection_policy_recorded_at=(
                    active_selection_policy.recorded_at
                    if active_selection_policy is not None
                    else ""
                ),
                selection_policy_version=(
                    active_selection_policy.selection_policy_version
                    if active_selection_policy is not None
                    else ""
                ),
                selection_policy_fingerprint=(
                    active_selection_policy.selection_policy_fingerprint
                    if active_selection_policy is not None
                    else ""
                ),
                selector_arm_id=selector_arm_id,
                constitution_hash=constitution_hash,
                decision_cycle_id=decision_cycle_id,
                opportunity_id=opportunity_id,
                selection_quote_json=selection_quote_json,
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
        if self.sample_activation is not None:
            data_quality_state = (
                "BLOCKED" if warning_assessment.fatal else "COMPLETE"
            )
        else:
            warnings = (
                list(candidate.trade_plan.warnings)
                + list(candidate.trade_plan.blocking_reasons)
            )
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
            candidate_score=float(scoring.get("composite_score") or 0),
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
            sample_metadata=self.sample_definition,
            selection_policy_recorded_at=(
                active_selection_policy.recorded_at
                if active_selection_policy is not None
                else ""
            ),
            selection_policy_version=(
                active_selection_policy.selection_policy_version
                if active_selection_policy is not None
                else ""
            ),
            selection_policy_fingerprint=(
                active_selection_policy.selection_policy_fingerprint
                if active_selection_policy is not None
                else ""
            ),
            selector_arm_id=selector_arm_id,
            constitution_hash=constitution_hash,
            decision_cycle_id=decision_cycle_id,
            opportunity_id=opportunity_id,
            selection_quote_json=selection_quote_json,
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
        self._refresh_sample_activation()
        state = self.store.load()
        selector_arm = (
            self.selector_arm_record()
            if self.sample_activation is not None
            else None
        )
        decision_cycles = self.decision_cycle_store.load()
        audits = {trade.shadow_trade_id: audit_shadow_trade(trade) for trade in state.trades}
        review = build_shadow_review_snapshot(
            state.trades,
            audits,
            sample_definition=self.sample_definition,
            policy=self.policy,
        )
        readiness = audit_shadow_sample_readiness(
            self.sample_definition,
            policy=self.policy,
            trades=state.trades,
        )
        return {
            "schemaVersion": SHADOW_SCHEMA_VERSION,
            "mode": SHADOW_MODE,
            "engineVersion": SHADOW_ENGINE_VERSION,
            "transmitting": False,
            "summary": "Prospective Shadow Trading uses supplied evidence and FakeBroker execution only.",
            "trades": [shadow_trade_to_dict(trade) for trade in state.trades],
            "metrics": review["metrics"],
            "reviewTrades": review["trades"],
            "sample": review["sample"],
            "reviewMetrics": review["metrics"],
            "sampleReadiness": shadow_sample_readiness_to_dict(readiness),
            "selectorArm": {
                "state": "ARMED" if selector_arm is not None else "NOT_ARMED",
                "armId": selector_arm.arm_id if selector_arm is not None else None,
                "constitutionHash": (
                    selector_arm.constitution_hash
                    if selector_arm is not None
                    else shadow_constitution_hash()
                ),
                "orderTransmission": "UNAVAILABLE",
            },
            "decisionCycles": decision_cycle_summary(
                decision_cycles.cycles,
                state.trades,
            ),
            "audits": {
                trade_id: {
                    "status": report.status,
                    "findings": [asdict(finding) for finding in report.findings],
                }
                for trade_id, report in audits.items()
            },
        }

    def _refresh_sample_activation(self) -> None:
        activation = self.activation_store.load()
        if activation is None:
            if self.sample_activation is not None:
                raise ShadowStateError(
                    "Persisted Shadow sample activation disappeared during runtime."
                )
            return
        self._validate_activation_for_policy(activation)
        if (
            self.sample_activation is not None
            and activation != self.sample_activation
        ):
            raise ShadowStateError(
                "Persisted Shadow sample activation changed during runtime."
            )
        self.sample_activation = activation
        self.sample_definition = activation.sample_metadata

    def _validate_activation_for_policy(
        self,
        activation: ShadowSampleActivation,
    ) -> None:
        findings = shadow_sample_metadata_findings(
            activation.sample_metadata,
            expected_policy=self.policy,
            require_current_contract=True,
        )
        if not activation.sample_metadata.official_sample_authorized:
            findings.append("Official sample authorization is false.")
        if findings:
            raise ShadowStateError(
                "Persisted Shadow sample activation does not match the active policy: "
                + " | ".join(findings)
            )

    def _validate_selection_policy_for_active_sample(
        self,
        policy: ShadowSelectionPolicy,
    ) -> None:
        validate_shadow_selection_policy(policy)
        if (
            policy.sample_version != self.sample_definition.sample_version
            or policy.strategy_configuration_fingerprint
            != self.sample_definition.strategy_configuration_fingerprint
        ):
            raise ShadowStateError(
                "Persisted Shadow selection policy does not match the active sample."
            )
        assert self.sample_activation is not None
        recorded_at = require_datetime(
            policy.recorded_at,
            "Shadow selection policy recorded_at",
        )
        activated_at = require_datetime(
            self.sample_activation.activated_at,
            "Shadow sample activation timestamp",
        )
        if recorded_at < activated_at:
            raise ShadowStateError(
                "Persisted Shadow selection policy predates sample activation."
            )

    @staticmethod
    def _validate_state_for_activation(
        definition: ShadowSampleMetadata,
        state: ShadowTradingState,
        *,
        allow_existing: bool,
    ) -> None:
        active_legacy = [
            trade.shadow_trade_id or "unknown"
            for trade in state.trades
            if trade.status in ACTIVE_TRADE_STATES
            and trade.sample_metadata != definition
        ]
        if active_legacy:
            raise ShadowStateError(
                "Official Shadow sample activation is blocked by active legacy or "
                f"preflight trade(s): {', '.join(active_legacy)}"
            )
        matching = [
            trade
            for trade in state.trades
            if trade.sample_metadata.sample_version == definition.sample_version
        ]
        conflicting = [
            trade.shadow_trade_id or "unknown"
            for trade in matching
            if trade.sample_metadata != definition
        ]
        if conflicting:
            raise ShadowStateError(
                "Official Shadow sample activation conflicts with persisted record(s): "
                + ", ".join(conflicting)
            )
        if matching and not allow_existing:
            raise ShadowStateError(
                "Official Shadow sample records exist without the required activation evidence."
            )

    @staticmethod
    def _validate_prospective_official_evidence(
        metadata: dict[str, Any],
        *,
        decision_at: datetime,
        activation: ShadowSampleActivation,
    ) -> None:
        if not ShadowTradingService._official_evidence_is_post_activation(
            metadata,
            decision_at=decision_at,
            activation=activation,
        ):
            raise ValueError(
                "Official Shadow sample evidence predates sample activation."
            )

    @staticmethod
    def _official_evidence_is_post_activation(
        metadata: dict[str, Any],
        *,
        decision_at: datetime,
        activation: ShadowSampleActivation,
    ) -> bool:
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError(
                "Official Shadow sample decision time must include a UTC offset."
            )
        activated_at = require_datetime(
            activation.activated_at,
            "Shadow sample activation timestamp",
        )
        generated_at = require_datetime(
            str(metadata.get("generated_at", "")),
            "trade-planning report generated_at",
        )
        capture_at = require_datetime(
            str(metadata.get("source_capture_time", "")),
            "trade-planning source_capture_time",
        )
        if (
            generated_at.tzinfo is None
            or generated_at.utcoffset() is None
            or capture_at.tzinfo is None
            or capture_at.utcoffset() is None
        ):
            raise ValueError(
                "Official Shadow sample report timestamps must include UTC offsets."
            )
        if capture_at < activated_at or generated_at < activated_at:
            return False
        if capture_at > generated_at:
            raise ValueError(
                "Official Shadow sample source capture is later than report generation."
            )
        if generated_at > decision_at or capture_at > decision_at:
            raise ValueError(
                "Official Shadow sample evidence is later than the decision timestamp."
            )
        return True

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
        if trade.sample_metadata.official_sample_authorized:
            quote_age = (received_at - quote_time).total_seconds()
            if quote_age < 0 or quote_age > ShadowMarketValidityPolicy().quote_max_age_seconds:
                reason = (
                    "Official Shadow observation is future-dated or older than "
                    "the frozen 30-second quote boundary."
                )
                return append_trade_event(
                    replace(processed_trade, last_reason=reason),
                    timestamp=received_at.isoformat(),
                    event_type="quote_rejected",
                    requested_action="shadow_quote_rejected",
                    result="blocked",
                    reason=reason,
                )
            quote_eastern = quote_time.astimezone(EASTERN_TZ)
            decision_eastern = decision_time.astimezone(EASTERN_TZ)
            forced_exit = (
                quote_eastern.date() > decision_eastern.date()
                or quote_eastern >= forced_exit_deadline(quote_time)
            )
            if trade.position is not None and forced_exit:
                validation_reason = self.fake_broker.validate_quote(
                    quote,
                    received_at=received_at,
                )
                if validation_reason:
                    return append_trade_event(
                        replace(processed_trade, last_reason=validation_reason),
                        timestamp=quote.timestamp,
                        event_type="quote_rejected",
                        requested_action="shadow_quote_rejected",
                        result="blocked",
                        reason=validation_reason,
                    )
                forced_trade = processed_trade
                if trade.order is not None and trade.order.remaining_quantity > 0:
                    cancelled_order = replace(
                        trade.order,
                        status="cancelled",
                        last_update_at=quote.timestamp,
                        reason="Unfilled entry remainder cancelled at the session exit boundary.",
                    )
                    forced_trade = append_trade_event(
                        replace(forced_trade, order=cancelled_order),
                        timestamp=quote.timestamp,
                        event_type="fake_order_cancelled",
                        requested_action="fake_entry_remainder_cancelled",
                        result="cancelled",
                        reason=cancelled_order.reason,
                    )
                position = update_position_excursions(trade.position, quote)
                return self._close_position(
                    forced_trade,
                    quote,
                    position,
                    stop_executable=False,
                    target_executable=False,
                    exit_reason_override="forced_session_exit",
                )
            if (
                trade.position is None
                and trade.order is not None
                and entry_window_findings(quote_time)
            ):
                cancelled_order = replace(
                    trade.order,
                    status="cancelled",
                    last_update_at=quote.timestamp,
                    reason="Unfilled official entry cancelled outside the frozen entry window.",
                )
                return append_trade_event(
                    replace(
                        processed_trade,
                        status="cancelled",
                        order=cancelled_order,
                        last_reason=cancelled_order.reason,
                    ),
                    timestamp=quote.timestamp,
                    event_type="fake_order_cancelled",
                    requested_action="fake_entry_cancelled",
                    result="cancelled",
                    reason=cancelled_order.reason,
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
        exit_reason_override: str = "",
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
        exit_reason = (
            exit_reason_override
            or ("stop" if stop_executable else "target_1")
        )
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
    for message in shadow_sample_metadata_findings(trade.sample_metadata):
        findings.append(AuditFinding(trade.shadow_trade_id, "sample_metadata", message))
    findings.extend(automatic_selection_findings(trade))
    findings.extend(frozen_evidence_findings(trade))
    findings.extend(frozen_plan_findings(trade))
    expected_shadow_trade_id = stable_id("shadow-trade", trade.simulation_command_id, trade.evidence_snapshot_id)
    if trade.shadow_trade_id != expected_shadow_trade_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "shadow_trade_id", "Shadow Trade identity does not match its command and evidence identities."))
    if trade.outcome_id != stable_id("shadow-outcome", trade.shadow_trade_id):
        findings.append(AuditFinding(trade.shadow_trade_id, "outcome_id", "Outcome identity does not match its Shadow Trade."))
    expected_risk_id = stable_id("risk", trade.evidence_snapshot_id, trade.trade_plan_id)
    if trade.risk_decision_id != expected_risk_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "risk_decision_id", "Risk decision identity does not match the frozen evidence and TradePlan."))
    try:
        risk_payload = trade.risk_result_payload()
    except (json.JSONDecodeError, TypeError, ValueError):
        risk_payload = {}
    if str(risk_payload.get("result_id", "")) != trade.risk_decision_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "risk_result_json", "Frozen Risk Governor result does not match its identity."))
    ledger_report = audit_execution_ledger(ExecutionLedger(list(trade.ledger_events)))
    findings.extend(ledger_report.findings)
    actions = [event.requested_action for event in trade.ledger_events]
    if "risk_gate_evaluated" not in actions:
        findings.append(AuditFinding(trade.shadow_trade_id, "risk_decision_id", "Missing Risk Governor evidence."))
    if trade.order is not None:
        if "simulated_order_previewed" not in actions or "fake_order_submitted" not in actions:
            findings.append(AuditFinding(trade.shadow_trade_id, "order", "Missing preview or submit evidence."))
    if trade.ticket is not None:
        ticket_sample = (
            trade.ticket.sample_version,
            trade.ticket.strategy_configuration_fingerprint,
            trade.ticket.fill_model_version,
            trade.ticket.evidence_schema_version,
        )
        trade_sample = (
            trade.sample_metadata.sample_version,
            trade.sample_metadata.strategy_configuration_fingerprint,
            trade.sample_metadata.fill_model_version,
            trade.sample_metadata.evidence_schema_version,
        )
        if ticket_sample != trade_sample:
            findings.append(
                AuditFinding(
                    trade.shadow_trade_id,
                    "ticket",
                    "Nontransmitting ticket sample metadata does not match the Shadow Trade.",
                )
            )
        ticket_selection = (
            trade.ticket.selection_policy_recorded_at,
            trade.ticket.selection_policy_version,
            trade.ticket.selection_policy_fingerprint,
            trade.ticket.selector_arm_id,
            trade.ticket.constitution_hash,
            trade.ticket.decision_cycle_id,
            trade.ticket.opportunity_id,
            trade.ticket.selection_quote_json,
        )
        trade_selection = (
            trade.selection_policy_recorded_at,
            trade.selection_policy_version,
            trade.selection_policy_fingerprint,
            trade.selector_arm_id,
            trade.constitution_hash,
            trade.decision_cycle_id,
            trade.opportunity_id,
            trade.selection_quote_json,
        )
        if ticket_selection != trade_selection:
            findings.append(
                AuditFinding(
                    trade.shadow_trade_id,
                    "ticket",
                    "Nontransmitting ticket selection policy does not match the Shadow Trade.",
                )
            )
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


def automatic_selection_findings(trade: ShadowTrade) -> list[AuditFinding]:
    if not trade.sample_metadata.official_sample_authorized:
        return []

    findings: list[AuditFinding] = []
    if (
        not trade.selector_arm_id
        or trade.constitution_hash != shadow_constitution_hash()
        or not trade.decision_cycle_id
        or not trade.opportunity_id
        or not trade.selection_quote_json
    ):
        findings.append(
            AuditFinding(
                trade.shadow_trade_id,
                "market_validity",
                "Official Shadow Trade lacks selector-arm, constitution, "
                "decision-cycle, opportunity, or selection-quote evidence.",
            )
        )
    cycle_payload = next(
        (
            event.payload
            for event in trade.ledger_events
            if event.requested_action == "risk_gate_evaluated"
        ),
        {},
    )
    if any(
        str(cycle_payload.get(field_name, ""))
        != expected_value
        for field_name, expected_value in (
            ("selector_arm_id", trade.selector_arm_id),
            ("constitution_hash", trade.constitution_hash),
            ("decision_cycle_id", trade.decision_cycle_id),
            ("opportunity_id", trade.opportunity_id),
        )
    ):
        findings.append(
            AuditFinding(
                trade.shadow_trade_id,
                "market_validity",
                "Risk evidence does not match the frozen market-validity context.",
            )
        )
    expected = expected_shadow_selection_policy_evidence()
    if (
        trade.selection_policy_version != expected["selection_policy_version"]
        or trade.selection_policy_fingerprint
        != expected["selection_policy_fingerprint"]
    ):
        findings.append(
            AuditFinding(
                trade.shadow_trade_id,
                "selection_policy",
                "Official Shadow Trade does not carry the frozen automatic selection policy.",
            )
        )
    try:
        policy_recorded_at = require_datetime(
            trade.selection_policy_recorded_at,
            "Shadow selection policy recorded_at",
        )
        decision_at = require_datetime(
            trade.decision_timestamp,
            "Shadow Trade decision timestamp",
        )
    except ValueError:
        policy_recorded_at = None
        decision_at = None
    if (
        policy_recorded_at is None
        or decision_at is None
        or policy_recorded_at > decision_at
    ):
        findings.append(
            AuditFinding(
                trade.shadow_trade_id,
                "selection_policy",
                "Official Shadow selection policy was not frozen before its trade decision.",
            )
        )
    expected_command_id = stable_id(
        "shadow-auto-report",
        trade.evidence.source_sha256,
    )
    if trade.simulation_command_id != expected_command_id:
        findings.append(
            AuditFinding(
                trade.shadow_trade_id,
                "simulation_command_id",
                "Official Shadow command identity is not derived from its source report.",
            )
        )
    risk_events = [
        event
        for event in trade.ledger_events
        if event.requested_action == "risk_gate_evaluated"
    ]
    if (
        len(risk_events) != 1
        or str(
            risk_events[0].payload.get(
                "selection_policy_recorded_at",
                "",
            )
        )
        != trade.selection_policy_recorded_at
        or any(
            str(risk_events[0].payload.get(field_name, ""))
            != expected[field_name]
            for field_name in (
                "selection_policy_version",
                "selection_policy_fingerprint",
            )
        )
    ):
        findings.append(
            AuditFinding(
                trade.shadow_trade_id,
                "selection_policy",
                "Risk evidence does not contain the frozen automatic selection policy.",
            )
        )
    try:
        selection_quote = json.loads(trade.selection_quote_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        selection_quote = None
    if not isinstance(selection_quote, dict):
        findings.append(
            AuditFinding(
                trade.shadow_trade_id,
                "market_validity",
                "Official Shadow selection quote is not valid frozen JSON evidence.",
            )
        )
    elif str(
        risk_events[0].payload.get("selection_quote_sha256", "")
    ) != hashlib.sha256(trade.selection_quote_json.encode("utf-8")).hexdigest():
        findings.append(
            AuditFinding(
                trade.shadow_trade_id,
                "market_validity",
                "Risk evidence does not match the frozen selection quote.",
            )
        )
    return findings


def frozen_evidence_findings(trade: ShadowTrade) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    if trade.evidence.evidence_snapshot_id != trade.evidence_snapshot_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "evidence_snapshot_id", "Evidence identity does not match the trade."))
    if trade.evidence.candidate_id != trade.candidate_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "candidate_id", "Frozen evidence candidate identity does not match the trade."))
    if trade.evidence.decision_timestamp != trade.decision_timestamp:
        findings.append(AuditFinding(trade.shadow_trade_id, "decision_timestamp", "Frozen evidence decision timestamp does not match the trade."))
    if hashlib.sha256(trade.evidence.source_report_json.encode("utf-8")).hexdigest() != trade.evidence.source_sha256:
        findings.append(AuditFinding(trade.shadow_trade_id, "source_sha256", "Frozen source report does not match its hash."))
    try:
        source_report = json.loads(trade.evidence.source_report_json)
        candidate_payload = json.loads(trade.evidence.candidate_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        findings.append(AuditFinding(trade.shadow_trade_id, "candidate_json", "Frozen source or candidate evidence is not valid JSON."))
        return findings
    if not isinstance(source_report, dict) or not isinstance(candidate_payload, dict):
        findings.append(AuditFinding(trade.shadow_trade_id, "candidate_json", "Frozen source and candidate evidence must be objects."))
        return findings
    metadata = source_report.get("metadata", {}) if isinstance(source_report.get("metadata"), dict) else {}
    if str(metadata.get("generated_at", "")) != trade.evidence.source_generated_at:
        findings.append(AuditFinding(trade.shadow_trade_id, "source_generated_at", "Frozen source generation timestamp does not match its report."))
    if str(metadata.get("source_capture_path", "")) != trade.evidence.source_capture_path:
        findings.append(AuditFinding(trade.shadow_trade_id, "source_capture_path", "Frozen capture path does not match its report."))
    if str(metadata.get("source_capture_time", "")) != trade.evidence.source_capture_time:
        findings.append(AuditFinding(trade.shadow_trade_id, "source_capture_time", "Frozen capture timestamp does not match its report."))
    rows = source_report.get("candidates") or source_report.get("top_5_for_capital") or []
    matches = [
        (index, row)
        for index, row in enumerate(rows, 1)
        if isinstance(row, dict) and str(row.get("symbol", "")).upper() == trade.symbol.upper()
    ] if isinstance(rows, list) else []
    if len(matches) != 1 or canonical_json(matches[0][1]) != trade.evidence.candidate_json:
        findings.append(AuditFinding(trade.shadow_trade_id, "candidate_json", "Frozen candidate evidence does not match the frozen source report."))
        return findings
    rank, _ = matches[0]
    source_capture_key = "|".join(
        [
            trade.evidence.source_capture_path,
            trade.evidence.source_capture_time,
            trade.symbol.upper(),
            str(rank),
        ]
    )
    expected_candidate_id = stable_id(
        "candidate",
        source_capture_key,
        trade.evidence.source_sha256,
        trade.evidence.candidate_json,
    )
    if trade.candidate_id != expected_candidate_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "candidate_id", "Candidate identity does not match the frozen candidate evidence."))
    expected_evidence_id = stable_id(
        "evidence",
        trade.evidence.source_sha256,
        trade.evidence.candidate_json,
        trade.decision_timestamp,
    )
    if trade.evidence_snapshot_id != expected_evidence_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "evidence_snapshot_id", "Evidence identity does not match the frozen source, candidate, and decision time."))
    return findings


def frozen_plan_findings(trade: ShadowTrade) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    if hashlib.sha256(trade.trade_plan_json.encode("utf-8")).hexdigest() != trade.plan_fingerprint:
        findings.append(AuditFinding(trade.shadow_trade_id, "plan_fingerprint", "Frozen TradePlan fingerprint does not match."))
    try:
        plan = trade.trade_plan()
        candidate_payload = trade.evidence.candidate_payload()
    except (json.JSONDecodeError, TypeError, ValueError):
        findings.append(AuditFinding(trade.shadow_trade_id, "trade_plan_json", "Frozen TradePlan evidence is not valid."))
        return findings
    if stable_trade_plan_id(trade.symbol, plan) != trade.trade_plan_id:
        findings.append(AuditFinding(trade.shadow_trade_id, "trade_plan_id", "TradePlan identity does not match the frozen plan."))
    candidate_plan = candidate_payload.get("trade_plan")
    if not isinstance(candidate_plan, dict) or canonical_json(candidate_plan) != trade.trade_plan_json:
        findings.append(AuditFinding(trade.shadow_trade_id, "trade_plan_json", "Frozen TradePlan does not match the candidate evidence snapshot."))
    return findings


def build_shadow_review_snapshot(
    trades: Iterable[ShadowTrade],
    audits: dict[str, AuditReport] | None = None,
    *,
    sample_definition: ShadowSampleMetadata | None = None,
    policy: ShadowExecutionPolicy | None = None,
) -> dict[str, Any]:
    items = list(trades)
    active_definition = sample_definition or (
        items[0].sample_metadata
        if items
        else build_shadow_sample_metadata(ShadowExecutionPolicy())
    )
    audit_by_id = audits or {trade.shadow_trade_id: audit_shadow_trade(trade) for trade in items}
    review_trades = [
        shadow_review_trade_to_dict(
            trade,
            audit_by_id[trade.shadow_trade_id],
            sample_definition=active_definition,
        )
        for trade in items
    ]
    eligible_completed = [
        trade
        for trade, review in zip(items, review_trades)
        if review["countsTowardSample"]
    ]
    sample_items = [
        trade
        for trade in items
        if trade.sample_metadata == active_definition
    ]
    sample_reviews = [
        review
        for trade, review in zip(items, review_trades)
        if trade.sample_metadata == active_definition
    ]
    metrics = shadow_metrics(eligible_completed)
    required_sessions = (
        ShadowMarketValidityPolicy().required_distinct_sessions_for_strategy_review
    )
    distinct_sessions = {
        require_datetime(
            trade.decision_timestamp,
            "Shadow decision timestamp",
        )
        .astimezone(EASTERN_TZ)
        .date()
        .isoformat()
        for trade in eligible_completed
    }
    strategy_conclusion_eligible = (
        len(eligible_completed) >= MIN_MEANINGFUL_SAMPLE_SIZE
        and len(distinct_sessions) >= required_sessions
    )
    gated_fields = (
        "winRatePercent",
        "averageWin",
        "averageLoss",
        "expectancy",
        "averageR",
        "maximumDrawdown",
        "profitFactor",
        "idealPnl",
        "executablePnl",
        "idealVsExecutableGap",
    )
    if metrics["sampleStatus"] != "MEANINGFUL":
        for field_name in gated_fields:
            metrics[field_name] = None
        metrics["conclusion"] = (
            "Evidence collection in progress. Results are not yet sufficient for strategy conclusions."
        )
    elif not strategy_conclusion_eligible:
        metrics["conclusion"] = (
            "Descriptive metrics are available, but strategy conclusions remain "
            f"blocked until at least {required_sessions} distinct trading sessions "
            "are represented."
        )
    active_count = sum(1 for trade in sample_items if trade.status in ACTIVE_TRADE_STATES)
    readiness = audit_shadow_sample_readiness(
        active_definition,
        policy=policy,
        trades=items,
    )
    sample = {
        "minimumRequired": MIN_MEANINGFUL_SAMPLE_SIZE,
        "eligibleCompleted": len(eligible_completed),
        "completed": sum(1 for trade in sample_items if trade.status == "completed"),
        "active": active_count,
        "unfilled": sum(1 for trade in sample_items if trade.status == "pending_entry"),
        "riskRejected": sum(1 for trade in sample_items if trade.status == "blocked"),
        "dataQualityInvalidated": sum(
            1 for trade in sample_items if trade.data_quality_state != "COMPLETE"
        ),
        "excluded": sum(1 for review in sample_reviews if not review["evidenceEligible"]),
        "gateSatisfied": len(eligible_completed) >= MIN_MEANINGFUL_SAMPLE_SIZE,
        "distinctTradingSessions": len(distinct_sessions),
        "minimumDistinctSessionsForStrategyReview": required_sessions,
        "strategyConclusionEligible": strategy_conclusion_eligible,
        "concentration": {
            "symbols": concentration_counts(
                eligible_completed,
                lambda trade: trade.symbol,
            ),
            "setups": concentration_counts(
                eligible_completed,
                lambda trade: trade.setup_type,
            ),
            "catalysts": concentration_counts(
                eligible_completed,
                lambda trade: trade.catalyst,
            ),
            "marketRegimes": concentration_counts(
                eligible_completed,
                lambda trade: trade.market_regime,
            ),
            "timeOfDay": concentration_counts(
                eligible_completed,
                trade_time_bucket,
            ),
            "sectorStatus": "UNAVAILABLE_WITHOUT_FROZEN_SECTOR_IDENTITY",
        },
        "sampleVersion": active_definition.sample_version,
        "strategyConfigurationFingerprint": (
            active_definition.strategy_configuration_fingerprint
        ),
        "fillModelVersion": active_definition.fill_model_version,
        "evidenceSchemaVersion": active_definition.evidence_schema_version,
        "officialSampleAuthorized": active_definition.official_sample_authorized,
        "readinessStatus": readiness.status,
        "canStartOfficialSample": readiness.can_start_official_sample,
        "readinessFindings": list(readiness.findings),
        "status": (
            "Evidence sample is sufficient for descriptive aggregate metrics; "
            "the distinct-session gate also permits a strategy review."
            if strategy_conclusion_eligible
            else (
                "Evidence sample is sufficient for descriptive aggregate metrics, "
                "but the distinct-session strategy-review gate is not satisfied."
                if len(eligible_completed) >= MIN_MEANINGFUL_SAMPLE_SIZE
                else "Evidence collection in progress. Results are not yet sufficient for strategy conclusions."
            )
        ),
    }
    return {
        "trades": review_trades,
        "sample": sample,
        "metrics": metrics,
        "sampleReadiness": shadow_sample_readiness_to_dict(readiness),
    }


def shadow_review_trade_to_dict(
    trade: ShadowTrade,
    audit: AuditReport,
    *,
    sample_definition: ShadowSampleMetadata,
) -> dict[str, Any]:
    plan = trade.trade_plan()
    risk = trade.risk_result_payload()
    plan_frozen = not frozen_plan_findings(trade)
    evidence_frozen = not frozen_evidence_findings(trade)
    correction_terms = ("correct", "override", "amend", "edit", "mutat")
    correction_events = [
        event
        for event in trade.ledger_events
        if any(
            term in f"{event.event_type} {event.requested_action}".lower()
            for term in correction_terms
        )
    ]
    post_decision_correction = bool(correction_events)
    lock_reasons: list[str] = []
    if not evidence_frozen:
        lock_reasons.append("Frozen evidence identity or source hash does not match.")
    if not plan_frozen:
        lock_reasons.append("Frozen TradePlan fingerprint does not match.")
    if post_decision_correction:
        lock_reasons.append("A post-decision correction or override event exists.")
    if audit.status != "PASS":
        lock_reasons.extend(finding.message for finding in audit.findings)
    if trade.data_quality_state != "COMPLETE":
        lock_reasons.append(f"Data quality is {trade.data_quality_state}; this record is excluded.")
    metadata_findings = shadow_sample_metadata_findings(trade.sample_metadata)
    lock_reasons.extend(metadata_findings)
    if not trade.sample_metadata.official_sample_authorized:
        lock_reasons.append("Official sample collection was not authorized for this record.")
    if trade.sample_metadata != sample_definition:
        lock_reasons.append("Record belongs to a different or obsolete sample definition.")
    evidence_eligible = (
        evidence_frozen
        and plan_frozen
        and not post_decision_correction
        and audit.status == "PASS"
        and trade.data_quality_state == "COMPLETE"
        and not metadata_findings
        and trade.sample_metadata.official_sample_authorized
        and trade.sample_metadata == sample_definition
    )
    counts_toward_sample = (
        evidence_eligible
        and trade.status == "completed"
        and trade.outcome is not None
        and trade.outcome.status == "COMPLETED"
    )
    fill_events = [
        event
        for event in trade.ledger_events
        if event.requested_action == "fake_order_filled"
    ]
    last_fill = fill_events[-1] if fill_events else None
    spread_percent = numeric_payload(last_fill, "spread_percent")
    slippage_bps = numeric_payload(last_fill, "slippage_bps")
    if (
        slippage_bps is None
        and trade.order is not None
        and trade.order.average_fill_price is not None
        and plan.bullish_entry
    ):
        slippage_bps = round(
            (trade.order.average_fill_price - plan.bullish_entry) / plan.bullish_entry * 10_000,
            4,
        )
    execution_explanation = shadow_execution_quality_explanation(
        trade,
        spread_percent=spread_percent,
        slippage_bps=slippage_bps,
    )
    outcome = trade.outcome
    return {
        "shadowTradeId": trade.shadow_trade_id,
        "symbol": trade.symbol,
        "setup": trade.setup_type or "Unknown",
        "catalyst": trade.catalyst or "Unknown",
        "marketRegime": trade.market_regime or "Unknown",
        "session": trade.ticket.session if trade.ticket is not None else "Unknown",
        "decisionTimestamp": trade.decision_timestamp,
        "evidenceSnapshotTimestamp": (
            trade.evidence.source_capture_time
            or trade.evidence.source_generated_at
            or trade.evidence.decision_timestamp
        ),
        "tradePlanId": trade.trade_plan_id,
        "riskDecisionId": trade.risk_decision_id,
        "riskDecision": str(risk.get("status") or "Unavailable"),
        "riskReasons": [str(reason) for reason in risk.get("reasons", []) if str(reason).strip()],
        "proposedEntry": plan.bullish_entry,
        "simulatedFill": trade.order.average_fill_price if trade.order is not None else None,
        "spreadPercent": spread_percent,
        "slippageBps": slippage_bps,
        "stop": plan.bullish_stop,
        "targets": [
            value
            for value in (plan.bullish_target_1, plan.bullish_target_2)
            if value is not None
        ],
        "exit": outcome.exit_price if outcome is not None else None,
        "exitReason": outcome.exit_reason if outcome is not None else "",
        "idealPnl": outcome.gross_pnl if outcome is not None else None,
        "executablePnl": outcome.executable_pnl if outcome is not None else None,
        "rMultiple": outcome.r_multiple if outcome is not None else None,
        "mfeDollars": outcome.mfe_dollars if outcome is not None else None,
        "maeDollars": outcome.mae_dollars if outcome is not None else None,
        "durationSeconds": outcome.duration_seconds if outcome is not None else None,
        "outcome": (
            outcome.classification
            if outcome is not None
            else "RISK_REJECTED"
            if trade.status == "blocked"
            else "UNFILLED"
            if trade.status == "pending_entry"
            else "ACTIVE"
            if trade.status in ACTIVE_TRADE_STATES
            else trade.status.upper()
        ),
        "lifecycleState": trade.status,
        "dataQualityState": trade.data_quality_state,
        "sampleMetadata": shadow_sample_metadata_to_dict(trade.sample_metadata),
        "lastReason": trade.last_reason,
        "evidenceLock": {
            "evidenceFrozen": evidence_frozen,
            "planFrozen": plan_frozen,
            "decisionTimestamp": trade.decision_timestamp,
            "postDecisionCorrectionOccurred": post_decision_correction,
            "auditStatus": audit.status,
            "reasons": lock_reasons,
        },
        "evidenceEligible": evidence_eligible,
        "countsTowardSample": counts_toward_sample,
        "executionQuality": {
            "summary": execution_explanation[0],
            "factors": execution_explanation,
            "technicalCodes": [
                {
                    "timestamp": event.timestamp,
                    "eventType": event.event_type,
                    "action": event.requested_action,
                    "result": event.result,
                    "reason": event.reason,
                }
                for event in trade.ledger_events
            ],
        },
    }


def shadow_execution_quality_explanation(
    trade: ShadowTrade,
    *,
    spread_percent: float | None,
    slippage_bps: float | None,
) -> list[str]:
    explanations: list[str] = []
    if trade.status == "blocked":
        explanations.append("Risk Governor rejected the prospective trade before FakeBroker execution.")
    if trade.status == "pending_entry":
        explanations.append("No fill has occurred; the FakeBroker limit remains pending.")
    if trade.order is not None and trade.order.status == "partially_filled":
        explanations.append(
            f"Partial fill: {trade.order.filled_quantity} of {trade.order.quantity} simulated shares filled."
        )
    if trade.order is not None and trade.order.average_fill_price is not None:
        if spread_percent is not None:
            explanations.append(f"Observed spread at fill was {spread_percent:.2f}%.")
        if slippage_bps is not None:
            explanations.append(f"FakeBroker applied {slippage_bps:.2f} basis points of entry slippage.")
        submitted = parse_datetime(trade.order.submitted_at)
        filled = parse_datetime(trade.order.last_update_at)
        if submitted is not None and filled is not None and filled > submitted:
            delay_seconds = int((filled - submitted).total_seconds())
            explanations.append(f"Simulated fill arrived {delay_seconds} seconds after the frozen decision.")
    for event in trade.ledger_events:
        combined = f"{event.event_type} {event.result} {event.reason}".lower()
        if event.requested_action == "fake_order_unfilled":
            explanations.append(f"No fill: {event.reason or 'the later quote did not satisfy the limit.'}")
        elif event.requested_action == "shadow_quote_rejected":
            if "stale" in combined:
                explanations.append(f"Stale quote rejected: {event.reason}")
            elif "no quote" in combined or "missing" in combined:
                explanations.append(f"Missing quote: {event.reason}")
            elif "halt" in combined:
                explanations.append(f"Trading halt: {event.reason}")
            else:
                explanations.append(f"Quote rejected: {event.reason}")
    if (
        trade.outcome is not None
        and trade.outcome.exit_reason == "stop"
        and trade.position is not None
        and trade.outcome.exit_price < trade.position.stop_price
    ):
        gap = trade.position.stop_price - trade.outcome.exit_price
        explanations.append(f"Stop gap: executable exit was ${gap:.4f} below the frozen stop.")
    if not explanations:
        explanations.append("No execution-quality difference is recorded yet.")
    return list(dict.fromkeys(explanations))


def numeric_payload(event: ExecutionLedgerEvent | None, name: str) -> float | None:
    if event is None:
        return None
    value = event.payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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


def concentration_counts(
    trades: Iterable[ShadowTrade],
    key_fn,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for trade in trades:
        key = str(key_fn(trade) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    return [
        {
            "group": key,
            "count": count,
            "percent": rounded_ratio(count, total),
        }
        for key, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
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
            f"- Sample version: `{ticket.sample_version or 'UNVERSIONED'}`",
            f"- Strategy/configuration fingerprint: `{ticket.strategy_configuration_fingerprint or 'UNAVAILABLE'}`",
            f"- Fill-model version: `{ticket.fill_model_version or 'UNVERSIONED'}`",
            f"- Evidence-schema version: {ticket.evidence_schema_version or 'UNVERSIONED'}",
            f"- Selection-policy recorded: {ticket.selection_policy_recorded_at or 'UNAVAILABLE'}",
            f"- Selection-policy version: `{ticket.selection_policy_version or 'UNVERSIONED'}`",
            f"- Selection-policy fingerprint: `{ticket.selection_policy_fingerprint or 'UNAVAILABLE'}`",
            f"- Selector-arm ID: `{ticket.selector_arm_id or 'UNAVAILABLE'}`",
            f"- Constitution hash: `{ticket.constitution_hash or 'UNAVAILABLE'}`",
            f"- Decision-cycle ID: `{ticket.decision_cycle_id or 'UNAVAILABLE'}`",
            f"- Opportunity ID: `{ticket.opportunity_id or 'UNAVAILABLE'}`",
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


def shadow_sample_metadata_to_dict(metadata: ShadowSampleMetadata) -> dict[str, Any]:
    return {
        "sampleVersion": metadata.sample_version,
        "strategyConfigurationFingerprint": metadata.strategy_configuration_fingerprint,
        "fillModelVersion": metadata.fill_model_version,
        "evidenceSchemaVersion": metadata.evidence_schema_version,
        "officialSampleAuthorized": metadata.official_sample_authorized,
    }


def shadow_sample_readiness_to_dict(readiness: ShadowSampleReadiness) -> dict[str, Any]:
    return {
        "status": readiness.status,
        "canStartOfficialSample": readiness.can_start_official_sample,
        "sampleVersion": readiness.sample_version,
        "strategyConfigurationFingerprint": readiness.strategy_configuration_fingerprint,
        "fillModelVersion": readiness.fill_model_version,
        "evidenceSchemaVersion": readiness.evidence_schema_version,
        "officialSampleAuthorized": readiness.official_sample_authorized,
        "findings": list(readiness.findings),
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
    sample_payload = payload.get("sample_metadata")
    if sample_payload is None:
        sample_metadata = ShadowSampleMetadata()
    elif isinstance(sample_payload, dict):
        sample_metadata = ShadowSampleMetadata(
            sample_version=str(sample_payload.get("sample_version", "")),
            strategy_configuration_fingerprint=str(
                sample_payload.get("strategy_configuration_fingerprint", "")
            ),
            strategy_configuration_json=str(
                sample_payload.get("strategy_configuration_json", "")
            ),
            fill_model_version=str(sample_payload.get("fill_model_version", "")),
            evidence_schema_version=optional_int(
                sample_payload.get("evidence_schema_version")
            )
            or 0,
            official_sample_authorized=(
                sample_payload.get("official_sample_authorized") is True
            ),
        )
    else:
        raise ShadowStateError("Shadow state field 'sample_metadata' must be an object.")
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
        candidate_score=float(payload.get("candidate_score", 0)),
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
        sample_metadata=sample_metadata,
        selection_policy_recorded_at=str(
            payload.get("selection_policy_recorded_at", "")
        ),
        selection_policy_version=str(
            payload.get("selection_policy_version", "")
        ),
        selection_policy_fingerprint=str(
            payload.get("selection_policy_fingerprint", "")
        ),
        selector_arm_id=str(payload.get("selector_arm_id", "")),
        constitution_hash=str(payload.get("constitution_hash", "")),
        decision_cycle_id=str(payload.get("decision_cycle_id", "")),
        opportunity_id=str(payload.get("opportunity_id", "")),
        selection_quote_json=str(payload.get("selection_quote_json", "")),
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


def is_canonical_scheduled_trade_report_path(path: Path) -> bool:
    return (
        path.suffix.lower() == ".json"
        and path.name.startswith("trade-plan-briefing-")
        and not path.name.startswith("event-")
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


def selector_proof_bundle_paths(bundle: Path) -> dict[str, Path]:
    return {
        name: bundle / f"{name}.json"
        for name in SHADOW_SELECTOR_ARM_REQUIRED_PROOFS
    }


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
    subparsers.add_parser(
        "sample-status",
        help="Print the immutable official-sample activation and readiness state.",
    )
    sample_start_parser = subparsers.add_parser(
        "sample-start",
        help="Create the write-once official-sample activation record without creating a trade.",
    )
    sample_start_parser.add_argument(
        "--sample-version",
        default=OFFICIAL_SHADOW_SAMPLE_VERSION,
    )
    arm_check_parser = subparsers.add_parser(
        "selector-arm-check",
        help="Verify the complete selector proof bundle without persisting state.",
    )
    arm_check_parser.add_argument("--proof-bundle", type=Path, required=True)
    arm_parser = subparsers.add_parser(
        "selector-arm",
        help="Create the write-once selector arm after every proof passes.",
    )
    arm_parser.add_argument("--proof-bundle", type=Path, required=True)

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
    elif args.command == "sample-status":
        result = service.sample_activation_status()
    elif args.command == "sample-start":
        confirmation = input(
            f"Type {SHADOW_SAMPLE_ACTIVATION_CONFIRMATION!r} to activate the "
            "prospective FakeBroker-only sample: "
        )
        activation = service.activate_official_sample(
            confirmation=confirmation,
            sample_version=args.sample_version,
        )
        result = {
            "activationState": "ACTIVE",
            "activatedAt": activation.activated_at,
            "sampleDefinition": shadow_sample_metadata_to_dict(
                activation.sample_metadata
            ),
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
            "persistedTradeCount": len(service.store.load().trades),
        }
    elif args.command == "selector-arm-check":
        proofs, verified_at = service.verify_automatic_selector_prerequisites(
            selector_proof_bundle_paths(args.proof_bundle)
        )
        result = {
            "armState": "READY_TO_ARM",
            "verifiedAt": verified_at.isoformat(),
            "sampleVersion": service.sample_definition.sample_version,
            "proofArtifactCount": len(proofs.hashes),
            "proofs": proofs.hashes,
            "proofPaths": proofs.paths,
            "persistedTradeCount": len(service.store.load().trades),
            "stateMutated": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }
    elif args.command == "selector-arm":
        confirmation = input(
            f"Type {SHADOW_SELECTOR_ARM_CONFIRMATION!r} to create the "
            "FakeBroker-only selector arm: "
        )
        arm = service.arm_automatic_selector(
            confirmation=confirmation,
            prerequisite_proof_paths=selector_proof_bundle_paths(
                args.proof_bundle
            ),
        )
        result = {
            "armState": "ARMED",
            "armId": arm.arm_id,
            "armedAt": arm.armed_at,
            "sampleVersion": arm.sample_version,
            "proofArtifactCount": len(arm.prerequisite_proofs),
            "persistedTradeCount": len(service.store.load().trades),
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }
    else:
        result = service.snapshot()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
