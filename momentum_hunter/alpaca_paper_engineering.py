from __future__ import annotations

"""Prospective Momentum Hunter decisions for the Canary Alpaca Paper lane."""

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from momentum_hunter.alpaca_paper_broker import (
    PAPER_ENGINEERING_CONFIRMATION,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperBrokerError,
    AlpacaPaperOrder,
    AlpacaPaperOrderRequest,
    AlpacaPaperPosition,
    AlpacaPaperProviderReceipt,
    PaperOrderResolution,
    authorize_paper_engineering_order,
)
from momentum_hunter.alpaca_paper_lifecycle import (
    AlpacaPaperLifecycleError,
    adjudicate_lifecycle_capabilities,
)
from momentum_hunter.alpaca_paper_onboarding import (
    ALPACA_PAPER_BASE_URL,
    AlpacaPaperLane,
)
from momentum_hunter.broker_capabilities import BrokerCapabilityRegistry
from momentum_hunter.paper_risk_governor import (
    PaperRiskDecision,
    PaperRiskPolicy,
    evaluate_paper_candidate,
)
from momentum_hunter.provider_neutral_allocation import (
    AccountSnapshot,
    AllocationRequest,
    ProviderNeutralAllocationDecision,
    ProviderNeutralAllocationPolicy,
    QuantityPolicy,
    allocate_provider_neutral_position,
    evidence_fingerprint,
)
from momentum_hunter.schwab_market_data import (
    SchwabMarketDataQuoteSource,
    build_regular_market_quote_proof,
)
from momentum_hunter.shadow_market_validity import (
    ShadowMarketValidityPolicy,
    canonical_candidate_rows,
    forced_exit_deadline,
    validate_report_clocks,
)
from momentum_hunter.shadow_selection import (
    load_report_object,
    report_evidence_authority_findings,
)
from momentum_hunter.time_utils import now_central


