from __future__ import annotations

"""Independent one-entry Alpaca Paper supervisor for continuous admissions."""

import argparse
import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Protocol

from momentum_hunter.alpaca_paper_broker import (
    AlpacaPaperBrokerAdapter,
    AlpacaPaperBrokerError,
)
from momentum_hunter.alpaca_paper_engineering import (
    CONTINUOUS_PAPER_DECISION_CONFIRMATION,
    AlpacaPaperEngineeringEngine,
    PaperEngineeringAnomaly,
    PaperEngineeringError,
    load_paper_engineering_arm,
    load_paper_engineering_policy,
)
from momentum_hunter.alpaca_paper_onboarding import (
    ALPACA_PAPER_BASE_URL,
    AlpacaPaperLane,
)
from momentum_hunter.continuous_paper_contract import (
    ContinuousPaperAdmissionIntent,
    ContinuousPaperContractError,
    parse_continuous_paper_admission_intent,
)
from momentum_hunter.continuous_production import (
    ProductionRemoteWriter,
    _read_config as _read_research_config,
    _topology as _research_topology,
)
from momentum_hunter.continuous_runtime import (
    WRITER_ACCEPTED,
    WRITER_DUPLICATE,
    build_evidence_write_intent,
)
from momentum_hunter.provider_neutral_allocation import evidence_fingerprint
from momentum_hunter.schwab_market_data import SchwabMarketDataQuoteSource
from momentum_hunter.time_utils import now_central


SCHEMA_VERSION = 1
PROFILE = "continuous-paper-one-entry-canary-v1"
ENTRY_AUTHORITY_DISABLED = "ENTRY_AUTHORITY_DISABLED"
CANARY_ARMED_ONE_ENTRY = "CANARY_ARMED_ONE_ENTRY"
LOCKED_AFTER_CANARY_ENTRY = "LOCKED_AFTER_CANARY_ENTRY"
PAUSED_AFTER_CANARY = "PAUSED_AFTER_CANARY"
ALLOWED_MODES = frozenset(
    {
        ENTRY_AUTHORITY_DISABLED,
        CANARY_ARMED_ONE_ENTRY,
        LOCKED_AFTER_CANARY_ENTRY,
        PAUSED_AFTER_CANARY,
    }
)
TRADE_PLAN_PRODUCER_AVAILABLE = "AVAILABLE"
ARM_CONFIRMATION = "ARM ONE CONTINUOUS ALPACA PAPER ENTRY"
PAPER_EXECUTION_EVENT = "PAPER_EXECUTION_EVENT"
PAPER_TRADE_CREATED = "PAPER_TRADE_CREATED"
_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ContinuousPaperError(RuntimeError):
    pass


class ContinuousPaperEnvironmentAnomaly(ContinuousPaperError):
    pass


class EvidenceWriter(Protocol):
    def write_intent(self, intent): ...


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes({"domain": domain, "value": value})
    ).hexdigest()


def _atomic_replace(path: Path, payload: object) -> None:
    encoded = _canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    with temporary.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class ContinuousPaperConfig:
    research_deployment_config_path: Path
    paper_state_root: Path
    paper_engineering_root: Path
    installed_product_sha: str
    sample_id: str
    policy_fingerprint: str
    activation_timestamp: str
    broker_host: str = ALPACA_PAPER_BASE_URL
    profile: str = PROFILE

    def validate(self) -> None:
        if self.profile != PROFILE:
            raise ContinuousPaperError("Continuous Paper profile is invalid.")
        if self.broker_host != ALPACA_PAPER_BASE_URL:
            raise ContinuousPaperError("Continuous Paper host is not the exact Paper host.")
        if not _GIT_SHA.fullmatch(self.installed_product_sha):
            raise ContinuousPaperError("Continuous Paper product identity is invalid.")
        if not self.sample_id.startswith("continuous-paper-engineering-"):
            raise ContinuousPaperError("Continuous Paper sample identity is invalid.")
        if not _SHA256.fullmatch(self.policy_fingerprint):
            raise ContinuousPaperError("Continuous Paper policy identity is invalid.")
        observed = _aware(self.activation_timestamp)
        if observed is None:
            raise ContinuousPaperError("Continuous Paper activation timestamp is invalid.")


