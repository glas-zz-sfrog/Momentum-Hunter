from __future__ import annotations

"""Immutable read-only evidence checkpoints for the official Shadow sample."""

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_trading import (
    MIN_MEANINGFUL_SAMPLE_SIZE,
    SHADOW_MODE,
    SHADOW_REPORTS_DIR,
    SHADOW_STATE_PATH,
    ShadowExecutionPolicy,
    ShadowSampleActivation,
    ShadowSampleActivationStore,
    ShadowSampleMetadata,
    ShadowStateStore,
    ShadowTradingService,
    canonical_json,
    shadow_sample_metadata_findings,
    shadow_sample_metadata_to_dict,
    stable_id,
)
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import parse_datetime


SHADOW_CHECKPOINT_SCHEMA_VERSION = 1
SHADOW_CHECKPOINT_ENGINE_VERSION = "shadow_evidence_checkpoints_v1"
SHADOW_CHECKPOINT_THRESHOLDS = (5, 10, 20, 30)
SHADOW_CHECKPOINTS_DIR = SHADOW_REPORTS_DIR / "shadow-evidence-checkpoints"
MAX_CHECKPOINT_BYTES = 8 * 1024 * 1024
GATED_METRIC_FIELDS = (
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


class ShadowEvidenceCheckpointError(ValueError):
    """Raised when checkpoint evidence cannot be frozen safely."""


@dataclass(frozen=True)
class ShadowEvidenceCheckpointWrite:
    threshold: int
    checkpoint_id: str
    json_path: Path
    markdown_path: Path
    created: bool


def generate_shadow_evidence_checkpoints(
    *,
    state_path: Path = SHADOW_STATE_PATH,
    output_dir: Path = SHADOW_CHECKPOINTS_DIR,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or now_central()
    _require_aware_timestamp(timestamp)
    store = ShadowStateStore(state_path.expanduser().resolve())
    activation_store = ShadowSampleActivationStore.for_state_store(store)
    source_snapshots = _read_source_snapshots(
        (store.path, activation_store.path)
    )
    activation = activation_store.load()
    if activation is None:
        _verify_source_snapshots(source_snapshots)
        return {
            "schemaVersion": SHADOW_CHECKPOINT_SCHEMA_VERSION,
            "engineVersion": SHADOW_CHECKPOINT_ENGINE_VERSION,
            "generatedAt": timestamp.isoformat(),
            "status": "NOT_ACTIVATED",
            "eligibleCompleted": 0,
            "nextCheckpoint": SHADOW_CHECKPOINT_THRESHOLDS[0],
            "checkpoints": [],
            "transmitting": False,
            "brokerRequestPerformed": False,
            "orderActionPerformed": False,
            "sourceStateMutated": False,
        }

    policy = _policy_from_activation(activation)
    service = ShadowTradingService(
        store=store,
        policy=policy,
        sample_version=activation.sample_metadata.sample_version,
    )
    snapshot = service.snapshot()
    payloads = build_shadow_evidence_checkpoint_payloads(
        snapshot,
        activation=activation,
        generated_at=timestamp,
        source_state_path=store.path,
        source_state_sha256=_snapshot_sha256(
            source_snapshots.get(store.path)
        ),
        activation_path=activation_store.path,
        activation_sha256=_snapshot_sha256(
            source_snapshots.get(activation_store.path)
        ),
    )
    writes = write_shadow_evidence_checkpoints(
        payloads,
        output_dir=output_dir,
    )
    _verify_source_snapshots(source_snapshots)
    eligible = int(snapshot["sample"]["eligibleCompleted"])
    return {
        "schemaVersion": SHADOW_CHECKPOINT_SCHEMA_VERSION,
        "engineVersion": SHADOW_CHECKPOINT_ENGINE_VERSION,
        "generatedAt": timestamp.isoformat(),
        "status": (
            "CHECKPOINTS_AVAILABLE"
            if payloads
            else "AWAITING_FIRST_CHECKPOINT"
        ),
        "eligibleCompleted": eligible,
        "nextCheckpoint": next(
            (
                threshold
                for threshold in SHADOW_CHECKPOINT_THRESHOLDS
                if threshold > eligible
            ),
            None,
        ),
        "checkpoints": [
            {
                "threshold": item.threshold,
                "checkpointId": item.checkpoint_id,
                "jsonPath": str(item.json_path),
                "markdownPath": str(item.markdown_path),
                "created": item.created,
            }
            for item in writes
        ],
        "transmitting": False,
        "brokerRequestPerformed": False,
        "orderActionPerformed": False,
        "sourceStateMutated": False,
    }


def build_shadow_evidence_checkpoint_payloads(
    snapshot: dict[str, Any],
    *,
    activation: ShadowSampleActivation,
    generated_at: datetime,
    source_state_path: Path,
    source_state_sha256: str | None,
    activation_path: Path,
    activation_sha256: str,
) -> list[dict[str, Any]]:
    _require_aware_timestamp(generated_at)
    _validate_activation(activation)
    if snapshot.get("mode") != SHADOW_MODE or snapshot.get("transmitting") is not False:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint source must be the nontransmitting review snapshot."
        )
    sample = snapshot.get("sample")
    review_trades = snapshot.get("reviewTrades")
    metrics = snapshot.get("reviewMetrics")
    if not isinstance(sample, dict) or not isinstance(review_trades, list):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint source is missing canonical review evidence."
        )
    if not isinstance(metrics, dict):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint source is missing canonical review metrics."
        )
    if sample.get("sampleVersion") != activation.sample_metadata.sample_version:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint sample version does not match activation."
        )
    if (
        sample.get("strategyConfigurationFingerprint")
        != activation.sample_metadata.strategy_configuration_fingerprint
        or sample.get("fillModelVersion")
        != activation.sample_metadata.fill_model_version
        or sample.get("evidenceSchemaVersion")
        != activation.sample_metadata.evidence_schema_version
        or sample.get("officialSampleAuthorized") is not True
    ):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint sample identity does not match activation."
        )
    if sample.get("minimumRequired") != MIN_MEANINGFUL_SAMPLE_SIZE:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint source has an unexpected sample gate."
        )
    if not re.fullmatch(r"[0-9a-f]{64}", activation_sha256):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint activation hash is invalid."
        )

    eligible = [
        _validate_review_trade(row, activation.sample_metadata)
        for row in review_trades
        if isinstance(row, dict) and row.get("countsTowardSample") is True
    ]
    declared_count = sample.get("eligibleCompleted")
    if (
        isinstance(declared_count, bool)
        or not isinstance(declared_count, int)
        or declared_count != len(eligible)
    ):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint eligible count does not match review evidence."
        )
    if declared_count and not (
        isinstance(source_state_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", source_state_sha256)
    ):
        raise ShadowEvidenceCheckpointError(
            "Eligible Shadow checkpoint evidence requires a source-state hash."
        )
    trade_ids = [str(row["shadowTradeId"]) for row in eligible]
    if len(trade_ids) != len(set(trade_ids)):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint review contains duplicate trade identity."
        )
    eligible.sort(
        key=lambda row: (
            _decision_timestamp(row).astimezone(timezone.utc),
            str(row["shadowTradeId"]),
        )
    )
    if declared_count < MIN_MEANINGFUL_SAMPLE_SIZE:
        if any(metrics.get(field) is not None for field in GATED_METRIC_FIELDS):
            raise ShadowEvidenceCheckpointError(
                "Shadow checkpoint source exposes gated metrics below 30 trades."
            )
    elif (
        metrics.get("sampleStatus") != "MEANINGFUL"
        or metrics.get("completedTradeCount") != declared_count
    ):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint metrics do not match the eligible sample."
        )

    payloads: list[dict[str, Any]] = []
    for threshold in SHADOW_CHECKPOINT_THRESHOLDS:
        if threshold > declared_count:
            continue
        selected = eligible[:threshold]
        selected_manifest = [
            {
                "shadowTradeId": row["shadowTradeId"],
                "decisionTimestamp": row["decisionTimestamp"],
                "tradeRecordSha256": hashlib.sha256(
                    canonical_json(row).encode("utf-8")
                ).hexdigest(),
            }
            for row in selected
        ]
        selected_manifest_sha256 = hashlib.sha256(
            canonical_json(selected_manifest).encode("utf-8")
        ).hexdigest()
        checkpoint_id = stable_id(
            "shadow-evidence-checkpoint",
            activation.sample_metadata.sample_version,
            str(threshold),
            selected_manifest_sha256,
        )
        exact_count = declared_count == threshold
        checkpoint_metrics = metrics if exact_count else None
        payloads.append(
            {
                "schema_version": SHADOW_CHECKPOINT_SCHEMA_VERSION,
                "engine_version": SHADOW_CHECKPOINT_ENGINE_VERSION,
                "checkpoint_id": checkpoint_id,
                "generated_at": generated_at.isoformat(),
                "mode": "OFFICIAL SHADOW EVIDENCE CHECKPOINT / READ ONLY",
                "transmitting": False,
                "broker_request_performed": False,
                "order_action_performed": False,
                "source_state_mutated": False,
                "source_state_path": str(source_state_path.resolve()),
                "source_state_sha256": source_state_sha256,
                "activation_path": str(activation_path.resolve()),
                "activation_sha256": activation_sha256,
                "activated_at": activation.activated_at,
                "sample_definition": shadow_sample_metadata_to_dict(
                    activation.sample_metadata
                ),
                "threshold": threshold,
                "eligible_completed_at_generation": declared_count,
                "late_reconstruction": not exact_count,
                "selected_trade_count": len(selected),
                "selected_trade_manifest": selected_manifest,
                "selected_trade_manifest_sha256": selected_manifest_sha256,
                "selected_trades": selected,
                "metrics_status": (
                    "CANONICAL_EXACT_COUNT_SNAPSHOT"
                    if exact_count
                    else "LATE_RECONSTRUCTION_METRICS_WITHHELD"
                ),
                "metrics": checkpoint_metrics,
                "strategy_conclusion_authorized": False,
                "trading_authorized": False,
                "conclusion": _checkpoint_conclusion(
                    threshold,
                    exact_count=exact_count,
                ),
            }
        )
    return payloads


