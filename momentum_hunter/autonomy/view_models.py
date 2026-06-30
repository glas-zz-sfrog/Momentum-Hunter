from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from momentum_hunter.models import Candidate
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import (
    DEFAULT_CAPITAL,
    UNKNOWN_RVOL,
    TradePlan,
    TradePlanRow,
    assign_ranks,
    build_trade_plan_row,
)

from momentum_hunter.autonomy.risk_governor import RiskGovernorResult, SIMULATION_MODE, evaluate_trade_plan


@dataclass(frozen=True)
class LadderRow:
    field: str
    value: str


@dataclass(frozen=True)
class Top5CandidatePlan:
    rank: int
    ticker: str
    company: str
    setup_label: str
    plan_status: str
    gate_state: str
    source_summary: str
    catalyst_summary: str
    chart_summary: str
    trade_plan_id: str
    trade_plan: TradePlan
    risk_result: RiskGovernorResult
    composite_score: int
    risk_on_rank: int = 0
    risk_off_rank: int = 0
    warnings: list[str] = field(default_factory=list)
    source_name: str = "current candidates"
    source_path: str = ""

    @property
    def button_text(self) -> str:
        return (
            f"{self.rank}. {self.ticker} | {self.setup_label}\n"
            f"Plan: {self.plan_status} | Gate: {self.gate_state}"
        )


def build_top5_candidate_plans(
    *,
    report_path: Path | None = None,
    candidates: Iterable[Candidate] | None = None,
    limit: int = 5,
) -> list[Top5CandidatePlan]:
    if report_path is not None and report_path.exists():
        report_plans = build_candidate_plans_from_report(report_path, limit=limit)
        if report_plans:
            return report_plans
    return build_candidate_plans_from_candidates(list(candidates or []), limit=limit)


def build_candidate_plans_from_report(path: Path, *, limit: int = 5) -> list[Top5CandidatePlan]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("top_5_for_capital") or payload.get("candidates") or []
    metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    plans: list[Top5CandidatePlan] = []
    for index, raw in enumerate(rows[:limit], 1):
        if not isinstance(raw, dict):
            continue
        plan = candidate_plan_from_report_row(
            raw,
            rank=index,
            source_name=path.name,
            source_path=str(path),
            source_generated_at=str(metadata.get("generated_at", "")),
        )
        if plan is not None:
            plans.append(plan)
    return plans


def candidate_plan_from_report_row(
    row: dict,
    *,
    rank: int,
    source_name: str,
    source_path: str,
    source_generated_at: str = "",
) -> Top5CandidatePlan | None:
    raw_plan = row.get("trade_plan")
    if not isinstance(raw_plan, dict):
        return None
    try:
        trade_plan = TradePlan(**raw_plan)
    except TypeError:
        return None
    symbol = str(row.get("symbol") or "").upper()
    scoring = row.get("scoring", {}) if isinstance(row.get("scoring"), dict) else {}
    market_data = row.get("market_data", {}) if isinstance(row.get("market_data"), dict) else {}
    catalyst_cluster = str(scoring.get("catalyst_cluster") or "")
    catalyst_summary = str(scoring.get("catalyst_summary") or "No catalyst summary in trade-planning report.")
    composite = int(scoring.get("composite_score") or 0)
    trade_plan_id = stable_trade_plan_id(symbol, trade_plan)
    warnings = list(trade_plan.warnings) + list(trade_plan.blocking_reasons)
    risk_result = evaluate_trade_plan(
        trade_plan,
        ticker=symbol,
        trade_plan_id=trade_plan_id,
        mode=SIMULATION_MODE,
    )
    source_bits = [f"Report: {source_name}", f"Composite: {composite}", f"Readiness: {trade_plan.readiness}"]
    if source_generated_at:
        source_bits.append(f"Generated: {source_generated_at}")
    return Top5CandidatePlan(
        rank=rank,
        ticker=symbol,
        company=str(row.get("company") or ""),
        setup_label=setup_label(catalyst_cluster, trade_plan),
        plan_status=plan_status_text(trade_plan),
        gate_state=risk_result.status,
        source_summary=" | ".join(source_bits),
        catalyst_summary=catalyst_summary,
        chart_summary=chart_summary_from_values(market_data, trade_plan),
        trade_plan_id=trade_plan_id,
        trade_plan=trade_plan,
        risk_result=risk_result,
        composite_score=composite,
        risk_on_rank=int(row.get("fed_event_analysis", {}).get("risk_on_rank") or 0)
        if isinstance(row.get("fed_event_analysis"), dict)
        else 0,
        risk_off_rank=int(row.get("fed_event_analysis", {}).get("risk_off_rank") or 0)
        if isinstance(row.get("fed_event_analysis"), dict)
        else 0,
        warnings=warnings,
        source_name=source_name,
        source_path=source_path,
    )


def build_candidate_plans_from_candidates(candidates: list[Candidate], *, limit: int = 5) -> list[Top5CandidatePlan]:
    if not candidates:
        return []
    capture_date = now_central().date().isoformat()
    rows = [
        build_trade_plan_row(
            candidate,
            capture_date=capture_date,
            capital=DEFAULT_CAPITAL,
            bars=[],
            market_tape=None,
            rvol_type=UNKNOWN_RVOL,
        )
        for candidate in candidates
    ]
    ranked = assign_ranks(sorted(rows, key=lambda row: row.composite_score, reverse=True))
    ordered = sorted(ranked, key=top5_rank_key)[:limit]
    return [candidate_plan_from_trade_row(row, rank=index) for index, row in enumerate(ordered, 1)]