@dataclass
class ContinuousPaperState:
    mode: str = ENTRY_AUTHORITY_DISABLED
    pipeline_state: str = "IDLE"
    broker_state: str = "PAPER_UNCHECKED"
    entry_budget_consumed: bool = False
    current_admission_id: str = ""
    current_trade_plan_id: str = ""
    current_symbol: str = ""
    current_broker_order_id: str = ""
    current_position_quantity: str = ""
    protective_order_state: str = ""
    last_paper_forward_progress_at: str = ""
    last_evidence_sequence: int = 0
    processed_admission_fingerprints: list[str] = field(default_factory=list)
    processed_trade_plan_ids: list[str] = field(default_factory=list)
    last_classification: str = ""
    last_failure: str = ""

    def validate(self) -> None:
        if self.mode not in ALLOWED_MODES:
            raise ContinuousPaperError("Continuous Paper mode is invalid.")
        if self.last_evidence_sequence < 0:
            raise ContinuousPaperError("Continuous Paper sequence is invalid.")
        if len(self.processed_admission_fingerprints) > 2048 or any(
            not _SHA256.fullmatch(item)
            for item in self.processed_admission_fingerprints
        ):
            raise ContinuousPaperError("Continuous Paper processed identity is invalid.")
        if len(self.processed_trade_plan_ids) > 2048 or any(
            not _SHA256.fullmatch(item) for item in self.processed_trade_plan_ids
        ):
            raise ContinuousPaperError(
                "Continuous Paper processed TradePlan identity is invalid."
            )
        if self.entry_budget_consumed and self.mode == CANARY_ARMED_ONE_ENTRY:
            raise ContinuousPaperError("Consumed Paper entry budget cannot remain armed.")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": SCHEMA_VERSION,
            "profile": PROFILE,
            "mode": self.mode,
            "pipelineState": self.pipeline_state,
            "brokerState": self.broker_state,
            "entryBudgetConsumed": self.entry_budget_consumed,
            "currentAdmissionId": self.current_admission_id,
            "currentTradePlanId": self.current_trade_plan_id,
            "currentSymbol": self.current_symbol,
            "currentBrokerOrderId": self.current_broker_order_id,
            "currentPositionQuantity": self.current_position_quantity,
            "protectiveOrderState": self.protective_order_state,
            "lastPaperForwardProgressAt": self.last_paper_forward_progress_at,
            "lastEvidenceSequence": self.last_evidence_sequence,
            "processedAdmissionFingerprints": list(
                self.processed_admission_fingerprints
            ),
            "processedTradePlanIds": list(self.processed_trade_plan_ids),
            "lastClassification": self.last_classification,
            "lastFailure": self.last_failure,
            "environment": "ALPACA_PAPER",
            "brokerHost": ALPACA_PAPER_BASE_URL,
            "alpacaLive": "UNAVAILABLE",
            "schwabOrders": "UNAVAILABLE",
            "liveExecution": "UNAVAILABLE",
        }
        payload["fingerprint"] = evidence_fingerprint(payload)
        return payload


def load_config(path: Path) -> ContinuousPaperConfig:
    payload = _read_json(path, "Continuous Paper configuration")
    try:
        config = ContinuousPaperConfig(
            research_deployment_config_path=Path(
                str(payload["researchDeploymentConfigPath"])
            ),
            paper_state_root=Path(str(payload["paperStateRoot"])),
            paper_engineering_root=Path(str(payload["paperEngineeringRoot"])),
            installed_product_sha=str(payload["installedProductSha"]),
            sample_id=str(payload["sampleId"]),
            policy_fingerprint=str(payload["policyFingerprint"]),
            activation_timestamp=str(payload["activationTimestamp"]),
            broker_host=str(payload["brokerHost"]),
            profile=str(payload["profile"]),
        )
    except (KeyError, TypeError, ValueError):
        raise ContinuousPaperError(
            "Continuous Paper configuration fields are invalid."
        ) from None
    config.validate()
    if payload.get("fingerprint") != evidence_fingerprint(
        {key: value for key, value in payload.items() if key != "fingerprint"}
    ):
        raise ContinuousPaperError("Continuous Paper configuration changed.")
    return config


