from __future__ import annotations

"""Deterministic automatic selection for the official FakeBroker Shadow sample."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.shadow_trading import (
    SHADOW_MODE,
    ShadowStateError,
    ShadowTrade,
    ShadowTradingService,
    automatic_shadow_selector_is_armed,
    audit_shadow_trade,
    expected_shadow_selection_policy_evidence,
    first_automatic_shadow_candidate,
    stable_id,
)
from momentum_hunter.time_utils import now_central


SELECTION_STARTED = "TRADE_STARTED"
SELECTION_ALREADY_PROCESSED = "REPORT_ALREADY_PROCESSED"
SELECTION_NO_ELIGIBLE_CANDIDATE = "NO_ELIGIBLE_CANDIDATE"
SELECTION_SAMPLE_INACTIVE = "SAMPLE_NOT_ACTIVE"
SELECTION_NO_REPORT = "NO_REPORT"
SELECTION_REPORT_NOT_PROSPECTIVE = "REPORT_NOT_PROSPECTIVE"
SELECTION_CONSTITUTION_NOT_ARMED = "CONSTITUTION_NOT_ARMED"


@dataclass(frozen=True)
class AutomaticShadowSelectionResult:
    status: str
    reason: str
    report_path: str = ""
    report_sha256: str = ""
    candidates_evaluated: int = 0
    selected_symbol: str = ""
    selected_rank: int = 0
    simulation_command_id: str = ""
    shadow_trade_id: str = ""
    selection_policy_recorded_at: str = ""
    selection_policy_version: str = ""
    selection_policy_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": SHADOW_MODE,
            "transmitting": False,
            "status": self.status,
            "reason": self.reason,
            "reportPath": self.report_path,
            "reportSha256": self.report_sha256,
            "candidatesEvaluated": self.candidates_evaluated,
            "selectedSymbol": self.selected_symbol or None,
            "selectedRank": self.selected_rank or None,
            "simulationCommandId": self.simulation_command_id or None,
            "shadowTradeId": self.shadow_trade_id or None,
            "selectionPolicyRecordedAt": (
                self.selection_policy_recorded_at or None
            ),
            "selectionPolicyVersion": self.selection_policy_version or None,
            "selectionPolicyFingerprint": (
                self.selection_policy_fingerprint or None
            ),
            "orderTransmission": "UNAVAILABLE",
        }


class AutomaticShadowSelector:
    """Selects at most one clean Risk-Governor-approved candidate per report."""

    def __init__(self, service: ShadowTradingService) -> None:
        self.service = service

    def select(
        self,
        report_path: Path,
        *,
        decision_at: datetime | None = None,
    ) -> AutomaticShadowSelectionResult:
        decision_at = decision_at or now_central()
        activation = self.service.sample_activation_status()
        if activation["activationState"] != "ACTIVE":
            return AutomaticShadowSelectionResult(
                status=SELECTION_SAMPLE_INACTIVE,
                reason="The official Shadow sample is not active; no automatic selection occurred.",
                report_path=str(report_path),
            )
        if not automatic_shadow_selector_is_armed():
            return AutomaticShadowSelectionResult(
                status=SELECTION_CONSTITUTION_NOT_ARMED,
                reason=(
                    "The official Shadow sample is activated, but automatic "
                    "selection is not armed because the Shadow Sample "
                    "Constitution gates are incomplete."
                ),
                report_path=str(report_path),
            )
        source_bytes = report_path.read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        existing = [
            trade
            for trade in self.service.store.load().trades
            if trade.evidence.source_sha256 == source_sha256
        ]
        if len(existing) > 1:
            raise ShadowStateError(
                "More than one Shadow Trade references the same source report."
            )

        report = load_report_object(source_bytes)
        rows = report.get("candidates") or report.get("top_5_for_capital") or []
        if not isinstance(rows, list):
            raise ValueError(
                "The trade-planning report is missing its candidate collection."
            )
        metadata = (
            report.get("metadata", {})
            if isinstance(report.get("metadata"), dict)
            else {}
        )
        if not self.service.is_prospective_official_evidence(
            metadata,
            decision_at=decision_at,
        ):
            return AutomaticShadowSelectionResult(
                status=SELECTION_REPORT_NOT_PROSPECTIVE,
                reason=(
                    "The latest scheduled report predates official sample "
                    "activation; no automatic selection occurred."
                ),
                report_path=str(report_path),
                report_sha256=source_sha256,
            )
        if existing:
            self.service.load_automatic_selection_policy()
            audit = audit_shadow_trade(existing[0])
            if not audit.passed:
                raise ShadowStateError(
                    "Existing Shadow Trade for this report failed its automatic "
                    "selection evidence audit."
                )
            return result_for_existing_trade(
                report_path,
                source_sha256,
                existing[0],
            )
        selection_policy = self.service.freeze_automatic_selection_policy(
            recorded_at=decision_at,
        )
        choice, evaluated = first_automatic_shadow_candidate(
            rows,
            metadata=metadata,
            report_path=report_path,
            decision_at=decision_at,
        )
        if choice is not None:
            command_id = stable_id("shadow-auto-report", source_sha256)
            trade = self.service.start_trade(
                report_path,
                symbol=choice.symbol,
                simulation_command_id=command_id,
                decision_at=decision_at,
                expected_source_sha256=source_sha256,
                selection_policy_evidence=(
                    expected_shadow_selection_policy_evidence()
                ),
            )
            if trade.status == "blocked" or trade.data_quality_state != "COMPLETE":
                raise ShadowStateError(
                    "Automatic selection produced a blocked or partial Shadow record."
                )
            return AutomaticShadowSelectionResult(
                status=SELECTION_STARTED,
                reason=(
                    "The first clean Risk-Governor-approved candidate was frozen "
                    "through the nontransmitting FakeBroker boundary."
                ),
                report_path=str(report_path),
                report_sha256=source_sha256,
                candidates_evaluated=evaluated,
                selected_symbol=trade.symbol,
                selected_rank=trade.candidate_rank,
                simulation_command_id=trade.simulation_command_id,
                shadow_trade_id=trade.shadow_trade_id,
                selection_policy_recorded_at=(
                    selection_policy.recorded_at
                ),
                selection_policy_version=(
                    selection_policy.selection_policy_version
                ),
                selection_policy_fingerprint=(
                    selection_policy.selection_policy_fingerprint
                ),
            )

        return AutomaticShadowSelectionResult(
            status=SELECTION_NO_ELIGIBLE_CANDIDATE,
            reason=(
                "No candidate passed the existing Risk Governor with complete, "
                "warning-free Shadow evidence; no trade was created."
            ),
            report_path=str(report_path),
            report_sha256=source_sha256,
            candidates_evaluated=evaluated,
            selection_policy_recorded_at=selection_policy.recorded_at,
            selection_policy_version=(
                selection_policy.selection_policy_version
            ),
            selection_policy_fingerprint=(
                selection_policy.selection_policy_fingerprint
            ),
        )


def load_report_object(source_bytes: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The trade-planning report is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("The trade-planning report must contain an object.")
    return payload


def result_for_existing_trade(
    report_path: Path,
    source_sha256: str,
    trade: ShadowTrade,
) -> AutomaticShadowSelectionResult:
    return AutomaticShadowSelectionResult(
        status=SELECTION_ALREADY_PROCESSED,
        reason=(
            "This exact report already has one persisted Shadow Trade; "
            "no additional trade was created."
        ),
        report_path=str(report_path),
        report_sha256=source_sha256,
        candidates_evaluated=0,
        selected_symbol=trade.symbol,
        selected_rank=trade.candidate_rank,
        simulation_command_id=trade.simulation_command_id,
        shadow_trade_id=trade.shadow_trade_id,
        selection_policy_recorded_at=trade.selection_policy_recorded_at,
        selection_policy_version=trade.selection_policy_version,
        selection_policy_fingerprint=trade.selection_policy_fingerprint,
    )


def no_report_result() -> AutomaticShadowSelectionResult:
    return AutomaticShadowSelectionResult(
        status=SELECTION_NO_REPORT,
        reason="No canonical scheduled trade-planning report is available.",
    )