PAPER_ENGINEERING_SCHEMA_VERSION = 1
PAPER_ENGINEERING_PROFILE = "alpaca-paper-engineering-v1"
PAPER_ENGINEERING_SAMPLE_CONFIRMATION = "FREEZE ALPACA PAPER ENGINEERING SAMPLE"
PAPER_ENGINEERING_ROLLOVER_CONFIRMATION = (
    "CLOSE INVALIDATED PAPER SAMPLE AND START VERSION 2"
)
PAPER_ENGINEERING_DECISION_CONFIRMATION = "RUN PROSPECTIVE ALPACA PAPER DECISION"
PAPER_TRADE_CREATED = "PAPER_TRADE_CREATED"
NO_TRADE = "NO_TRADE"
DEFAULT_PAPER_ENGINEERING_DIRECTORY = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "MomentumHunter"
    / "Alpaca"
    / "paper-engineering"
)
_SHA256_PATTERN = re.compile(r"^[0-9A-Fa-f]{64}$")
_SECRET_PATTERNS = (
    re.compile(r"\b(?:PK|AK)[A-Z0-9]{16,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)
_PAPER_SESSION_MUTEX_NAME = "Global\\MomentumHunterAlpacaPaperEngineering"


class PaperEngineeringError(RuntimeError):
    pass


class PaperEngineeringAnomaly(PaperEngineeringError):
    pass


class PaperAdapter(Protocol):
    evidence_sink: Callable[[AlpacaPaperProviderReceipt], None] | None
    credentials: object

    def get_account(self): ...
    def get_asset(self, symbol: str): ...
    def list_positions(self) -> list[AlpacaPaperPosition]: ...
    def list_orders(
        self,
        *,
        status: str = "open",
        symbols: tuple[str, ...] = (),
    ) -> list[AlpacaPaperOrder]: ...
    def get_order(self, order_id: str) -> AlpacaPaperOrder: ...
    def try_get_order_by_client_id(self, client_order_id: str) -> AlpacaPaperOrder | None: ...
    def submit_order_idempotently(
        self,
        request: AlpacaPaperOrderRequest,
        *,
        authorization,
    ) -> PaperOrderResolution: ...
    def cancel_order(self, order_id: str, *, authorization) -> AlpacaPaperOrder: ...


@dataclass(frozen=True)
class PaperEngineeringPolicy:
    policy_id: str
    sample_id: str
    allocation: ProviderNeutralAllocationPolicy
    risk: PaperRiskPolicy
    entry_notional_buffer_percent: Decimal
    minimum_entry_notional_dollars: Decimal
    order_poll_attempts: int
    order_poll_interval_seconds: float
    schema_version: int = PAPER_ENGINEERING_SCHEMA_VERSION
    profile: str = PAPER_ENGINEERING_PROFILE

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(_policy_dict(self))


@dataclass(frozen=True)
class PaperEngineeringArm:
    sample_id: str
    activated_at: str
    policy_fingerprint: str
    capability_proof_fingerprint: str
    capability_registry_fingerprint: str
    lane: str
    endpoint: str
    environment: str
    order_transmission: str
    schema_version: int = PAPER_ENGINEERING_SCHEMA_VERSION
    profile: str = PAPER_ENGINEERING_PROFILE

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    symbol: str
    canonical_rank: int
    composite_score: Decimal | None
    setup_family: str
    risk: PaperRiskDecision
    allocation: ProviderNeutralAllocationDecision | None
    blockers: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return (
            not self.blockers
            and self.risk.authorized
            and self.allocation is not None
            and self.allocation.authorized
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidateId": self.candidate_id,
            "symbol": self.symbol,
            "canonicalRank": self.canonical_rank,
            "compositeScore": _decimal_text(self.composite_score),
            "setupFamily": self.setup_family,
            "eligible": self.eligible,
            "blockers": list(self.blockers),
            "risk": self.risk.to_dict(),
            "allocation": (
                self.allocation.to_dict()
                if self.allocation is not None
                else None
            ),
        }


def freeze_paper_engineering_sample(
    *,
    policy: PaperEngineeringPolicy,
    lifecycle_proof_path: Path,
    output_directory: Path = DEFAULT_PAPER_ENGINEERING_DIRECTORY,
    confirmation: str,
    activated_at: datetime | None = None,
) -> PaperEngineeringArm:
    if confirmation != PAPER_ENGINEERING_SAMPLE_CONFIRMATION:
        raise PaperEngineeringError(
            "The exact Paper engineering sample confirmation was not provided."
        )
    _validate_policy(policy)
    proof = _load_json_object(lifecycle_proof_path, "Paper lifecycle proof")
    registry = adjudicate_lifecycle_capabilities(proof)
    proof_fingerprint = str(proof.get("fingerprint", ""))
    if not _SHA256_PATTERN.fullmatch(proof_fingerprint):
        raise PaperEngineeringError("Paper lifecycle proof fingerprint is invalid.")
    activated = activated_at or now_central()
    _require_aware(activated, "Paper sample activation")
    arm = PaperEngineeringArm(
        sample_id=policy.sample_id,
        activated_at=activated.isoformat(),
        policy_fingerprint=policy.fingerprint,
        capability_proof_fingerprint=proof_fingerprint,
        capability_registry_fingerprint=registry.fingerprint,
        lane=AlpacaPaperLane.CANARY_REALISTIC.value,
        endpoint=ALPACA_PAPER_BASE_URL,
        environment="PAPER_ONLY",
        order_transmission="ALPACA_PAPER_ONLY",
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_same_or_fail(
        output_directory / "policy.json",
        {**_policy_dict(policy), "fingerprint": policy.fingerprint},
    )
    _write_same_or_fail(
        output_directory / "arm.json",
        {**asdict(arm), "fingerprint": arm.fingerprint},
    )
    proof_binding = {
        "schemaVersion": PAPER_ENGINEERING_SCHEMA_VERSION,
        "proofPath": str(lifecycle_proof_path.resolve()),
        "proofFileSha256": _file_sha256(lifecycle_proof_path),
        "proofFingerprint": proof_fingerprint,
        "capabilityRegistry": registry.to_dict(),
    }
    _write_same_or_fail(output_directory / "capability-proof.json", proof_binding)
    return arm


def load_paper_engineering_policy(
    output_directory: Path = DEFAULT_PAPER_ENGINEERING_DIRECTORY,
) -> PaperEngineeringPolicy:
    if (output_directory / "sample-closure.json").exists():
        raise PaperEngineeringError("The Paper engineering sample is closed.")
    payload = _load_json_object(output_directory / "policy.json", "Paper policy")
    allocation = payload.get("allocation")
    risk = payload.get("risk")
    if not isinstance(allocation, Mapping) or not isinstance(risk, Mapping):
        raise PaperEngineeringError("Paper policy has invalid nested contracts.")
    try:
        policy = PaperEngineeringPolicy(
            policy_id=str(payload["policyId"]),
            sample_id=str(payload["sampleId"]),
            allocation=ProviderNeutralAllocationPolicy(
                policy_id=str(allocation["policyId"]),
                fixed_unit_risk_dollars=Decimal(str(allocation["fixedUnitRiskDollars"])),
                max_position_notional_dollars=Decimal(str(allocation["maxPositionNotionalDollars"])),
                minimum_cash_reserve_dollars=Decimal(str(allocation["minimumCashReserveDollars"])),
                max_total_open_risk_dollars=Decimal(str(allocation["maxTotalOpenRiskDollars"])),
                daily_loss_limit_dollars=Decimal(str(allocation["dailyLossLimitDollars"])),
                max_open_positions=int(allocation["maxOpenPositions"]),
                max_snapshot_age_seconds=int(allocation["maxSnapshotAgeSeconds"]),
                quantity_policy=QuantityPolicy(str(allocation["quantityPolicy"])),
            ),
            risk=PaperRiskPolicy(
                policy_id=str(risk["policyId"]),
                maximum_spread_percent=Decimal(str(risk["maximumSpreadPercent"])),
                maximum_entry_extension_percent=Decimal(str(risk["maximumEntryExtensionPercent"])),
                minimum_reward_risk=Decimal(str(risk["minimumRewardRisk"])),
            ),
            entry_notional_buffer_percent=Decimal(str(payload["entryNotionalBufferPercent"])),
            minimum_entry_notional_dollars=Decimal(str(payload["minimumEntryNotionalDollars"])),
            order_poll_attempts=int(payload["orderPollAttempts"]),
            order_poll_interval_seconds=float(payload["orderPollIntervalSeconds"]),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise PaperEngineeringError("Paper policy contains invalid fields.") from None
    _validate_policy(policy)
    if payload.get("fingerprint") != policy.fingerprint:
        raise PaperEngineeringError("Paper policy fingerprint is invalid.")
    return policy


def rollover_invalidated_paper_engineering_sample(
    *,
    expected_sample_id: str,
    new_sample_id: str,
    new_identity_date: str,
    adjudication_path: Path,
    confirmation: str,
    output_directory: Path = DEFAULT_PAPER_ENGINEERING_DIRECTORY,
    archive_root: Path | None = None,
    closed_at: datetime | None = None,
) -> dict[str, object]:
    if confirmation != PAPER_ENGINEERING_ROLLOVER_CONFIRMATION:
        raise PaperEngineeringError(
            "The exact Paper engineering rollover confirmation was not provided."
        )
    if not re.fullmatch(r"\d{8}", new_identity_date):
        raise PaperEngineeringError("The new Paper identity date is invalid.")
    if not new_sample_id.endswith("-v2"):
        raise PaperEngineeringError("The replacement Paper sample must be version 2.")
    if new_sample_id == expected_sample_id:
        raise PaperEngineeringError("The replacement Paper sample identity must be new.")
    policy = load_paper_engineering_policy(output_directory)
    arm, _ = load_paper_engineering_arm(
        policy=policy,
        output_directory=output_directory,
    )
    if policy.sample_id != expected_sample_id or arm.sample_id != expected_sample_id:
        raise PaperEngineeringError("The active Paper sample identity is unexpected.")
    if any((output_directory / "active").glob("*.json")):
        raise PaperEngineeringAnomaly("The Paper sample has an active lifecycle.")
    if any((output_directory / "intents").glob("*.json")):
        raise PaperEngineeringAnomaly(
            "The Paper sample contains an entry intent and requires provider adjudication."
        )

    decisions = []
    for path in sorted((output_directory / "decisions").glob("*.json")):
        decision = _load_verified_record(path, "Paper decision")
        if (
            decision.get("sampleId") != expected_sample_id
            or decision.get("classification") != NO_TRADE
            or decision.get("paperOrderCreated") is not False
            or decision.get("providerCalls") != []
        ):
            raise PaperEngineeringAnomaly(
                "The invalidated sample is not a no-order, no-provider-call sample."
            )
        decisions.append(
            {
                "decisionCycleId": decision.get("decisionCycleId"),
                "fileSha256": _file_sha256(path),
                "fingerprint": decision.get("fingerprint"),
            }
        )
    if not decisions:
        raise PaperEngineeringError("The invalidated Paper sample has no decisions.")

    adjudication = _load_json_object(adjudication_path, "opening adjudication")
    adjudication_fingerprint = str(adjudication.get("fingerprint", ""))
    candidate = {
        key: value for key, value in adjudication.items() if key != "fingerprint"
    }
    if (
        adjudication.get("classification") != "SYSTEM_DATA_CONTRACT_FAILURE"
        or adjudication.get("decisionState") != "DECISION_NOT_REACHED"
        or adjudication_fingerprint != evidence_fingerprint(candidate)
    ):
        raise PaperEngineeringError("The opening adjudication is invalid.")
    adjudicated_decisions = {
        (
            str(paper.get("decisionCycleId", "")),
            str(paper.get("originalFingerprint", "")),
            str(paper.get("sampleId", "")),
        )
        for case in adjudication.get("cases", [])
        if isinstance(case, dict)
        for paper in case.get("paperDecisions", [])
        if isinstance(paper, dict)
    }
    sample_decisions = {
        (
            str(decision["decisionCycleId"]),
            str(decision["fingerprint"]),
            expected_sample_id,
        )
        for decision in decisions
    }
    if adjudicated_decisions != sample_decisions:
        raise PaperEngineeringError(
            "The opening adjudication does not bind the exact active Paper decisions."
        )

    closure_time = closed_at or now_central()
    _require_aware(closure_time, "Paper sample closure")
    source_files = [
        {
            "path": str(path.relative_to(output_directory)).replace("\\", "/"),
            "sha256": _file_sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(item for item in output_directory.rglob("*") if item.is_file())
    ]
    closure = {
        "schemaVersion": PAPER_ENGINEERING_SCHEMA_VERSION,
        "classification": "CLOSED_INVALIDATED_SYSTEM_DATA_CONTRACT_FAILURE",
        "sampleId": expected_sample_id,
        "closedAt": closure_time.isoformat(),
        "decisionState": "DECISION_NOT_REACHED",
        "countsTowardAnySample": False,
        "paperOrdersCreated": 0,
        "providerCalls": 0,
        "adjudicationPath": str(adjudication_path.resolve()),
        "adjudicationFileSha256": _file_sha256(adjudication_path),
        "adjudicationFingerprint": adjudication_fingerprint,
        "decisions": decisions,
        "sourceFiles": source_files,
        "successorSampleId": new_sample_id,
    }
    closure["fingerprint"] = evidence_fingerprint(closure)
    _assert_sanitized(closure)
    archive = (archive_root or output_directory.parent / "paper-engineering-archive") / expected_sample_id
    if archive.exists():
        raise PaperEngineeringAnomaly("The write-once Paper sample archive already exists.")
    proof_binding = _load_json_object(
        output_directory / "capability-proof.json",
        "Paper capability binding",
    )
    lifecycle_proof_path = Path(str(proof_binding.get("proofPath", "")))
    new_policy = replace(
        policy,
        policy_id=f"alpaca-paper-canary-engineering-policy-{new_identity_date}-v2",
        sample_id=new_sample_id,
        allocation=replace(
            policy.allocation,
            policy_id=f"alpaca-paper-canary-allocation-{new_identity_date}-v2",
        ),
        risk=replace(
            policy.risk,
            policy_id=f"alpaca-paper-canary-risk-{new_identity_date}-v2",
        ),
    )
    _validate_policy(new_policy)
    staging = output_directory.with_name(
        f"{output_directory.name}-{new_sample_id}-staging"
    )
    if staging.exists():
        raise PaperEngineeringAnomaly("The Paper replacement staging path already exists.")
    new_arm = freeze_paper_engineering_sample(
        policy=new_policy,
        lifecycle_proof_path=lifecycle_proof_path,
        output_directory=staging,
        confirmation=PAPER_ENGINEERING_SAMPLE_CONFIRMATION,
        activated_at=closure_time,
    )
    lineage = {
        "schemaVersion": PAPER_ENGINEERING_SCHEMA_VERSION,
        "recordType": "PAPER_ENGINEERING_SAMPLE_LINEAGE",
        "sampleId": new_sample_id,
        "predecessorSampleId": expected_sample_id,
        "predecessorClosureFingerprint": closure["fingerprint"],
        "policyValuesChanged": False,
        "archivePath": str(archive.resolve()),
        "activatedAt": new_arm.activated_at,
    }
    lineage["fingerprint"] = evidence_fingerprint(lineage)
    _write_same_or_fail(staging / "lineage.json", lineage)

    archive.parent.mkdir(parents=True, exist_ok=True)
    os.replace(output_directory, archive)
    try:
        _write_same_or_fail(archive / "sample-closure.json", closure)
        os.replace(staging, output_directory)
    except Exception as exc:
        closure_path = archive / "sample-closure.json"
        if closure_path.exists():
            closure_path.unlink()
        try:
            os.replace(archive, output_directory)
        except OSError as rollback_exc:
            raise PaperEngineeringAnomaly(
                "The Paper sample rollover failed and automatic rollback was unsuccessful."
            ) from rollback_exc
        if staging.exists():
            shutil.rmtree(staging)
        raise PaperEngineeringError(
            "The Paper sample rollover failed; the original sample was restored."
        ) from exc
    return {
        "classification": "PAPER_ENGINEERING_SAMPLE_ROLLED_OVER",
        "closedSampleId": expected_sample_id,
        "closedSampleClassification": closure["classification"],
        "newSampleId": new_sample_id,
        "newArmFingerprint": new_arm.fingerprint,
        "policyValuesChanged": False,
        "archivePath": str(archive.resolve()),
        "activeDirectory": str(output_directory.resolve()),
        "paperOrdersCreated": 0,
        "providerCalls": 0,
        "endpoint": ALPACA_PAPER_BASE_URL,
        "liveEndpointReachable": False,
    }


def load_paper_engineering_arm(
    *,
    policy: PaperEngineeringPolicy,
    output_directory: Path = DEFAULT_PAPER_ENGINEERING_DIRECTORY,
) -> tuple[PaperEngineeringArm, BrokerCapabilityRegistry]:
    payload = _load_json_object(output_directory / "arm.json", "Paper arm")
    try:
        arm = PaperEngineeringArm(
            sample_id=str(payload["sample_id"]),
            activated_at=str(payload["activated_at"]),
            policy_fingerprint=str(payload["policy_fingerprint"]),
            capability_proof_fingerprint=str(payload["capability_proof_fingerprint"]),
            capability_registry_fingerprint=str(payload["capability_registry_fingerprint"]),
            lane=str(payload["lane"]),
            endpoint=str(payload["endpoint"]),
            environment=str(payload["environment"]),
            order_transmission=str(payload["order_transmission"]),
            schema_version=int(payload["schema_version"]),
            profile=str(payload["profile"]),
        )
    except (KeyError, TypeError, ValueError):
        raise PaperEngineeringError("Paper arm contains invalid fields.") from None
    if payload.get("fingerprint") != arm.fingerprint:
        raise PaperEngineeringError("Paper arm fingerprint is invalid.")
    _validate_arm(arm, policy)
    proof_binding = _load_json_object(
        output_directory / "capability-proof.json",
        "Paper capability binding",
    )
    proof_path = Path(str(proof_binding.get("proofPath", "")))
    if (
        not proof_path.is_file()
        or proof_binding.get("proofFileSha256") != _file_sha256(proof_path)
    ):
        raise PaperEngineeringError("Bound Paper capability proof changed or disappeared.")
    proof = _load_json_object(proof_path, "Paper lifecycle proof")
    registry = adjudicate_lifecycle_capabilities(proof)
    if (
        proof.get("fingerprint") != arm.capability_proof_fingerprint
        or registry.fingerprint != arm.capability_registry_fingerprint
    ):
        raise PaperEngineeringError("Paper arm capability identity is inconsistent.")
    return arm, registry


class AlpacaPaperEngineeringEngine:
    def __init__(
        self,
        *,
        adapter: PaperAdapter,
        quote_source: object,
        output_directory: Path = DEFAULT_PAPER_ENGINEERING_DIRECTORY,
        clock: Callable[[], datetime] = now_central,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adapter = adapter
        self.quote_source = quote_source
        self.output_directory = output_directory
        self.clock = clock
        self.sleep = sleep

    def run_decision(
        self,
        report_path: Path,
        *,
        confirmation: str,
    ) -> dict[str, object]:
        if confirmation != PAPER_ENGINEERING_DECISION_CONFIRMATION:
            raise PaperEngineeringError(
                "The exact prospective Paper decision confirmation was not provided."
            )
        policy = load_paper_engineering_policy(self.output_directory)
        arm, capabilities = load_paper_engineering_arm(
            policy=policy,
            output_directory=self.output_directory,
        )
        decision_started_at = self.clock()
        _require_aware(decision_started_at, "Paper decision start")
        report_bytes = report_path.read_bytes()
        report_sha = hashlib.sha256(report_bytes).hexdigest().upper()
        cycle_id = _stable_id("paper-cycle", arm.fingerprint, report_sha)
        final_path = self._decision_path(cycle_id)
        if final_path.is_file():
            return _load_verified_final(final_path)
        intent_path = self.output_directory / "intents" / f"{cycle_id}.json"
        if intent_path.is_file():
            receipts: list[AlpacaPaperProviderReceipt] = []
            self.adapter.evidence_sink = receipts.append
            return self._recover_intent(
                intent_path=intent_path,
                final_path=final_path,
                cycle_id=cycle_id,
                policy=policy,
                arm=arm,
                report_sha=report_sha,
                receipts=receipts,
            )

        report = load_report_object(report_bytes)
        metadata = report.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        report_blockers = list(report_evidence_authority_findings(metadata))
        opening_readiness = metadata.get("opening_candle_readiness")
        if isinstance(opening_readiness, Mapping):
            readiness_status = str(opening_readiness.get("status", "")).strip()
            if readiness_status != "READY":
                report_blockers.append(
                    readiness_status or "CANONICAL_CANDLE_READINESS_INVALID"
                )
        report_blockers.extend(
            validate_report_clocks(metadata, decision_at=decision_started_at)
        )
        raw_rows = report.get("candidates") or report.get("top_5_for_capital") or []
        if not isinstance(raw_rows, list):
            report_blockers.append("PAPER_REPORT_CANDIDATES_INVALID")
            raw_rows = []
        try:
            ordered = canonical_candidate_rows(raw_rows)
        except ValueError as exc:
            report_blockers.append(f"PAPER_REPORT_ORDER_INVALID:{_sanitize_text(str(exc))}")
            ordered = []

        base = {
            "schemaVersion": PAPER_ENGINEERING_SCHEMA_VERSION,
            "profile": PAPER_ENGINEERING_PROFILE,
            "sampleId": policy.sample_id,
            "sampleArmFingerprint": arm.fingerprint,
            "policyFingerprint": policy.fingerprint,
            "decisionCycleId": cycle_id,
            "decisionStartedAt": decision_started_at.isoformat(),
            "decisionAt": decision_started_at.isoformat(),
            "sourceReportPath": str(report_path.resolve()),
            "sourceReportSha256": report_sha,
            "sourceCapturePath": str(metadata.get("source_capture_path", "")),
            "sourceCaptureTime": str(metadata.get("source_capture_time", "")),
            "mode": "ALPACA PAPER ENGINEERING",
            "lane": AlpacaPaperLane.CANARY_REALISTIC.value,
            "endpoint": ALPACA_PAPER_BASE_URL,
            "liveEndpointReachable": False,
            "countsTowardFinalStrategySample": False,
            "retrospective": False,
        }
        if report_blockers or not ordered:
            reasons = list(dict.fromkeys(report_blockers))
            if not ordered:
                reasons.append("PAPER_NO_CANDIDATES_IN_PROSPECTIVE_REPORT")
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": reasons,
                    "candidatesEvaluated": 0,
                    "candidateEvaluations": [],
                    "providerCalls": [],
                    "paperOrderCreated": False,
                },
            )

        symbols = tuple(str(row.get("symbol", "")).strip().upper() for _, row in ordered)
        try:
            quote_proof = build_regular_market_quote_proof(
                self.quote_source,
                symbols,
                clock=self.clock,
                require_clock_proof=True,
            )
        except Exception as exc:
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": [f"PAPER_SCHWAB_QUOTE_PROOF_UNAVAILABLE:{type(exc).__name__}"],
                    "candidatesEvaluated": 0,
                    "candidateEvaluations": [],
                    "providerCalls": [],
                    "paperOrderCreated": False,
                },
            )
        quote_results = {
            str(item.get("symbol", "")).strip().upper(): dict(item)
            for item in quote_proof.get("quotes", [])
            if isinstance(item, Mapping)
        }
        base["quoteProof"] = quote_proof

        receipts: list[AlpacaPaperProviderReceipt] = []
        self.adapter.evidence_sink = receipts.append
        try:
            account = self._account_snapshot(cycle_id, policy, receipts)
        except (AlpacaPaperBrokerError, PaperEngineeringError) as exc:
            failed_at = self.clock()
            _require_aware(failed_at, "Paper failed decision")
            if failed_at < decision_started_at:
                raise PaperEngineeringError(
                    "Paper failed-decision clock preceded cycle start."
                )
            base["decisionAt"] = failed_at.isoformat()
            base["evidenceAcquiredAt"] = failed_at.isoformat()
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": [f"PAPER_ACCOUNT_PREFLIGHT_FAILED:{type(exc).__name__}"],
                    "candidatesEvaluated": 0,
                    "candidateEvaluations": [],
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": False,
                },
            )

        decision_at = self.clock()
        _require_aware(decision_at, "Paper decision")
        if decision_at < decision_started_at:
            raise PaperEngineeringError("Paper decision clock preceded cycle start.")
        base["decisionAt"] = decision_at.isoformat()
        base["evidenceAcquiredAt"] = decision_at.isoformat()
        final_clock_findings = validate_report_clocks(
            metadata,
            decision_at=decision_at,
        )
        if final_clock_findings:
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": list(final_clock_findings),
                    "candidatesEvaluated": 0,
                    "candidateEvaluations": [],
                    "accountSnapshot": _account_dict(account),
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": False,
                },
            )

        evaluations: list[CandidateEvaluation] = []
        selected: CandidateEvaluation | None = None
        selected_plan = None
        for _persisted_index, row in ordered:
            symbol = str(row.get("symbol", "")).strip().upper()
            risk, plan = evaluate_paper_candidate(
                row,
                quote_result=quote_results.get(symbol),
                decision_at=decision_at,
                policy=policy.risk,
            )
            allocation: ProviderNeutralAllocationDecision | None = None
            blockers = list(risk.blockers)
            if risk.authorized and plan is not None and risk.execution_price is not None:
                request = AllocationRequest(
                    decision_cycle_id=cycle_id,
                    candidate_id=risk.candidate_id,
                    canonical_rank=risk.canonical_rank,
                    symbol=symbol,
                    trade_plan_id=risk.trade_plan_id,
                    risk_decision_id=risk.risk_decision_id,
                    entry_order_type="market",
                    entry_price=risk.execution_price,
                    stop_price=Decimal(str(plan.bullish_stop)),
                    target_price=Decimal(str(plan.bullish_target_1)),
                    decision_at=decision_at.isoformat(),
                )
                allocation = allocate_provider_neutral_position(
                    request=request,
                    policy=policy.allocation,
                    account=account,
                    capabilities=capabilities,
                )
                blockers.extend(allocation.blockers)
            scoring = row.get("scoring")
            scoring = scoring if isinstance(scoring, Mapping) else {}
            intraday = row.get("trade_plan")
            intraday = intraday if isinstance(intraday, Mapping) else {}
            intraday = intraday.get("intraday_evidence")
            intraday = intraday if isinstance(intraday, Mapping) else {}
            evaluation = CandidateEvaluation(
                candidate_id=risk.candidate_id,
                symbol=symbol,
                canonical_rank=risk.canonical_rank,
                composite_score=_decimal(scoring.get("composite_score")),
                setup_family=str(intraday.get("setup_family", "")),
                risk=risk,
                allocation=allocation,
                blockers=tuple(dict.fromkeys(blockers)),
            )
            evaluations.append(evaluation)
            if selected is None and evaluation.eligible:
                selected = evaluation
                selected_plan = plan

        if selected is None or selected.allocation is None or selected_plan is None:
            reasons = [
                reason
                for evaluation in evaluations
                for reason in evaluation.blockers
            ] or ["PAPER_NO_ELIGIBLE_CANDIDATE"]
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": list(dict.fromkeys(reasons)),
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": [item.to_dict() for item in evaluations],
                    "accountSnapshot": _account_dict(account),
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": False,
                },
            )

        return self._execute_selected(
            base=base,
            final_path=final_path,
            cycle_id=cycle_id,
            policy=policy,
            selected=selected,
            plan=selected_plan,
            account=account,
            evaluations=evaluations,
            receipts=receipts,
        )

    def run_session(
        self,
        report_path: Path,
        *,
        confirmation: str,
        reconcile_interval_seconds: float = 5.0,
        maximum_runtime_seconds: int = 25_200,
    ) -> dict[str, object]:
        """Run one prospective decision and supervise any resulting Paper position."""

        with _exclusive_paper_session():
            if not 1 <= maximum_runtime_seconds <= 28_800:
                raise PaperEngineeringError("Paper session runtime limit is invalid.")
            if not 0.1 <= reconcile_interval_seconds <= 60:
                raise PaperEngineeringError("Paper reconciliation interval is invalid.")
            decision = self.run_decision(report_path, confirmation=confirmation)
            if (
                decision.get("classification") != PAPER_TRADE_CREATED
                or decision.get("positionFlat") is True
            ):
                return {
                    "classification": "PAPER_ENGINEERING_SESSION_TERMINAL",
                    "decision": decision,
                    "outcome": None,
                }
            cycle_id = str(decision.get("decisionCycleId", ""))
            deadline = time.monotonic() + maximum_runtime_seconds
            while True:
                outcomes = self.reconcile_active()
                terminal = next(
                    (
                        item
                        for item in outcomes
                        if item.get("decisionCycleId") == cycle_id
                        and item.get("classification") == "POSITION_CLOSED"
                    ),
                    None,
                )
                if terminal is not None:
                    return {
                        "classification": "PAPER_ENGINEERING_SESSION_TERMINAL",
                        "decision": decision,
                        "outcome": terminal,
                    }
                if time.monotonic() >= deadline:
                    raise PaperEngineeringAnomaly(
                        "Paper session monitor reached its finite limit before a terminal outcome."
                    )
                self.sleep(reconcile_interval_seconds)

    def _account_snapshot(
        self,
        cycle_id: str,
        policy: PaperEngineeringPolicy,
        receipts: list[AlpacaPaperProviderReceipt],
    ) -> AccountSnapshot:
        account = self.adapter.get_account()
        account_receipt = _latest_receipt(receipts, "/v2/account")
        positions = self.adapter.list_positions()
        open_orders = self.adapter.list_orders(status="open")
        if open_orders:
            raise PaperEngineeringAnomaly(
                "Canary Paper has an open order outside a recovered decision."
            )
        if not account.usable:
            raise PaperEngineeringAnomaly("Canary Paper account is not usable.")
        if any(item.side != "long" or item.quantity <= 0 for item in positions):
            raise PaperEngineeringAnomaly("Canary Paper contains an unexpected position.")
        portfolio_receipt = receipts[-1] if receipts else account_receipt
        repository = getattr(self.adapter, "credentials", None)
        fingerprint_loader = getattr(repository, "binding_fingerprint", None)
        if not callable(fingerprint_loader):
            raise PaperEngineeringError("Paper credential binding identity is unavailable.")
        binding_fingerprint = str(fingerprint_loader())
        if not _SHA256_PATTERN.fullmatch(binding_fingerprint):
            raise PaperEngineeringError("Paper credential binding identity is invalid.")
        realized = (
            account.equity - account.last_equity
            if account.equity is not None and account.last_equity is not None
            else Decimal("NaN")
        )
        committed_notional = sum(abs(item.market_value) for item in positions)
        committed_risk = (
            policy.allocation.max_total_open_risk_dollars
            if positions
            else Decimal("0")
        )
        return AccountSnapshot(
            snapshot_id=_stable_id("paper-account", cycle_id, binding_fingerprint),
            decision_cycle_id=cycle_id,
            lane=AlpacaPaperLane.CANARY_REALISTIC.value,
            provider="ALPACA_TRADING_API",
            environment="PAPER_ONLY",
            binding_fingerprint=binding_fingerprint,
            authorized_account_count=1,
            status=account.status if account.usable else "BLOCKED",
            cash_available=account.cash,
            buying_power=account.buying_power,
            committed_notional=committed_notional,
            committed_open_risk=committed_risk,
            open_position_count=len(positions),
            realized_pnl_today=realized,
            provider_timestamp=account_receipt.received_at,
            portfolio_timestamp=portfolio_receipt.received_at,
            receipt_timestamp=portfolio_receipt.received_at,
            source_identity="ALPACA_PAPER_ACCOUNT_AND_PORTFOLIO_LOCAL_RECEIPT_V1",
        )

    def _execute_selected(
        self,
        *,
        base: dict[str, object],
        final_path: Path,
        cycle_id: str,
        policy: PaperEngineeringPolicy,
        selected: CandidateEvaluation,
        plan,
        account: AccountSnapshot,
        evaluations: list[CandidateEvaluation],
        receipts: list[AlpacaPaperProviderReceipt],
    ) -> dict[str, object]:
        allocation = selected.allocation
        assert allocation is not None
        raw_notional = allocation.position_notional
        if raw_notional is None:
            raise PaperEngineeringError("Authorized allocation omitted position notional.")
        buffer = Decimal("1") - policy.entry_notional_buffer_percent / Decimal("100")
        submitted_notional = (raw_notional * buffer).quantize(
            Decimal("0.01"),
            rounding=ROUND_FLOOR,
        )
        if submitted_notional < policy.minimum_entry_notional_dollars:
            selected = CandidateEvaluation(
                **{
                    **selected.__dict__,
                    "blockers": (*selected.blockers, "PAPER_ENTRY_NOTIONAL_BELOW_PROVEN_MINIMUM"),
                }
            )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": ["PAPER_ENTRY_NOTIONAL_BELOW_PROVEN_MINIMUM"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": [
                        selected.to_dict() if item.candidate_id == selected.candidate_id else item.to_dict()
                        for item in evaluations
                    ],
                    "accountSnapshot": _account_dict(account),
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": False,
                },
            )
        token = cycle_id.rsplit("-", 1)[-1][:16]
        prefix = f"mh-paper-engineering-{token}-"
        entry_client_id = f"{prefix}entry"
        stop_client_id = f"{prefix}stop"
        exit_client_id = f"{prefix}exit"
        intent = {
            **base,
            "intentType": "ALPACA_PAPER_ENTRY_INTENT",
            "selectedCandidate": selected.to_dict(),
            "candidateEvaluations": [item.to_dict() for item in evaluations],
            "accountSnapshot": _account_dict(account),
            "submittedNotional": _decimal_text(submitted_notional),
            "plannedQuantity": _decimal_text(allocation.final_authorized_quantity),
            "planEntryPrice": _decimal_text(Decimal(str(plan.bullish_entry))),
            "stopPrice": _decimal_text(Decimal(str(plan.bullish_stop))),
            "targetPrice": _decimal_text(Decimal(str(plan.bullish_target_1))),
            "forcedFlatAt": plan.intraday_evidence.forced_flat_at,
            "entryClientOrderId": entry_client_id,
            "stopClientOrderId": stop_client_id,
            "exitClientOrderId": exit_client_id,
            "clientOrderPrefix": prefix,
        }
        intent["fingerprint"] = evidence_fingerprint(intent)
        intent_path = self.output_directory / "intents" / f"{cycle_id}.json"
        _write_same_or_fail(intent_path, intent)

        asset = self.adapter.get_asset(selected.symbol)
        if not (asset.status == "active" and asset.tradable and asset.fractionable):
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": ["PAPER_ASSET_NOT_ACTIVE_TRADABLE_FRACTIONABLE"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": [item.to_dict() for item in evaluations],
                    "accountSnapshot": _account_dict(account),
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": False,
                    "intentFingerprint": intent["fingerprint"],
                },
            )
        if self.adapter.list_positions() or self.adapter.list_orders(status="open"):
            raise PaperEngineeringAnomaly(
                "Canary Paper state changed after allocation and before submission."
            )
        entry_authorization = authorize_paper_engineering_order(
            confirmation=PAPER_ENGINEERING_CONFIRMATION,
            maximum_notional=submitted_notional,
            allowed_sides=("buy",),
            allowed_symbols=(selected.symbol,),
            client_order_prefix=prefix,
        )
        entry_request = AlpacaPaperOrderRequest(
            symbol=selected.symbol,
            side="buy",
            order_type="market",
            time_in_force="day",
            client_order_id=entry_client_id,
            notional=submitted_notional,
        )
        entry_resolution = self.adapter.submit_order_idempotently(
            entry_request,
            authorization=entry_authorization,
        )
        entry = self._poll(entry_resolution.order, policy)
        if not entry.terminal:
            entry = self.adapter.cancel_order(
                entry.order_id,
                authorization=entry_authorization,
            )
            entry = self._poll(entry, policy)
        if entry.filled_quantity <= 0:
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": ["PAPER_ENTRY_UNFILLED"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": [item.to_dict() for item in evaluations],
                    "accountSnapshot": _account_dict(account),
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "intentFingerprint": intent["fingerprint"],
                },
            )
        position = _find_position(self.adapter.list_positions(), selected.symbol)
        if position is None or position.quantity != entry.filled_quantity:
            raise PaperEngineeringAnomaly(
                "Paper entry fill and position identity do not reconcile."
            )
        post_fill_risk = _post_fill_risk_evidence(
            candidate_id=selected.candidate_id,
            symbol=selected.symbol,
            plan_entry_price=Decimal(str(plan.bullish_entry)),
            stop_price=Decimal(str(plan.bullish_stop)),
            target_price=Decimal(str(plan.bullish_target_1)),
            authorized_quantity=allocation.final_authorized_quantity,
            pre_entry_open_risk=account.committed_open_risk,
            entry=entry,
            position=position,
            policy=policy,
        )
        exit_authorization = authorize_paper_engineering_order(
            confirmation=PAPER_ENGINEERING_CONFIRMATION,
            maximum_notional=max(submitted_notional, abs(position.market_value)),
            maximum_quantity=position.quantity,
            allowed_sides=("sell",),
            allowed_symbols=(selected.symbol,),
            client_order_prefix=prefix,
        )
        if post_fill_risk["status"] != "PASS":
            emergency = self._emergency_exit(
                selected.symbol,
                position,
                exit_client_id,
                exit_authorization,
                policy,
            )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": PAPER_TRADE_CREATED,
                    "terminal": True,
                    "reasons": ["PAPER_POST_FILL_RISK_FAILED_EMERGENCY_EXIT"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": [item.to_dict() for item in evaluations],
                    "selectedCandidateId": selected.candidate_id,
                    "selectedSymbol": selected.symbol,
                    "selectedRank": selected.canonical_rank,
                    "accountSnapshot": _account_dict(account),
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "postFillRisk": post_fill_risk,
                    "emergencyExitOrder": _order_dict(emergency),
                    "positionProtected": False,
                    "positionFlat": not self.adapter.list_positions(),
                    "intentFingerprint": intent["fingerprint"],
                },
            )
        stop_request = AlpacaPaperOrderRequest(
            symbol=selected.symbol,
            side="sell",
            order_type="stop",
            time_in_force="day",
            client_order_id=stop_client_id,
            quantity=position.quantity,
            stop_price=Decimal(str(plan.bullish_stop)),
        )
        stop_order: AlpacaPaperOrder | None = None
        try:
            stop_resolution = self.adapter.submit_order_idempotently(
                stop_request,
                authorization=exit_authorization,
            )
            stop_order = stop_resolution.order
            _validate_protective_stop(
                stop_order,
                symbol=selected.symbol,
                client_order_id=stop_client_id,
                expected_quantity=position.quantity,
                expected_stop_price=Decimal(str(plan.bullish_stop)),
            )
            protected_position = _find_position(
                self.adapter.list_positions(),
                selected.symbol,
            )
            if protected_position is None or protected_position.quantity != position.quantity:
                raise PaperEngineeringAnomaly(
                    "Paper position changed while protective stop was being installed."
                )
        except PaperEngineeringAnomaly:
            canceled_stop, emergency, position_flat = self._close_after_protection_anomaly(
                symbol=selected.symbol,
                position=position,
                stop_order=stop_order,
                exit_client_id=exit_client_id,
                client_order_prefix=prefix,
                policy=policy,
            )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": PAPER_TRADE_CREATED,
                    "terminal": True,
                    "reasons": ["PAPER_PROTECTION_MISMATCH_EMERGENCY_EXIT"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": [item.to_dict() for item in evaluations],
                    "accountSnapshot": _account_dict(account),
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "postFillRisk": post_fill_risk,
                    "protectiveStopOrder": (
                        _order_dict(canceled_stop) if canceled_stop is not None else None
                    ),
                    "emergencyExitOrder": (
                        _order_dict(emergency) if emergency is not None else None
                    ),
                    "positionProtected": False,
                    "positionFlat": position_flat,
                    "intentFingerprint": intent["fingerprint"],
                },
            )
        except AlpacaPaperBrokerError:
            emergency = self._emergency_exit(
                selected.symbol,
                position,
                exit_client_id,
                exit_authorization,
                policy,
            )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": PAPER_TRADE_CREATED,
                    "terminal": True,
                    "reasons": ["PAPER_PROTECTION_FAILED_EMERGENCY_EXIT"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": [item.to_dict() for item in evaluations],
                    "accountSnapshot": _account_dict(account),
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "postFillRisk": post_fill_risk,
                    "emergencyExitOrder": _order_dict(emergency),
                    "positionProtected": False,
                    "positionFlat": not self.adapter.list_positions(),
                    "intentFingerprint": intent["fingerprint"],
                },
            )

        active = {
            **base,
            "recordType": "ACTIVE_ALPACA_PAPER_ENGINEERING_POSITION",
            "symbol": selected.symbol,
            "quantity": _decimal_text(position.quantity),
            "entryPrice": _decimal_text(entry.filled_average_price),
            "stopPrice": _decimal_text(Decimal(str(plan.bullish_stop))),
            "targetPrice": _decimal_text(Decimal(str(plan.bullish_target_1))),
            "forcedFlatAt": plan.intraday_evidence.forced_flat_at,
            "entryOrder": _order_dict(entry),
            "postFillRisk": post_fill_risk,
            "protectiveStopOrder": _order_dict(stop_order),
            "exitClientOrderId": exit_client_id,
            "clientOrderPrefix": prefix,
            "intentFingerprint": intent["fingerprint"],
        }
        active["fingerprint"] = evidence_fingerprint(active)
        _write_same_or_fail(
            self.output_directory / "active" / f"{cycle_id}.json",
            active,
        )
        return self._write_final(
            final_path,
            {
                **base,
                "classification": PAPER_TRADE_CREATED,
                "terminal": True,
                "reasons": [],
                "candidatesEvaluated": len(evaluations),
                "candidateEvaluations": [item.to_dict() for item in evaluations],
                "selectedCandidateId": selected.candidate_id,
                "selectedSymbol": selected.symbol,
                "selectedRank": selected.canonical_rank,
                "accountSnapshot": _account_dict(account),
                "providerCalls": [_receipt_dict(item) for item in receipts],
                "paperOrderCreated": True,
                "entryOrder": _order_dict(entry),
                "postFillRisk": post_fill_risk,
                "protectiveStopOrder": _order_dict(stop_order),
                "positionProtected": stop_order.status not in {"canceled", "expired", "rejected"},
                "positionFlat": False,
                "activePositionFingerprint": active["fingerprint"],
                "intentFingerprint": intent["fingerprint"],
            },
        )

    def _recover_intent(
        self,
        *,
        intent_path: Path,
        final_path: Path,
        cycle_id: str,
        policy: PaperEngineeringPolicy,
        arm: PaperEngineeringArm,
        report_sha: str,
        receipts: list[AlpacaPaperProviderReceipt],
    ) -> dict[str, object]:
        """Recover an accepted Paper entry without ever submitting a late new entry."""

        intent = _load_json_object(intent_path, "Paper entry intent")
        fingerprint = intent.get("fingerprint")
        unsigned = {key: value for key, value in intent.items() if key != "fingerprint"}
        if fingerprint != evidence_fingerprint(unsigned):
            raise PaperEngineeringAnomaly("Paper entry intent fingerprint is invalid.")
        if (
            intent.get("schemaVersion") != PAPER_ENGINEERING_SCHEMA_VERSION
            or intent.get("profile") != PAPER_ENGINEERING_PROFILE
            or intent.get("intentType") != "ALPACA_PAPER_ENTRY_INTENT"
            or intent.get("decisionCycleId") != cycle_id
            or intent.get("sourceReportSha256") != report_sha
            or intent.get("sampleId") != policy.sample_id
            or intent.get("sampleArmFingerprint") != arm.fingerprint
            or intent.get("policyFingerprint") != policy.fingerprint
            or intent.get("endpoint") != ALPACA_PAPER_BASE_URL
            or intent.get("liveEndpointReachable") is not False
        ):
            raise PaperEngineeringAnomaly("Paper entry intent identity is invalid.")

        selected = intent.get("selectedCandidate")
        selected = dict(selected) if isinstance(selected, Mapping) else {}
        symbol = str(selected.get("symbol", "")).strip().upper()
        prefix = str(intent.get("clientOrderPrefix", ""))
        entry_client_id = str(intent.get("entryClientOrderId", ""))
        stop_client_id = str(intent.get("stopClientOrderId", ""))
        exit_client_id = str(intent.get("exitClientOrderId", ""))
        submitted_notional = _decimal(intent.get("submittedNotional"))
        stop_price = _decimal(intent.get("stopPrice"))
        target_price = _decimal(intent.get("targetPrice"))
        plan_entry_price = _decimal(intent.get("planEntryPrice"))
        forced_flat_at = _aware_datetime(intent.get("forcedFlatAt"))
        if (
            not symbol
            or not prefix.startswith("mh-paper-engineering-")
            or entry_client_id != f"{prefix}entry"
            or stop_client_id != f"{prefix}stop"
            or exit_client_id != f"{prefix}exit"
            or submitted_notional is None
            or submitted_notional <= 0
            or plan_entry_price is None
            or stop_price is None
            or target_price is None
            or forced_flat_at is None
        ):
            raise PaperEngineeringAnomaly("Paper entry intent execution fields are invalid.")

        base = {
            key: intent[key]
            for key in (
                "schemaVersion",
                "profile",
                "sampleId",
                "sampleArmFingerprint",
                "policyFingerprint",
                "decisionCycleId",
                "decisionAt",
                "sourceReportPath",
                "sourceReportSha256",
                "sourceCapturePath",
                "sourceCaptureTime",
                "mode",
                "lane",
                "endpoint",
                "liveEndpointReachable",
                "countsTowardFinalStrategySample",
                "retrospective",
            )
        }
        evaluations = intent.get("candidateEvaluations")
        evaluations = list(evaluations) if isinstance(evaluations, list) else [selected]
        account_snapshot = intent.get("accountSnapshot")
        account_snapshot = dict(account_snapshot) if isinstance(account_snapshot, Mapping) else {}

        entry = self.adapter.try_get_order_by_client_id(entry_client_id)
        positions = self.adapter.list_positions()
        open_orders = self.adapter.list_orders(status="open")
        owned_ids = {entry_client_id, stop_client_id, exit_client_id}
        if any(item.client_order_id not in owned_ids for item in open_orders):
            raise PaperEngineeringAnomaly("Paper recovery found an unrelated open order.")
        if any(item.symbol != symbol or item.side != "long" for item in positions):
            raise PaperEngineeringAnomaly("Paper recovery found an unrelated position.")

        if entry is None:
            if positions or open_orders:
                raise PaperEngineeringAnomaly(
                    "Paper recovery found provider state without its entry order identity."
                )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": ["PAPER_RECOVERY_UNSUBMITTED_INTENT"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": evaluations,
                    "accountSnapshot": account_snapshot,
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": False,
                    "recoveredAfterInterruption": True,
                    "intentFingerprint": fingerprint,
                },
            )

        _validate_recovered_order(
            entry,
            symbol=symbol,
            side="buy",
            client_order_id=entry_client_id,
        )
        entry_authorization = authorize_paper_engineering_order(
            confirmation=PAPER_ENGINEERING_CONFIRMATION,
            maximum_notional=submitted_notional,
            allowed_sides=("buy",),
            allowed_symbols=(symbol,),
            client_order_prefix=prefix,
        )
        entry = self._poll(entry, policy)
        if not entry.terminal:
            entry = self.adapter.cancel_order(
                entry.order_id,
                authorization=entry_authorization,
            )
            entry = self._poll(entry, policy)
        position = _find_position(self.adapter.list_positions(), symbol)
        if entry.filled_quantity <= 0 and position is None:
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": NO_TRADE,
                    "terminal": True,
                    "reasons": ["PAPER_ENTRY_UNFILLED_AFTER_RECOVERY"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": evaluations,
                    "accountSnapshot": account_snapshot,
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "recoveredAfterInterruption": True,
                    "intentFingerprint": fingerprint,
                },
            )
        if position is None:
            stop = self.adapter.try_get_order_by_client_id(stop_client_id)
            exit_order = self.adapter.try_get_order_by_client_id(exit_client_id)
            if not any(
                order is not None and order.filled_quantity > 0
                for order in (stop, exit_order)
            ):
                raise PaperEngineeringAnomaly(
                    "Paper recovery found a filled entry without a position or owned exit."
                )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": PAPER_TRADE_CREATED,
                    "terminal": True,
                    "reasons": ["PAPER_RECOVERY_POSITION_ALREADY_CLOSED"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": evaluations,
                    "selectedCandidateId": selected.get("candidateId"),
                    "selectedSymbol": symbol,
                    "selectedRank": selected.get("canonicalRank"),
                    "accountSnapshot": account_snapshot,
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "protectiveStopOrder": _order_dict(stop) if stop is not None else None,
                    "exitOrder": _order_dict(exit_order) if exit_order is not None else None,
                    "positionProtected": False,
                    "positionFlat": True,
                    "recoveredAfterInterruption": True,
                    "intentFingerprint": fingerprint,
                },
            )
        if position.quantity > entry.filled_quantity:
            raise PaperEngineeringAnomaly(
                "Paper recovery position exceeds the owned entry fill."
            )

        allocation_payload = selected.get("allocation")
        allocation_payload = (
            dict(allocation_payload) if isinstance(allocation_payload, Mapping) else {}
        )
        authorized_quantity = _decimal(
            allocation_payload.get("finalAuthorizedQuantity")
        )
        pre_entry_open_risk = _decimal(account_snapshot.get("committedOpenRisk"))
        post_fill_risk = _post_fill_risk_evidence(
            candidate_id=str(selected.get("candidateId", "")),
            symbol=symbol,
            plan_entry_price=plan_entry_price,
            stop_price=stop_price,
            target_price=target_price,
            authorized_quantity=authorized_quantity,
            pre_entry_open_risk=pre_entry_open_risk,
            entry=entry,
            position=position,
            policy=policy,
        )

        exit_authorization = authorize_paper_engineering_order(
            confirmation=PAPER_ENGINEERING_CONFIRMATION,
            maximum_notional=max(submitted_notional, abs(position.market_value)),
            maximum_quantity=position.quantity,
            allowed_sides=("sell",),
            allowed_symbols=(symbol,),
            client_order_prefix=prefix,
        )
        if post_fill_risk["status"] != "PASS":
            emergency = self._emergency_exit(
                symbol,
                position,
                exit_client_id,
                exit_authorization,
                policy,
            )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": PAPER_TRADE_CREATED,
                    "terminal": True,
                    "reasons": ["PAPER_RECOVERY_POST_FILL_RISK_FAILED_EMERGENCY_EXIT"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": evaluations,
                    "selectedCandidateId": selected.get("candidateId"),
                    "selectedSymbol": symbol,
                    "selectedRank": selected.get("canonicalRank"),
                    "accountSnapshot": account_snapshot,
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "postFillRisk": post_fill_risk,
                    "emergencyExitOrder": _order_dict(emergency),
                    "positionProtected": False,
                    "positionFlat": not self.adapter.list_positions(),
                    "recoveredAfterInterruption": True,
                    "intentFingerprint": fingerprint,
                },
            )
        stop_order = self.adapter.try_get_order_by_client_id(stop_client_id)
        if stop_order is not None:
            _validate_recovered_order(
                stop_order,
                symbol=symbol,
                side="sell",
                client_order_id=stop_client_id,
                order_type="stop",
            )
            try:
                _validate_protective_stop(
                    stop_order,
                    symbol=symbol,
                    client_order_id=stop_client_id,
                    expected_quantity=position.quantity,
                    expected_stop_price=stop_price,
                )
            except PaperEngineeringAnomaly:
                canceled_stop, emergency, position_flat = (
                    self._close_after_protection_anomaly(
                        symbol=symbol,
                        position=position,
                        stop_order=stop_order,
                        exit_client_id=exit_client_id,
                        client_order_prefix=prefix,
                        policy=policy,
                    )
                )
                return self._write_final(
                    final_path,
                    {
                        **base,
                        "classification": PAPER_TRADE_CREATED,
                        "terminal": True,
                        "reasons": ["PAPER_RECOVERY_PROTECTION_MISMATCH_EMERGENCY_EXIT"],
                        "candidatesEvaluated": len(evaluations),
                        "candidateEvaluations": evaluations,
                        "selectedCandidateId": selected.get("candidateId"),
                        "selectedSymbol": symbol,
                        "selectedRank": selected.get("canonicalRank"),
                        "accountSnapshot": account_snapshot,
                        "providerCalls": [_receipt_dict(item) for item in receipts],
                        "paperOrderCreated": True,
                        "entryOrder": _order_dict(entry),
                        "postFillRisk": post_fill_risk,
                        "protectiveStopOrder": (
                            _order_dict(canceled_stop)
                            if canceled_stop is not None
                            else None
                        ),
                        "emergencyExitOrder": (
                            _order_dict(emergency) if emergency is not None else None
                        ),
                        "positionProtected": False,
                        "positionFlat": position_flat,
                        "recoveredAfterInterruption": True,
                        "intentFingerprint": fingerprint,
                    },
                )
        if stop_order is None:
            stop_request = AlpacaPaperOrderRequest(
                symbol=symbol,
                side="sell",
                order_type="stop",
                time_in_force="day",
                client_order_id=stop_client_id,
                quantity=position.quantity,
                stop_price=stop_price,
            )
            try:
                stop_order = self.adapter.submit_order_idempotently(
                    stop_request,
                    authorization=exit_authorization,
                ).order
                _validate_protective_stop(
                    stop_order,
                    symbol=symbol,
                    client_order_id=stop_client_id,
                    expected_quantity=position.quantity,
                    expected_stop_price=stop_price,
                )
            except PaperEngineeringAnomaly:
                canceled_stop, emergency, position_flat = (
                    self._close_after_protection_anomaly(
                        symbol=symbol,
                        position=position,
                        stop_order=stop_order,
                        exit_client_id=exit_client_id,
                        client_order_prefix=prefix,
                        policy=policy,
                    )
                )
                return self._write_final(
                    final_path,
                    {
                        **base,
                        "classification": PAPER_TRADE_CREATED,
                        "terminal": True,
                        "reasons": ["PAPER_RECOVERY_PROTECTION_MISMATCH_EMERGENCY_EXIT"],
                        "candidatesEvaluated": len(evaluations),
                        "candidateEvaluations": evaluations,
                        "selectedCandidateId": selected.get("candidateId"),
                        "selectedSymbol": symbol,
                        "selectedRank": selected.get("canonicalRank"),
                        "accountSnapshot": account_snapshot,
                        "providerCalls": [_receipt_dict(item) for item in receipts],
                        "paperOrderCreated": True,
                        "entryOrder": _order_dict(entry),
                        "postFillRisk": post_fill_risk,
                        "protectiveStopOrder": (
                            _order_dict(canceled_stop)
                            if canceled_stop is not None
                            else None
                        ),
                        "emergencyExitOrder": (
                            _order_dict(emergency) if emergency is not None else None
                        ),
                        "positionProtected": False,
                        "positionFlat": position_flat,
                        "recoveredAfterInterruption": True,
                        "intentFingerprint": fingerprint,
                    },
                )
            except AlpacaPaperBrokerError:
                emergency = self._emergency_exit(
                    symbol,
                    position,
                    exit_client_id,
                    exit_authorization,
                    policy,
                )
                return self._write_final(
                    final_path,
                    {
                        **base,
                        "classification": PAPER_TRADE_CREATED,
                        "terminal": True,
                        "reasons": ["PAPER_RECOVERY_PROTECTION_FAILED_EMERGENCY_EXIT"],
                        "candidatesEvaluated": len(evaluations),
                        "candidateEvaluations": evaluations,
                        "selectedCandidateId": selected.get("candidateId"),
                        "selectedSymbol": symbol,
                        "selectedRank": selected.get("canonicalRank"),
                        "accountSnapshot": account_snapshot,
                        "providerCalls": [_receipt_dict(item) for item in receipts],
                        "paperOrderCreated": True,
                        "entryOrder": _order_dict(entry),
                        "postFillRisk": post_fill_risk,
                        "emergencyExitOrder": _order_dict(emergency),
                        "positionProtected": False,
                        "positionFlat": not self.adapter.list_positions(),
                        "recoveredAfterInterruption": True,
                        "intentFingerprint": fingerprint,
                    },
                )
        elif stop_order.status in {"canceled", "expired", "rejected"}:
            emergency = self._emergency_exit(
                symbol,
                position,
                exit_client_id,
                exit_authorization,
                policy,
            )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": PAPER_TRADE_CREATED,
                    "terminal": True,
                    "reasons": ["PAPER_RECOVERY_PROTECTION_UNAVAILABLE_EMERGENCY_EXIT"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": evaluations,
                    "selectedCandidateId": selected.get("candidateId"),
                    "selectedSymbol": symbol,
                    "selectedRank": selected.get("canonicalRank"),
                    "accountSnapshot": account_snapshot,
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "protectiveStopOrder": _order_dict(stop_order),
                    "emergencyExitOrder": _order_dict(emergency),
                    "positionProtected": False,
                    "positionFlat": not self.adapter.list_positions(),
                    "recoveredAfterInterruption": True,
                    "intentFingerprint": fingerprint,
                },
            )

        protected_position = _find_position(self.adapter.list_positions(), symbol)
        if (
            protected_position is None
            or protected_position.quantity != position.quantity
        ):
            canceled_stop, emergency, position_flat = (
                self._close_after_protection_anomaly(
                    symbol=symbol,
                    position=position,
                    stop_order=stop_order,
                    exit_client_id=exit_client_id,
                    client_order_prefix=prefix,
                    policy=policy,
                )
            )
            return self._write_final(
                final_path,
                {
                    **base,
                    "classification": PAPER_TRADE_CREATED,
                    "terminal": True,
                    "reasons": ["PAPER_RECOVERY_POSITION_CHANGED_EMERGENCY_EXIT"],
                    "candidatesEvaluated": len(evaluations),
                    "candidateEvaluations": evaluations,
                    "selectedCandidateId": selected.get("candidateId"),
                    "selectedSymbol": symbol,
                    "selectedRank": selected.get("canonicalRank"),
                    "accountSnapshot": account_snapshot,
                    "providerCalls": [_receipt_dict(item) for item in receipts],
                    "paperOrderCreated": True,
                    "entryOrder": _order_dict(entry),
                    "postFillRisk": post_fill_risk,
                    "protectiveStopOrder": (
                        _order_dict(canceled_stop) if canceled_stop is not None else None
                    ),
                    "emergencyExitOrder": (
                        _order_dict(emergency) if emergency is not None else None
                    ),
                    "positionProtected": False,
                    "positionFlat": position_flat,
                    "recoveredAfterInterruption": True,
                    "intentFingerprint": fingerprint,
                },
            )

        active = {
            **base,
            "recordType": "ACTIVE_ALPACA_PAPER_ENGINEERING_POSITION",
            "symbol": symbol,
            "quantity": _decimal_text(position.quantity),
            "entryPrice": _decimal_text(entry.filled_average_price),
            "stopPrice": _decimal_text(stop_price),
            "targetPrice": _decimal_text(target_price),
            "forcedFlatAt": forced_flat_at.isoformat(),
            "entryOrder": _order_dict(entry),
            "postFillRisk": post_fill_risk,
            "protectiveStopOrder": _order_dict(stop_order),
            "exitClientOrderId": exit_client_id,
            "clientOrderPrefix": prefix,
            "intentFingerprint": fingerprint,
        }
        active["fingerprint"] = evidence_fingerprint(active)
        active_path = self.output_directory / "active" / f"{cycle_id}.json"
        if active_path.is_file():
            persisted_active = _load_verified_record(active_path, "active Paper position")
            if persisted_active.get("intentFingerprint") != fingerprint:
                raise PaperEngineeringAnomaly(
                    "Recovered active Paper position does not match its intent."
                )
            active = persisted_active
        else:
            _write_same_or_fail(active_path, active)
        return self._write_final(
            final_path,
            {
                **base,
                "classification": PAPER_TRADE_CREATED,
                "terminal": True,
                "reasons": ["PAPER_RECOVERED_AFTER_INTERRUPTION"],
                "candidatesEvaluated": len(evaluations),
                "candidateEvaluations": evaluations,
                "selectedCandidateId": selected.get("candidateId"),
                "selectedSymbol": symbol,
                "selectedRank": selected.get("canonicalRank"),
                "accountSnapshot": account_snapshot,
                "providerCalls": [_receipt_dict(item) for item in receipts],
                "paperOrderCreated": True,
                "entryOrder": _order_dict(entry),
                "postFillRisk": post_fill_risk,
                "protectiveStopOrder": _order_dict(stop_order),
                "positionProtected": True,
                "positionFlat": False,
                "activePositionFingerprint": active["fingerprint"],
                "recoveredAfterInterruption": True,
                "intentFingerprint": fingerprint,
            },
        )

    def reconcile_active(self) -> list[dict[str, object]]:
        """Reconcile active Paper positions and force flat at target/session deadline."""

        policy = load_paper_engineering_policy(self.output_directory)
        load_paper_engineering_arm(policy=policy, output_directory=self.output_directory)
        results: list[dict[str, object]] = []
        active_directory = self.output_directory / "active"
        if not active_directory.is_dir():
            return results
        for path in sorted(active_directory.glob("*.json")):
            active = _load_json_object(path, "active Paper position")
            if active.get("fingerprint") != evidence_fingerprint(
                {key: value for key, value in active.items() if key != "fingerprint"}
            ):
                raise PaperEngineeringAnomaly("Active Paper position evidence is invalid.")
            cycle_id = str(active.get("decisionCycleId", ""))
            outcome_path = self.output_directory / "outcomes" / f"{cycle_id}.json"
            if outcome_path.is_file():
                results.append(_load_verified_final(outcome_path))
                continue
            results.append(self._reconcile_one(active, outcome_path, policy))
        return results

    def _reconcile_one(
        self,
        active: Mapping[str, object],
        outcome_path: Path,
        policy: PaperEngineeringPolicy,
    ) -> dict[str, object]:
        symbol = str(active.get("symbol", "")).strip().upper()
        quantity = Decimal(str(active.get("quantity")))
        target = Decimal(str(active.get("targetPrice")))
        stop_payload = active.get("protectiveStopOrder")
        stop_payload = stop_payload if isinstance(stop_payload, Mapping) else {}
        stop_order_id = str(stop_payload.get("orderId", ""))
        prefix = str(active.get("clientOrderPrefix", ""))
        exit_client_id = str(active.get("exitClientOrderId", ""))
        maximum_notional = max(
            Decimal("1"),
            Decimal(str(stop_payload.get("quantity") or quantity)) * target,
        )
        authorization = authorize_paper_engineering_order(
            confirmation=PAPER_ENGINEERING_CONFIRMATION,
            maximum_notional=maximum_notional,
            maximum_quantity=quantity,
            allowed_sides=("sell",),
            allowed_symbols=(symbol,),
            client_order_prefix=prefix,
        )
        stop_order = self.adapter.get_order(stop_order_id)
        position = _find_position(self.adapter.list_positions(), symbol)
        if position is None:
            return self._write_final(
                outcome_path,
                {
                    "schemaVersion": PAPER_ENGINEERING_SCHEMA_VERSION,
                    "profile": PAPER_ENGINEERING_PROFILE,
                    "recordType": "ALPACA_PAPER_ENGINEERING_OUTCOME",
                    "decisionCycleId": active.get("decisionCycleId"),
                    "symbol": symbol,
                    "classification": "POSITION_CLOSED",
                    "exitReason": "PROTECTIVE_STOP" if stop_order.filled_quantity > 0 else "PROVIDER_POSITION_CLOSED",
                    "stopOrder": _order_dict(stop_order),
                    "positionFlat": True,
                    "recordedAt": self.clock().isoformat(),
                },
            )
        try:
            _validate_protective_stop(
                stop_order,
                symbol=symbol,
                client_order_id=str(stop_payload.get("clientOrderId", "")),
                expected_quantity=position.quantity,
                expected_stop_price=Decimal(str(active.get("stopPrice"))),
            )
            if position.quantity != quantity:
                raise PaperEngineeringAnomaly(
                    "Paper broker position no longer matches active evidence."
                )
        except PaperEngineeringAnomaly:
            canceled_stop, emergency, position_flat = (
                self._close_after_protection_anomaly(
                    symbol=symbol,
                    position=position,
                    stop_order=stop_order,
                    exit_client_id=exit_client_id,
                    client_order_prefix=prefix,
                    policy=policy,
                )
            )
            return self._write_final(
                outcome_path,
                {
                    "schemaVersion": PAPER_ENGINEERING_SCHEMA_VERSION,
                    "profile": PAPER_ENGINEERING_PROFILE,
                    "recordType": "ALPACA_PAPER_ENGINEERING_OUTCOME",
                    "decisionCycleId": active.get("decisionCycleId"),
                    "symbol": symbol,
                    "classification": "POSITION_CLOSED",
                    "exitReason": "PROTECTION_QUANTITY_MISMATCH",
                    "stopOrder": (
                        _order_dict(canceled_stop) if canceled_stop is not None else None
                    ),
                    "exitOrder": (
                        _order_dict(emergency) if emergency is not None else None
                    ),
                    "positionProtected": False,
                    "positionFlat": position_flat,
                    "recordedAt": self.clock().isoformat(),
                },
            )
        current = self.clock()
        _require_aware(current, "Paper reconciliation")
        forced_at = _aware_datetime(active.get("forcedFlatAt"))
        exit_reason = ""
        if forced_at is not None and current >= forced_at:
            exit_reason = "FORCED_FLAT"
        else:
            proof = build_regular_market_quote_proof(
                self.quote_source,
                (symbol,),
                clock=self.clock,
                require_clock_proof=True,
            )
            quotes = proof.get("quotes")
            quote = quotes[0] if isinstance(quotes, list) and quotes else {}
            bid = _decimal(quote.get("bid")) if isinstance(quote, Mapping) else None
            if isinstance(quote, Mapping) and quote.get("status") == "PASS" and bid is not None and bid >= target:
                exit_reason = "TARGET_REACHED"
        if not exit_reason:
            if stop_order.status in {"canceled", "expired", "rejected"}:
                exit_reason = "PROTECTION_UNAVAILABLE_EMERGENCY_EXIT"
            else:
                return {
                    "classification": "POSITION_WORKING",
                    "decisionCycleId": active.get("decisionCycleId"),
                    "symbol": symbol,
                    "positionProtected": True,
                }
        if not stop_order.terminal:
            stop_order = self.adapter.cancel_order(
                stop_order.order_id,
                authorization=authorization,
            )
            stop_order = self._poll(stop_order, policy)
        current_position = _find_position(self.adapter.list_positions(), symbol)
        if current_position is None:
            return self._write_final(
                outcome_path,
                {
                    "schemaVersion": PAPER_ENGINEERING_SCHEMA_VERSION,
                    "profile": PAPER_ENGINEERING_PROFILE,
                    "recordType": "ALPACA_PAPER_ENGINEERING_OUTCOME",
                    "decisionCycleId": active.get("decisionCycleId"),
                    "symbol": symbol,
                    "classification": "POSITION_CLOSED",
                    "exitReason": "PROTECTIVE_STOP_RACE",
                    "stopOrder": _order_dict(stop_order),
                    "positionFlat": True,
                    "recordedAt": current.isoformat(),
                },
            )
        exit_order = self._emergency_exit(
            symbol,
            current_position,
            exit_client_id,
            authorization,
            policy,
        )
        remaining = _find_position(self.adapter.list_positions(), symbol)
        if remaining is not None:
            raise PaperEngineeringAnomaly("Paper exit did not reconcile to flat.")
        return self._write_final(
            outcome_path,
            {
                "schemaVersion": PAPER_ENGINEERING_SCHEMA_VERSION,
                "profile": PAPER_ENGINEERING_PROFILE,
                "recordType": "ALPACA_PAPER_ENGINEERING_OUTCOME",
                "decisionCycleId": active.get("decisionCycleId"),
                "symbol": symbol,
                "classification": "POSITION_CLOSED",
                "exitReason": exit_reason,
                "stopOrder": _order_dict(stop_order),
                "exitOrder": _order_dict(exit_order),
                "positionFlat": True,
                "recordedAt": current.isoformat(),
            },
        )

    def _emergency_exit(
        self,
        symbol: str,
        position: AlpacaPaperPosition,
        client_order_id: str,
        authorization,
        policy: PaperEngineeringPolicy,
    ) -> AlpacaPaperOrder:
        request = AlpacaPaperOrderRequest(
            symbol=symbol,
            side="sell",
            order_type="market",
            time_in_force="day",
            client_order_id=client_order_id,
            quantity=position.quantity,
        )
        resolution = self.adapter.submit_order_idempotently(
            request,
            authorization=authorization,
        )
        order = self._poll(resolution.order, policy)
        remaining = _find_position(self.adapter.list_positions(), symbol)
        if order.filled_quantity < position.quantity or remaining is not None:
            raise PaperEngineeringAnomaly(
                "Paper emergency exit did not reconcile the owned position to flat."
            )
        return order

    def _close_after_protection_anomaly(
        self,
        *,
        symbol: str,
        position: AlpacaPaperPosition,
        stop_order: AlpacaPaperOrder | None,
        exit_client_id: str,
        client_order_prefix: str,
        policy: PaperEngineeringPolicy,
    ) -> tuple[AlpacaPaperOrder | None, AlpacaPaperOrder | None, bool]:
        canceled_stop = stop_order
        if stop_order is not None and not stop_order.terminal:
            stop_quantity = stop_order.quantity or position.quantity
            cancellation_authorization = authorize_paper_engineering_order(
                confirmation=PAPER_ENGINEERING_CONFIRMATION,
                maximum_notional=max(
                    Decimal("1"),
                    abs(position.market_value),
                    stop_quantity * max(position.current_price, Decimal("1")),
                ),
                maximum_quantity=max(stop_quantity, position.quantity),
                allowed_sides=("sell",),
                allowed_symbols=(symbol,),
                client_order_prefix=client_order_prefix,
            )
            canceled_stop = self.adapter.cancel_order(
                stop_order.order_id,
                authorization=cancellation_authorization,
            )
            canceled_stop = self._poll(canceled_stop, policy)
            if canceled_stop.status != "canceled":
                raise PaperEngineeringAnomaly(
                    "Mismatched Paper protective stop could not be canceled."
                )

        current_position = _find_position(self.adapter.list_positions(), symbol)
        if current_position is None:
            return canceled_stop, None, True
        exit_authorization = authorize_paper_engineering_order(
            confirmation=PAPER_ENGINEERING_CONFIRMATION,
            maximum_notional=max(Decimal("1"), abs(current_position.market_value)),
            maximum_quantity=current_position.quantity,
            allowed_sides=("sell",),
            allowed_symbols=(symbol,),
            client_order_prefix=client_order_prefix,
        )
        emergency = self._emergency_exit(
            symbol,
            current_position,
            exit_client_id,
            exit_authorization,
            policy,
        )
        return canceled_stop, emergency, not self.adapter.list_positions()

    def _poll(
        self,
        order: AlpacaPaperOrder,
        policy: PaperEngineeringPolicy,
    ) -> AlpacaPaperOrder:
        current = order
        for _ in range(policy.order_poll_attempts):
            if current.terminal:
                return current
            self.sleep(policy.order_poll_interval_seconds)
            current = self.adapter.get_order(current.order_id)
        return current

    def _decision_path(self, cycle_id: str) -> Path:
        return self.output_directory / "decisions" / f"{cycle_id}.json"

    def _write_final(self, path: Path, payload: dict[str, object]) -> dict[str, object]:
        canonical = dict(payload)
        canonical["fingerprint"] = evidence_fingerprint(canonical)
        _assert_sanitized(canonical)
        _write_same_or_fail(path, canonical)
        _write_same_or_fail(path.with_suffix(".md"), _markdown_record(canonical))
        return canonical


