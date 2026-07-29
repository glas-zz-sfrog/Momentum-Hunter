from __future__ import annotations

"""Deterministic per-trade research artifacts for Shadow sample evidence.

The builder reads persisted Shadow state and related evidence, then writes an
immutable JSON/Markdown projection. It has no market-data client, account
binding, credential access, broker action, or order transmission capability.
"""

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_market_validity import DecisionCycleStore
from momentum_hunter.shadow_paper_reconciliation import (
    PAPER_RECONCILIATIONS_DIR,
    PaperMoneyReconciliationRecord,
    load_paper_money_reconciliation,
)
from momentum_hunter.shadow_trading import (
    SHADOW_DECISION_CYCLES_PATH,
    SHADOW_STATE_PATH,
    ShadowStateStore,
    ShadowTrade,
    audit_shadow_trade,
    canonical_json,
    shadow_review_trade_to_dict,
    shadow_sample_metadata_to_dict,
    stable_id,
)


SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION = 1
SHADOW_TRADE_EXPERIMENT_ENGINE_VERSION = "shadow_trade_experiments_v1"
SHADOW_TRADE_EXPERIMENT_MODE = (
    "SHADOW TRADE EXPERIMENT / READ-ONLY / NONTRANSMITTING"
)
SHADOW_TRADE_EXPERIMENTS_DIR = (
    DATA_DIR / "reports" / "shadow-trade-experiments"
)
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_DECISION_CYCLES_BYTES = 16 * 1024 * 1024
MAX_RECONCILIATION_BYTES = 1024 * 1024
MAX_EXPERIMENT_BYTES = 8 * 1024 * 1024
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ShadowTradeExperimentError(ValueError):
    """Raised when a per-trade experiment artifact cannot be proven safely."""


@dataclass(frozen=True)
class ShadowTradeExperimentWrite:
    experiment_id: str
    shadow_trade_id: str
    json_path: Path
    markdown_path: Path
    created: bool
    source_state_unchanged: bool


def load_shadow_trade_experiment(path: Path) -> dict[str, Any]:
    """Load and validate one canonical immutable experiment artifact."""

    resolved = path.expanduser().resolve()
    source = _read_bounded_source(
        resolved,
        maximum_bytes=MAX_EXPERIMENT_BYTES,
        label="Shadow trade experiment",
        required=True,
    )
    assert source is not None
    try:
        envelope = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowTradeExperimentError(
            "Shadow experiment artifact is not valid UTF-8 JSON."
        ) from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("schema_version")
        != SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION
        or not isinstance(envelope.get("experiment"), dict)
    ):
        raise ShadowTradeExperimentError(
            "Shadow experiment artifact has an unsupported envelope."
        )
    experiment = dict(envelope["experiment"])
    _validate_experiment(experiment)
    expected_hash = hashlib.sha256(
        canonical_json(experiment).encode("utf-8")
    ).hexdigest()
    if envelope.get("experiment_sha256") != expected_hash:
        raise ShadowTradeExperimentError(
            "Shadow experiment envelope hash does not match its content."
        )
    expected_name = (
        f"{experiment['identity']['shadow_trade_id']}-"
        f"{experiment['experiment_id']}.json"
    )
    if resolved.name != expected_name:
        raise ShadowTradeExperimentError(
            "Shadow experiment filename does not match its immutable identity."
        )
    return experiment