def candidate_plan_from_trade_row(row: TradePlanRow, *, rank: int) -> Top5CandidatePlan:
    trade_plan_id = stable_trade_plan_id(row.symbol, row.trade_plan)
    risk_result = evaluate_trade_plan(row.trade_plan, ticker=row.symbol, trade_plan_id=trade_plan_id)
    warnings = list(row.trade_plan.warnings) + list(row.trade_plan.blocking_reasons)
    return Top5CandidatePlan(
        rank=rank,
        ticker=row.symbol,
        company=row.company,
        setup_label=setup_label(row.catalyst_cluster, row.trade_plan),
        plan_status=plan_status_text(row.trade_plan),
        gate_state=risk_result.status,
        source_summary=(
            f"Current candidate data | Composite: {row.composite_score} | "
            f"Readiness: {row.trade_plan.readiness}"
        ),
        catalyst_summary=row.catalyst_summary or "No catalyst summary available.",
        chart_summary=chart_summary_from_trade_row(row),
        trade_plan_id=trade_plan_id,
        trade_plan=row.trade_plan,
        risk_result=risk_result,
        composite_score=row.composite_score,
        risk_on_rank=row.risk_on_rank,
        risk_off_rank=row.risk_off_rank,
        warnings=warnings,
        source_name="current candidates",
    )


def top5_rank_key(row: TradePlanRow) -> tuple[int, int]:
    return (row.risk_on_rank or row.rank or 999, -row.composite_score)


def stable_trade_plan_id(ticker: str, plan: TradePlan) -> str:
    parts = [
        ticker.upper() or "UNKNOWN",
        format_identity_value(plan.bullish_entry),
        format_identity_value(plan.bullish_stop),
        format_identity_value(plan.bullish_target_1),
        plan.readiness or "UNKNOWN",
    ]
    return "tp-" + "-".join(parts).replace(".", "_").replace(" ", "_")


def setup_label(cluster: str, plan: TradePlan) -> str:
    if cluster:
        return cluster
    if plan.readiness.startswith("EXECUTION_READY"):
        return "Execution-ready setup"
    if plan.blocking_reasons:
        return "Planning setup"
    return "Momentum setup"


def plan_status_text(plan: TradePlan) -> str:
    if required_plan_fields_missing(plan):
        return "Missing fields"
    if plan.readiness.startswith("DO_NOT_TRADE") or plan.blocking_reasons:
        return "Needs review"
    if plan.readiness.startswith("EXECUTION_READY"):
        return "Simulation candidate"
    if plan.warnings:
        return "Needs review"
    return "Draft plan"


def required_plan_fields_missing(plan: TradePlan) -> bool:
    return any(
        value is None
        for value in [
            plan.bullish_entry,
            plan.bullish_stop,
            plan.bullish_target_1,
            plan.risk_reward_ratio,
            plan.estimated_dollar_risk,
        ]
    )


def ladder_rows_for_candidate(candidate: Top5CandidatePlan | None) -> list[LadderRow]:
    if candidate is None:
        return []
    plan = candidate.trade_plan
    return [
        LadderRow("Ticker", candidate.ticker),
        LadderRow("Setup type", candidate.setup_label),
        LadderRow("Entry trigger", entry_trigger_text(plan)),
        LadderRow("Entry/limit", money(plan.bullish_entry)),
        LadderRow("Stop/invalidation", money(plan.bullish_stop)),
        LadderRow("Target 1", money(plan.bullish_target_1)),
        LadderRow("Target 2", money(plan.bullish_target_2)),
        LadderRow("Target 3", "Not modeled by TradePlan v1"),
        LadderRow("Trailing rule", "Manual trailing rule required before paper or live trading."),
        LadderRow("Position size", shares(plan.estimated_shares_for_500)),
        LadderRow("Max dollar risk", money(plan.estimated_dollar_risk)),
        LadderRow("Risk/reward", decimal(plan.risk_reward_ratio)),
        LadderRow("Manual override state", "None. Any future Steven edit requires Risk Governor re-check."),
        LadderRow("Risk Governor status", candidate.risk_result.status),
    ]


def entry_trigger_text(plan: TradePlan) -> str:
    if plan.bullish_entry is None:
        return "Missing entry trigger"
    return f"Break and hold above {money(plan.bullish_entry)} in simulation review."


def chart_summary_from_trade_row(row: TradePlanRow) -> str:
    return chart_summary_from_values(
        {"last_price": row.last_price, "relative_volume": row.relative_volume, "spread_percent": row.spread_percent},
        row.trade_plan,
    )


def chart_summary_from_values(values: dict, plan: TradePlan) -> str:
    return (
        f"Last: {money(values.get('last_price'))} | Entry: {money(plan.bullish_entry)} | "
        f"Stop: {money(plan.bullish_stop)} | RVOL: {decimal(values.get('relative_volume'))} | "
        f"Spread: {decimal(values.get('spread_percent'))}%"
    )


def money(value: object | None) -> str:
    if value is None or value == "":
        return "Missing"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def shares(value: object | None) -> str:
    if value is None or value == "":
        return "Missing"
    try:
        return f"{float(value):,.4f} estimated shares for $500"
    except (TypeError, ValueError):
        return str(value)


def decimal(value: object | None) -> str:
    if value is None or value == "":
        return "Missing"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def format_identity_value(value: object | None) -> str:
    if value is None:
        return "missing"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
