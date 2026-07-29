from __future__ import annotations

"""Idempotent automation for terminal Shadow experiment evidence."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_experiment_pipeline import (
    ShadowExperimentPipelineResult,
    run_shadow_experiment_pipeline,
)
from momentum_hunter.shadow_experiment_study import (
    MAX_STUDY_BYTES,
    load_shadow_experiment_study,
)
from momentum_hunter.shadow_market_validity import (
    SHADOW_DECISION_CYCLE_SCHEMA_VERSION,
)
from momentum_hunter.shadow_paper_reconciliation import (
    MAX_RECONCILIATION_BYTES,
    PAPER_RECONCILIATIONS_DIR,
)
from momentum_hunter.shadow_trade_experiments import (
    MAX_DECISION_CYCLES_BYTES,
    MAX_EXPERIMENT_BYTES,
    MAX_STATE_BYTES,
    load_shadow_trade_experiment,
)
from momentum_hunter.shadow_trading import (
    SHADOW_DECISION_CYCLES_PATH,
    SHADOW_SCHEMA_VERSION,
    SHADOW_STATE_PATH,
    TERMINAL_TRADE_STATES,
    canonical_json,
    shadow_state_from_dict,
    shadow_trade_to_dict,
    stable_id,
)


SHADOW_EXPERIMENT_AUTOMATION_SCHEMA_VERSION = 1
SHADOW_EXPERIMENT_AUTOMATION_ENGINE_VERSION = (
    "shadow_experiment_automation_v1"
)
SHADOW_EXPERIMENT_AUTOMATION_MODE = (
    "SHADOW EXPERIMENT AUTOMATION / READ-ONLY / NONTRANSMITTING"
)
SHADOW_EXPERIMENT_AUTOMATION_RECEIPTS_DIR = (
    DATA_DIR / "reports" / "shadow-experiment-automation-receipts"
)
MAX_AUTOMATION_RECEIPT_BYTES = 1024 * 1024


class ShadowExperimentAutomationError(ValueError):
    """Raised when terminal experiment evidence cannot be automated safely."""


@dataclass(frozen=True)
class ShadowExperimentAutomationResult:
    schema_version: int
    engine_version: str
    mode: str
    status: str
    terminal_trade_count: int
    terminal_trade_ids: tuple[str, ...]
    terminal_evidence_fingerprint: str | None
    receipt_id: str | None
    receipt_path: Path | None
    receipt_created: bool
    pipeline_status: str | None
    experiment_ids: tuple[str, ...]
    study_id: str | None
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
            "terminalTradeCount": self.terminal_trade_count,
            "terminalTradeIds": list(self.terminal_trade_ids),
            "terminalEvidenceFingerprint": (
                self.terminal_evidence_fingerprint
            ),
            "receiptId": self.receipt_id,
            "receiptPath": (
                str(self.receipt_path)
                if self.receipt_path is not None
                else None
            ),
            "receiptCreated": self.receipt_created,
            "pipelineStatus": self.pipeline_status,
            "experimentIds": list(self.experiment_ids),
            "studyId": self.study_id,
            "transmitting": self.transmitting,
            "brokerRequestPerformed": self.broker_request_performed,
            "orderActionPerformed": self.order_action_performed,
            "sourceArtifactsUnchanged": self.source_artifacts_unchanged,
        }


@dataclass(frozen=True)
class _TerminalEvidence:
    terminal_trade_ids: tuple[str, ...]
    fingerprint: str | None
    source_snapshots: Mapping[Path, bytes | None]


def automate_shadow_experiment_evidence(
    *,
    state_path: Path = SHADOW_STATE_PATH,
    decision_cycles_path: Path | None = None,
    experiments_dir: Path,
    studies_dir: Path,
    receipts_dir: Path = SHADOW_EXPERIMENT_AUTOMATION_RECEIPTS_DIR,
) -> ShadowExperimentAutomationResult:
    """Generate experiment evidence once per terminal-evidence fingerprint."""

    source_state_path = state_path.expanduser().resolve()
    cycle_path = _decision_cycles_path(
        source_state_path,
        decision_cycles_path,
    )
    terminal = _terminal_evidence(source_state_path, cycle_path)
    if not terminal.terminal_trade_ids:
        _verify_source_snapshots(terminal.source_snapshots)
        return _result(
            status="NO_TERMINAL_TRADES",
            terminal=terminal,
        )

    assert terminal.fingerprint is not None
    receipt_id = stable_id(
        "shadow-experiment-automation",
        terminal.fingerprint,
    )
    receipt_path = _receipt_path(receipts_dir, receipt_id)
    if receipt_path.exists():
        receipt = load_shadow_experiment_automation_receipt(receipt_path)
        _require_matching_receipt(
            receipt,
            receipt_id=receipt_id,
            terminal=terminal,
        )
        _verify_receipt_artifacts(
            receipt,
            experiments_dir=experiments_dir,
            studies_dir=studies_dir,
        )
        _verify_source_snapshots(terminal.source_snapshots)
        return _result(
            status="UP_TO_DATE",
            terminal=terminal,
            receipt=receipt,
            receipt_path=receipt_path,
        )

    pipeline = run_shadow_experiment_pipeline(
        state_path=source_state_path,
        decision_cycles_path=cycle_path,
        experiments_dir=experiments_dir,
        studies_dir=studies_dir,
    )
    _verify_pipeline_terminal_coverage(
        pipeline,
        terminal.terminal_trade_ids,
    )
    _verify_source_snapshots(terminal.source_snapshots)
    current_terminal = _terminal_evidence(source_state_path, cycle_path)
    if (
        current_terminal.fingerprint != terminal.fingerprint
        or current_terminal.terminal_trade_ids
        != terminal.terminal_trade_ids
    ):
        raise ShadowExperimentAutomationError(
            "Terminal Shadow evidence changed during automation."
        )
    _verify_source_snapshots(current_terminal.source_snapshots)

    receipt = _build_receipt(
        receipt_id=receipt_id,
        terminal=terminal,
        pipeline=pipeline,
    )
    created = _write_receipt_once(receipt_path, receipt)
    persisted = load_shadow_experiment_automation_receipt(receipt_path)
    if persisted != receipt:
        raise ShadowExperimentAutomationError(
            "Persisted Shadow experiment automation receipt changed."
        )
    _verify_receipt_artifacts(
        persisted,
        experiments_dir=experiments_dir,
        studies_dir=studies_dir,
    )
    _verify_source_snapshots(current_terminal.source_snapshots)
    return _result(
        status="EVIDENCE_GENERATED" if created else "UP_TO_DATE",
        terminal=terminal,
        receipt=persisted,
        receipt_path=receipt_path,
        receipt_created=created,
    )


def load_shadow_experiment_automation_receipt(
    path: Path,
) -> dict[str, Any]:
    """Load and verify one content-addressed automation receipt."""

    resolved = path.expanduser().resolve()
    source = _read_bounded_source(
        resolved,
        maximum_bytes=MAX_AUTOMATION_RECEIPT_BYTES,
        label="Shadow experiment automation receipt",
        required=True,
    )
    assert source is not None
    try:
        envelope = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt is not valid UTF-8 JSON."
        ) from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("schema_version")
        != SHADOW_EXPERIMENT_AUTOMATION_SCHEMA_VERSION
        or not isinstance(envelope.get("receipt"), dict)
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt has an invalid envelope."
        )
    receipt = dict(envelope["receipt"])
    _validate_receipt(receipt)
    expected_hash = hashlib.sha256(
        canonical_json(receipt).encode("utf-8")
    ).hexdigest()
    if envelope.get("receipt_sha256") != expected_hash:
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt hash is invalid."
        )
    expected_name = (
        "shadow-experiment-automation-"
        f"{receipt['receipt_id']}.json"
    )
    if resolved.name != expected_name:
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt filename is invalid."
        )
    return receipt


def _terminal_evidence(
    state_path: Path,
    decision_cycles_path: Path,
) -> _TerminalEvidence:
    state_source = _read_bounded_source(
        state_path,
        maximum_bytes=MAX_STATE_BYTES,
        label="Shadow state",
        required=False,
    )
    cycle_source = _read_bounded_source(
        decision_cycles_path,
        maximum_bytes=MAX_DECISION_CYCLES_BYTES,
        label="Shadow decision-cycle evidence",
        required=False,
    )
    snapshots: dict[Path, bytes | None] = {
        state_path: state_source,
        decision_cycles_path: cycle_source,
    }
    if state_source is None:
        return _TerminalEvidence((), None, snapshots)

    state_payload = _json_mapping(
        state_source,
        "Shadow state",
    )
    if state_payload.get("schema_version") != SHADOW_SCHEMA_VERSION:
        raise ShadowExperimentAutomationError(
            "Shadow state has an unsupported schema."
        )
    try:
        state = shadow_state_from_dict(state_payload)
    except (TypeError, ValueError) as exc:
        raise ShadowExperimentAutomationError(
            "Shadow state cannot be validated for experiment automation."
        ) from exc
    cycles = _decision_cycles(cycle_source)
    by_cycle_id: dict[str, list[dict[str, Any]]] = {}
    for cycle in cycles:
        cycle_id = str(cycle.get("cycle_id") or "")
        if cycle_id:
            by_cycle_id.setdefault(cycle_id, []).append(cycle)

    projections: list[dict[str, Any]] = []
    terminal_ids: list[str] = []
    for trade in sorted(
        (
            item
            for item in state.trades
            if item.status in TERMINAL_TRADE_STATES
        ),
        key=lambda item: (
            item.decision_timestamp,
            item.shadow_trade_id,
        ),
    ):
        linked_cycles = (
            by_cycle_id.get(trade.decision_cycle_id, [])
            if trade.decision_cycle_id
            else []
        )
        if len(linked_cycles) > 1:
            raise ShadowExperimentAutomationError(
                "Decision-cycle evidence contains a duplicate linked cycle ID."
            )
        reconciliation_path = _reconciliation_path(
            state_path,
            trade.shadow_trade_id,
        )
        reconciliation_source = _read_bounded_source(
            reconciliation_path,
            maximum_bytes=MAX_RECONCILIATION_BYTES,
            label=(
                "paperMoney reconciliation for "
                f"{trade.shadow_trade_id}"
            ),
            required=False,
        )
        snapshots[reconciliation_path] = reconciliation_source
        terminal_ids.append(trade.shadow_trade_id)
        projections.append(
            {
                "trade": shadow_trade_to_dict(trade),
                "decisionCycle": (
                    linked_cycles[0] if linked_cycles else None
                ),
                "paperReconciliationSha256": _optional_sha256(
                    reconciliation_source
                ),
            }
        )
    if not terminal_ids:
        return _TerminalEvidence((), None, snapshots)
    fingerprint = hashlib.sha256(
        canonical_json(
            {
                "schemaVersion": 1,
                "terminalTrades": projections,
            }
        ).encode("utf-8")
    ).hexdigest()
    return _TerminalEvidence(
        tuple(terminal_ids),
        fingerprint,
        snapshots,
    )


def _decision_cycles(source: bytes | None) -> tuple[dict[str, Any], ...]:
    if source is None:
        return ()
    payload = _json_mapping(source, "Shadow decision-cycle evidence")
    raw_cycles = payload.get("cycles")
    if (
        payload.get("schema_version")
        != SHADOW_DECISION_CYCLE_SCHEMA_VERSION
        or not isinstance(raw_cycles, list)
        or any(not isinstance(item, dict) for item in raw_cycles)
    ):
        raise ShadowExperimentAutomationError(
            "Shadow decision-cycle evidence has an invalid schema."
        )
    return tuple(dict(item) for item in raw_cycles)


def _verify_pipeline_terminal_coverage(
    pipeline: ShadowExperimentPipelineResult,
    terminal_trade_ids: tuple[str, ...],
) -> None:
    writes = {
        item.shadow_trade_id: item
        for item in pipeline.experiment_writes
    }
    if any(
        trade_id not in writes
        for trade_id in terminal_trade_ids
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment pipeline omitted a terminal trade."
        )
    for trade_id in terminal_trade_ids:
        experiment = load_shadow_trade_experiment(
            writes[trade_id].json_path
        )
        if (
            experiment["identity"]["shadow_trade_id"] != trade_id
            or experiment["artifact_status"]
            not in {
                "COMPLETE",
                "TERMINAL_BLOCKED",
                "TERMINAL_INCONCLUSIVE",
                "EVIDENCE_INVALID",
            }
        ):
            raise ShadowExperimentAutomationError(
                "Shadow experiment pipeline produced invalid terminal evidence."
            )
    if (
        pipeline.transmitting
        or pipeline.broker_request_performed
        or pipeline.order_action_performed
        or not pipeline.source_artifacts_unchanged
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment pipeline violated its read-only boundary."
        )


def _build_receipt(
    *,
    receipt_id: str,
    terminal: _TerminalEvidence,
    pipeline: ShadowExperimentPipelineResult,
) -> dict[str, Any]:
    assert terminal.fingerprint is not None
    return {
        "schema_version": SHADOW_EXPERIMENT_AUTOMATION_SCHEMA_VERSION,
        "engine_version": SHADOW_EXPERIMENT_AUTOMATION_ENGINE_VERSION,
        "mode": SHADOW_EXPERIMENT_AUTOMATION_MODE,
        "receipt_id": receipt_id,
        "terminal_evidence_fingerprint": terminal.fingerprint,
        "terminal_trade_count": len(terminal.terminal_trade_ids),
        "terminal_trade_ids": list(terminal.terminal_trade_ids),
        "pipeline_status": pipeline.status,
        "pipeline_source_state_sha256": (
            pipeline.source_state_sha256
        ),
        "experiment_artifacts": [
            {
                "experiment_id": item.experiment_id,
                "shadow_trade_id": item.shadow_trade_id,
                "json_path": str(item.json_path),
                "json_sha256": _file_sha256(
                    item.json_path,
                    maximum_bytes=MAX_EXPERIMENT_BYTES,
                    label="Shadow trade experiment JSON",
                ),
                "markdown_path": str(item.markdown_path),
                "markdown_sha256": _file_sha256(
                    item.markdown_path,
                    maximum_bytes=MAX_EXPERIMENT_BYTES,
                    label="Shadow trade experiment Markdown",
                ),
            }
            for item in pipeline.experiment_writes
        ],
        "study_artifact": {
            "study_id": pipeline.study_write.study_id,
            "json_path": str(pipeline.study_write.json_path),
            "json_sha256": _file_sha256(
                pipeline.study_write.json_path,
                maximum_bytes=MAX_STUDY_BYTES,
                label="Shadow experiment study JSON",
            ),
            "markdown_path": str(
                pipeline.study_write.markdown_path
            ),
            "markdown_sha256": _file_sha256(
                pipeline.study_write.markdown_path,
                maximum_bytes=MAX_STUDY_BYTES,
                label="Shadow experiment study Markdown",
            ),
        },
        "transmitting": False,
        "broker_request_performed": False,
        "order_action_performed": False,
        "source_artifacts_unchanged": True,
    }


def _validate_receipt(receipt: dict[str, Any]) -> None:
    if (
        receipt.get("schema_version")
        != SHADOW_EXPERIMENT_AUTOMATION_SCHEMA_VERSION
        or receipt.get("engine_version")
        != SHADOW_EXPERIMENT_AUTOMATION_ENGINE_VERSION
        or receipt.get("mode") != SHADOW_EXPERIMENT_AUTOMATION_MODE
        or receipt.get("transmitting") is not False
        or receipt.get("broker_request_performed") is not False
        or receipt.get("order_action_performed") is not False
        or receipt.get("source_artifacts_unchanged") is not True
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt violates its boundary."
        )
    terminal_ids = receipt.get("terminal_trade_ids")
    experiment_artifacts = receipt.get("experiment_artifacts")
    study_artifact = receipt.get("study_artifact")
    fingerprint = str(
        receipt.get("terminal_evidence_fingerprint") or ""
    )
    if (
        not isinstance(terminal_ids, list)
        or not terminal_ids
        or any(
            not isinstance(item, str) or not item
            for item in terminal_ids
        )
        or len(set(terminal_ids)) != len(terminal_ids)
        or receipt.get("terminal_trade_count") != len(terminal_ids)
        or not isinstance(experiment_artifacts, list)
        or any(
            not isinstance(item, dict)
            or not str(item.get("experiment_id") or "")
            or not str(item.get("shadow_trade_id") or "")
            or not str(item.get("json_path") or "")
            or not _is_sha256(
                str(item.get("json_sha256") or "")
            )
            or not str(item.get("markdown_path") or "")
            or not _is_sha256(
                str(item.get("markdown_sha256") or "")
            )
            for item in experiment_artifacts
        )
        or not isinstance(study_artifact, dict)
        or not str(study_artifact.get("study_id") or "")
        or not str(study_artifact.get("json_path") or "")
        or not _is_sha256(
            str(study_artifact.get("json_sha256") or "")
        )
        or not str(study_artifact.get("markdown_path") or "")
        or not _is_sha256(
            str(study_artifact.get("markdown_sha256") or "")
        )
        or not _is_sha256(fingerprint)
        or not str(receipt.get("pipeline_status") or "")
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt is incomplete."
        )
    expected_id = stable_id(
        "shadow-experiment-automation",
        fingerprint,
    )
    if receipt.get("receipt_id") != expected_id:
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt identity is invalid."
        )


def _verify_receipt_artifacts(
    receipt: dict[str, Any],
    *,
    experiments_dir: Path,
    studies_dir: Path,
) -> None:
    expected_experiments_dir = experiments_dir.expanduser().resolve()
    expected_studies_dir = studies_dir.expanduser().resolve()
    covered_trade_ids: set[str] = set()
    for item in receipt["experiment_artifacts"]:
        json_path = Path(str(item["json_path"])).expanduser().resolve()
        markdown_path = Path(
            str(item["markdown_path"])
        ).expanduser().resolve()
        if (
            json_path.parent != expected_experiments_dir
            or markdown_path.parent != expected_experiments_dir
            or json_path.stem != markdown_path.stem
        ):
            raise ShadowExperimentAutomationError(
                "Shadow experiment automation receipt references "
                "an artifact outside its configured directory."
            )
        _require_file_sha256(
            json_path,
            str(item["json_sha256"]),
            label="Shadow trade experiment JSON",
            maximum_bytes=MAX_EXPERIMENT_BYTES,
        )
        experiment = load_shadow_trade_experiment(json_path)
        trade_id = str(
            experiment["identity"]["shadow_trade_id"]
        )
        if (
            experiment["experiment_id"] != item["experiment_id"]
            or trade_id != item["shadow_trade_id"]
        ):
            raise ShadowExperimentAutomationError(
                "Shadow experiment automation receipt references "
                "the wrong experiment artifact."
            )
        _require_file_sha256(
            markdown_path,
            str(item["markdown_sha256"]),
            label="Shadow trade experiment Markdown",
            maximum_bytes=MAX_EXPERIMENT_BYTES,
        )
        covered_trade_ids.add(trade_id)
    if any(
        trade_id not in covered_trade_ids
        for trade_id in receipt["terminal_trade_ids"]
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt omits terminal evidence."
        )

    study_item = receipt["study_artifact"]
    study_path = Path(
        str(study_item["json_path"])
    ).expanduser().resolve()
    study_markdown_path = Path(
        str(study_item["markdown_path"])
    ).expanduser().resolve()
    if (
        study_path.parent != expected_studies_dir
        or study_markdown_path.parent != expected_studies_dir
        or study_path.stem != study_markdown_path.stem
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt references "
            "a study outside its configured directory."
        )
    _require_file_sha256(
        study_path,
        str(study_item["json_sha256"]),
        label="Shadow experiment study JSON",
        maximum_bytes=MAX_STUDY_BYTES,
    )
    study = load_shadow_experiment_study(study_path)
    if study["study_id"] != study_item["study_id"]:
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt references "
            "the wrong study artifact."
        )
    _require_file_sha256(
        study_markdown_path,
        str(study_item["markdown_sha256"]),
        label="Shadow experiment study Markdown",
        maximum_bytes=MAX_STUDY_BYTES,
    )


def _require_file_sha256(
    path: Path,
    expected: str,
    *,
    label: str,
    maximum_bytes: int,
) -> None:
    try:
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > maximum_bytes
        ):
            raise ShadowExperimentAutomationError(
                f"{label} is missing or invalid."
            )
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ShadowExperimentAutomationError(
                f"{label} is missing or invalid."
            )
    except OSError as exc:
        raise ShadowExperimentAutomationError(
            f"{label} cannot be read."
        ) from exc


def _file_sha256(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
) -> str:
    resolved = path.expanduser().resolve()
    try:
        if (
            resolved.is_symlink()
            or not resolved.is_file()
            or resolved.stat().st_size > maximum_bytes
        ):
            raise ShadowExperimentAutomationError(
                f"{label} is missing or invalid."
            )
        return hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        raise ShadowExperimentAutomationError(
            f"{label} cannot be read."
        ) from exc


def _require_matching_receipt(
    receipt: dict[str, Any],
    *,
    receipt_id: str,
    terminal: _TerminalEvidence,
) -> None:
    if (
        receipt["receipt_id"] != receipt_id
        or receipt["terminal_evidence_fingerprint"]
        != terminal.fingerprint
        or tuple(receipt["terminal_trade_ids"])
        != terminal.terminal_trade_ids
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation receipt does not match terminal evidence."
        )


def _write_receipt_once(
    path: Path,
    receipt: dict[str, Any],
) -> bool:
    _validate_receipt(receipt)
    envelope = {
        "schema_version": SHADOW_EXPERIMENT_AUTOMATION_SCHEMA_VERSION,
        "receipt_sha256": hashlib.sha256(
            canonical_json(receipt).encode("utf-8")
        ).hexdigest(),
        "receipt": receipt,
    }
    text = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if (
        path.parent.is_symlink()
        or not path.parent.is_dir()
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation output is not a regular directory."
        )
    if path.exists():
        existing = load_shadow_experiment_automation_receipt(path)
        if existing != receipt:
            raise ShadowExperimentAutomationError(
                "Existing Shadow experiment automation receipt conflicts."
            )
        return False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        existing = load_shadow_experiment_automation_receipt(path)
        if existing != receipt:
            raise ShadowExperimentAutomationError(
                "Concurrent Shadow experiment automation receipt conflicts."
            )
        return False
    return True


def _receipt_path(receipts_dir: Path, receipt_id: str) -> Path:
    destination = receipts_dir.expanduser().resolve()
    if destination.exists() and (
        destination.is_symlink()
        or not destination.is_dir()
    ):
        raise ShadowExperimentAutomationError(
            "Shadow experiment automation output is not a regular directory."
        )
    return (
        destination
        / f"shadow-experiment-automation-{receipt_id}.json"
    )


def _result(
    *,
    status: str,
    terminal: _TerminalEvidence,
    receipt: dict[str, Any] | None = None,
    receipt_path: Path | None = None,
    receipt_created: bool = False,
) -> ShadowExperimentAutomationResult:
    return ShadowExperimentAutomationResult(
        schema_version=SHADOW_EXPERIMENT_AUTOMATION_SCHEMA_VERSION,
        engine_version=SHADOW_EXPERIMENT_AUTOMATION_ENGINE_VERSION,
        mode=SHADOW_EXPERIMENT_AUTOMATION_MODE,
        status=status,
        terminal_trade_count=len(terminal.terminal_trade_ids),
        terminal_trade_ids=terminal.terminal_trade_ids,
        terminal_evidence_fingerprint=terminal.fingerprint,
        receipt_id=(
            str(receipt["receipt_id"])
            if receipt is not None
            else None
        ),
        receipt_path=receipt_path,
        receipt_created=receipt_created,
        pipeline_status=(
            str(receipt["pipeline_status"])
            if receipt is not None
            else None
        ),
        experiment_ids=(
            tuple(
                str(item["experiment_id"])
                for item in receipt["experiment_artifacts"]
            )
            if receipt is not None
            else ()
        ),
        study_id=(
            str(receipt["study_artifact"]["study_id"])
            if receipt is not None
            else None
        ),
        transmitting=False,
        broker_request_performed=False,
        order_action_performed=False,
        source_artifacts_unchanged=True,
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
        PAPER_RECONCILIATIONS_DIR
        if state_path == SHADOW_STATE_PATH.expanduser().resolve()
        else state_path.parent / "paper-reconciliations"
    )
    return (
        directory
        / f"paper-reconciliation-{shadow_trade_id}.json"
    ).expanduser().resolve()


def _read_bounded_source(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
    required: bool,
) -> bytes | None:
    if not path.exists():
        if required:
            raise ShadowExperimentAutomationError(
                f"{label} does not exist."
            )
        return None
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > maximum_bytes
    ):
        raise ShadowExperimentAutomationError(
            f"{label} is not a bounded regular file."
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ShadowExperimentAutomationError(
            f"{label} cannot be read: {type(exc).__name__}."
        ) from exc


def _verify_source_snapshots(
    snapshots: Mapping[Path, bytes | None],
) -> None:
    for path, expected in snapshots.items():
        try:
            current = (
                path.read_bytes()
                if path.exists()
                and path.is_file()
                and not path.is_symlink()
                else None
            )
        except OSError as exc:
            raise ShadowExperimentAutomationError(
                "Terminal Shadow evidence changed during automation."
            ) from exc
        if current != expected:
            raise ShadowExperimentAutomationError(
                "Terminal Shadow evidence changed during automation."
            )


def _json_mapping(source: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowExperimentAutomationError(
            f"{label} is not valid UTF-8 JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise ShadowExperimentAutomationError(
            f"{label} must contain a JSON object."
        )
    return payload


def _optional_sha256(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _is_sha256(value: str) -> bool:
    return (
        len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