def generate_shadow_trade_experiment(
    *,
    shadow_trade_id: str,
    state_path: Path = SHADOW_STATE_PATH,
    decision_cycles_path: Path | None = None,
    paper_reconciliation_path: Path | None = None,
    paper_reconciliations_dir: Path | None = None,
    output_dir: Path = SHADOW_TRADE_EXPERIMENTS_DIR,
) -> ShadowTradeExperimentWrite:
    """Build and persist one immutable read-only Shadow experiment snapshot."""

    normalized_trade_id = _safe_identifier(
        shadow_trade_id,
        "Shadow Trade identifier",
    )
    source_state_path = state_path.expanduser().resolve()
    source_state = _read_bounded_source(
        source_state_path,
        maximum_bytes=MAX_STATE_BYTES,
        label="Shadow state",
        required=True,
    )
    state = ShadowStateStore(source_state_path).load()
    matching_trades = [
        trade
        for trade in state.trades
        if trade.shadow_trade_id == normalized_trade_id
    ]
    if len(matching_trades) != 1:
        raise ShadowTradeExperimentError(
            "Shadow state must contain exactly one matching trade."
        )
    trade = matching_trades[0]

    cycle_path = _decision_cycles_path(
        source_state_path,
        decision_cycles_path,
    )
    cycle_source = _read_bounded_source(
        cycle_path,
        maximum_bytes=MAX_DECISION_CYCLES_BYTES,
        label="Shadow decision-cycle evidence",
        required=False,
    )
    cycle = None
    if cycle_source is not None and trade.decision_cycle_id:
        matching_cycles = [
            item
            for item in DecisionCycleStore(cycle_path).load().cycles
            if item.get("cycle_id") == trade.decision_cycle_id
        ]
        if len(matching_cycles) > 1:
            raise ShadowTradeExperimentError(
                "Decision-cycle evidence contains a duplicate linked cycle ID."
            )
        cycle = matching_cycles[0] if matching_cycles else None

    reconciliation_path, reconciliation_source = _reconciliation_source(
        trade,
        state_path=source_state_path,
        supplied=paper_reconciliation_path,
        supplied_dir=paper_reconciliations_dir,
    )
    reconciliation = (
        load_paper_money_reconciliation(reconciliation_path)
        if reconciliation_source is not None
        else None
    )

    source_snapshots = {
        source_state_path: source_state,
        cycle_path: cycle_source,
        reconciliation_path: reconciliation_source,
    }
    experiment = build_shadow_trade_experiment(
        trade,
        source_state_path=source_state_path,
        source_state_sha256=_sha256(source_state),
        decision_cycles_path=cycle_path,
        decision_cycles_sha256=_optional_sha256(cycle_source),
        decision_cycle=cycle,
        paper_reconciliation_path=reconciliation_path,
        paper_reconciliation_sha256=_optional_sha256(
            reconciliation_source
        ),
        paper_reconciliation=reconciliation,
    )
    result = write_shadow_trade_experiment(
        experiment,
        output_dir=output_dir,
    )
    _verify_source_snapshots(source_snapshots)
    return ShadowTradeExperimentWrite(
        experiment_id=result.experiment_id,
        shadow_trade_id=result.shadow_trade_id,
        json_path=result.json_path,
        markdown_path=result.markdown_path,
        created=result.created,
        source_state_unchanged=True,
    )