def write_shadow_evidence_checkpoints(
    payloads: Iterable[dict[str, Any]],
    *,
    output_dir: Path = SHADOW_CHECKPOINTS_DIR,
) -> list[ShadowEvidenceCheckpointWrite]:
    items = list(payloads)
    if not items:
        return []
    destination = output_dir.expanduser().resolve()
    _validate_output_directory(destination, items)
    destination.mkdir(parents=True, exist_ok=True)
    writes: list[ShadowEvidenceCheckpointWrite] = []
    for payload in items:
        _validate_checkpoint_payload(payload)
        sample_version = str(payload["sample_definition"]["sampleVersion"])
        threshold = int(payload["threshold"])
        stem = f"shadow-evidence-checkpoint-{sample_version}-{threshold}"
        json_path = destination / f"{stem}.json"
        markdown_path = destination / f"{stem}.md"
        existing = _load_checkpoint(json_path)
        if existing is not None:
            _require_same_checkpoint(existing, payload)
            expected_markdown = format_shadow_evidence_checkpoint_markdown(
                existing
            )
            if markdown_path.exists():
                if (
                    markdown_path.read_text(encoding="utf-8")
                    != expected_markdown
                ):
                    raise ShadowEvidenceCheckpointError(
                        "Existing Shadow checkpoint Markdown is inconsistent."
                    )
            else:
                _write_once(markdown_path, expected_markdown)
            writes.append(
                ShadowEvidenceCheckpointWrite(
                    threshold=threshold,
                    checkpoint_id=str(existing["checkpoint_id"]),
                    json_path=json_path,
                    markdown_path=markdown_path,
                    created=False,
                )
            )
            continue
        if markdown_path.exists():
            raise ShadowEvidenceCheckpointError(
                "Shadow checkpoint Markdown exists without its JSON evidence."
            )
        envelope = {
            "schema_version": SHADOW_CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_sha256": hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest(),
            "checkpoint": payload,
        }
        _write_once(
            json_path,
            json.dumps(
                envelope,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n",
        )
        _write_once(
            markdown_path,
            format_shadow_evidence_checkpoint_markdown(payload),
        )
        writes.append(
            ShadowEvidenceCheckpointWrite(
                threshold=threshold,
                checkpoint_id=str(payload["checkpoint_id"]),
                json_path=json_path,
                markdown_path=markdown_path,
                created=True,
            )
        )
    return writes


def format_shadow_evidence_checkpoint_markdown(
    payload: dict[str, Any],
) -> str:
    lines = [
        f"# Official Shadow Evidence Checkpoint {payload['threshold']}",
        "",
        f"- Checkpoint ID: `{payload['checkpoint_id']}`",
        f"- Generated: {payload['generated_at']}",
        f"- Sample: `{payload['sample_definition']['sampleVersion']}`",
        f"- Fill model: `{payload['sample_definition']['fillModelVersion']}`",
        f"- Selected eligible trades: {payload['selected_trade_count']}",
        (
            "- Eligible trades at generation: "
            f"{payload['eligible_completed_at_generation']}"
        ),
        f"- Metrics status: `{payload['metrics_status']}`",
        f"- Late reconstruction: {str(payload['late_reconstruction']).lower()}",
        "- Mode: read-only, nontransmitting",
        "- Strategy conclusion authorized: no",
        "- Trading authorized: no",
        "",
        "## Evidence",
        "",
        "| Decision | Symbol | Outcome | Audit | Executable P&L | R |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in payload["selected_trades"]:
        lines.append(
            "| {decision} | {symbol} | {outcome} | {audit} | {pnl} | {r} |".format(
                decision=row["decisionTimestamp"],
                symbol=row["symbol"],
                outcome=row["outcome"],
                audit=row["evidenceLock"]["auditStatus"],
                pnl=_display(row["executablePnl"]),
                r=_display(row["rMultiple"]),
            )
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            str(payload["conclusion"]),
            "",
        ]
    )
    return "\n".join(lines)


def _validate_review_trade(
    row: dict[str, Any],
    sample_metadata: ShadowSampleMetadata,
) -> dict[str, Any]:
    trade_id = row.get("shadowTradeId")
    evidence_lock = row.get("evidenceLock")
    if not isinstance(trade_id, str) or not trade_id.strip():
        raise ShadowEvidenceCheckpointError(
            "Eligible Shadow review record has no trade identity."
        )
    _decision_timestamp(row)
    if (
        row.get("evidenceEligible") is not True
        or not isinstance(evidence_lock, dict)
        or evidence_lock.get("auditStatus") != "PASS"
        or evidence_lock.get("evidenceFrozen") is not True
        or evidence_lock.get("planFrozen") is not True
        or evidence_lock.get("postDecisionCorrectionOccurred") is not False
    ):
        raise ShadowEvidenceCheckpointError(
            "Eligible Shadow review record does not have frozen PASS evidence."
        )
    if row.get("sampleMetadata") != shadow_sample_metadata_to_dict(
        sample_metadata
    ):
        raise ShadowEvidenceCheckpointError(
            "Eligible Shadow review record has a different sample definition."
        )
    required_fields = {
        "symbol",
        "outcome",
        "executablePnl",
        "rMultiple",
        "dataQualityState",
    }
    if any(field not in row for field in required_fields):
        raise ShadowEvidenceCheckpointError(
            "Eligible Shadow review record is missing checkpoint evidence."
        )
    return row


def _decision_timestamp(row: dict[str, Any]) -> datetime:
    parsed = parse_datetime(str(row.get("decisionTimestamp") or ""))
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShadowEvidenceCheckpointError(
            "Eligible Shadow review record has an invalid decision timestamp."
        )
    return parsed


def _policy_from_activation(
    activation: ShadowSampleActivation,
) -> ShadowExecutionPolicy:
    _validate_activation(activation)
    try:
        configuration = json.loads(
            activation.sample_metadata.strategy_configuration_json
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise ShadowEvidenceCheckpointError(
            "Shadow activation configuration cannot be loaded."
        ) from exc
    execution = (
        configuration.get("execution_policy")
        if isinstance(configuration, dict)
        else None
    )
    expected_fields = set(asdict(ShadowExecutionPolicy()))
    if not isinstance(execution, dict) or set(execution) != expected_fields:
        raise ShadowEvidenceCheckpointError(
            "Shadow activation execution policy is incomplete."
        )
    try:
        policy = ShadowExecutionPolicy(**execution)
    except TypeError as exc:
        raise ShadowEvidenceCheckpointError(
            "Shadow activation execution policy is invalid."
        ) from exc
    findings = shadow_sample_metadata_findings(
        activation.sample_metadata,
        expected_policy=policy,
        require_current_contract=True,
    )
    if findings:
        raise ShadowEvidenceCheckpointError(
            "Shadow activation does not match its frozen policy: "
            + " | ".join(findings)
        )
    return policy


def _validate_activation(activation: ShadowSampleActivation) -> None:
    activated_at = parse_datetime(activation.activated_at)
    if (
        activated_at is None
        or activated_at.tzinfo is None
        or activated_at.utcoffset() is None
        or not activation.sample_metadata.official_sample_authorized
    ):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint requires a valid official sample activation."
        )
    findings = shadow_sample_metadata_findings(
        activation.sample_metadata,
        require_current_contract=True,
    )
    if findings:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint activation is invalid: " + " | ".join(findings)
        )