def _policy_dict(policy: PaperEngineeringPolicy) -> dict[str, object]:
    return {
        "schemaVersion": policy.schema_version,
        "profile": policy.profile,
        "policyId": policy.policy_id,
        "sampleId": policy.sample_id,
        "allocation": {
            "schemaVersion": policy.allocation.schema_version,
            "profile": policy.allocation.profile,
            "policyId": policy.allocation.policy_id,
            "fixedUnitRiskDollars": _decimal_text(policy.allocation.fixed_unit_risk_dollars),
            "maxPositionNotionalDollars": _decimal_text(policy.allocation.max_position_notional_dollars),
            "minimumCashReserveDollars": _decimal_text(policy.allocation.minimum_cash_reserve_dollars),
            "maxTotalOpenRiskDollars": _decimal_text(policy.allocation.max_total_open_risk_dollars),
            "dailyLossLimitDollars": _decimal_text(policy.allocation.daily_loss_limit_dollars),
            "maxOpenPositions": policy.allocation.max_open_positions,
            "maxSnapshotAgeSeconds": policy.allocation.max_snapshot_age_seconds,
            "quantityPolicy": policy.allocation.quantity_policy.value,
            "fingerprint": policy.allocation.fingerprint,
        },
        "risk": {
            "schemaVersion": policy.risk.schema_version,
            "profile": policy.risk.profile,
            "policyId": policy.risk.policy_id,
            "maximumSpreadPercent": _decimal_text(policy.risk.maximum_spread_percent),
            "maximumEntryExtensionPercent": _decimal_text(policy.risk.maximum_entry_extension_percent),
            "minimumRewardRisk": _decimal_text(policy.risk.minimum_reward_risk),
            "fingerprint": policy.risk.fingerprint,
        },
        "entryNotionalBufferPercent": _decimal_text(policy.entry_notional_buffer_percent),
        "minimumEntryNotionalDollars": _decimal_text(policy.minimum_entry_notional_dollars),
        "orderPollAttempts": policy.order_poll_attempts,
        "orderPollIntervalSeconds": float(policy.order_poll_interval_seconds),
    }