def load_state(config: ContinuousPaperConfig) -> ContinuousPaperState:
    path = config.paper_state_root / "paper-state.json"
    if not path.exists():
        return ContinuousPaperState()
    payload = _read_json(path, "Continuous Paper state")
    fingerprint = payload.pop("fingerprint", None)
    if fingerprint != evidence_fingerprint(payload):
        raise ContinuousPaperError("Continuous Paper state fingerprint is invalid.")
    try:
        state = ContinuousPaperState(
            mode=str(payload["mode"]),
            pipeline_state=str(payload["pipelineState"]),
            broker_state=str(payload["brokerState"]),
            entry_budget_consumed=bool(payload["entryBudgetConsumed"]),
            current_admission_id=str(payload["currentAdmissionId"]),
            current_trade_plan_id=str(payload["currentTradePlanId"]),
            current_symbol=str(payload["currentSymbol"]),
            current_broker_order_id=str(payload.get("currentBrokerOrderId", "")),
            current_position_quantity=str(
                payload.get("currentPositionQuantity", "")
            ),
            protective_order_state=str(payload.get("protectiveOrderState", "")),
            last_paper_forward_progress_at=str(
                payload["lastPaperForwardProgressAt"]
            ),
            last_evidence_sequence=int(payload["lastEvidenceSequence"]),
            processed_admission_fingerprints=[
                str(item) for item in payload["processedAdmissionFingerprints"]
            ],
            processed_trade_plan_ids=[
                str(item) for item in payload.get("processedTradePlanIds", [])
            ],
            last_classification=str(payload["lastClassification"]),
            last_failure=str(payload["lastFailure"]),
        )
    except (KeyError, TypeError, ValueError):
        raise ContinuousPaperError("Continuous Paper state fields are invalid.") from None
    state.validate()
    return state


def save_state(config: ContinuousPaperConfig, state: ContinuousPaperState) -> None:
    state.validate()
    _atomic_replace(config.paper_state_root / "paper-state.json", state.to_dict())


def write_disabled_config(
    *,
    path: Path,
    research_deployment_config_path: Path,
    paper_state_root: Path,
    paper_engineering_root: Path,
    installed_product_sha: str,
    sample_id: str,
    policy_fingerprint: str,
    activation_timestamp: str,
) -> ContinuousPaperConfig:
    config = ContinuousPaperConfig(
        research_deployment_config_path=research_deployment_config_path,
        paper_state_root=paper_state_root,
        paper_engineering_root=paper_engineering_root,
        installed_product_sha=installed_product_sha,
        sample_id=sample_id,
        policy_fingerprint=policy_fingerprint,
        activation_timestamp=activation_timestamp,
    )
    config.validate()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "profile": PROFILE,
        "researchDeploymentConfigPath": str(research_deployment_config_path),
        "paperStateRoot": str(paper_state_root),
        "paperEngineeringRoot": str(paper_engineering_root),
        "installedProductSha": installed_product_sha,
        "sampleId": sample_id,
        "policyFingerprint": policy_fingerprint,
        "activationTimestamp": activation_timestamp,
        "brokerHost": ALPACA_PAPER_BASE_URL,
        "entryAuthority": ENTRY_AUTHORITY_DISABLED,
        "alpacaLive": "UNAVAILABLE",
        "schwabOrders": "UNAVAILABLE",
        "liveExecution": "UNAVAILABLE",
    }
    payload["fingerprint"] = evidence_fingerprint(payload)
    encoded = _canonical_bytes(payload)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ContinuousPaperError(
                "Existing Continuous Paper configuration conflicts with the requested identity."
            )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    state_path = paper_state_root / "paper-state.json"
    if not state_path.exists():
        save_state(config, ContinuousPaperState())
    return config


