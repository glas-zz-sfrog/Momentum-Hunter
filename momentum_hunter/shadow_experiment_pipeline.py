from __future__ import annotations

"""Coherent read-only batch generation for Shadow experiment evidence."""

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.shadow_experiment_study import (
    SHADOW_EXPERIMENT_STUDIES_DIR,
    ShadowExperimentStudyWrite,
    generate_shadow_experiment_study,
)
from momentum_hunter.shadow_paper_reconciliation import (
    PAPER_RECONCILIATIONS_DIR,
)
from momentum_hunter.shadow_trade_experiments import (
    MAX_DECISION_CYCLES_BYTES,
    MAX_RECONCILIATION_BYTES,
    MAX_STATE_BYTES,
    SHADOW_TRADE_EXPERIMENTS_DIR,
    ShadowTradeExperimentWrite,
    generate_shadow_trade_experiment,
)
from momentum_hunter.shadow_trading import (
    SHADOW_DECISION_CYCLES_PATH,
    SHADOW_SAMPLE_ACTIVATION_PATH,
    SHADOW_STATE_PATH,
    ShadowSampleActivationStore,
    ShadowStateStore,
)


SHADOW_EXPERIMENT_PIPELINE_SCHEMA_VERSION = 1
SHADOW_EXPERIMENT_PIPELINE_ENGINE_VERSION = "shadow_experiment_pipeline_v1"
SHADOW_EXPERIMENT_PIPELINE_MODE = (
    "SHADOW EXPERIMENT PIPELINE / READ-ONLY / NONTRANSMITTING"
)
MAX_ACTIVATION_BYTES = 1024 * 1024


class ShadowExperimentPipelineError(ValueError):
    """Raised when a coherent read-only experiment batch cannot be proven."""


@dataclass(frozen=True)
class ShadowExperimentPipelineResult:
    schema_version: int
    engine_version: str
    mode: str
    status: str
    source_state_path: Path
    source_state_sha256: str | None
    active_sample_version: str | None
    trade_count: int
    experiment_writes: tuple[ShadowTradeExperimentWrite, ...]
    study_write: ShadowExperimentStudyWrite
    transmitting: bool
    broker_request_performed: bool
    order_action_performed: bool
    source_artifacts_unchanged: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "engineVersion": self.engine_version,
            "mode": self.mode,
            "status": self.status,
            "sourceStatePath": str(self.source_state_path),
            "sourceStateSha256": self.source_state_sha256,
            "activeSampleVersion": self.active_sample_version,
            "tradeCount": self.trade_count,
            "experiments": [
                {
                    "experimentId": item.experiment_id,
                    "shadowTradeId": item.shadow_trade_id,
                    "jsonPath": str(item.json_path),
                    "markdownPath": str(item.markdown_path),
                    "created": item.created,
                }
                for item in self.experiment_writes
            ],
            "study": {
                "studyId": self.study_write.study_id,
                "jsonPath": str(self.study_write.json_path),
                "markdownPath": str(self.study_write.markdown_path),
                "created": self.study_write.created,
            },
            "transmitting": self.transmitting,
            "brokerRequestPerformed": self.broker_request_performed,
            "orderActionPerformed": self.order_action_performed,
            "sourceArtifactsUnchanged": self.source_artifacts_unchanged,
        }