def _validate_policy(policy: PaperEngineeringPolicy) -> None:
    if (
        policy.schema_version != PAPER_ENGINEERING_SCHEMA_VERSION
        or policy.profile != PAPER_ENGINEERING_PROFILE
        or not policy.policy_id.strip()
        or not policy.sample_id.startswith("alpaca-paper-engineering-")
    ):
        raise PaperEngineeringError("Paper engineering policy identity is invalid.")
    for value, label in (
        (policy.entry_notional_buffer_percent, "entry notional buffer"),
        (policy.minimum_entry_notional_dollars, "minimum entry notional"),
    ):
        if not value.is_finite() or value <= 0:
            raise PaperEngineeringError(f"Paper {label} is invalid.")
    if policy.entry_notional_buffer_percent >= Decimal("100"):
        raise PaperEngineeringError("Paper entry notional buffer is invalid.")
    if policy.order_poll_attempts < 1 or policy.order_poll_attempts > 60:
        raise PaperEngineeringError("Paper order poll count is invalid.")
    if not 0 <= policy.order_poll_interval_seconds <= 5:
        raise PaperEngineeringError("Paper order poll interval is invalid.")


def _validate_arm(arm: PaperEngineeringArm, policy: PaperEngineeringPolicy) -> None:
    if (
        arm.schema_version != PAPER_ENGINEERING_SCHEMA_VERSION
        or arm.profile != PAPER_ENGINEERING_PROFILE
        or arm.sample_id != policy.sample_id
        or arm.policy_fingerprint != policy.fingerprint
        or arm.lane != AlpacaPaperLane.CANARY_REALISTIC.value
        or arm.endpoint != ALPACA_PAPER_BASE_URL
        or arm.environment != "PAPER_ONLY"
        or arm.order_transmission != "ALPACA_PAPER_ONLY"
        or not _SHA256_PATTERN.fullmatch(arm.capability_proof_fingerprint)
        or not _SHA256_PATTERN.fullmatch(arm.capability_registry_fingerprint)
    ):
        raise PaperEngineeringError("Paper engineering arm identity is invalid.")
    _require_aware(_aware_datetime(arm.activated_at), "Paper arm activation")


