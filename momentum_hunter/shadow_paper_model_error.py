from __future__ import annotations

"""Read-only model-error audit for manual paperMoney reconciliations."""

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable
from uuid import uuid4

from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_paper_reconciliation import (
    PAPER_RECONCILIATIONS_DIR,
    PaperMoneyReconciliationRecord,
    load_paper_money_reconciliation,
)
from momentum_hunter.shadow_trading import MIN_MEANINGFUL_SAMPLE_SIZE
from momentum_hunter.time_utils import now_central


MODEL_ERROR_AUDIT_SCHEMA_VERSION = 1
MODEL_ERROR_AUDIT_ENGINE_VERSION = "shadow_paper_model_error_v1"
MODEL_ERROR_REPORTS_DIR = DATA_DIR / "reports"
MODEL_ERROR_JSON_NAME = "shadow-paper-model-error-latest.json"
MODEL_ERROR_MARKDOWN_NAME = "shadow-paper-model-error-latest.md"
MAX_EVIDENCE_FILES = 10_000


class PaperMoneyModelErrorError(ValueError):
    """Raised when model-error evidence cannot be audited safely."""


def build_paper_money_model_error_audit(
    *,
    evidence_dir: Path = PAPER_RECONCILIATIONS_DIR,
    generated_at: datetime | None = None,
    minimum_sample_size: int = MIN_MEANINGFUL_SAMPLE_SIZE,
) -> dict[str, Any]:
    timestamp = generated_at or now_central()
    _require_aware_timestamp(timestamp)
    _validate_minimum_sample_size(minimum_sample_size)
    source_dir = evidence_dir.expanduser().resolve()
    if source_dir.exists() and not source_dir.is_dir():
        raise PaperMoneyModelErrorError(
            "paperMoney reconciliation source must be a directory."
        )

    paths = (
        sorted(source_dir.glob("paper-reconciliation-*.json"))
        if source_dir.exists()
        else []
    )
    if len(paths) > MAX_EVIDENCE_FILES:
        raise PaperMoneyModelErrorError(
            "paperMoney reconciliation source exceeds the audit file limit."
        )

    snapshots: dict[Path, bytes] = {}
    manifest: list[dict[str, str]] = []
    records: list[PaperMoneyReconciliationRecord] = []
    trade_ids: set[str] = set()
    reconciliation_ids: set[str] = set()
    for path in paths:
        try:
            raw = path.read_bytes()
            record = load_paper_money_reconciliation(path)
        except (OSError, ValueError) as exc:
            raise PaperMoneyModelErrorError(
                f"Invalid paperMoney reconciliation artifact {path.name!r}: "
                f"{type(exc).__name__}."
            ) from exc
        expected_name = f"paper-reconciliation-{record.shadow_trade_id}.json"
        if path.name != expected_name:
            raise PaperMoneyModelErrorError(
                "paperMoney reconciliation filename does not match its "
                "Shadow Trade identity."
            )
        if record.shadow_trade_id in trade_ids:
            raise PaperMoneyModelErrorError(
                "Duplicate Shadow Trade identity in reconciliation evidence."
            )
        if record.reconciliation_id in reconciliation_ids:
            raise PaperMoneyModelErrorError(
                "Duplicate reconciliation identity in reconciliation evidence."
            )
        if not record.fill_model_version.strip():
            raise PaperMoneyModelErrorError(
                "Reconciliation evidence has no frozen fill-model version."
            )
        trade_ids.add(record.shadow_trade_id)
        reconciliation_ids.add(record.reconciliation_id)
        snapshots[path] = raw
        manifest.append(
            {
                "filename": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        records.append(record)

    for path, expected in snapshots.items():
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise PaperMoneyModelErrorError(
                "Reconciliation evidence changed while the audit was built."
            ) from exc
        if current != expected:
            raise PaperMoneyModelErrorError(
                "Reconciliation evidence changed while the audit was built."
            )

    manifest_hash = hashlib.sha256(
        _canonical_json(manifest).encode("utf-8")
    ).hexdigest()
    return _summarize_records(
        records,
        generated_at=timestamp,
        source_directory=source_dir,
        source_manifest=manifest,
        source_manifest_sha256=manifest_hash,
        minimum_sample_size=minimum_sample_size,
    )


def _summarize_records(
    records: Iterable[PaperMoneyReconciliationRecord],
    *,
    generated_at: datetime,
    source_directory: Path,
    source_manifest: list[dict[str, str]],
    source_manifest_sha256: str,
    minimum_sample_size: int,
) -> dict[str, Any]:
    _require_aware_timestamp(generated_at)
    _validate_minimum_sample_size(minimum_sample_size)
    items = sorted(
        records,
        key=lambda item: (
            item.fill_model_version,
            item.recorded_at,
            item.shadow_trade_id,
        ),
    )
    trade_ids = [item.shadow_trade_id for item in items]
    reconciliation_ids = [item.reconciliation_id for item in items]
    if len(trade_ids) != len(set(trade_ids)):
        raise PaperMoneyModelErrorError(
            "Duplicate Shadow Trade identity in reconciliation evidence."
        )
    if len(reconciliation_ids) != len(set(reconciliation_ids)):
        raise PaperMoneyModelErrorError(
            "Duplicate reconciliation identity in reconciliation evidence."
        )
    if any(not item.fill_model_version.strip() for item in items):
        raise PaperMoneyModelErrorError(
            "Reconciliation evidence has no frozen fill-model version."
        )

    grouped: dict[str, list[PaperMoneyReconciliationRecord]] = {}
    for record in items:
        grouped.setdefault(record.fill_model_version, []).append(record)
    fill_model_groups = [
        _summarize_fill_model(
            version,
            grouped[version],
            minimum_sample_size=minimum_sample_size,
        )
        for version in sorted(grouped)
    ]
    model_versions = sorted(grouped)
    lifecycle_ready = (
        len(model_versions) == 1
        and bool(fill_model_groups)
        and fill_model_groups[0]["pnl_per_share"]["gate_satisfied"]
    )
    if not items:
        overall_status = "NO_EVIDENCE"
    elif len(model_versions) > 1:
        overall_status = "MIXED_FILL_MODEL_VERSIONS"
    elif lifecycle_ready:
        overall_status = "DESCRIPTIVE_MODEL_ERROR_READY"
    else:
        overall_status = "INSUFFICIENT_SAMPLE"

    return {
        "schema_version": MODEL_ERROR_AUDIT_SCHEMA_VERSION,
        "engine_version": MODEL_ERROR_AUDIT_ENGINE_VERSION,
        "generated_at": generated_at.isoformat(),
        "overall_status": overall_status,
        "mode": "READ_ONLY_PAPERMONEY_VS_FAKEBROKER_MODEL_ERROR_AUDIT",
        "transmitting": False,
        "broker_request_performed": False,
        "order_action_performed": False,
        "source_records_mutated": False,
        "source_directory": str(source_directory),
        "source_record_count": len(items),
        "source_manifest": source_manifest,
        "source_manifest_sha256": source_manifest_sha256,
        "minimum_sample_size": minimum_sample_size,
        "fill_model_versions": model_versions,
        "paper_result_counts": _counter_rows(
            Counter(record.paper_money_result for record in items)
        ),
        "comparison_status_counts": _counter_rows(
            Counter(record.comparison_status for record in items)
        ),
        "fill_model_groups": fill_model_groups,
        "records": [_record_projection(record) for record in items],
        "strategy_conclusion_authorized": False,
        "trading_authorized": False,
        "conclusion": _conclusion(overall_status, minimum_sample_size),
    }


def _summarize_fill_model(
    version: str,
    records: list[PaperMoneyReconciliationRecord],
    *,
    minimum_sample_size: int,
) -> dict[str, Any]:
    entry_bps = _values(records, "paper_minus_fake_entry_bps")
    exit_bps = [
        round(
            record.paper_minus_fake_exit_price
            / record.fakebroker_exit_price
            * 10_000,
            4,
        )
        for record in records
        if record.paper_minus_fake_exit_price is not None
        and record.fakebroker_exit_price is not None
        and record.fakebroker_exit_price > 0
    ]
    pnl_per_share = _values(records, "paper_minus_fake_pnl_per_share")
    total_pnl = _values(records, "paper_minus_fake_executable_pnl")
    return {
        "fill_model_version": version,
        "record_count": len(records),
        "sample_versions": sorted(
            {record.sample_version for record in records}
        ),
        "entry_bps": _gated_metrics(
            entry_bps,
            minimum_sample_size=minimum_sample_size,
            unit="basis_points",
        ),
        "exit_bps": _gated_metrics(
            exit_bps,
            minimum_sample_size=minimum_sample_size,
            unit="basis_points",
        ),
        "pnl_per_share": _gated_metrics(
            pnl_per_share,
            minimum_sample_size=minimum_sample_size,
            unit="dollars_per_share",
        ),
        "equal_quantity_total_pnl": _gated_metrics(
            total_pnl,
            minimum_sample_size=minimum_sample_size,
            unit="dollars",
        ),
        "comparison_status_counts": _counter_rows(
            Counter(record.comparison_status for record in records)
        ),
    }


def _gated_metrics(
    values: list[float],
    *,
    minimum_sample_size: int,
    unit: str,
) -> dict[str, Any]:
    gate_satisfied = len(values) >= minimum_sample_size
    return {
        "unit": unit,
        "observation_count": len(values),
        "minimum_required": minimum_sample_size,
        "gate_satisfied": gate_satisfied,
        "signed_mean": (
            round(float(mean(values)), 6) if gate_satisfied else None
        ),
        "median": (
            round(float(median(values)), 6) if gate_satisfied else None
        ),
        "mean_absolute_error": (
            round(float(mean(abs(value) for value in values)), 6)
            if gate_satisfied
            else None
        ),
        "minimum": round(min(values), 6) if gate_satisfied else None,
        "maximum": round(max(values), 6) if gate_satisfied else None,
        "status": (
            "DESCRIPTIVE_METRICS_AVAILABLE"
            if gate_satisfied
            else "WITHHELD_INSUFFICIENT_SAMPLE"
        ),
    }


def _record_projection(
    record: PaperMoneyReconciliationRecord,
) -> dict[str, Any]:
    exit_bps = (
        round(
            record.paper_minus_fake_exit_price
            / record.fakebroker_exit_price
            * 10_000,
            4,
        )
        if record.paper_minus_fake_exit_price is not None
        and record.fakebroker_exit_price is not None
        and record.fakebroker_exit_price > 0
        else None
    )
    return {
        "reconciliation_id": record.reconciliation_id,
        "recorded_at": record.recorded_at,
        "shadow_trade_id": record.shadow_trade_id,
        "symbol": record.symbol,
        "sample_version": record.sample_version,
        "fill_model_version": record.fill_model_version,
        "paper_money_result": record.paper_money_result,
        "paper_money_filled_quantity": record.paper_money_filled_quantity,
        "fakebroker_filled_quantity": record.fakebroker_filled_quantity,
        "comparison_status": record.comparison_status,
        "paper_minus_fake_entry_bps": (
            record.paper_minus_fake_entry_bps
        ),
        "paper_minus_fake_exit_bps": exit_bps,
        "paper_minus_fake_executable_pnl": (
            record.paper_minus_fake_executable_pnl
        ),
        "paper_minus_fake_pnl_per_share": (
            record.paper_minus_fake_pnl_per_share
        ),
    }


def export_paper_money_model_error_audit(
    payload: dict[str, Any],
    *,
    output_dir: Path = MODEL_ERROR_REPORTS_DIR,
) -> tuple[Path, Path]:
    destination = output_dir.expanduser().resolve()
    source = Path(str(payload.get("source_directory") or "")).resolve()
    if destination == source or _is_relative_to(destination, source):
        raise PaperMoneyModelErrorError(
            "Derived model-error reports cannot be written inside reconciliation "
            "evidence."
        )
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / MODEL_ERROR_JSON_NAME
    markdown_path = destination / MODEL_ERROR_MARKDOWN_NAME
    _atomic_write_text(
        json_path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
    )
    _atomic_write_text(markdown_path, format_paper_money_model_error_markdown(payload))
    return json_path, markdown_path


def format_paper_money_model_error_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Shadow paperMoney vs FakeBroker Model Error Audit",
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Status: `{payload.get('overall_status', 'UNKNOWN')}`",
        f"- Source records: {payload.get('source_record_count', 0)}",
        f"- Minimum comparable observations: {payload.get('minimum_sample_size', 0)}",
        f"- Source manifest SHA-256: `{payload.get('source_manifest_sha256', '')}`",
        "- Mode: read-only, nontransmitting",
        "- Strategy conclusion authorized: no",
        "- Trading authorized: no",
        "",
        "## Fill Model Groups",
        "",
        "| Fill model | Records | Entry gate | Exit gate | P&L/share gate |",
        "| --- | ---: | --- | --- | --- |",
    ]
    groups = payload.get("fill_model_groups") or []
    if groups:
        for group in groups:
            lines.append(
                "| {version} | {count} | {entry} | {exit} | {pnl} |".format(
                    version=group["fill_model_version"],
                    count=group["record_count"],
                    entry=group["entry_bps"]["status"],
                    exit=group["exit_bps"]["status"],
                    pnl=group["pnl_per_share"]["status"],
                )
            )
    else:
        lines.append("| None | 0 | WITHHELD | WITHHELD | WITHHELD |")
    lines.extend(
        [
            "",
            "## Reconciliations",
            "",
            "| Recorded | Symbol | Result | Comparison | Entry delta (bps) | "
            "Exit delta (bps) | P&L/share delta |",
            "| --- | --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    records = payload.get("records") or []
    if records:
        for record in records:
            lines.append(
                "| {recorded} | {symbol} | {result} | {comparison} | "
                "{entry} | {exit} | {pnl} |".format(
                    recorded=record["recorded_at"],
                    symbol=record["symbol"],
                    result=record["paper_money_result"],
                    comparison=record["comparison_status"],
                    entry=_display(record["paper_minus_fake_entry_bps"]),
                    exit=_display(record["paper_minus_fake_exit_bps"]),
                    pnl=_display(record["paper_minus_fake_pnl_per_share"]),
                )
            )
    else:
        lines.append("| None |  |  |  |  |  |  |")
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            str(payload.get("conclusion") or ""),
            "",
        ]
    )
    return "\n".join(lines)


def _values(
    records: Iterable[PaperMoneyReconciliationRecord],
    field_name: str,
) -> list[float]:
    values: list[float] = []
    for record in records:
        value = getattr(record, field_name)
        if value is not None:
            values.append(float(value))
    return values


def _counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "count": counter[name]}
        for name in sorted(counter)
    ]


