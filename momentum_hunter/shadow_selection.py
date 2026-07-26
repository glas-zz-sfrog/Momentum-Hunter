from __future__ import annotations

"""Deterministic, market-valid automatic selection for official Shadow v1."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from momentum_hunter.autonomy.risk_governor import evaluate_trade_plan
from momentum_hunter.autonomy.view_models import (
    candidate_plan_from_report_row,
    stable_trade_plan_id,
)
from momentum_hunter.shadow_market_validity import (
    DecisionCycleStore,
    ShadowMarketValidityPolicy,
    canonical_candidate_rows,
    canonical_json,
    classify_warnings,
    opportunity_identity,
    portfolio_findings,
    report_clock_evidence,
    shadow_constitution_hash,
    stable_hash,
    validate_report_clocks,
    validate_selection_quote,
)
from momentum_hunter.trade_planning import REPORT_SCHEMA_VERSION, parse_datetime
from momentum_hunter.shadow_trading import (
    SHADOW_MODE,
    ShadowStateError,
    ShadowTrade,
    ShadowTradingService,
    audit_shadow_trade,
    expected_shadow_selection_policy_evidence,
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
SELECTION_INVALID_REPORT = "INVALID_REPORT"
SELECTION_DUPLICATE_CAPTURE = "SOURCE_CAPTURE_ALREADY_PROCESSED"
SELECTION_FAILED = "SELECTION_FAILED"


class QuoteSource(Protocol):
    def quote(
        self,
        symbol: str,
        *,
        decision_at: datetime,
    ) -> dict[str, Any] | None: ...


class BatchQuoteSource(Protocol):
    def quotes(
        self,
        symbols: Sequence[str],
        *,
        decision_at: datetime,
    ) -> dict[str, dict[str, Any]]: ...


@dataclass(frozen=True)
class AutomaticShadowSelectionResult:
    status: str
    reason: str
    report_path: str = ""
    report_sha256: str = ""
    decision_cycle_id: str = ""
    candidates_evaluated: int = 0
    selected_symbol: str = ""
    selected_rank: int = 0
    simulation_command_id: str = ""
    shadow_trade_id: str = ""
    opportunity_id: str = ""
    selector_arm_id: str = ""
    constitution_hash: str = ""
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
            "decisionCycleId": self.decision_cycle_id or None,
            "candidatesEvaluated": self.candidates_evaluated,
            "selectedSymbol": self.selected_symbol or None,
            "selectedRank": self.selected_rank or None,
            "simulationCommandId": self.simulation_command_id or None,
            "shadowTradeId": self.shadow_trade_id or None,
            "opportunityId": self.opportunity_id or None,
            "selectorArmId": self.selector_arm_id or None,
            "constitutionHash": self.constitution_hash or None,
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
    """Ranks all candidates, records every reason, then selects at most one."""

    def __init__(
        self,
        service: ShadowTradingService,
        *,
        quote_source: QuoteSource | Callable[..., dict[str, Any] | None],
        decision_store: DecisionCycleStore | None = None,
        market_policy: ShadowMarketValidityPolicy | None = None,
    ) -> None:
        self.service = service
        self.quote_source = quote_source
        self.decision_store = decision_store or service.decision_cycle_store
        self.market_policy = market_policy or ShadowMarketValidityPolicy()

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
        arm = self.service.selector_arm_record()
        if arm is None:
            return AutomaticShadowSelectionResult(
                status=SELECTION_CONSTITUTION_NOT_ARMED,
                reason=(
                    "The official Shadow sample is activated, but no immutable "
                    "selector-arm record exists."
                ),
                report_path=str(report_path),
            )

        source_bytes = report_path.read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        existing_cycle = self.decision_store.find_report(source_sha256)
        if existing_cycle is not None:
            return result_for_existing_cycle(existing_cycle)

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
        identity_findings: list[str] = []
        if report.get("schema_version") != REPORT_SCHEMA_VERSION:
            identity_findings.append(
                "TradePlan report schema version is missing or unsupported."
            )
        if not str(metadata.get("source_provider", "")).strip():
            identity_findings.append(
                "TradePlan report source-provider identity is missing."
            )
        if not str(metadata.get("source_capture_path", "")).strip():
            identity_findings.append(
                "TradePlan report source-capture identity is missing."
            )
        if identity_findings:
            return self._record_terminal_cycle(
                status=SELECTION_INVALID_REPORT,
                reason=" | ".join(identity_findings),
                report_path=report_path,
                report_sha256=source_sha256,
                metadata=metadata,
                decision_at=decision_at,
                arm_id=arm.arm_id,
            )
        if not self.service.is_prospective_official_evidence(
            metadata,
            decision_at=decision_at,
        ):
            return self._record_terminal_cycle(
                status=SELECTION_REPORT_NOT_PROSPECTIVE,
                reason=(
                    "The latest scheduled report predates official sample "
                    "activation; no automatic selection occurred."
                ),
                report_path=report_path,
                report_sha256=source_sha256,
                metadata=metadata,
                decision_at=decision_at,
                arm_id=arm.arm_id,
            )

        clock_findings = validate_report_clocks(
            metadata,
            decision_at=decision_at,
            policy=self.market_policy,
        )
        if clock_findings:
            return self._record_terminal_cycle(
                status=SELECTION_INVALID_REPORT,
                reason=" | ".join(clock_findings),
                report_path=report_path,
                report_sha256=source_sha256,
                metadata=metadata,
                decision_at=decision_at,
                arm_id=arm.arm_id,
            )

        duplicate_capture = self._existing_source_capture_cycle(metadata)
        if duplicate_capture is not None:
            return self._record_terminal_cycle(
                status=SELECTION_DUPLICATE_CAPTURE,
                reason=(
                    "This source capture already has a persisted decision cycle; "
                    "the regenerated report cannot create another trade."
                ),
                report_path=report_path,
                report_sha256=source_sha256,
                metadata=metadata,
                decision_at=decision_at,
                arm_id=arm.arm_id,
            )

        selection_policy = self.service.load_automatic_selection_policy()
        state = self.service.store.load()
        canonical_rows = canonical_candidate_rows(rows)
        quote_symbols = [
            str(row.get("symbol", "")).strip().upper()
            for _, row in canonical_rows
        ]
        quote_symbols.extend(self.market_policy.benchmark_symbols)
        cycle_quotes = self._quotes(
            quote_symbols,
            decision_at=decision_at,
        )
        assessments: list[dict[str, Any]] = []
        for persisted_index, row in canonical_rows:
            symbol = str(row.get("symbol", "")).strip().upper()
            assessments.append(
                self._assess_candidate(
                    row,
                    persisted_index=persisted_index,
                    report_path=report_path,
                    metadata=metadata,
                    decision_at=decision_at,
                    existing_trades=state.trades,
                    quote=cycle_quotes.get(symbol),
                )
            )

        eligible = [
            item for item in assessments if item.get("eligible") is True
        ]
        selected = eligible[0] if eligible else None
        deterministic_random = (
            eligible[int(source_sha256, 16) % len(eligible)] if eligible else None
        )
        benchmarks = {
            symbol: cycle_quotes.get(symbol)
            for symbol in self.market_policy.benchmark_symbols
        }
        cycle_id = stable_hash("shadow-decision-cycle-v1", source_sha256)
        base_cycle = {
            "schema_version": 1,
            "cycle_kind": "DECISION",
            "cycle_id": cycle_id,
            "decision_at": decision_at.isoformat(),
            "updated_at": decision_at.isoformat(),
            "capture_succeeded": True,
            "report_path": str(report_path),
            "report_sha256": source_sha256,
            "source_capture_path": str(metadata.get("source_capture_path", "")),
            "source_capture_time": str(metadata.get("source_capture_time", "")),
            "report_generated_at": str(metadata.get("generated_at", "")),
            "report_schema_version": report.get("schema_version"),
            "source_provider": str(metadata.get("source_provider", "")),
            "clock_evidence": report_clock_evidence(
                metadata,
                decision_at=decision_at,
            ),
            "selector_arm_id": arm.arm_id,
            "constitution_hash": arm.constitution_hash,
            "selection_policy_fingerprint": (
                selection_policy.selection_policy_fingerprint
            ),
            "candidate_assessments": assessments,
            "eligible_candidate_count": len(eligible),
            "deterministic_random_eligible": (
                {
                    "symbol": deterministic_random["symbol"],
                    "canonical_rank": deterministic_random["canonical_rank"],
                }
                if deterministic_random is not None
                else None
            ),
            "benchmark_symbols": list(self.market_policy.benchmark_symbols),
            "benchmark_baselines": benchmarks,
            "market_observations": [],
            "selected_symbol": (
                selected["symbol"] if selected is not None else None
            ),
            "selected_rank": (
                selected["canonical_rank"] if selected is not None else None
            ),
            "opportunity_id": (
                selected["opportunity_id"] if selected is not None else None
            ),
            "selection_quote": (
                selected["quote"] if selected is not None else None
            ),
            "status": (
                "SELECTION_PENDING"
                if selected is not None
                else SELECTION_NO_ELIGIBLE_CANDIDATE
            ),
            "reason": (
                "The highest-ranked eligible candidate passed every frozen gate."
                if selected is not None
                else "No candidate passed every ranking, data, risk, quote, session, duplicate, and portfolio gate."
            ),
            "shadow_trade_id": None,
        }
        self.decision_store.save_cycle(base_cycle)
        if selected is None:
            return AutomaticShadowSelectionResult(
                status=SELECTION_NO_ELIGIBLE_CANDIDATE,
                reason=base_cycle["reason"],
                report_path=str(report_path),
                report_sha256=source_sha256,
                decision_cycle_id=cycle_id,
                candidates_evaluated=len(assessments),
                selector_arm_id=arm.arm_id,
                constitution_hash=arm.constitution_hash,
                selection_policy_recorded_at=selection_policy.recorded_at,
                selection_policy_version=selection_policy.selection_policy_version,
                selection_policy_fingerprint=(
                    selection_policy.selection_policy_fingerprint
                ),
            )

        command_id = stable_id("shadow-auto-report", source_sha256)
        try:
            trade = self.service.start_trade(
                report_path,
                symbol=selected["symbol"],
                simulation_command_id=command_id,
                decision_at=decision_at,
                expected_source_sha256=source_sha256,
                selection_policy_evidence=(
                    expected_shadow_selection_policy_evidence()
                ),
                decision_cycle_id=cycle_id,
                opportunity_id=selected["opportunity_id"],
                selector_arm_id=arm.arm_id,
                constitution_hash=arm.constitution_hash,
                selection_quote_json=canonical_json(selected["quote"]),
            )
            if trade.status == "blocked" or trade.data_quality_state == "BLOCKED":
                raise ShadowStateError(
                    "Market-valid automatic selection produced a blocked Shadow record."
                )
        except Exception as exc:
            self.decision_store.save_cycle(
                {
                    **base_cycle,
                    "status": SELECTION_FAILED,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            raise
        self.decision_store.save_cycle(
            {
                **base_cycle,
                "status": SELECTION_STARTED,
                "reason": (
                    "The highest-ranked market-valid candidate was frozen through "
                    "the nontransmitting FakeBroker boundary."
                ),
                "shadow_trade_id": trade.shadow_trade_id,
            }
        )
        return AutomaticShadowSelectionResult(
            status=SELECTION_STARTED,
            reason=(
                "The highest-ranked market-valid candidate was frozen through "
                "the nontransmitting FakeBroker boundary."
            ),
            report_path=str(report_path),
            report_sha256=source_sha256,
            decision_cycle_id=cycle_id,
            candidates_evaluated=len(assessments),
            selected_symbol=trade.symbol,
            selected_rank=trade.candidate_rank,
            simulation_command_id=trade.simulation_command_id,
            shadow_trade_id=trade.shadow_trade_id,
            opportunity_id=trade.opportunity_id,
            selector_arm_id=trade.selector_arm_id,
            constitution_hash=trade.constitution_hash,
            selection_policy_recorded_at=selection_policy.recorded_at,
            selection_policy_version=selection_policy.selection_policy_version,
            selection_policy_fingerprint=(
                selection_policy.selection_policy_fingerprint
            ),
        )

    def _assess_candidate(
        self,
        row: dict[str, Any],
        *,
        persisted_index: int,
        report_path: Path,
        metadata: dict[str, Any],
        decision_at: datetime,
        existing_trades: tuple[ShadowTrade, ...],
        quote: dict[str, Any] | None,
    ) -> dict[str, Any]:
        canonical_rank = int(row["rank"])
        scoring = row.get("scoring") if isinstance(row.get("scoring"), dict) else {}
        symbol = str(row.get("symbol", "")).strip().upper()
        score = float(scoring["composite_score"])
        candidate = candidate_plan_from_report_row(
            row,
            rank=canonical_rank,
            source_name=report_path.name,
            source_path=str(report_path),
            source_generated_at=str(metadata.get("generated_at", "")),
        )
        reasons: list[str] = []
        fatal_warnings: tuple[str, ...] = ()
        informational_warnings: tuple[str, ...] = ()
        risk_payload: dict[str, Any] = {}
        opportunity_id = ""
        plan_fingerprint = ""
        if candidate is None:
            reasons.append("Candidate does not contain a valid persisted TradePlan.")
        else:
            plan = candidate.trade_plan
            warning_assessment = classify_warnings(
                plan.warnings,
                plan.blocking_reasons,
            )
            fatal_warnings = warning_assessment.fatal
            informational_warnings = warning_assessment.informational
            reasons.extend(fatal_warnings)
            plan_json = canonical_json(asdict(plan))
            plan_fingerprint = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
            opportunity_id = opportunity_identity(
                row,
                plan_fingerprint=plan_fingerprint,
                decision_at=decision_at,
            )
            risk = evaluate_trade_plan(
                plan,
                ticker=symbol,
                trade_plan_id=stable_trade_plan_id(symbol, plan),
                checked_at=decision_at,
            )
            risk_payload = {
                "status": risk.status,
                "allows_simulation": risk.allows_simulation,
                "reasons": list(risk.reasons),
            }
            if not risk.allows_simulation or risk.status != "Simulation-only":
                reasons.extend(risk.reasons or ("Risk Governor did not allow simulation.",))
            try:
                quantity = int(plan.estimated_shares_for_500 or 0)
                entry = float(plan.bullish_entry)
                stop = float(plan.bullish_stop)
                target = float(plan.bullish_target_1)
            except (TypeError, ValueError, OverflowError):
                reasons.append(
                    "TradePlan lacks a positive quantity and numeric entry, stop, or target."
                )
            else:
                reasons.extend(
                    validate_selection_quote(
                        quote,
                        decision_at=decision_at,
                        entry=entry,
                        stop=stop,
                        target=target,
                        quantity=quantity,
                        maximum_spread_percent=self.service.policy.max_spread_percent,
                        buying_power=self.service.policy.buying_power,
                        expected_symbol=symbol,
                        policy=self.market_policy,
                    )
                )
            reasons.extend(
                portfolio_findings(
                    existing_trades,
                    symbol=symbol,
                    opportunity_id=opportunity_id,
                    decision_at=decision_at,
                    daily_loss_limit=self.service.policy.daily_loss_limit,
                )
            )
        reasons = list(dict.fromkeys(str(item) for item in reasons if str(item)))
        quote_at = parse_datetime(
            str(quote.get("timestamp", ""))
            if isinstance(quote, dict)
            else ""
        )
        return {
            "persisted_index": persisted_index,
            "canonical_rank": canonical_rank,
            "composite_score": score,
            "candidate_key": str(row.get("candidate_id") or symbol),
            "symbol": symbol,
            "eligible": not reasons,
            "rejection_reasons": reasons,
            "fatal_warnings": list(fatal_warnings),
            "informational_warnings": list(informational_warnings),
            "risk": risk_payload,
            "quote": quote,
            "quote_source": (
                str(quote.get("source", ""))
                if isinstance(quote, dict)
                else ""
            ),
            "quote_age_seconds": (
                (decision_at - quote_at).total_seconds()
                if quote_at is not None
                and quote_at.tzinfo is not None
                and quote_at.utcoffset() is not None
                else None
            ),
            "opportunity_id": opportunity_id,
            "plan_fingerprint": plan_fingerprint,
        }

    def _quote(
        self,
        symbol: str,
        *,
        decision_at: datetime,
    ) -> dict[str, Any] | None:
        loader = getattr(self.quote_source, "quote", self.quote_source)
        quote = loader(symbol, decision_at=decision_at)
        return dict(quote) if isinstance(quote, dict) else None

    def _quotes(
        self,
        symbols: Sequence[str],
        *,
        decision_at: datetime,
    ) -> dict[str, dict[str, Any]]:
        normalized = tuple(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in symbols
                if str(symbol).strip()
            )
        )
        batch_loader = getattr(self.quote_source, "quotes", None)
        if callable(batch_loader):
            payload = batch_loader(
                normalized,
                decision_at=decision_at,
            )
            if not isinstance(payload, dict):
                raise ValueError("Batch quote source returned an invalid shape.")
            return {
                str(symbol).strip().upper(): dict(quote)
                for symbol, quote in payload.items()
                if isinstance(quote, dict)
            }
        return {
            symbol: quote
            for symbol in normalized
            if (
                quote := self._quote(
                    symbol,
                    decision_at=decision_at,
                )
            )
            is not None
        }

    def _existing_source_capture_cycle(
        self,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        source_key = (
            str(metadata.get("source_capture_path", "")),
            str(metadata.get("source_capture_time", "")),
        )
        return next(
            (
                cycle
                for cycle in self.decision_store.load().cycles
                if (
                    str(cycle.get("source_capture_path", "")),
                    str(cycle.get("source_capture_time", "")),
                )
                == source_key
            ),
            None,
        )

    def _record_terminal_cycle(
        self,
        *,
        status: str,
        reason: str,
        report_path: Path,
        report_sha256: str,
        metadata: dict[str, Any],
        decision_at: datetime,
        arm_id: str,
    ) -> AutomaticShadowSelectionResult:
        cycle_id = stable_hash("shadow-decision-cycle-v1", report_sha256)
        cycle = {
            "schema_version": 1,
            "cycle_kind": "DECISION",
            "cycle_id": cycle_id,
            "decision_at": decision_at.isoformat(),
            "updated_at": decision_at.isoformat(),
            "capture_succeeded": True,
            "report_path": str(report_path),
            "report_sha256": report_sha256,
            "source_capture_path": str(metadata.get("source_capture_path", "")),
            "source_capture_time": str(metadata.get("source_capture_time", "")),
            "report_generated_at": str(metadata.get("generated_at", "")),
            "source_provider": str(metadata.get("source_provider", "")),
            "clock_evidence": report_clock_evidence(
                metadata,
                decision_at=decision_at,
            ),
            "selector_arm_id": arm_id,
            "constitution_hash": shadow_constitution_hash(),
            "candidate_assessments": [],
            "eligible_candidate_count": 0,
            "benchmark_symbols": list(self.market_policy.benchmark_symbols),
            "benchmark_baselines": {},
            "market_observations": [],
            "selected_symbol": None,
            "selected_rank": None,
            "opportunity_id": None,
            "selection_quote": None,
            "status": status,
            "reason": reason,
            "shadow_trade_id": None,
        }
        self.decision_store.save_cycle(cycle)
        return AutomaticShadowSelectionResult(
            status=status,
            reason=reason,
            report_path=str(report_path),
            report_sha256=report_sha256,
            decision_cycle_id=cycle_id,
            selector_arm_id=arm_id,
            constitution_hash=shadow_constitution_hash(),
        )


def load_report_object(source_bytes: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The trade-planning report is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("The trade-planning report must contain an object.")
    return payload


def result_for_existing_cycle(
    cycle: dict[str, Any],
) -> AutomaticShadowSelectionResult:
    return AutomaticShadowSelectionResult(
        status=SELECTION_ALREADY_PROCESSED,
        reason=(
            f"This exact report already has a persisted decision cycle "
            f"({cycle.get('status', 'UNKNOWN')}); no duplicate work occurred."
        ),
        report_path=str(cycle.get("report_path", "")),
        report_sha256=str(cycle.get("report_sha256", "")),
        decision_cycle_id=str(cycle.get("cycle_id", "")),
        candidates_evaluated=len(cycle.get("candidate_assessments", [])),
        selected_symbol=str(cycle.get("selected_symbol") or ""),
        selected_rank=int(cycle.get("selected_rank") or 0),
        shadow_trade_id=str(cycle.get("shadow_trade_id") or ""),
        opportunity_id=str(cycle.get("opportunity_id") or ""),
        selector_arm_id=str(cycle.get("selector_arm_id") or ""),
        constitution_hash=str(cycle.get("constitution_hash") or ""),
    )


def no_report_result() -> AutomaticShadowSelectionResult:
    return AutomaticShadowSelectionResult(
        status=SELECTION_NO_REPORT,
        reason="No canonical scheduled trade-planning report is available.",
    )