def build_shadow_trade_experiment(
    trade: ShadowTrade,
    *,
    source_state_path: Path,
    source_state_sha256: str,
    decision_cycles_path: Path,
    decision_cycles_sha256: str | None,
    decision_cycle: dict[str, Any] | None,
    paper_reconciliation_path: Path,
    paper_reconciliation_sha256: str | None,
    paper_reconciliation: PaperMoneyReconciliationRecord | None,
) -> dict[str, Any]:
    """Project canonical evidence without changing any source object or file."""

    if not SAFE_IDENTIFIER_PATTERN.fullmatch(trade.shadow_trade_id):
        raise ShadowTradeExperimentError(
            "Shadow Trade identifier is unsafe for experiment evidence."
        )
    if not re.fullmatch(r"[0-9a-f]{64}", source_state_sha256):
        raise ShadowTradeExperimentError("Shadow state hash is invalid.")

    audit = audit_shadow_trade(trade)
    review = shadow_review_trade_to_dict(
        trade,
        audit,
        sample_definition=trade.sample_metadata,
    )
    cycle_projection, cycle_findings = _decision_cycle_projection(
        trade,
        decision_cycle,
    )
    reconciliation_projection, reconciliation_findings = (
        _paper_reconciliation_projection(
            trade,
            paper_reconciliation,
        )
    )
    integrity_findings = [
        *[
            {
                "source": "shadow_trade_audit",
                "field": finding.field,
                "message": finding.message,
            }
            for finding in audit.findings
        ],
        *[
            {
                "source": "decision_cycle",
                "field": field,
                "message": message,
            }
            for field, message in cycle_findings
        ],
        *[
            {
                "source": "paper_reconciliation",
                "field": field,
                "message": message,
            }
            for field, message in reconciliation_findings
        ],
    ]
    plan = asdict(trade.trade_plan())
    risk = trade.risk_result_payload()
    status = _experiment_status(trade, integrity_findings)
    core = {
        "schema_version": SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION,
        "engine_version": SHADOW_TRADE_EXPERIMENT_ENGINE_VERSION,
        "mode": SHADOW_TRADE_EXPERIMENT_MODE,
        "transmitting": False,
        "broker_request_performed": False,
        "order_action_performed": False,
        "artifact_status": status,
        "identity": {
            "shadow_trade_id": trade.shadow_trade_id,
            "simulation_command_id": trade.simulation_command_id,
            "candidate_id": trade.candidate_id,
            "evidence_snapshot_id": trade.evidence_snapshot_id,
            "trade_plan_id": trade.trade_plan_id,
            "risk_decision_id": trade.risk_decision_id,
            "outcome_id": trade.outcome_id,
            "decision_cycle_id": trade.decision_cycle_id or None,
            "opportunity_id": trade.opportunity_id or None,
        },
        "source_evidence": {
            "state_path": str(source_state_path),
            "state_sha256": source_state_sha256,
            "decision_cycles_path": str(decision_cycles_path),
            "decision_cycles_sha256": decision_cycles_sha256,
            "paper_reconciliation_path": str(paper_reconciliation_path),
            "paper_reconciliation_sha256": (
                paper_reconciliation_sha256
            ),
            "frozen_source_path": trade.evidence.source_path,
            "frozen_source_sha256": trade.evidence.source_sha256,
            "frozen_source_generated_at": (
                trade.evidence.source_generated_at
            ),
            "frozen_capture_path": trade.evidence.source_capture_path,
            "frozen_capture_time": trade.evidence.source_capture_time,
        },
        "sample_definition": shadow_sample_metadata_to_dict(
            trade.sample_metadata
        ),
        "candidate": {
            "symbol": trade.symbol,
            "rank": trade.candidate_rank,
            "score": trade.candidate_score,
            "setup": trade.setup_type or "Unknown",
            "catalyst": trade.catalyst or "Unknown",
            "market_regime": trade.market_regime or "Unknown",
            "decision_timestamp": trade.decision_timestamp,
            "frozen_payload": trade.evidence.candidate_payload(),
        },
        "selection_experiment": cycle_projection,
        "trade_plan": plan,
        "risk_governor": risk,
        "execution": {
            "lifecycle_state": trade.status,
            "data_quality_state": trade.data_quality_state,
            "risk_rejection_reasons": list(
                trade.risk_rejection_reasons
            ),
            "order": asdict(trade.order) if trade.order else None,
            "position": (
                asdict(trade.position) if trade.position else None
            ),
            "ledger_events": [
                event.to_dict() for event in trade.ledger_events
            ],
            "last_observation_timestamp": (
                trade.last_observation_timestamp or None
            ),
            "last_reason": trade.last_reason,
        },
        "outcome": asdict(trade.outcome) if trade.outcome else None,
        "paper_money_reconciliation": reconciliation_projection,
        "review_projection": review,
        "integrity": {
            "status": "PASS" if not integrity_findings else "FAIL",
            "findings": integrity_findings,
            "source_state_mutated": False,
        },
        "research_limits": {
            "counts_toward_official_sample": review[
                "countsTowardSample"
            ],
            "single_trade_strategy_conclusion_authorized": False,
            "trading_authorized": False,
            "conclusion": (
                "This artifact records one prospective Shadow experiment. "
                "It does not authorize a strategy conclusion or a trade."
            ),
        },
    }
    fingerprint = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return {
        "experiment_id": stable_id(
            "shadow-trade-experiment",
            trade.shadow_trade_id,
            fingerprint,
        ),
        "experiment_fingerprint": fingerprint,
        **core,
    }