def _validate_checkpoint_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SHADOW_CHECKPOINT_SCHEMA_VERSION:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint payload has an unsupported schema."
        )
    threshold = payload.get("threshold")
    if threshold not in SHADOW_CHECKPOINT_THRESHOLDS:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint threshold is not canonical."
        )
    if (
        payload.get("transmitting") is not False
        or payload.get("broker_request_performed") is not False
        or payload.get("order_action_performed") is not False
        or payload.get("strategy_conclusion_authorized") is not False
        or payload.get("trading_authorized") is not False
    ):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint cannot claim execution or conclusion authority."
        )
    selected = payload.get("selected_trades")
    manifest = payload.get("selected_trade_manifest")
    if (
        not isinstance(selected, list)
        or len(selected) != threshold
        or not isinstance(manifest, list)
        or len(manifest) != threshold
    ):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint selected evidence count is inconsistent."
        )
    expected_manifest = [
        {
            "shadowTradeId": row["shadowTradeId"],
            "decisionTimestamp": row["decisionTimestamp"],
            "tradeRecordSha256": hashlib.sha256(
                canonical_json(row).encode("utf-8")
            ).hexdigest(),
        }
        for row in selected
    ]
    if manifest != expected_manifest:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint selected trade manifest is inconsistent."
        )
    manifest_sha256 = hashlib.sha256(
        canonical_json(manifest).encode("utf-8")
    ).hexdigest()
    if payload.get("selected_trade_manifest_sha256") != manifest_sha256:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint selected trade manifest hash is inconsistent."
        )
    sample = payload.get("sample_definition")
    if not isinstance(sample, dict):
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint sample definition is missing."
        )
    expected_id = stable_id(
        "shadow-evidence-checkpoint",
        str(sample.get("sampleVersion") or ""),
        str(threshold),
        manifest_sha256,
    )
    if payload.get("checkpoint_id") != expected_id:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint identity is inconsistent."
        )