class ContinuousPaperSupervisor:
    def __init__(
        self,
        *,
        config: ContinuousPaperConfig,
        adapter=None,
        quote_source=None,
        writer: EvidenceWriter | None = None,
        clock: Callable[[], datetime] = now_central,
    ) -> None:
        config.validate()
        self.config = config
        self.clock = clock
        self.research_config = _read_research_config(
            config.research_deployment_config_path
        )
        self._validate_deployment_identity()
        policy = load_paper_engineering_policy(config.paper_engineering_root)
        arm, _ = load_paper_engineering_arm(
            policy=policy,
            output_directory=config.paper_engineering_root,
        )
        if (
            policy.sample_id != config.sample_id
            or policy.fingerprint != config.policy_fingerprint
            or arm.sample_id != config.sample_id
            or arm.policy_fingerprint != config.policy_fingerprint
            or arm.activated_at != config.activation_timestamp
        ):
            raise ContinuousPaperError(
                "Continuous Paper sample, policy, arm, or activation identity is inconsistent."
            )
        self.adapter = adapter or AlpacaPaperBrokerAdapter(
            lane=AlpacaPaperLane.CANARY_REALISTIC,
            base_url=config.broker_host,
        )
        self.quote_source = quote_source or SchwabMarketDataQuoteSource()
        self.writer = writer or ProductionRemoteWriter(
            self.research_config,
            source_identity=(
                "production-continuous-paper-"
                + hashlib.sha256(config.sample_id.encode("ascii")).hexdigest()[:24]
            ),
        )
        self.engine = AlpacaPaperEngineeringEngine(
            adapter=self.adapter,
            quote_source=self.quote_source,
            output_directory=config.paper_engineering_root,
            clock=clock,
        )

    def _validate_deployment_identity(self) -> None:
        if self.research_config.get("mode") != "RESEARCH_ONLY":
            raise ContinuousPaperError("Continuous research is not RESEARCH_ONLY.")
        if self.research_config.get("orderCapability") != "UNAVAILABLE":
            raise ContinuousPaperError(
                "Continuous research unexpectedly exposes order capability."
            )
        if self.research_config.get("installedProductSha") != self.config.installed_product_sha:
            raise ContinuousPaperError(
                "Continuous Paper product identity does not match the installed research runtime."
            )

    def _assert_trade_plan_producer_available(self) -> None:
        if (
            self.research_config.get("continuousTradePlanProducer")
            != TRADE_PLAN_PRODUCER_AVAILABLE
        ):
            raise ContinuousPaperError(
                "CONTINUOUS_TRADEPLAN_PRODUCER_UNAVAILABLE"
            )

    def preflight_environment(self) -> dict[str, object]:
        receipts = []
        self.adapter.evidence_sink = receipts.append
        account = self.adapter.get_account()
        positions = self.adapter.list_positions()
        orders = self.adapter.list_orders(status="open")
        if not account.usable:
            raise ContinuousPaperEnvironmentAnomaly(
                "Canary Paper account is not active and usable."
            )
        if positions or orders:
            raise ContinuousPaperEnvironmentAnomaly(
                "PAPER_ENVIRONMENT_NOT_CLEAN"
            )
        return {
            "classification": "PAPER_ENVIRONMENT_CLEAN",
            "environment": "ALPACA_PAPER",
            "host": ALPACA_PAPER_BASE_URL,
            "accountStatus": account.status,
            "positions": 0,
            "openOrders": 0,
            "providerPaths": [item.path for item in receipts],
            "providerStatuses": [item.http_status for item in receipts],
            "credentialsLoaded": True,
            "unknownActivityModified": 0,
            "alpacaLive": "UNAVAILABLE",
        }

    def arm(self, *, confirmation: str) -> dict[str, object]:
        if confirmation != ARM_CONFIRMATION:
            raise ContinuousPaperError(
                "The exact one-entry Paper arm confirmation was not provided."
            )
        self._assert_trade_plan_producer_available()
        audit = self.preflight_environment()
        state = load_state(self.config)
        if state.entry_budget_consumed or state.mode in {
            LOCKED_AFTER_CANARY_ENTRY,
            PAUSED_AFTER_CANARY,
        }:
            raise ContinuousPaperError("The one-entry Paper budget is already closed.")
        state.mode = CANARY_ARMED_ONE_ENTRY
        state.pipeline_state = "ARMED_WAITING_FOR_ELIGIBLE_PLAN"
        state.broker_state = "PAPER_CONNECTED"
        state.last_paper_forward_progress_at = self.clock().isoformat()
        self._write_event("CONTINUOUS_PAPER_ACTIVATION_START", state, audit)
        save_state(self.config, state)
        return {**audit, **state.to_dict()}

    def tick(self) -> ContinuousPaperState:
        state = load_state(self.config)
        state.last_paper_forward_progress_at = self.clock().isoformat()
        if state.mode == ENTRY_AUTHORITY_DISABLED:
            state.pipeline_state = "IDLE_ENTRY_AUTHORITY_DISABLED"
            save_state(self.config, state)
            return state
        if state.broker_state == "PAPER_ENVIRONMENT_CONTAMINATED":
            state.pipeline_state = "DEGRADED"
            save_state(self.config, state)
            return state

        outcomes = self.engine.reconcile_active()
        if outcomes:
            latest = outcomes[-1]
            self._update_lifecycle_health(state, latest)
            state.last_classification = str(latest.get("classification", ""))
            state.pipeline_state = (
                "TERMINAL"
                if latest.get("classification") == "POSITION_CLOSED"
                else (
                    "PROTECTED"
                    if latest.get("positionProtected") is True
                    else "POSITION_ACTIVE"
                )
            )
            self._write_event("PAPER_RECONCILIATION", state, _compact_result(latest))
            if latest.get("classification") == "POSITION_CLOSED":
                state.mode = PAUSED_AFTER_CANARY
                state.pipeline_state = "TERMINAL"

        if state.mode != CANARY_ARMED_ONE_ENTRY:
            save_state(self.config, state)
            return state

        for source_path, admission in self._admissions():
            if (
                admission.fingerprint in state.processed_admission_fingerprints
                or admission.trade_plan_id in state.processed_trade_plan_ids
            ):
                continue
            state.current_admission_id = admission.admission_id
            state.current_trade_plan_id = admission.trade_plan_id
            state.current_symbol = admission.symbol
            state.pipeline_state = "PLAN_ADMITTED"
            save_state(self.config, state)
            try:
                self.preflight_environment()
            except ContinuousPaperEnvironmentAnomaly:
                state.pipeline_state = "DEGRADED"
                state.broker_state = "PAPER_ENVIRONMENT_CONTAMINATED"
                state.last_failure = "PAPER_ENVIRONMENT_NOT_CLEAN"
                save_state(self.config, state)
                return state
            state.pipeline_state = "SUBMITTING"
            state.broker_state = "PAPER_CONNECTED"
            save_state(self.config, state)
            result = self.engine.run_continuous_admission(
                admission.to_dict(),
                source_path=source_path,
                confirmation=CONTINUOUS_PAPER_DECISION_CONFIRMATION,
            )
            self._update_lifecycle_health(state, result)
            state.processed_admission_fingerprints.append(admission.fingerprint)
            state.processed_admission_fingerprints = (
                state.processed_admission_fingerprints[-2048:]
            )
            state.processed_trade_plan_ids.append(admission.trade_plan_id)
            state.processed_trade_plan_ids = state.processed_trade_plan_ids[-2048:]
            state.last_classification = str(result.get("classification", ""))
            if result.get("paperOrderCreated") is True or state.last_classification == PAPER_TRADE_CREATED:
                state.entry_budget_consumed = True
                if (
                    result.get("terminal") is True
                    and result.get("positionFlat") is not False
                ):
                    state.mode = PAUSED_AFTER_CANARY
                    state.pipeline_state = "TERMINAL"
                else:
                    state.mode = LOCKED_AFTER_CANARY_ENTRY
                    state.pipeline_state = (
                        "PROTECTED"
                        if result.get("positionProtected") is True
                        else "POSITION_ACTIVE"
                    )
            else:
                state.pipeline_state = "ARMED_WAITING_FOR_ELIGIBLE_PLAN"
            self._write_event("PAPER_ADMISSION_RESULT", state, _compact_result(result))
            save_state(self.config, state)
            break
        else:
            state.pipeline_state = "ARMED_WAITING_FOR_ELIGIBLE_PLAN"
            save_state(self.config, state)
        return state

    @staticmethod
    def _update_lifecycle_health(
        state: ContinuousPaperState,
        result: Mapping[str, object],
    ) -> None:
        entry = result.get("entryOrder")
        if isinstance(entry, Mapping):
            order_id = str(entry.get("orderId") or "")
            if order_id:
                state.current_broker_order_id = order_id
            filled_quantity = str(entry.get("filledQuantity") or "")
            if filled_quantity:
                state.current_position_quantity = filled_quantity
        current_quantity = str(result.get("currentPositionQuantity") or "")
        if current_quantity:
            state.current_position_quantity = current_quantity
        protective = result.get("protectiveStopOrder")
        if isinstance(protective, Mapping):
            state.protective_order_state = ":".join(
                item
                for item in (
                    str(protective.get("status") or ""),
                    str(protective.get("orderId") or ""),
                )
                if item
            )
        elif result.get("positionProtected") is False:
            state.protective_order_state = "NOT_CONFIRMED"
        if result.get("positionFlat") is True:
            state.current_position_quantity = "0"

    def _admissions(self) -> list[tuple[Path, ContinuousPaperAdmissionIntent]]:
        topology = _research_topology(self.research_config)
        activation = _aware(self.config.activation_timestamp)
        if activation is None:
            raise ContinuousPaperError(
                "Continuous Paper activation timestamp is invalid."
            )
        runtime_configuration_fingerprint = str(
            self.research_config.get("configurationFingerprint", "")
        )
        record_root = (
            Path(str(self.research_config["evidenceRoot"]))
            / topology.namespace
            / "records"
            / "continuous-plan-ledger"
        )
        found: list[tuple[Path, ContinuousPaperAdmissionIntent]] = []
        for path in sorted(record_root.glob("*/*.json")):
            record = _read_json(path, "Continuous admission writer record")
            record_fingerprint = record.pop("recordFingerprint", None)
            if record_fingerprint != _fingerprint(
                "production-continuous-record-v1", record
            ):
                raise ContinuousPaperError("Continuous admission record is tampered.")
            intent = record.get("intent")
            payload = record.get("payload")
            if not isinstance(intent, Mapping) or not isinstance(payload, Mapping):
                raise ContinuousPaperError("Continuous admission record shape is invalid.")
            if intent.get("evidence_type") != "PAPER_ADMISSION_INTENT":
                continue
            admission = parse_continuous_paper_admission_intent(payload)
            if (
                intent.get("record_identity") != admission.admission_id
                or intent.get("record_fingerprint") != admission.fingerprint
                or admission.product_sha != self.config.installed_product_sha
                or admission.runtime_configuration_fingerprint
                != runtime_configuration_fingerprint
            ):
                raise ContinuousPaperError("Continuous admission lineage is invalid.")
            known_at = _aware(admission.known_at)
            if known_at is None:
                raise ContinuousPaperError(
                    "Continuous admission timestamp is invalid."
                )
            if known_at < activation:
                continue
            found.append((path, admission))
        return sorted(found, key=lambda item: (item[1].known_at, item[1].admission_id))

    def _write_event(
        self,
        event_type: str,
        state: ContinuousPaperState,
        detail: Mapping[str, object],
    ) -> None:
        known_at = str(
            detail.get("decisionAt")
            or detail.get("recordedAt")
            or (
                self.config.activation_timestamp
                if event_type == "CONTINUOUS_PAPER_ACTIVATION_START"
                else self.clock().isoformat()
            )
        )
        if _aware(known_at) is None:
            raise ContinuousPaperError("Paper evidence timestamp is invalid.")
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "profile": PROFILE,
            "payloadType": PAPER_EXECUTION_EVENT,
            "eventType": event_type,
            "sampleId": self.config.sample_id,
            "productSha": self.config.installed_product_sha,
            "policyFingerprint": self.config.policy_fingerprint,
            "knownAt": known_at,
            "mode": state.mode,
            "pipelineState": state.pipeline_state,
            "entryBudgetConsumed": state.entry_budget_consumed,
            "admissionId": state.current_admission_id,
            "tradePlanId": state.current_trade_plan_id,
            "symbol": state.current_symbol,
            "detail": dict(detail),
            "environment": "ALPACA_PAPER",
            "brokerHost": ALPACA_PAPER_BASE_URL,
            "alpacaLive": "UNAVAILABLE",
            "schwabOrders": "UNAVAILABLE",
            "liveExecution": "UNAVAILABLE",
        }
        payload_fingerprint = _fingerprint(
            "continuous-evidence-payload-v1", payload
        )
        record_fingerprint = _fingerprint(
            "continuous-paper-execution-event-v1", payload
        )
        sequence = state.last_evidence_sequence + 1
        intent = build_evidence_write_intent(
            runtime_instance_id=(
                "production-continuous-paper-"
                + hashlib.sha256(self.config.sample_id.encode("ascii")).hexdigest()[:24]
            ),
            sequence=sequence,
            evidence_type=PAPER_EXECUTION_EVENT,
            record_identity=f"paper-event-{record_fingerprint[:24]}",
            record_fingerprint=record_fingerprint,
            predecessor_identity=None,
            requested_at=str(payload["knownAt"]),
            payload_fingerprint=payload_fingerprint,
            payload=payload,
        )
        result = self.writer.write_intent(intent)
        if result.status not in {WRITER_ACCEPTED, WRITER_DUPLICATE}:
            raise ContinuousPaperError(
                f"Paper evidence writer rejected event: {result.status}"
            )
        state.last_evidence_sequence = sequence