def run_shadow_experiment_pipeline(
    *,
    state_path: Path = SHADOW_STATE_PATH,
    decision_cycles_path: Path | None = None,
    experiments_dir: Path = SHADOW_TRADE_EXPERIMENTS_DIR,
    studies_dir: Path = SHADOW_EXPERIMENT_STUDIES_DIR,
) -> ShadowExperimentPipelineResult:
    """Generate all experiment snapshots and one study from a stable source view."""

    source_state_path = state_path.expanduser().resolve()
    store = ShadowStateStore(source_state_path)
    activation_path = _activation_path(source_state_path)
    cycle_path = _decision_cycles_path(
        source_state_path,
        decision_cycles_path,
    )
    if len(
        {source_state_path, activation_path, cycle_path}
    ) != 3:
        raise ShadowExperimentPipelineError(
            "Shadow pipeline source paths must be distinct."
        )
    source_snapshots: dict[Path, bytes | None] = {
        source_state_path: _read_optional_source(
            source_state_path,
            maximum_bytes=MAX_STATE_BYTES,
            label="Shadow state",
        ),
        activation_path: _read_optional_source(
            activation_path,
            maximum_bytes=MAX_ACTIVATION_BYTES,
            label="Shadow sample activation",
        ),
        cycle_path: _read_optional_source(
            cycle_path,
            maximum_bytes=MAX_DECISION_CYCLES_BYTES,
            label="Shadow decision cycles",
        ),
    }
    state = store.load()
    activation = ShadowSampleActivationStore(activation_path).load()
    active_sample_version = _active_sample_version(
        state.trades,
        activation.sample_metadata.sample_version
        if activation is not None
        else None,
    )
    ordered_trades = tuple(
        sorted(
            state.trades,
            key=lambda trade: (
                trade.decision_timestamp,
                trade.shadow_trade_id,
            ),
        )
    )
    for trade in ordered_trades:
        reconciliation_path = _reconciliation_path(
            source_state_path,
            trade.shadow_trade_id,
        )
        source_snapshots[reconciliation_path] = _read_optional_source(
            reconciliation_path,
            maximum_bytes=MAX_RECONCILIATION_BYTES,
            label=f"paperMoney reconciliation for {trade.shadow_trade_id}",
        )

    experiment_output = experiments_dir.expanduser().resolve()
    study_output = studies_dir.expanduser().resolve()
    if experiment_output.exists() and not experiment_output.is_dir():
        raise ShadowExperimentPipelineError(
            "Shadow experiment output path must identify a directory."
        )
    if study_output.exists() and not study_output.is_dir():
        raise ShadowExperimentPipelineError(
            "Shadow study output path must identify a directory."
        )
    experiment_output.mkdir(parents=True, exist_ok=True)
    writes: list[ShadowTradeExperimentWrite] = []
    for trade in ordered_trades:
        writes.append(
            generate_shadow_trade_experiment(
                shadow_trade_id=trade.shadow_trade_id,
                state_path=source_state_path,
                decision_cycles_path=cycle_path,
                output_dir=experiment_output,
            )
        )
        _verify_source_snapshots(source_snapshots)

    _verify_source_snapshots(source_snapshots)
    study = generate_shadow_experiment_study(
        experiments_dir=experiment_output,
        output_dir=study_output,
        sample_version=active_sample_version,
    )
    _verify_source_snapshots(source_snapshots)
    return ShadowExperimentPipelineResult(
        schema_version=SHADOW_EXPERIMENT_PIPELINE_SCHEMA_VERSION,
        engine_version=SHADOW_EXPERIMENT_PIPELINE_ENGINE_VERSION,
        mode=SHADOW_EXPERIMENT_PIPELINE_MODE,
        status=(
            "REPORTS_AND_STUDY_AVAILABLE"
            if ordered_trades
            else "NO_TRADES_STUDY_WITHHELD"
        ),
        source_state_path=source_state_path,
        source_state_sha256=_optional_sha256(
            source_snapshots[source_state_path]
        ),
        active_sample_version=active_sample_version,
        trade_count=len(ordered_trades),
        experiment_writes=tuple(writes),
        study_write=study,
        transmitting=False,
        broker_request_performed=False,
        order_action_performed=False,
        source_artifacts_unchanged=True,
    )


def _active_sample_version(
    trades: tuple[Any, ...],
    activation_sample_version: str | None,
) -> str | None:
    official_versions = {
        trade.sample_metadata.sample_version
        for trade in trades
        if trade.sample_metadata.official_sample_authorized
        and trade.sample_metadata.sample_version
    }
    if activation_sample_version:
        conflicting = official_versions - {activation_sample_version}
        if conflicting:
            raise ShadowExperimentPipelineError(
                "Shadow activation conflicts with persisted official sample versions."
            )
        return activation_sample_version
    if len(official_versions) > 1:
        raise ShadowExperimentPipelineError(
            "Shadow state contains multiple official sample versions without activation."
        )
    return next(iter(official_versions), None)


def _activation_path(state_path: Path) -> Path:
    if state_path == SHADOW_STATE_PATH.expanduser().resolve():
        return SHADOW_SAMPLE_ACTIVATION_PATH.expanduser().resolve()
    return state_path.with_name(
        f"{state_path.stem}-sample-activation.json"
    )


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


def _reconciliation_path(
    state_path: Path,
    shadow_trade_id: str,
) -> Path:
    directory = (
        PAPER_RECONCILIATIONS_DIR.expanduser().resolve()
        if state_path == SHADOW_STATE_PATH.expanduser().resolve()
        else state_path.parent / "paper-reconciliations"
    )
    return directory / f"paper-reconciliation-{shadow_trade_id}.json"


def _read_optional_source(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
) -> bytes | None:
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ShadowExperimentPipelineError(
            f"{label} is not a bounded regular file."
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ShadowExperimentPipelineError(
            f"{label} cannot be read: {type(exc).__name__}."
        ) from exc


def _verify_source_snapshots(
    snapshots: dict[Path, bytes | None],
) -> None:
    for path, expected in snapshots.items():
        try:
            current = (
                path.read_bytes()
                if path.exists() and path.is_file()
                else None
            )
        except OSError as exc:
            raise ShadowExperimentPipelineError(
                f"Read-only source changed during the batch: {path.name}."
            ) from exc
        if current != expected:
            raise ShadowExperimentPipelineError(
                f"Read-only source changed during the batch: {path.name}."
            )


def _optional_sha256(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate coherent read-only Shadow experiment and study evidence."
        )
    )
    parser.add_argument("--state-path", type=Path, default=SHADOW_STATE_PATH)
    parser.add_argument("--decision-cycles-path", type=Path)
    parser.add_argument(
        "--experiments-dir",
        type=Path,
        default=SHADOW_TRADE_EXPERIMENTS_DIR,
    )
    parser.add_argument(
        "--studies-dir",
        type=Path,
        default=SHADOW_EXPERIMENT_STUDIES_DIR,
    )
    args = parser.parse_args(argv)
    result = run_shadow_experiment_pipeline(
        state_path=args.state_path,
        decision_cycles_path=args.decision_cycles_path,
        experiments_dir=args.experiments_dir,
        studies_dir=args.studies_dir,
    )
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