def _load_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise ShadowEvidenceCheckpointError(
            "Existing Shadow checkpoint is not a bounded regular file."
        )
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ShadowEvidenceCheckpointError(
            "Existing Shadow checkpoint cannot be loaded."
        ) from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("schema_version") != SHADOW_CHECKPOINT_SCHEMA_VERSION
        or not isinstance(envelope.get("checkpoint"), dict)
    ):
        raise ShadowEvidenceCheckpointError(
            "Existing Shadow checkpoint envelope is malformed."
        )
    checkpoint = envelope["checkpoint"]
    expected_sha256 = hashlib.sha256(
        canonical_json(checkpoint).encode("utf-8")
    ).hexdigest()
    if envelope.get("checkpoint_sha256") != expected_sha256:
        raise ShadowEvidenceCheckpointError(
            "Existing Shadow checkpoint hash does not match its content."
        )
    _validate_checkpoint_payload(checkpoint)
    return checkpoint


def _require_same_checkpoint(
    existing: dict[str, Any],
    proposed: dict[str, Any],
) -> None:
    if (
        existing.get("checkpoint_id") != proposed.get("checkpoint_id")
        or existing.get("selected_trade_manifest_sha256")
        != proposed.get("selected_trade_manifest_sha256")
    ):
        raise ShadowEvidenceCheckpointError(
            "A different immutable Shadow checkpoint already exists."
        )