def write_shadow_trade_experiment(
    experiment: dict[str, Any],
    *,
    output_dir: Path = SHADOW_TRADE_EXPERIMENTS_DIR,
) -> ShadowTradeExperimentWrite:
    """Write an experiment once; identical repeats are idempotent."""

    _validate_experiment(experiment)
    destination = output_dir.expanduser().resolve()
    if destination.exists() and not destination.is_dir():
        raise ShadowTradeExperimentError(
            "Shadow experiment output path must identify a directory."
        )
    destination.mkdir(parents=True, exist_ok=True)
    trade_id = str(experiment["identity"]["shadow_trade_id"])
    experiment_id = str(experiment["experiment_id"])
    stem = f"{trade_id}-{experiment_id}"
    json_path = destination / f"{stem}.json"
    markdown_path = destination / f"{stem}.md"
    envelope = {
        "schema_version": SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION,
        "experiment_sha256": hashlib.sha256(
            canonical_json(experiment).encode("utf-8")
        ).hexdigest(),
        "experiment": experiment,
    }
    json_text = json.dumps(
        envelope,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"
    markdown = format_shadow_trade_experiment_markdown(experiment)
    if (
        len(json_text.encode("utf-8")) > MAX_EXPERIMENT_BYTES
        or len(markdown.encode("utf-8")) > MAX_EXPERIMENT_BYTES
    ):
        raise ShadowTradeExperimentError(
            "Shadow experiment artifact exceeds the bounded size limit."
        )

    created = _write_or_require_identical(json_path, json_text)
    _write_or_require_identical(markdown_path, markdown)
    return ShadowTradeExperimentWrite(
        experiment_id=experiment_id,
        shadow_trade_id=trade_id,
        json_path=json_path,
        markdown_path=markdown_path,
        created=created,
        source_state_unchanged=True,
    )


def format_shadow_trade_experiment_markdown(
    experiment: dict[str, Any],
) -> str:
    identity = experiment["identity"]
    candidate = experiment["candidate"]
    execution = experiment["execution"]
    outcome = experiment["outcome"]
    selection = experiment["selection_experiment"]
    integrity = experiment["integrity"]
    review = experiment["review_projection"]
    lines = [
        f"# Shadow Trade Experiment: {candidate['symbol']}",
        "",
        f"- Experiment ID: `{experiment['experiment_id']}`",
        f"- Shadow Trade ID: `{identity['shadow_trade_id']}`",
        f"- Decision: {candidate['decision_timestamp']}",
        f"- Status: `{experiment['artifact_status']}`",
        f"- Lifecycle: `{execution['lifecycle_state']}`",
        f"- Integrity: `{integrity['status']}`",
        "- Mode: read-only, nontransmitting",
        "- Broker request performed: no",
        "- Order action performed by this report: no",
        "- Trading authorized: no",
        "- Single-trade strategy conclusion authorized: no",
        "",
        "## Frozen Decision",
        "",
        f"- Candidate rank: {candidate['rank']}",
        f"- Candidate score: {candidate['score']}",
        f"- Setup: {candidate['setup']}",
        f"- Catalyst: {candidate['catalyst']}",
        f"- Market regime: {candidate['market_regime']}",
        f"- Risk decision: {review['riskDecision']}",
        f"- Proposed entry: {_display(review['proposedEntry'])}",
        f"- Stop: {_display(review['stop'])}",
        f"- Targets: {', '.join(_display(value) for value in review['targets']) or 'Unavailable'}",
        "",
        "## Prospective Execution And Outcome",
        "",
        f"- Simulated fill: {_display(review['simulatedFill'])}",
        f"- Exit: {_display(review['exit'])}",
        f"- Exit reason: {review['exitReason'] or 'Pending'}",
        f"- Outcome: {review['outcome']}",
        f"- Executable P&L: {_display(review['executablePnl'])}",
        f"- Ideal P&L: {_display(review['idealPnl'])}",
        f"- R multiple: {_display(review['rMultiple'])}",
        f"- MFE dollars: {_display(review['mfeDollars'])}",
        f"- MAE dollars: {_display(review['maeDollars'])}",
        f"- Duration seconds: {_display(review['durationSeconds'])}",
        "",
        "## Selection Experiment",
        "",
        f"- Decision-cycle evidence: `{selection['evidence_status']}`",
        f"- Cycle result: `{selection['cycle_status']}`",
        f"- Eligible candidate count: {selection['eligible_candidate_count']}",
        f"- Counterfactual status: `{selection['counterfactual_status']}`",
        "",
        "| Symbol | Roles | Return % | Measurement | Available |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for mark in selection["counterfactual_marks"]:
        lines.append(
            "| {symbol} | {roles} | {return_percent} | {measurement} | {available} |".format(
                symbol=mark.get("symbol", "Unknown"),
                roles=", ".join(mark.get("roles", [])) or "Unknown",
                return_percent=_display(mark.get("return_percent")),
                measurement=mark.get("measurement", "Unknown"),
                available=(
                    "yes" if mark.get("available") is True else "no"
                ),
            )
        )
    if not selection["counterfactual_marks"]:
        lines.append("| Unavailable | - | - | - | no |")
    lines.extend(
        [
            "",
            "## Integrity",
            "",
        ]
    )
    if integrity["findings"]:
        lines.extend(
            f"- `{item['source']}:{item['field']}` {item['message']}"
            for item in integrity["findings"]
        )
    else:
        lines.append("- PASS: frozen evidence and linked records are consistent.")
    lines.extend(
        [
            "",
            "## Research Limit",
            "",
            experiment["research_limits"]["conclusion"],
            "",
        ]
    )
    return "\n".join(lines)


def _decision_cycle_projection(
    trade: ShadowTrade,
    cycle: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    findings: list[tuple[str, str]] = []
    if not trade.decision_cycle_id:
        if trade.sample_metadata.official_sample_authorized:
            findings.append(
                (
                    "decision_cycle_id",
                    "Official Shadow Trade is missing a decision-cycle identity.",
                )
            )
        return (
            {
                "evidence_status": (
                    "MISSING" if findings else "NOT_APPLICABLE"
                ),
                "cycle_id": None,
                "cycle_status": "NOT_RECORDED",
                "reason": "",
                "decision_at": None,
                "report_sha256": None,
                "selected_symbol": None,
                "eligible_candidate_count": 0,
                "candidate_assessments": [],
                "deterministic_random_eligible": None,
                "benchmark_baselines": {},
                "counterfactual_status": "NOT_RECORDED",
                "counterfactual_horizon_at": None,
                "counterfactual_marks": [],
            },
            findings,
        )
    if cycle is None:
        findings.append(
            (
                "decision_cycle",
                "Linked Shadow decision-cycle evidence is missing.",
            )
        )
        return (
            {
                "evidence_status": "MISSING",
                "cycle_id": trade.decision_cycle_id,
                "cycle_status": "NOT_FOUND",
                "reason": "",
                "decision_at": None,
                "report_sha256": None,
                "selected_symbol": None,
                "eligible_candidate_count": 0,
                "candidate_assessments": [],
                "deterministic_random_eligible": None,
                "benchmark_baselines": {},
                "counterfactual_status": "NOT_RECORDED",
                "counterfactual_horizon_at": None,
                "counterfactual_marks": [],
            },
            findings,
        )

    expected = {
        "cycle_id": trade.decision_cycle_id,
        "shadow_trade_id": trade.shadow_trade_id,
        "selected_symbol": trade.symbol,
        "report_sha256": trade.evidence.source_sha256,
    }
    for field, expected_value in expected.items():
        actual = str(cycle.get(field) or "")
        if actual != expected_value:
            findings.append(
                (
                    field,
                    f"Decision cycle {field} does not match the Shadow Trade.",
                )
            )
    if trade.opportunity_id and str(
        cycle.get("opportunity_id") or ""
    ) != trade.opportunity_id:
        findings.append(
            (
                "opportunity_id",
                "Decision-cycle opportunity does not match the Shadow Trade.",
            )
        )
    assessments = [
        item
        for item in cycle.get("candidate_assessments", [])
        if isinstance(item, dict)
    ]
    marks = [
        item
        for item in cycle.get("counterfactual_marks", [])
        if isinstance(item, dict)
    ]
    return (
        {
            "evidence_status": "PASS" if not findings else "FAIL",
            "cycle_id": str(cycle.get("cycle_id") or ""),
            "cycle_status": str(cycle.get("status") or "UNKNOWN"),
            "reason": str(cycle.get("reason") or ""),
            "decision_at": str(cycle.get("decision_at") or "") or None,
            "report_sha256": (
                str(cycle.get("report_sha256") or "") or None
            ),
            "selected_symbol": (
                str(cycle.get("selected_symbol") or "") or None
            ),
            "eligible_candidate_count": sum(
                item.get("eligible") is True for item in assessments
            ),
            "candidate_assessments": assessments,
            "deterministic_random_eligible": (
                cycle.get("deterministic_random_eligible")
                if isinstance(
                    cycle.get("deterministic_random_eligible"),
                    dict,
                )
                else None
            ),
            "benchmark_baselines": (
                cycle.get("benchmark_baselines")
                if isinstance(cycle.get("benchmark_baselines"), dict)
                else {}
            ),
            "counterfactual_status": str(
                cycle.get("counterfactual_status")
                or "MARK_TO_LATEST"
            ),
            "counterfactual_horizon_at": (
                str(cycle.get("counterfactual_horizon_at") or "")
                or None
            ),
            "counterfactual_marks": marks,
        },
        findings,
    )


def _paper_reconciliation_projection(
    trade: ShadowTrade,
    record: PaperMoneyReconciliationRecord | None,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    if record is None:
        return (
            {
                "evidence_status": "NOT_RECORDED",
                "reconciliation_id": None,
                "recorded_at": None,
                "paper_money_result": None,
                "comparison_status": None,
                "paper_minus_fake_entry_price": None,
                "paper_minus_fake_entry_bps": None,
                "paper_minus_fake_exit_price": None,
                "paper_minus_fake_executable_pnl": None,
                "paper_minus_fake_pnl_per_share": None,
            },
            [],
        )
    findings: list[tuple[str, str]] = []
    for field, expected in {
        "shadow_trade_id": trade.shadow_trade_id,
        "trade_plan_id": trade.trade_plan_id,
        "risk_decision_id": trade.risk_decision_id,
        "evidence_snapshot_id": trade.evidence_snapshot_id,
        "plan_fingerprint": trade.plan_fingerprint,
    }.items():
        if getattr(record, field) != expected:
            findings.append(
                (
                    field,
                    f"paperMoney reconciliation {field} does not match the Shadow Trade.",
                )
            )
    return (
        {
            "evidence_status": "PASS" if not findings else "FAIL",
            "reconciliation_id": record.reconciliation_id,
            "recorded_at": record.recorded_at,
            "paper_money_result": record.paper_money_result,
            "comparison_status": record.comparison_status,
            "paper_minus_fake_entry_price": (
                record.paper_minus_fake_entry_price
            ),
            "paper_minus_fake_entry_bps": (
                record.paper_minus_fake_entry_bps
            ),
            "paper_minus_fake_exit_price": (
                record.paper_minus_fake_exit_price
            ),
            "paper_minus_fake_executable_pnl": (
                record.paper_minus_fake_executable_pnl
            ),
            "paper_minus_fake_pnl_per_share": (
                record.paper_minus_fake_pnl_per_share
            ),
        },
        findings,
    )


def _experiment_status(
    trade: ShadowTrade,
    integrity_findings: list[dict[str, str]],
) -> str:
    if integrity_findings:
        return "EVIDENCE_INVALID"
    if trade.status == "completed" and trade.outcome is not None:
        return "COMPLETE"
    if trade.status in {"blocked", "entry_rejected"}:
        return "TERMINAL_BLOCKED"
    if trade.status in {"cancelled", "ambiguous_exit"}:
        return "TERMINAL_INCONCLUSIVE"
    if trade.status == "pending_entry":
        return "PENDING_OR_UNFILLED"
    return "IN_PROGRESS"


def _decision_cycles_path(
    state_path: Path,
    supplied: Path | None,
) -> Path:
    if supplied is not None:
        return supplied.expanduser().resolve()
    if state_path == SHADOW_STATE_PATH.expanduser().resolve():
        return SHADOW_DECISION_CYCLES_PATH.expanduser().resolve()
    return state_path.with_name(
        f"{state_path.stem}-decision-cycles.json"
    )


def _reconciliation_source(
    trade: ShadowTrade,
    *,
    state_path: Path,
    supplied: Path | None,
    supplied_dir: Path | None = None,
) -> tuple[Path, bytes | None]:
    if supplied is not None and supplied_dir is not None:
        raise ShadowTradeExperimentError(
            "Supply a reconciliation file or directory, not both."
        )
    explicit = supplied is not None
    default_directory = (
        supplied_dir.expanduser().resolve()
        if supplied_dir is not None
        else (
            PAPER_RECONCILIATIONS_DIR
            if state_path == SHADOW_STATE_PATH.expanduser().resolve()
            else state_path.parent / "paper-reconciliations"
        )
    )
    path = (
        supplied.expanduser().resolve()
        if supplied is not None
        else (
            default_directory
            / f"paper-reconciliation-{trade.shadow_trade_id}.json"
        )
        .expanduser()
        .resolve()
    )
    source = _read_bounded_source(
        path,
        maximum_bytes=MAX_RECONCILIATION_BYTES,
        label="paperMoney reconciliation",
        required=explicit,
    )
    return path, source


def _read_bounded_source(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
    required: bool,
) -> bytes | None:
    if not path.exists():
        if required:
            raise ShadowTradeExperimentError(f"{label} does not exist.")
        return None
    if not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ShadowTradeExperimentError(
            f"{label} is not a bounded regular file."
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ShadowTradeExperimentError(
            f"{label} cannot be read: {type(exc).__name__}."
        ) from exc


def _verify_source_snapshots(
    snapshots: dict[Path, bytes | None],
) -> None:
    for path, expected in snapshots.items():
        current = (
            path.read_bytes()
            if path.exists() and path.is_file()
            else None
        )
        if current != expected:
            raise ShadowTradeExperimentError(
                f"Read-only source changed while building evidence: {path.name}."
            )


def _validate_experiment(experiment: dict[str, Any]) -> None:
    if (
        experiment.get("schema_version")
        != SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION
        or experiment.get("engine_version")
        != SHADOW_TRADE_EXPERIMENT_ENGINE_VERSION
        or experiment.get("mode") != SHADOW_TRADE_EXPERIMENT_MODE
    ):
        raise ShadowTradeExperimentError(
            "Shadow experiment has an unsupported identity."
        )
    if (
        experiment.get("transmitting") is not False
        or experiment.get("broker_request_performed") is not False
        or experiment.get("order_action_performed") is not False
    ):
        raise ShadowTradeExperimentError(
            "Shadow experiment cannot claim broker or order activity."
        )
    identity = experiment.get("identity")
    integrity = experiment.get("integrity")
    limits = experiment.get("research_limits")
    if (
        not isinstance(identity, dict)
        or not isinstance(integrity, dict)
        or not isinstance(limits, dict)
    ):
        raise ShadowTradeExperimentError(
            "Shadow experiment is missing required evidence sections."
        )
    _safe_identifier(
        str(identity.get("shadow_trade_id") or ""),
        "Shadow Trade identifier",
    )
    _safe_identifier(
        str(experiment.get("experiment_id") or ""),
        "Experiment identifier",
    )
    if (
        limits.get("single_trade_strategy_conclusion_authorized")
        is not False
        or limits.get("trading_authorized") is not False
    ):
        raise ShadowTradeExperimentError(
            "Shadow experiment cannot authorize conclusions or trading."
        )
    fingerprint = str(experiment.get("experiment_fingerprint") or "")
    without_identity = {
        key: value
        for key, value in experiment.items()
        if key not in {"experiment_id", "experiment_fingerprint"}
    }
    expected_fingerprint = hashlib.sha256(
        canonical_json(without_identity).encode("utf-8")
    ).hexdigest()
    expected_id = stable_id(
        "shadow-trade-experiment",
        str(identity["shadow_trade_id"]),
        expected_fingerprint,
    )
    if fingerprint != expected_fingerprint or experiment[
        "experiment_id"
    ] != expected_id:
        raise ShadowTradeExperimentError(
            "Shadow experiment fingerprint does not match its content."
        )


def _write_or_require_identical(path: Path, text: str) -> bool:
    if path.exists():
        if (
            not path.is_file()
            or path.stat().st_size > MAX_EXPERIMENT_BYTES
            or path.read_text(encoding="utf-8") != text
        ):
            raise ShadowTradeExperimentError(
                f"Existing Shadow experiment artifact conflicts: {path.name}."
            )
        return False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return _write_or_require_identical(path, text)
    return True


def _safe_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not SAFE_IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ShadowTradeExperimentError(f"{label} is invalid.")
    return normalized


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _optional_sha256(value: bytes | None) -> str | None:
    return _sha256(value) if value is not None else None


def _display(value: Any) -> str:
    return "Unavailable" if value is None or value == "" else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write a read-only, nontransmitting Shadow trade experiment report."
        )
    )
    parser.add_argument("--trade-id", required=True)
    parser.add_argument("--state-path", type=Path, default=SHADOW_STATE_PATH)
    parser.add_argument("--decision-cycles-path", type=Path)
    parser.add_argument("--paper-reconciliation-path", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SHADOW_TRADE_EXPERIMENTS_DIR,
    )
    args = parser.parse_args(argv)
    result = generate_shadow_trade_experiment(
        shadow_trade_id=args.trade_id,
        state_path=args.state_path,
        decision_cycles_path=args.decision_cycles_path,
        paper_reconciliation_path=args.paper_reconciliation_path,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "experimentId": result.experiment_id,
                "shadowTradeId": result.shadow_trade_id,
                "jsonPath": str(result.json_path),
                "markdownPath": str(result.markdown_path),
                "created": result.created,
                "sourceStateUnchanged": result.source_state_unchanged,
                "transmitting": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