def _account_dict(value: AccountSnapshot) -> dict[str, object]:
    return {
        "schemaVersion": value.schema_version,
        "snapshotId": value.snapshot_id,
        "decisionCycleId": value.decision_cycle_id,
        "lane": value.lane,
        "provider": value.provider,
        "environment": value.environment,
        "bindingFingerprint": value.binding_fingerprint,
        "authorizedAccountCount": value.authorized_account_count,
        "status": value.status,
        "cashAvailable": _decimal_text(value.cash_available),
        "buyingPower": _decimal_text(value.buying_power),
        "committedNotional": _decimal_text(value.committed_notional),
        "committedOpenRisk": _decimal_text(value.committed_open_risk),
        "openPositionCount": value.open_position_count,
        "realizedPnlToday": _decimal_text(value.realized_pnl_today),
        "providerTimestamp": value.provider_timestamp,
        "portfolioTimestamp": value.portfolio_timestamp,
        "receiptTimestamp": value.receipt_timestamp,
        "sourceIdentity": value.source_identity,
        "fingerprint": value.fingerprint,
    }


def _order_dict(order: AlpacaPaperOrder) -> dict[str, object]:
    return {
        "orderId": order.order_id,
        "clientOrderId": order.client_order_id,
        "symbol": order.symbol,
        "side": order.side,
        "orderType": order.order_type,
        "status": order.status,
        "quantity": _decimal_text(order.quantity),
        "notional": _decimal_text(order.notional),
        "filledQuantity": _decimal_text(order.filled_quantity),
        "filledAveragePrice": _decimal_text(order.filled_average_price),
        "limitPrice": _decimal_text(order.limit_price),
        "stopPrice": _decimal_text(order.stop_price),
        "submittedAt": order.submitted_at,
        "updatedAt": order.updated_at,
        "filledAt": order.filled_at,
        "canceledAt": order.canceled_at,
        "requestIdPresent": order.request_id_present,
    }