def run_supervisor(config_path: Path) -> int:
    config = load_config(config_path)
    supervisor = ContinuousPaperSupervisor(config=config)
    while True:
        try:
            supervisor.tick()
        except (ContinuousPaperError, PaperEngineeringError, AlpacaPaperBrokerError) as exc:
            state = load_state(config)
            state.pipeline_state = "FAILED"
            state.last_failure = type(exc).__name__
            if isinstance(exc, AlpacaPaperBrokerError):
                state.broker_state = (
                    "PAPER_AUTH_FAILED"
                    if getattr(exc, "http_status", None) in {401, 403}
                    else "PAPER_UNAVAILABLE"
                )
            state.last_paper_forward_progress_at = now_central().isoformat()
            save_state(config, state)
        time.sleep(5)


def _compact_result(result: Mapping[str, object]) -> dict[str, object]:
    def order_summary(value: object) -> object:
        if not isinstance(value, Mapping):
            return None
        return {
            "orderId": value.get("orderId"),
            "clientOrderId": value.get("clientOrderId"),
            "status": value.get("status"),
            "filledQuantity": value.get("filledQuantity"),
            "filledAveragePrice": value.get("filledAveragePrice"),
            "quantity": value.get("quantity"),
            "notional": value.get("notional"),
            "stopPrice": value.get("stopPrice"),
        }

    selected = result.get("candidateEvaluations")
    selected = selected[0] if isinstance(selected, list) and selected else None
    return {
        "classification": result.get("classification"),
        "terminal": result.get("terminal"),
        "decisionAt": result.get("decisionAt"),
        "recordedAt": result.get("recordedAt"),
        "reasons": list(result.get("reasons", [])),
        "decisionCycleId": result.get("decisionCycleId"),
        "continuousAdmissionId": result.get("continuousAdmissionId"),
        "selectedSymbol": result.get("selectedSymbol"),
        "paperOrderCreated": result.get("paperOrderCreated"),
        "positionProtected": result.get("positionProtected"),
        "positionFlat": result.get("positionFlat"),
        "candidateEvaluation": selected,
        "entryOrder": order_summary(result.get("entryOrder")),
        "protectiveStopOrder": order_summary(result.get("protectiveStopOrder")),
        "emergencyExitOrder": order_summary(result.get("emergencyExitOrder")),
        "postFillRisk": result.get("postFillRisk"),
        "providerCalls": [
            {"method": item.get("method"), "path": item.get("path"), "httpStatus": item.get("httpStatus")}
            for item in result.get("providerCalls", [])
            if isinstance(item, Mapping)
        ],
    }


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ContinuousPaperError(f"{label} is unreadable.") from None
    if not isinstance(value, dict):
        raise ContinuousPaperError(f"{label} has invalid shape.")
    return value