def _validate_output_directory(
    destination: Path,
    payloads: list[dict[str, Any]],
) -> None:
    if destination.exists() and not destination.is_dir():
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint output must be a directory."
        )
    for payload in payloads:
        for source_name in ("source_state_path", "activation_path"):
            source = Path(str(payload[source_name])).resolve()
            if destination == source.parent or _is_relative_to(
                destination,
                source.parent,
            ):
                raise ShadowEvidenceCheckpointError(
                    "Shadow checkpoints cannot be written inside source state "
                    "storage."
                )


def _read_source_snapshots(
    paths: Iterable[Path],
) -> dict[Path, bytes | None]:
    snapshots: dict[Path, bytes | None] = {}
    for path in paths:
        resolved = path.resolve()
        try:
            snapshots[resolved] = (
                resolved.read_bytes() if resolved.exists() else None
            )
        except OSError as exc:
            raise ShadowEvidenceCheckpointError(
                "Shadow checkpoint source cannot be read."
            ) from exc
    return snapshots


def _verify_source_snapshots(
    snapshots: dict[Path, bytes | None],
) -> None:
    for path, expected in snapshots.items():
        try:
            current = path.read_bytes() if path.exists() else None
        except OSError as exc:
            raise ShadowEvidenceCheckpointError(
                "Shadow checkpoint source changed during generation."
            ) from exc
        if current != expected:
            raise ShadowEvidenceCheckpointError(
                "Shadow checkpoint source changed during generation."
            )