def _receipt_dict(receipt: AlpacaPaperProviderReceipt) -> dict[str, object]:
    return {
        "method": receipt.method,
        "path": receipt.path,
        "httpStatus": receipt.http_status,
        "requestIdPresent": receipt.request_id_present,
        "receivedAt": receipt.received_at,
        "payload": receipt.payload,
    }


def _latest_receipt(
    receipts: Sequence[AlpacaPaperProviderReceipt],
    path: str,
) -> AlpacaPaperProviderReceipt:
    matches = [item for item in receipts if item.path == path]
    if not matches:
        raise PaperEngineeringError(f"Paper provider receipt is missing for {path}.")
    return matches[-1]


def _find_position(
    positions: Sequence[AlpacaPaperPosition],
    symbol: str,
) -> AlpacaPaperPosition | None:
    matches = [item for item in positions if item.symbol == symbol]
    if len(matches) > 1:
        raise PaperEngineeringAnomaly("Paper provider returned duplicate positions.")
    return matches[0] if matches else None


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PaperEngineeringError(f"{label} could not be read.") from None
    if not isinstance(payload, dict):
        raise PaperEngineeringError(f"{label} has invalid shape.")
    return payload


def _load_verified_final(path: Path) -> dict[str, object]:
    return _load_verified_record(path, "Paper final evidence")