def _conclusion(status: str, minimum_sample_size: int) -> str:
    if status == "NO_EVIDENCE":
        return (
            "No paperMoney reconciliation evidence is available. No model-error "
            "conclusion is possible."
        )
    if status == "MIXED_FILL_MODEL_VERSIONS":
        return (
            "Fill-model versions are reported separately and must not be combined. "
            "No cross-version model-error conclusion is authorized."
        )
    if status == "DESCRIPTIVE_MODEL_ERROR_READY":
        return (
            "At least "
            f"{minimum_sample_size} comparable lifecycle observations support "
            "descriptive model-error metrics only. This does not validate strategy "
            "edge or authorize trading."
        )
    return (
        "Aggregate model-error metrics are withheld until at least "
        f"{minimum_sample_size} comparable observations exist for each metric."
    )


def _validate_minimum_sample_size(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < MIN_MEANINGFUL_SAMPLE_SIZE
    ):
        raise PaperMoneyModelErrorError(
            "Minimum sample size cannot be lower than the canonical "
            f"{MIN_MEANINGFUL_SAMPLE_SIZE}-observation evidence gate."
        )


def _require_aware_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperMoneyModelErrorError(
            "Model-error audit timestamp must include a UTC offset."
        )


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
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
            "Build a read-only aggregate audit of paperMoney versus FakeBroker "
            "model error."
        )
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=PAPER_RECONCILIATIONS_DIR,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=MODEL_ERROR_REPORTS_DIR,
    )
    parser.add_argument(
        "--minimum-sample-size",
        type=int,
        default=MIN_MEANINGFUL_SAMPLE_SIZE,
    )
    args = parser.parse_args(argv)
    payload = build_paper_money_model_error_audit(
        evidence_dir=args.evidence_dir,
        minimum_sample_size=args.minimum_sample_size,
    )
    json_path, markdown_path = export_paper_money_model_error_audit(
        payload,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "overallStatus": payload["overall_status"],
                "sourceRecordCount": payload["source_record_count"],
                "fillModelVersions": payload["fill_model_versions"],
                "sourceManifestSha256": payload["source_manifest_sha256"],
                "jsonPath": str(json_path),
                "markdownPath": str(markdown_path),
                "transmitting": False,
                "brokerRequestPerformed": False,
                "orderActionPerformed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
