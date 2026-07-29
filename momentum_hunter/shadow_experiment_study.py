from __future__ import annotations

"""Read-only selected-versus-counterfactual study for Shadow experiments."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_trade_experiments import (
    SHADOW_TRADE_EXPERIMENT_MODE,
    SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION,
    ShadowTradeExperimentError,
    load_shadow_trade_experiment,
)
from momentum_hunter.shadow_market_validity import ShadowMarketValidityPolicy
from momentum_hunter.shadow_trading import (
    MIN_MEANINGFUL_SAMPLE_SIZE,
    canonical_json,
    stable_id,
)
from momentum_hunter.trade_planning import parse_datetime


SHADOW_EXPERIMENT_STUDY_SCHEMA_VERSION = 1
SHADOW_EXPERIMENT_STUDY_ENGINE_VERSION = "shadow_experiment_study_v1"
SHADOW_EXPERIMENT_STUDY_MODE = (
    "SHADOW EXPERIMENT STUDY / READ-ONLY / NONTRANSMITTING"
)
SHADOW_EXPERIMENT_STUDIES_DIR = (
    DATA_DIR / "reports" / "shadow-experiment-studies"
)
MIN_DISTINCT_SESSIONS_FOR_STRATEGY_REVIEW = (
    ShadowMarketValidityPolicy().required_distinct_sessions_for_strategy_review
)
MAX_EXPERIMENT_ARTIFACTS = 512
MAX_EXPERIMENT_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_STUDY_BYTES = 8 * 1024 * 1024
SAFE_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
EASTERN_TZ = ZoneInfo("America/New_York")
EXPERIMENT_STATUS_PRIORITY = {
    "EVIDENCE_INVALID": 0,
    "PENDING_OR_UNFILLED": 1,
    "IN_PROGRESS": 2,
    "TERMINAL_INCONCLUSIVE": 3,
    "TERMINAL_BLOCKED": 4,
    "COMPLETE": 5,
}


class ShadowExperimentStudyError(ValueError):
    """Raised when immutable Shadow experiments cannot form a safe study."""


@dataclass(frozen=True)
class ShadowExperimentStudyWrite:
    study_id: str
    json_path: Path
    markdown_path: Path
    created: bool
    source_artifacts_unchanged: bool


def load_shadow_experiment_study(path: Path) -> dict[str, Any]:
    """Load and verify one content-addressed Shadow experiment study."""

    resolved = path.expanduser().resolve()
    try:
        if (
            resolved.is_symlink()
            or not resolved.is_file()
            or resolved.stat().st_size > MAX_STUDY_BYTES
        ):
            raise ShadowExperimentStudyError(
                "Shadow experiment study is not a bounded regular file."
            )
        source = resolved.read_bytes()
    except OSError as exc:
        raise ShadowExperimentStudyError(
            "Shadow experiment study cannot be read."
        ) from exc
    try:
        envelope = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowExperimentStudyError(
            "Shadow experiment study is not valid UTF-8 JSON."
        ) from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("schema_version")
        != SHADOW_EXPERIMENT_STUDY_SCHEMA_VERSION
        or not isinstance(envelope.get("study"), dict)
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment study has an invalid envelope."
        )
    study = dict(envelope["study"])
    _validate_study(study)
    expected_hash = hashlib.sha256(
        canonical_json(study).encode("utf-8")
    ).hexdigest()
    if envelope.get("study_sha256") != expected_hash:
        raise ShadowExperimentStudyError(
            "Shadow experiment study hash is invalid."
        )
    sample_label = _filename_label(
        str(study.get("sample_version") or "no-eligible-sample")
    )
    expected_name = (
        f"shadow-experiment-study-{sample_label}-"
        f"{study['study_id']}.json"
    )
    if resolved.name != expected_name:
        raise ShadowExperimentStudyError(
            "Shadow experiment study filename is invalid."
        )
    return study


def generate_shadow_experiment_study(
    *,
    experiments_dir: Path,
    output_dir: Path = SHADOW_EXPERIMENT_STUDIES_DIR,
    sample_version: str | None = None,
) -> ShadowExperimentStudyWrite:
    """Load immutable experiment files and write one content-addressed study."""

    source_dir = experiments_dir.expanduser().resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise ShadowExperimentStudyError(
            "Shadow experiment source directory does not exist."
        )
    paths = sorted(
        source_dir.glob(
            "shadow-trade-*-shadow-trade-experiment-*.json"
        ),
        key=lambda item: item.name,
    )
    if len(paths) > MAX_EXPERIMENT_ARTIFACTS:
        raise ShadowExperimentStudyError(
            "Shadow experiment source exceeds the bounded artifact limit."
        )
    source_snapshots: dict[Path, bytes] = {}
    experiments: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    for path in paths:
        resolved = path.resolve()
        source = _read_bounded_artifact(resolved)
        source_snapshots[resolved] = source
        try:
            experiment = load_shadow_trade_experiment(resolved)
        except ShadowTradeExperimentError as exc:
            raise ShadowExperimentStudyError(
                f"Invalid Shadow experiment artifact: {resolved.name}."
            ) from exc
        experiments.append(experiment)
        manifest.append(
            {
                "path": str(resolved),
                "sha256": hashlib.sha256(source).hexdigest(),
                "experiment_id": experiment["experiment_id"],
                "shadow_trade_id": experiment["identity"][
                    "shadow_trade_id"
                ],
            }
        )

    study = build_shadow_experiment_study(
        experiments,
        source_manifest=manifest,
        sample_version=sample_version,
    )
    result = write_shadow_experiment_study(
        study,
        output_dir=output_dir,
    )
    _verify_source_snapshots(source_snapshots)
    return ShadowExperimentStudyWrite(
        study_id=result.study_id,
        json_path=result.json_path,
        markdown_path=result.markdown_path,
        created=result.created,
        source_artifacts_unchanged=True,
    )


def build_shadow_experiment_study(
    experiments: Iterable[dict[str, Any]],
    *,
    source_manifest: list[dict[str, Any]],
    sample_version: str | None = None,
) -> dict[str, Any]:
    """Build one gated study from already validated experiment payloads."""

    requested_sample = _optional_label(sample_version, "Sample version")
    items = [dict(item) for item in experiments]
    for experiment in items:
        _require_experiment_shape(experiment)
    selected, superseded = _resolve_trade_snapshots(items)
    manifest_by_experiment = {
        str(item.get("experiment_id") or ""): item
        for item in source_manifest
        if isinstance(item, dict)
    }
    if len(manifest_by_experiment) != len(source_manifest):
        raise ShadowExperimentStudyError(
            "Shadow experiment source manifest has duplicate identities."
        )
    if {
        str(item["experiment_id"]) for item in items
    } != set(manifest_by_experiment):
        raise ShadowExperimentStudyError(
            "Shadow experiment source manifest does not match its artifacts."
        )
    for experiment in items:
        manifest_row = manifest_by_experiment[
            str(experiment["experiment_id"])
        ]
        if str(manifest_row.get("shadow_trade_id") or "") != str(
            experiment["identity"]["shadow_trade_id"]
        ):
            raise ShadowExperimentStudyError(
                "Shadow experiment source manifest has a mismatched trade identity."
            )
    for item in source_manifest:
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256") or "")):
            raise ShadowExperimentStudyError(
                "Shadow experiment source manifest contains an invalid hash."
            )

    eligible_candidates = [
        item
        for item in selected
        if _eligible_for_official_study(item)
    ]
    eligible_versions = {
        str(item["sample_definition"]["sampleVersion"])
        for item in eligible_candidates
    }
    if requested_sample is None:
        if len(eligible_versions) > 1:
            raise ShadowExperimentStudyError(
                "Eligible experiments contain multiple official sample versions."
            )
        active_sample = next(iter(eligible_versions), None)
    else:
        active_sample = requested_sample
    eligible = [
        item
        for item in eligible_candidates
        if item["sample_definition"]["sampleVersion"] == active_sample
    ]
    excluded_other_sample = sum(
        item in eligible_candidates and item not in eligible
        for item in selected
    )
    sessions = {
        _trading_session(item["candidate"]["decision_timestamp"])
        for item in eligible
    }
    gate_satisfied = len(eligible) >= MIN_MEANINGFUL_SAMPLE_SIZE
    strategy_review_eligible = (
        gate_satisfied
        and len(sessions)
        >= MIN_DISTINCT_SESSIONS_FOR_STRATEGY_REVIEW
    )
    metrics_status = (
        "DESCRIPTIVE_AVAILABLE"
        if gate_satisfied
        else "WITHHELD_BELOW_30"
    )
    selected_metrics = (
        _selected_metrics(eligible)
        if gate_satisfied
        else _withheld_selected_metrics(len(eligible))
    )
    comparisons = _counterfactual_comparisons(
        eligible,
        expose_metrics=gate_satisfied,
    )
    status_counts = Counter(
        str(item.get("artifact_status") or "UNKNOWN")
        for item in selected
    )
    integrity_counts = Counter(
        str(item.get("integrity", {}).get("status") or "UNKNOWN")
        for item in selected
    )
    sample_label = active_sample or "NO_ELIGIBLE_SAMPLE"
    manifest_sha256 = hashlib.sha256(
        canonical_json(source_manifest).encode("utf-8")
    ).hexdigest()
    core = {
        "schema_version": SHADOW_EXPERIMENT_STUDY_SCHEMA_VERSION,
        "engine_version": SHADOW_EXPERIMENT_STUDY_ENGINE_VERSION,
        "mode": SHADOW_EXPERIMENT_STUDY_MODE,
        "transmitting": False,
        "broker_request_performed": False,
        "order_action_performed": False,
        "sample_version": active_sample,
        "source_manifest": source_manifest,
        "source_manifest_sha256": manifest_sha256,
        "collection": {
            "artifact_count": len(items),
            "unique_trade_count": len(selected),
            "superseded_snapshot_count": superseded,
            "eligible_completed_count": len(eligible),
            "excluded_other_sample_count": excluded_other_sample,
            "artifact_status_counts": dict(sorted(status_counts.items())),
            "integrity_status_counts": dict(
                sorted(integrity_counts.items())
            ),
        },
        "sample_gate": {
            "minimum_completed": MIN_MEANINGFUL_SAMPLE_SIZE,
            "eligible_completed": len(eligible),
            "gate_satisfied": gate_satisfied,
            "metrics_status": metrics_status,
            "minimum_distinct_sessions_for_strategy_review": (
                MIN_DISTINCT_SESSIONS_FOR_STRATEGY_REVIEW
            ),
            "distinct_trading_sessions": len(sessions),
            "strategy_review_eligible": strategy_review_eligible,
            "strategy_conclusion_authorized": False,
            "trading_authorized": False,
        },
        "availability": _availability(eligible),
        "concentration": _concentration(eligible),
        "selected_results": selected_metrics,
        "paired_counterfactual_comparisons": comparisons,
        "conclusion": _conclusion(
            len(eligible),
            distinct_sessions=len(sessions),
        ),
        "limits": {
            "descriptive_only": True,
            "single_sample_proves_edge": False,
            "changes_scoring_or_selection": False,
            "changes_broker_or_order_behavior": False,
            "strategy_conclusion_authorized": False,
            "trading_authorized": False,
        },
    }
    fingerprint = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return {
        "study_id": stable_id(
            "shadow-experiment-study",
            sample_label,
            fingerprint,
        ),
        "study_fingerprint": fingerprint,
        **core,
    }


def write_shadow_experiment_study(
    study: dict[str, Any],
    *,
    output_dir: Path = SHADOW_EXPERIMENT_STUDIES_DIR,
) -> ShadowExperimentStudyWrite:
    """Persist one immutable study; exact repeats do not rewrite it."""

    _validate_study(study)
    destination = output_dir.expanduser().resolve()
    if destination.exists() and not destination.is_dir():
        raise ShadowExperimentStudyError(
            "Shadow study output path must identify a directory."
        )
    destination.mkdir(parents=True, exist_ok=True)
    sample_label = _filename_label(
        str(study.get("sample_version") or "no-eligible-sample")
    )
    stem = f"shadow-experiment-study-{sample_label}-{study['study_id']}"
    json_path = destination / f"{stem}.json"
    markdown_path = destination / f"{stem}.md"
    envelope = {
        "schema_version": SHADOW_EXPERIMENT_STUDY_SCHEMA_VERSION,
        "study_sha256": hashlib.sha256(
            canonical_json(study).encode("utf-8")
        ).hexdigest(),
        "study": study,
    }
    json_text = json.dumps(
        envelope,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"
    markdown = format_shadow_experiment_study_markdown(study)
    if (
        len(json_text.encode("utf-8")) > MAX_STUDY_BYTES
        or len(markdown.encode("utf-8")) > MAX_STUDY_BYTES
    ):
        raise ShadowExperimentStudyError(
            "Shadow study output exceeds the bounded size limit."
        )
    created = _write_or_require_identical(json_path, json_text)
    _write_or_require_identical(markdown_path, markdown)
    return ShadowExperimentStudyWrite(
        study_id=str(study["study_id"]),
        json_path=json_path,
        markdown_path=markdown_path,
        created=created,
        source_artifacts_unchanged=True,
    )


def format_shadow_experiment_study_markdown(
    study: dict[str, Any],
) -> str:
    collection = study["collection"]
    gate = study["sample_gate"]
    selected = study["selected_results"]
    lines = [
        "# Shadow Experiment Study",
        "",
        f"- Study ID: `{study['study_id']}`",
        f"- Sample: `{study['sample_version'] or 'No eligible sample'}`",
        f"- Mode: `{study['mode']}`",
        f"- Immutable artifacts read: {collection['artifact_count']}",
        f"- Unique Shadow trades: {collection['unique_trade_count']}",
        (
            "- Eligible completed: "
            f"{gate['eligible_completed']} / {gate['minimum_completed']}"
        ),
        (
            "- Distinct sessions: "
            f"{gate['distinct_trading_sessions']} / "
            f"{gate['minimum_distinct_sessions_for_strategy_review']}"
        ),
        f"- Metrics status: `{gate['metrics_status']}`",
        (
            "- Strategy review eligible: "
            f"{str(gate['strategy_review_eligible']).lower()}"
        ),
        "- Strategy conclusion authorized: no",
        "- Trading authorized: no",
        "",
        "## Selected Results",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Completed trades | {selected['completed_count']} |",
        f"| Win rate % | {_display(selected['win_rate_percent'])} |",
        f"| Mean R | {_display(selected['mean_r_multiple'])} |",
        f"| Median R | {_display(selected['median_r_multiple'])} |",
        f"| Executable P&L | {_display(selected['total_executable_pnl'])} |",
        f"| Ideal P&L | {_display(selected['total_ideal_pnl'])} |",
        f"| Execution drag | {_display(selected['ideal_vs_executable_gap'])} |",
        "",
        "## Paired Holding-Window Comparisons",
        "",
        "| Comparison | Pairs | Selected % | Comparison % | Lift pp |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, comparison in study[
        "paired_counterfactual_comparisons"
    ].items():
        lines.append(
            "| {name} | {count} | {selected} | {comparison} | {lift} |".format(
                name=name,
                count=comparison["paired_count"],
                selected=_display(
                    comparison["mean_selected_return_percent"]
                ),
                comparison=_display(
                    comparison["mean_comparison_return_percent"]
                ),
                lift=_display(
                    comparison["mean_lift_percentage_points"]
                ),
            )
        )
    lines.extend(
        [
            "",
            "## Concentration",
            "",
            f"- Symbols: {_format_counts(study['concentration']['symbols'])}",
            f"- Setups: {_format_counts(study['concentration']['setups'])}",
            f"- Catalysts: {_format_counts(study['concentration']['catalysts'])}",
            f"- Market regimes: {_format_counts(study['concentration']['market_regimes'])}",
            "",
            "## Conclusion",
            "",
            str(study["conclusion"]),
            "",
            "This report is descriptive evidence only. It does not modify selection, scoring, risk, broker, or order behavior.",
            "",
        ]
    )
    return "\n".join(lines)


def _resolve_trade_snapshots(
    experiments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_experiment_ids: set[str] = set()
    for item in experiments:
        experiment_id = str(item["experiment_id"])
        if experiment_id in seen_experiment_ids:
            raise ShadowExperimentStudyError(
                "Duplicate experiment identity is present."
            )
        seen_experiment_ids.add(experiment_id)
        grouped[str(item["identity"]["shadow_trade_id"])].append(item)

    selected: list[dict[str, Any]] = []
    superseded = 0
    for trade_id, snapshots in grouped.items():
        completed = [
            item
            for item in snapshots
            if item["artifact_status"] == "COMPLETE"
        ]
        if completed:
            chosen = _resolve_completed_snapshots(
                trade_id,
                completed,
            )
        else:
            ranked = sorted(
                snapshots,
                key=lambda item: (
                    EXPERIMENT_STATUS_PRIORITY.get(
                        str(item.get("artifact_status") or ""),
                        -1,
                    ),
                    _experiment_timestamp(item),
                    str(item["experiment_id"]),
                ),
                reverse=True,
            )
            if (
                len(ranked) > 1
                and _snapshot_rank(ranked[0]) == _snapshot_rank(ranked[1])
            ):
                raise ShadowExperimentStudyError(
                    f"Shadow Trade {trade_id} has ambiguous latest snapshots."
                )
            chosen = ranked[0]
        selected.append(chosen)
        superseded += len(snapshots) - 1
    return (
        sorted(
            selected,
            key=lambda item: (
                str(item["candidate"]["decision_timestamp"]),
                str(item["identity"]["shadow_trade_id"]),
            ),
        ),
        superseded,
    )


def _resolve_completed_snapshots(
    trade_id: str,
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    immutable_fingerprints = {
        hashlib.sha256(
            canonical_json(_completed_immutable_evidence(item)).encode(
                "utf-8"
            )
        ).hexdigest()
        for item in snapshots
    }
    if len(immutable_fingerprints) != 1:
        raise ShadowExperimentStudyError(
            f"Shadow Trade {trade_id} has conflicting final experiment evidence."
        )
    ranked = sorted(
        snapshots,
        key=lambda item: (
            _completed_enrichment_rank(item),
            str(item["experiment_id"]),
        ),
        reverse=True,
    )
    top_rank = _completed_enrichment_rank(ranked[0])
    tied = [
        item
        for item in ranked
        if _completed_enrichment_rank(item) == top_rank
    ]
    if len(tied) > 1:
        enrichment_fingerprints = {
            hashlib.sha256(
                canonical_json(
                    {
                        "selection_experiment": item[
                            "selection_experiment"
                        ],
                        "paper_money_reconciliation": item[
                            "paper_money_reconciliation"
                        ],
                    }
                ).encode("utf-8")
            ).hexdigest()
            for item in tied
        }
        if len(enrichment_fingerprints) != 1:
            raise ShadowExperimentStudyError(
                f"Shadow Trade {trade_id} has ambiguous final enrichment evidence."
            )
    return ranked[0]


def _completed_immutable_evidence(
    experiment: dict[str, Any],
) -> dict[str, Any]:
    source = experiment.get("source_evidence")
    source = source if isinstance(source, dict) else {}
    return {
        "identity": experiment["identity"],
        "frozen_source_evidence": {
            name: source.get(name)
            for name in (
                "frozen_source_path",
                "frozen_source_sha256",
                "frozen_source_generated_at",
                "frozen_capture_path",
                "frozen_capture_time",
            )
        },
        "sample_definition": experiment["sample_definition"],
        "candidate": experiment["candidate"],
        "trade_plan": experiment.get("trade_plan"),
        "risk_governor": experiment.get("risk_governor"),
        "execution": experiment.get("execution"),
        "outcome": experiment.get("outcome"),
        "review_projection": experiment["review_projection"],
    }


def _completed_enrichment_rank(
    experiment: dict[str, Any],
) -> tuple[int, int, int, float]:
    selection = experiment["selection_experiment"]
    paper = experiment.get("paper_money_reconciliation")
    paper = paper if isinstance(paper, dict) else {}
    marks = selection.get("counterfactual_marks")
    available_marks = sum(
        item.get("available") is True
        for item in marks
        if isinstance(item, dict)
    ) if isinstance(marks, list) else 0
    return (
        int(
            selection.get("counterfactual_status")
            == "FINALIZED_TO_SELECTED_TRADE_EXIT"
        ),
        int(paper.get("evidence_status") == "PASS"),
        available_marks,
        _optional_timestamp(paper.get("recorded_at")),
    )


def _optional_timestamp(value: Any) -> float:
    parsed = parse_datetime(str(value or ""))
    if (
        parsed is None
        or parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        return 0.0
    return parsed.timestamp()


def _eligible_for_official_study(experiment: dict[str, Any]) -> bool:
    sample = experiment["sample_definition"]
    return (
        experiment["artifact_status"] == "COMPLETE"
        and experiment["integrity"]["status"] == "PASS"
        and experiment["selection_experiment"]["evidence_status"] == "PASS"
        and experiment["review_projection"]["countsTowardSample"] is True
        and sample["officialSampleAuthorized"] is True
    )


def _selected_metrics(
    experiments: list[dict[str, Any]],
) -> dict[str, Any]:
    outcomes = [item["outcome"] for item in experiments]
    executable = [float(item["executable_pnl"]) for item in outcomes]
    ideal = [float(item["gross_pnl"]) for item in outcomes]
    r_values = [
        float(item["r_multiple"])
        for item in outcomes
        if item.get("r_multiple") is not None
    ]
    wins = sum(item.get("classification") == "WIN" for item in outcomes)
    return {
        "completed_count": len(outcomes),
        "win_rate_percent": round(wins / len(outcomes) * 100, 4),
        "mean_r_multiple": (
            round(mean(r_values), 6) if r_values else None
        ),
        "median_r_multiple": (
            round(median(r_values), 6) if r_values else None
        ),
        "total_executable_pnl": round(sum(executable), 2),
        "total_ideal_pnl": round(sum(ideal), 2),
        "ideal_vs_executable_gap": round(
            sum(ideal) - sum(executable),
            2,
        ),
        "mean_mfe_percent": round(
            mean(float(item["mfe_percent"]) for item in outcomes),
            6,
        ),
        "mean_mae_percent": round(
            mean(float(item["mae_percent"]) for item in outcomes),
            6,
        ),
        "mean_duration_seconds": round(
            mean(float(item["duration_seconds"]) for item in outcomes),
            2,
        ),
    }


def _withheld_selected_metrics(completed_count: int) -> dict[str, Any]:
    return {
        "completed_count": completed_count,
        "win_rate_percent": None,
        "mean_r_multiple": None,
        "median_r_multiple": None,
        "total_executable_pnl": None,
        "total_ideal_pnl": None,
        "ideal_vs_executable_gap": None,
        "mean_mfe_percent": None,
        "mean_mae_percent": None,
        "mean_duration_seconds": None,
    }


def _counterfactual_comparisons(
    experiments: list[dict[str, Any]],
    *,
    expose_metrics: bool,
) -> dict[str, dict[str, Any]]:
    pairs: dict[str, list[tuple[float, float]]] = {
        "DETERMINISTIC_RANDOM_ELIGIBLE": [],
        "OTHER_ELIGIBLE": [],
        "SPY": [],
        "IWM": [],
    }
    for experiment in experiments:
        marks = [
            mark
            for mark in experiment["selection_experiment"][
                "counterfactual_marks"
            ]
            if mark.get("available") is True
            and _finite(mark.get("return_percent")) is not None
        ]
        selected_marks = [
            mark for mark in marks if "SELECTED" in mark.get("roles", [])
        ]
        if len(selected_marks) != 1:
            continue
        selected_return = float(selected_marks[0]["return_percent"])
        random_returns = [
            float(mark["return_percent"])
            for mark in marks
            if "DETERMINISTIC_RANDOM_ELIGIBLE"
            in mark.get("roles", [])
        ]
        other_returns = [
            float(mark["return_percent"])
            for mark in marks
            if "OTHER_ELIGIBLE" in mark.get("roles", [])
        ]
        for name, values in (
            ("DETERMINISTIC_RANDOM_ELIGIBLE", random_returns),
            ("OTHER_ELIGIBLE", other_returns),
        ):
            if values:
                pairs[name].append((selected_return, mean(values)))
        for symbol in ("SPY", "IWM"):
            values = [
                float(mark["return_percent"])
                for mark in marks
                if mark.get("symbol") == symbol
                and "BENCHMARK" in mark.get("roles", [])
            ]
            if values:
                pairs[symbol].append((selected_return, mean(values)))
    return {
        name: _paired_metrics(values, expose=expose_metrics)
        for name, values in pairs.items()
    }


def _paired_metrics(
    pairs: list[tuple[float, float]],
    *,
    expose: bool,
) -> dict[str, Any]:
    if not expose or not pairs:
        return {
            "paired_count": len(pairs),
            "mean_selected_return_percent": None,
            "mean_comparison_return_percent": None,
            "mean_lift_percentage_points": None,
            "median_lift_percentage_points": None,
        }
    selected = [pair[0] for pair in pairs]
    compared = [pair[1] for pair in pairs]
    lift = [
        selected_value - comparison_value
        for selected_value, comparison_value in pairs
    ]
    return {
        "paired_count": len(pairs),
        "mean_selected_return_percent": round(mean(selected), 6),
        "mean_comparison_return_percent": round(mean(compared), 6),
        "mean_lift_percentage_points": round(mean(lift), 6),
        "median_lift_percentage_points": round(median(lift), 6),
    }


def _availability(
    experiments: list[dict[str, Any]],
) -> dict[str, Any]:
    role_counts: Counter[str] = Counter()
    cycles_with_selected = 0
    for experiment in experiments:
        marks = experiment["selection_experiment"][
            "counterfactual_marks"
        ]
        if any(
            mark.get("available") is True
            and "SELECTED" in mark.get("roles", [])
            for mark in marks
        ):
            cycles_with_selected += 1
        for mark in marks:
            if mark.get("available") is True:
                role_counts.update(
                    str(role) for role in mark.get("roles", [])
                )
                if "BENCHMARK" in mark.get("roles", []):
                    role_counts.update([str(mark.get("symbol") or "")])
    return {
        "eligible_cycle_count": len(experiments),
        "cycles_with_selected_holding_window_mark": cycles_with_selected,
        "available_mark_counts": dict(sorted(role_counts.items())),
    }


def _concentration(
    experiments: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    return {
        "symbols": _counts(
            str(item["candidate"].get("symbol") or "Unknown")
            for item in experiments
        ),
        "setups": _counts(
            str(item["candidate"].get("setup") or "Unknown")
            for item in experiments
        ),
        "catalysts": _counts(
            str(item["candidate"].get("catalyst") or "Unknown")
            for item in experiments
        ),
        "market_regimes": _counts(
            str(item["candidate"].get("market_regime") or "Unknown")
            for item in experiments
        ),
        "trading_sessions": _counts(
            _trading_session(item["candidate"]["decision_timestamp"])
            for item in experiments
        ),
    }


def _conclusion(
    eligible_count: int,
    *,
    distinct_sessions: int,
) -> str:
    if eligible_count < MIN_MEANINGFUL_SAMPLE_SIZE:
        return (
            "Evidence collection is in progress. Performance and paired "
            f"comparison metrics remain withheld until "
            f"{MIN_MEANINGFUL_SAMPLE_SIZE} eligible completed trades."
        )
    if distinct_sessions < MIN_DISTINCT_SESSIONS_FOR_STRATEGY_REVIEW:
        return (
            "Descriptive metrics are available, but broader strategy review "
            f"remains blocked until at least "
            f"{MIN_DISTINCT_SESSIONS_FOR_STRATEGY_REVIEW} distinct trading "
            "sessions are represented."
        )
    return (
        "The engineering and session gates permit descriptive strategy "
        "review. This study still does not prove durable edge or authorize "
        "a strategy or trade."
    )


def _require_experiment_shape(experiment: dict[str, Any]) -> None:
    required_objects = (
        "identity",
        "sample_definition",
        "candidate",
        "selection_experiment",
        "review_projection",
        "integrity",
        "research_limits",
    )
    if (
        experiment.get("schema_version")
        != SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION
        or experiment.get("mode") != SHADOW_TRADE_EXPERIMENT_MODE
        or any(
            not isinstance(experiment.get(name), dict)
            for name in required_objects
        )
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment payload is missing its canonical shape."
        )
    if (
        experiment.get("transmitting") is not False
        or experiment.get("broker_request_performed") is not False
        or experiment.get("order_action_performed") is not False
        or experiment["research_limits"].get("trading_authorized")
        is not False
        or experiment["research_limits"].get(
            "single_trade_strategy_conclusion_authorized"
        )
        is not False
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment payload claims prohibited authority."
        )
    if not isinstance(experiment.get("experiment_id"), str):
        raise ShadowExperimentStudyError(
            "Shadow experiment payload has no experiment identity."
        )
    if experiment.get("outcome") is not None and not isinstance(
        experiment.get("outcome"),
        dict,
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment outcome has an invalid shape."
        )


def _validate_study(study: dict[str, Any]) -> None:
    if (
        study.get("schema_version")
        != SHADOW_EXPERIMENT_STUDY_SCHEMA_VERSION
        or study.get("engine_version")
        != SHADOW_EXPERIMENT_STUDY_ENGINE_VERSION
        or study.get("mode") != SHADOW_EXPERIMENT_STUDY_MODE
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment study has an unsupported identity."
        )
    gate = study.get("sample_gate")
    limits = study.get("limits")
    if not isinstance(gate, dict) or not isinstance(limits, dict):
        raise ShadowExperimentStudyError(
            "Shadow experiment study is missing required gates."
        )
    if (
        study.get("transmitting") is not False
        or study.get("broker_request_performed") is not False
        or study.get("order_action_performed") is not False
        or gate.get("strategy_conclusion_authorized") is not False
        or gate.get("trading_authorized") is not False
        or limits.get("strategy_conclusion_authorized") is not False
        or limits.get("trading_authorized") is not False
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment study cannot authorize strategy or trading."
        )
    manifest = study.get("source_manifest")
    if (
        not isinstance(manifest, list)
        or study.get("source_manifest_sha256")
        != hashlib.sha256(
            canonical_json(manifest).encode("utf-8")
        ).hexdigest()
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment study source manifest hash is invalid."
        )
    fingerprint = str(study.get("study_fingerprint") or "")
    core = {
        key: value
        for key, value in study.items()
        if key not in {"study_id", "study_fingerprint"}
    }
    expected_fingerprint = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    sample_label = str(
        study.get("sample_version") or "NO_ELIGIBLE_SAMPLE"
    )
    expected_id = stable_id(
        "shadow-experiment-study",
        sample_label,
        expected_fingerprint,
    )
    if (
        fingerprint != expected_fingerprint
        or study.get("study_id") != expected_id
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment study fingerprint does not match its content."
        )
    gate_satisfied = (
        gate.get("eligible_completed", 0) >= MIN_MEANINGFUL_SAMPLE_SIZE
    )
    if (
        gate.get("minimum_completed") != MIN_MEANINGFUL_SAMPLE_SIZE
        or gate.get(
            "minimum_distinct_sessions_for_strategy_review"
        )
        != MIN_DISTINCT_SESSIONS_FOR_STRATEGY_REVIEW
        or gate.get("gate_satisfied") is not gate_satisfied
        or gate.get("metrics_status")
        != (
            "DESCRIPTIVE_AVAILABLE"
            if gate_satisfied
            else "WITHHELD_BELOW_30"
        )
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment study sample gate is inconsistent."
        )
    selected = study.get("selected_results")
    comparisons = study.get("paired_counterfactual_comparisons")
    if not isinstance(selected, dict) or not isinstance(comparisons, dict):
        raise ShadowExperimentStudyError(
            "Shadow experiment study is missing metrics."
        )
    expected_review_eligible = (
        gate_satisfied
        and gate.get("distinct_trading_sessions", 0)
        >= MIN_DISTINCT_SESSIONS_FOR_STRATEGY_REVIEW
    )
    if (
        gate.get("strategy_review_eligible")
        is not expected_review_eligible
        or selected.get("completed_count")
        != gate.get("eligible_completed")
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment study review gate or completed count is inconsistent."
        )
    if not gate_satisfied and (
        any(
            selected.get(name) is not None
            for name in selected
            if name != "completed_count"
        )
        or any(
            value is not None
            for comparison in comparisons.values()
            for name, value in comparison.items()
            if name != "paired_count"
        )
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment study exposes performance below the sample gate."
        )


def _experiment_timestamp(experiment: dict[str, Any]) -> float:
    outcome = experiment.get("outcome")
    execution = experiment.get("execution", {})
    candidate = experiment.get("candidate", {})
    raw = (
        outcome.get("exit_timestamp")
        if isinstance(outcome, dict)
        else None
    ) or execution.get("last_observation_timestamp") or candidate.get(
        "decision_timestamp"
    )
    parsed = parse_datetime(str(raw or ""))
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShadowExperimentStudyError(
            "Shadow experiment snapshot timestamp is invalid."
        )
    return parsed.timestamp()


def _snapshot_rank(experiment: dict[str, Any]) -> tuple[int, float]:
    return (
        EXPERIMENT_STATUS_PRIORITY.get(
            str(experiment.get("artifact_status") or ""),
            -1,
        ),
        _experiment_timestamp(experiment),
    )


def _trading_session(value: str) -> str:
    parsed = parse_datetime(str(value))
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShadowExperimentStudyError(
            "Shadow experiment decision timestamp must include an offset."
        )
    return parsed.astimezone(EASTERN_TZ).date().isoformat()


def _read_bounded_artifact(path: Path) -> bytes:
    if (
        not path.is_file()
        or path.stat().st_size > MAX_EXPERIMENT_ARTIFACT_BYTES
    ):
        raise ShadowExperimentStudyError(
            "Shadow experiment artifact is not a bounded regular file."
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ShadowExperimentStudyError(
            f"Shadow experiment artifact cannot be read: {type(exc).__name__}."
        ) from exc


def _verify_source_snapshots(snapshots: dict[Path, bytes]) -> None:
    for path, expected in snapshots.items():
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise ShadowExperimentStudyError(
                f"Shadow experiment source changed: {path.name}."
            ) from exc
        if current != expected:
            raise ShadowExperimentStudyError(
                f"Shadow experiment source changed: {path.name}."
            )


def _write_or_require_identical(path: Path, text: str) -> bool:
    if path.exists():
        if (
            not path.is_file()
            or path.stat().st_size > MAX_STUDY_BYTES
            or path.read_text(encoding="utf-8") != text
        ):
            raise ShadowExperimentStudyError(
                f"Existing Shadow study conflicts: {path.name}."
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


def _counts(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _finite(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if numeric == numeric and abs(numeric) != float("inf") else None


def _optional_label(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not SAFE_LABEL_PATTERN.fullmatch(normalized):
        raise ShadowExperimentStudyError(f"{label} is invalid.")
    return normalized


def _filename_label(value: str) -> str:
    normalized = value.strip().lower()
    if not SAFE_LABEL_PATTERN.fullmatch(normalized):
        raise ShadowExperimentStudyError(
            "Shadow study filename label is invalid."
        )
    return normalized


def _display(value: Any) -> str:
    return "Withheld" if value is None else str(value)


def _format_counts(values: dict[str, int]) -> str:
    return ", ".join(
        f"{name}={count}" for name, count in values.items()
    ) or "None"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a read-only selected-versus-counterfactual Shadow study."
        )
    )
    parser.add_argument("--experiments-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SHADOW_EXPERIMENT_STUDIES_DIR,
    )
    parser.add_argument("--sample-version")
    args = parser.parse_args(argv)
    result = generate_shadow_experiment_study(
        experiments_dir=args.experiments_dir,
        output_dir=args.output_dir,
        sample_version=args.sample_version,
    )
    print(
        json.dumps(
            {
                "studyId": result.study_id,
                "jsonPath": str(result.json_path),
                "markdownPath": str(result.markdown_path),
                "created": result.created,
                "sourceArtifactsUnchanged": (
                    result.source_artifacts_unchanged
                ),
                "transmitting": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