def _load_verified_record(path: Path, label: str) -> dict[str, object]:
    payload = _load_json_object(path, label)
    fingerprint = payload.get("fingerprint")
    candidate = {key: value for key, value in payload.items() if key != "fingerprint"}
    if fingerprint != evidence_fingerprint(candidate):
        raise PaperEngineeringAnomaly(f"{label.capitalize()} fingerprint is invalid.")
    _assert_sanitized(payload)
    return payload


def _post_fill_risk_evidence(
    *,
    candidate_id: str,
    symbol: str,
    plan_entry_price: Decimal | None,
    stop_price: Decimal | None,
    target_price: Decimal | None,
    authorized_quantity: Decimal | None,
    pre_entry_open_risk: Decimal | None,
    entry: AlpacaPaperOrder,
    position: AlpacaPaperPosition,
    policy: PaperEngineeringPolicy,
) -> dict[str, object]:
    blockers: list[str] = []
    fill_quantity = entry.filled_quantity
    fill_price = entry.filled_average_price
    position_quantity = position.quantity
    position_price = position.average_entry_price
    values = (
        (plan_entry_price, "PAPER_POST_FILL_PLAN_ENTRY_MISSING"),
        (stop_price, "PAPER_POST_FILL_STOP_MISSING"),
        (target_price, "PAPER_POST_FILL_TARGET_MISSING"),
        (authorized_quantity, "PAPER_POST_FILL_AUTHORIZED_QUANTITY_MISSING"),
        (pre_entry_open_risk, "PAPER_POST_FILL_OPEN_RISK_MISSING"),
        (fill_price, "PAPER_POST_FILL_AVERAGE_PRICE_MISSING"),
    )
    for value, blocker in values:
        if value is None or not value.is_finite():
            blockers.append(blocker)

    if fill_quantity <= 0 or not fill_quantity.is_finite():
        blockers.append("PAPER_POST_FILL_QUANTITY_INVALID")
    if position_quantity <= 0 or not position_quantity.is_finite():
        blockers.append("PAPER_POST_FILL_POSITION_QUANTITY_INVALID")
    if authorized_quantity is not None and fill_quantity > authorized_quantity:
        blockers.append("PAPER_POST_FILL_AUTHORIZATION_EXCEEDED")
    if position_quantity > fill_quantity:
        blockers.append("PAPER_POST_FILL_POSITION_EXCEEDS_FILL")
    if fill_price is not None and position_price != fill_price:
        blockers.append("PAPER_POST_FILL_AVERAGE_PRICE_MISMATCH")

    actual_risk_per_share: Decimal | None = None
    actual_dollar_risk: Decimal | None = None
    actual_reward_risk: Decimal | None = None
    entry_extension_percent: Decimal | None = None
    if (
        fill_price is not None
        and plan_entry_price is not None
        and stop_price is not None
        and target_price is not None
        and all(
            value.is_finite()
            for value in (fill_price, plan_entry_price, stop_price, target_price)
        )
        and plan_entry_price > 0
    ):
        actual_risk_per_share = fill_price - stop_price
        reward_per_share = target_price - fill_price
        entry_extension_percent = (
            (fill_price - plan_entry_price) / plan_entry_price * Decimal("100")
        )
        if actual_risk_per_share <= 0 or reward_per_share <= 0:
            blockers.append("PAPER_POST_FILL_LEVELS_INVALID")
        else:
            actual_dollar_risk = actual_risk_per_share * position_quantity
            actual_reward_risk = reward_per_share / actual_risk_per_share
            if actual_dollar_risk > policy.allocation.fixed_unit_risk_dollars:
                blockers.append("PAPER_POST_FILL_UNIT_RISK_EXCEEDED")
            if (
                pre_entry_open_risk is not None
                and pre_entry_open_risk.is_finite()
                and pre_entry_open_risk + actual_dollar_risk
                > policy.allocation.max_total_open_risk_dollars
            ):
                blockers.append("PAPER_POST_FILL_TOTAL_OPEN_RISK_EXCEEDED")
            if actual_reward_risk < policy.risk.minimum_reward_risk:
                blockers.append("PAPER_POST_FILL_REWARD_RISK_TOO_LOW")
        if entry_extension_percent > policy.risk.maximum_entry_extension_percent:
            blockers.append("PAPER_POST_FILL_ENTRY_EXTENSION_TOO_LARGE")

    blockers = list(dict.fromkeys(blockers))
    payload: dict[str, object] = {
        "status": "BLOCKED" if blockers else "PASS",
        "candidateId": candidate_id,
        "symbol": symbol,
        "planEntryPrice": _decimal_text(plan_entry_price),
        "stopPrice": _decimal_text(stop_price),
        "targetPrice": _decimal_text(target_price),
        "authorizedQuantity": _decimal_text(authorized_quantity),
        "entryFilledQuantity": _decimal_text(fill_quantity),
        "confirmedPositionQuantity": _decimal_text(position_quantity),
        "entryFilledAveragePrice": _decimal_text(fill_price),
        "confirmedPositionAveragePrice": _decimal_text(position_price),
        "actualRiskPerShare": _decimal_text(actual_risk_per_share),
        "actualDollarRisk": _decimal_text(actual_dollar_risk),
        "actualRewardRisk": _decimal_text(actual_reward_risk),
        "entryExtensionPercent": _decimal_text(entry_extension_percent),
        "preEntryOpenRisk": _decimal_text(pre_entry_open_risk),
        "maximumUnitRisk": _decimal_text(
            policy.allocation.fixed_unit_risk_dollars
        ),
        "maximumTotalOpenRisk": _decimal_text(
            policy.allocation.max_total_open_risk_dollars
        ),
        "minimumRewardRisk": _decimal_text(policy.risk.minimum_reward_risk),
        "maximumEntryExtensionPercent": _decimal_text(
            policy.risk.maximum_entry_extension_percent
        ),
        "blockers": blockers,
        "source": "ALPACA_PAPER_CONFIRMED_FILL_AND_POSITION",
    }
    payload["fingerprint"] = evidence_fingerprint(payload)
    return payload