def _snapshot_sha256(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _write_once(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ShadowEvidenceCheckpointError(
                "Shadow checkpoint output appeared concurrently."
            ) from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _checkpoint_conclusion(threshold: int, *, exact_count: bool) -> str:
    if not exact_count:
        return (
            "This checkpoint was reconstructed from immutable eligible records "
            "after its threshold. Aggregate metrics are withheld."
        )
    if threshold < MIN_MEANINGFUL_SAMPLE_SIZE:
        return (
            "This interim checkpoint evaluates mechanics and evidence quality only. "
            "Aggregate and strategy conclusions remain withheld."
        )
    return (
        "The 30-trade engineering gate permits descriptive evidence review only. "
        "It does not prove durable edge or authorize trading."
    )


def _require_aware_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowEvidenceCheckpointError(
            "Shadow checkpoint timestamp must include a UTC offset."
        )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _display(value: Any) -> str:
    return "" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write immutable 5/10/20/30 read-only official Shadow evidence "
            "checkpoints."
        )
    )
    parser.add_argument("--state-path", type=Path, default=SHADOW_STATE_PATH)
    parser.add_argument("--output-dir", type=Path, default=SHADOW_CHECKPOINTS_DIR)
    args = parser.parse_args(argv)
    result = generate_shadow_evidence_checkpoints(
        state_path=args.state_path,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