def _aware(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-entry continuous Alpaca Paper supervisor")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "command",
        choices=("create-config", "run", "status", "preflight", "arm", "tick"),
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--research-config", type=Path)
    parser.add_argument("--paper-state-root", type=Path)
    parser.add_argument("--paper-engineering-root", type=Path)
    parser.add_argument("--installed-product-sha", default="")
    parser.add_argument("--sample-id", default="")
    parser.add_argument("--policy-fingerprint", default="")
    parser.add_argument("--activation-timestamp", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "create-config":
            if not all(
                (
                    args.research_config,
                    args.paper_state_root,
                    args.paper_engineering_root,
                    args.installed_product_sha,
                    args.sample_id,
                    args.policy_fingerprint,
                    args.activation_timestamp,
                )
            ):
                raise ContinuousPaperError(
                    "Continuous Paper configuration arguments are incomplete."
                )
            config = write_disabled_config(
                path=args.config,
                research_deployment_config_path=args.research_config,
                paper_state_root=args.paper_state_root,
                paper_engineering_root=args.paper_engineering_root,
                installed_product_sha=args.installed_product_sha,
                sample_id=args.sample_id,
                policy_fingerprint=args.policy_fingerprint,
                activation_timestamp=args.activation_timestamp,
            )
            result: object = {
                "classification": "CONTINUOUS_PAPER_CONFIGURED_DISABLED",
                "configPath": str(args.config),
                "sampleId": config.sample_id,
                "policyFingerprint": config.policy_fingerprint,
                "entryAuthority": ENTRY_AUTHORITY_DISABLED,
                "brokerHost": ALPACA_PAPER_BASE_URL,
                "alpacaLive": "UNAVAILABLE",
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        config = load_config(args.config)
        if args.command == "run":
            return run_supervisor(args.config)
        if args.command == "status":
            result: object = load_state(config).to_dict()
        else:
            supervisor = ContinuousPaperSupervisor(config=config)
            if args.command == "preflight":
                result = supervisor.preflight_environment()
            elif args.command == "arm":
                result = supervisor.arm(confirmation=args.confirmation)
            else:
                result = supervisor.tick().to_dict()
    except (
        ContinuousPaperError,
        ContinuousPaperContractError,
        PaperEngineeringError,
        PaperEngineeringAnomaly,
        AlpacaPaperBrokerError,
    ) as exc:
        print(f"Continuous Paper stopped safely: {type(exc).__name__}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