def _validate_protective_stop(
    order: AlpacaPaperOrder,
    *,
    symbol: str,
    client_order_id: str,
    expected_quantity: Decimal,
    expected_stop_price: Decimal,
) -> None:
    _validate_recovered_order(
        order,
        symbol=symbol,
        side="sell",
        client_order_id=client_order_id,
        order_type="stop",
    )
    if order.quantity != expected_quantity:
        raise PaperEngineeringAnomaly(
            "Paper protective stop quantity does not match broker position."
        )
    if order.stop_price != expected_stop_price:
        raise PaperEngineeringAnomaly(
            "Paper protective stop price does not match the frozen plan."
        )
    if order.filled_quantity != 0 or order.status in {
        "canceled",
        "expired",
        "filled",
        "rejected",
    }:
        raise PaperEngineeringAnomaly(
            "Paper protective stop response is not an active unfilled order."
        )


def _validate_recovered_order(
    order: AlpacaPaperOrder,
    *,
    symbol: str,
    side: str,
    client_order_id: str,
    order_type: str | None = None,
) -> None:
    if (
        order.symbol != symbol
        or order.side != side
        or order.client_order_id != client_order_id
        or (order_type is not None and order.order_type != order_type)
    ):
        raise PaperEngineeringAnomaly("Recovered Paper order identity is invalid.")


def _write_same_or_fail(path: Path, payload: object) -> None:
    encoded = _canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise PaperEngineeringAnomaly(
                f"Write-once Paper evidence conflicts at {path.name}."
            ) from None


def _canonical_bytes(payload: object) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _markdown_record(payload: Mapping[str, object]) -> str:
    lines = [
        "# Alpaca Paper Engineering Evidence",
        "",
        f"- Classification: `{payload.get('classification', payload.get('recordType', 'UNKNOWN'))}`",
        f"- Decision cycle: `{payload.get('decisionCycleId', '')}`",
        f"- Sample: `{payload.get('sampleId', '')}`",
        f"- Symbol: `{payload.get('selectedSymbol', payload.get('symbol', '')) or 'NONE'}`",
        f"- Paper order created: `{payload.get('paperOrderCreated', False)}`",
        f"- Live endpoint reachable: `{payload.get('liveEndpointReachable', False)}`",
        "",
        "## Reasons",
        "",
    ]
    reasons = payload.get("reasons")
    if isinstance(reasons, list) and reasons:
        lines.extend(f"- `{item}`" for item in reasons)
    else:
        lines.append("- None")
    lines.extend(
        (
            "",
            "This is Alpaca Paper engineering evidence, not a live order or a profitability claim.",
            "",
        )
    )
    return "\n".join(lines)


def _assert_sanitized(payload: object) -> None:
    text = json.dumps(payload, sort_keys=True, default=str)
    lowered = text.lower()
    forbidden = (
        "secret_key",
        "api_key",
        "authorization",
        "access_token",
        "refresh_token",
        "account_number",
    )
    if any(value in lowered for value in forbidden) or any(
        pattern.search(text) for pattern in _SECRET_PATTERNS
    ):
        raise PaperEngineeringAnomaly("Paper evidence failed the secret scan.")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _stable_id(namespace: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join((namespace, *parts)).encode("utf-8")).hexdigest()
    return f"{namespace}-{digest[:24]}"


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    return parsed if parsed.is_finite() else None


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _require_aware(value: datetime | None, label: str) -> None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise PaperEngineeringError(f"{label} timestamp must include a UTC offset.")


def _sanitize_text(value: str) -> str:
    sanitized = str(value)
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    return sanitized[:500]


@contextmanager
def _exclusive_paper_session():
    if os.name != "nt":
        yield
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel32.ReleaseMutex.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.CreateMutexW(None, True, _PAPER_SESSION_MUTEX_NAME)
    if not handle:
        raise PaperEngineeringError("The Paper session mutex could not be created.")
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(handle)
        raise PaperEngineeringAnomaly(
            "Another Alpaca Paper engineering session is already active."
        )
    try:
        yield
    finally:
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


def _default_lifecycle_proof() -> Path:
    root = DEFAULT_PAPER_ENGINEERING_DIRECTORY.parent / "lifecycle-proofs"
    candidates = sorted(root.glob("*-final.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise PaperEngineeringError("No direct Alpaca Paper lifecycle proof is available.")
    return candidates[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prospective Alpaca Paper engineering lane.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze-sample")
    freeze.add_argument("--risk-dollars", required=True)
    freeze.add_argument("--max-notional", required=True)
    freeze.add_argument("--cash-reserve", required=True)
    freeze.add_argument("--max-open-risk", required=True)
    freeze.add_argument("--daily-loss-limit", required=True)
    freeze.add_argument("--max-positions", type=int, required=True)
    freeze.add_argument("--account-max-age", type=int, default=30)
    freeze.add_argument("--max-spread-percent", default="3")
    freeze.add_argument("--max-entry-extension-percent", default="0.25")
    freeze.add_argument("--minimum-reward-risk", default="1.5")
    freeze.add_argument("--entry-notional-buffer-percent", default="1")
    freeze.add_argument("--minimum-entry-notional", default="1")
    freeze.add_argument("--confirmation", required=True)
    freeze.add_argument("--lifecycle-proof", type=Path)
    rollover = subparsers.add_parser("rollover-invalidated-sample")
    rollover.add_argument("--expected-sample-id", required=True)
    rollover.add_argument("--new-sample-id", required=True)
    rollover.add_argument("--new-identity-date", required=True)
    rollover.add_argument("--adjudication", type=Path, required=True)
    rollover.add_argument("--confirmation", required=True)
    decide = subparsers.add_parser("decide")
    decide.add_argument("--report", type=Path, required=True)
    decide.add_argument("--confirmation", required=True)
    session = subparsers.add_parser("run-session")
    session.add_argument("--report", type=Path, required=True)
    session.add_argument("--confirmation", required=True)
    session.add_argument("--reconcile-interval", type=float, default=5.0)
    session.add_argument("--maximum-runtime", type=int, default=25_200)
    subparsers.add_parser("reconcile")
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze-sample":
            sample_date = now_central().date().isoformat().replace("-", "")
            policy = PaperEngineeringPolicy(
                policy_id=f"alpaca-paper-canary-engineering-policy-{sample_date}-v1",
                sample_id=f"alpaca-paper-engineering-{sample_date}-v1",
                allocation=ProviderNeutralAllocationPolicy(
                    policy_id=f"alpaca-paper-canary-allocation-{sample_date}-v1",
                    fixed_unit_risk_dollars=Decimal(args.risk_dollars),
                    max_position_notional_dollars=Decimal(args.max_notional),
                    minimum_cash_reserve_dollars=Decimal(args.cash_reserve),
                    max_total_open_risk_dollars=Decimal(args.max_open_risk),
                    daily_loss_limit_dollars=Decimal(args.daily_loss_limit),
                    max_open_positions=args.max_positions,
                    max_snapshot_age_seconds=args.account_max_age,
                ),
                risk=PaperRiskPolicy(
                    policy_id=f"alpaca-paper-canary-risk-{sample_date}-v1",
                    maximum_spread_percent=Decimal(args.max_spread_percent),
                    maximum_entry_extension_percent=Decimal(args.max_entry_extension_percent),
                    minimum_reward_risk=Decimal(args.minimum_reward_risk),
                ),
                entry_notional_buffer_percent=Decimal(args.entry_notional_buffer_percent),
                minimum_entry_notional_dollars=Decimal(args.minimum_entry_notional),
                order_poll_attempts=15,
                order_poll_interval_seconds=1.0,
            )
            arm = freeze_paper_engineering_sample(
                policy=policy,
                lifecycle_proof_path=args.lifecycle_proof or _default_lifecycle_proof(),
                confirmation=args.confirmation,
            )
            result: object = {
                "classification": "ALPACA_PAPER_ENGINEERING_SAMPLE_FROZEN",
                "sampleId": arm.sample_id,
                "armFingerprint": arm.fingerprint,
                "endpoint": arm.endpoint,
                "liveEndpointReachable": False,
            }
        elif args.command == "rollover-invalidated-sample":
            result = rollover_invalidated_paper_engineering_sample(
                expected_sample_id=args.expected_sample_id,
                new_sample_id=args.new_sample_id,
                new_identity_date=args.new_identity_date,
                adjudication_path=args.adjudication,
                confirmation=args.confirmation,
            )
        else:
            engine = AlpacaPaperEngineeringEngine(
                adapter=AlpacaPaperBrokerAdapter(lane=AlpacaPaperLane.CANARY_REALISTIC),
                quote_source=SchwabMarketDataQuoteSource(),
            )
            if args.command == "decide":
                result = engine.run_decision(
                    args.report,
                    confirmation=args.confirmation,
                )
            elif args.command == "run-session":
                result = engine.run_session(
                    args.report,
                    confirmation=args.confirmation,
                    reconcile_interval_seconds=args.reconcile_interval,
                    maximum_runtime_seconds=args.maximum_runtime,
                )
            else:
                result = engine.reconcile_active()
    except (PaperEngineeringError, PaperEngineeringAnomaly, AlpacaPaperBrokerError, AlpacaPaperLifecycleError) as exc:
        print(f"Alpaca Paper engineering stopped safely: {_sanitize_text(str(exc))}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
