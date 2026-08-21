from __future__ import annotations

"""Verify and adjudicate market-only thinkorswim RTD campaign evidence."""

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


TASK_ID = "ARGUS-THINKORSWIM-OVERNIGHT-RTD-001"
ALLOWED_FIELDS = {
    "SYMBOL", "DESCRIPTION", "LAST", "BID", "ASK", "MARK", "LAST_SIZE",
    "BID_SIZE", "ASK_SIZE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME",
    "EXCHANGE",
}
ORDERED_FIELDS = [
    "SYMBOL", "DESCRIPTION", "LAST", "BID", "ASK", "MARK", "LAST_SIZE",
    "BID_SIZE", "ASK_SIZE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME",
    "EXCHANGE",
]
SYMBOLS = ["SPY", "QQQ", "NVDA", "AAPL", "MU"]
CHECKPOINTS = [
    ("A_1955_ET", "2026-08-21T19:55:00-04:00"),
    ("B_2000_ET", "2026-08-21T20:00:00-04:00"),
    ("C_2005_ET", "2026-08-21T20:05:00-04:00"),
    ("D_2100_ET", "2026-08-21T21:00:00-04:00"),
    ("E_0030_ET", "2026-08-22T00:30:00-04:00"),
    ("F_0130_ET", "2026-08-22T01:30:00-04:00"),
    ("G_0355_ET", "2026-08-22T03:55:00-04:00"),
    ("H_0405_ET", "2026-08-22T04:05:00-04:00"),
]
FORBIDDEN_FRAGMENTS = ("POSITION", "P_L", "ACCOUNT", "BUYING_POWER", "ORDER")
SECRET_PATTERNS = (
    re.compile(rb"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(rb'"(?:access_token|refresh_token|client_secret|account_hash|password)"\s*:', re.IGNORECASE),
)


class VerificationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationError(f"{path.name} must contain an object.")
    return value


def validate_configuration(value: Mapping[str, object]) -> None:
    if value.get("taskId") != TASK_ID:
        raise VerificationError("Configuration task identity mismatch.")
    if value.get("symbols") != SYMBOLS:
        raise VerificationError("Fixed symbol basket mismatch.")
    fields = value.get("fields")
    if fields != ORDERED_FIELDS:
        raise VerificationError("Fixed market-only field list mismatch.")
    if any(field not in ALLOWED_FIELDS for field in fields):
        raise VerificationError("Configuration contains an unsupported field.")
    if any(fragment in str(field).upper() for field in fields for fragment in FORBIDDEN_FRAGMENTS):
        raise VerificationError("Configuration contains an account/order field.")
    if value.get("sampleIntervalSeconds") != 2:
        raise VerificationError("Fixed two-second observation cadence mismatch.")
    if value.get("phaseAClassification") != "CURRENT_SESSION_FUNCTIONAL_SMOKE_NOT_0400_BOUNDARY":
        raise VerificationError("Phase A classification would overclaim the missed 04:00 boundary.")
    if value.get("excelElevationPolicy") != "CURRENT_USER_PROVEN_75_CELL_RTD_SMOKE":
        raise VerificationError("Excel elevation policy mismatch.")
    if value.get("phaseADurationSeconds") != 1200:
        raise VerificationError("Fixed Phase A duration mismatch.")
    if value.get("checkpointDurationSeconds") != 120 or value.get("checkpointLeadSeconds") != 60:
        raise VerificationError("Fixed checkpoint window mismatch.")
    checkpoints = value.get("checkpoints")
    actual = (
        [(item.get("checkpointId"), item.get("scheduledAtEastern")) for item in checkpoints]
        if isinstance(checkpoints, list) and all(isinstance(item, dict) for item in checkpoints)
        else None
    )
    if actual != CHECKPOINTS:
        raise VerificationError("Fixed eight-checkpoint schedule mismatch.")


def validate_formula_manifest(value: Mapping[str, object], configuration: Mapping[str, object]) -> None:
    if value.get("taskId") != TASK_ID:
        raise VerificationError("Formula manifest task identity mismatch.")
    if value.get("timestampAuthority") != "LOCAL_OBSERVATION_TIMESTAMP_ONLY":
        raise VerificationError("RTD must not invent provider timestamps.")
    cells = value.get("cells")
    if not isinstance(cells, list):
        raise VerificationError("Formula cells are missing.")
    expected = len(configuration["symbols"]) * len(configuration["fields"])  # type: ignore[arg-type]
    if len(cells) != expected:
        raise VerificationError("Formula cell count mismatch.")
    for cell in cells:
        if not isinstance(cell, dict):
            raise VerificationError("Formula cell is invalid.")
        symbol, field = cell.get("symbol"), cell.get("field")
        expected_formula = f'=RTD("tos.rtd",,"{field}","{symbol}")'
        if field not in ALLOWED_FIELDS or cell.get("formula") != expected_formula:
            raise VerificationError("Formula manifest contains an unauthorized formula.")


def read_observations(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            value = json.loads(line)
            if not isinstance(value, dict) or value.get("taskId") != TASK_ID:
                raise VerificationError(f"Invalid observation at line {number}.")
            if value.get("timestampAuthority") != "LOCAL_OBSERVATION_TIMESTAMP_ONLY":
                raise VerificationError("Observation timestamp authority is invalid.")
            records.append(value)
    if not records:
        raise VerificationError("Checkpoint has no observations.")
    return records


def summarize_observations(records: Iterable[Mapping[str, object]]) -> dict[str, object]:
    series: dict[tuple[str, str], list[tuple[str, str | None]]] = defaultdict(list)
    sample_count = 0
    for record in records:
        sample_count += 1
        values = record.get("values")
        if not isinstance(values, list):
            raise VerificationError("Observation values are missing.")
        for item in values:
            if not isinstance(item, dict):
                raise VerificationError("Observation value is invalid.")
            symbol, field = str(item.get("symbol")), str(item.get("field"))
            if symbol not in SYMBOLS or field not in ALLOWED_FIELDS:
                raise VerificationError("Observation contains a forbidden symbol or field.")
            state = str(item.get("state"))
            if state not in {"PRESENT", "EMPTY", "ERROR"}:
                raise VerificationError("Observation state is invalid.")
            raw = item.get("value")
            series[(symbol, field)].append((state, None if raw is None else str(raw)))
    output: dict[str, object] = {}
    for (symbol, field), values in sorted(series.items()):
        present = [value for state, value in values if state == "PRESENT"]
        changes = sum(1 for left, right in zip(present, present[1:]) if left != right)
        if changes:
            classification = "LIVE_UPDATING"
        elif present:
            classification = "PRESENT_BUT_STATIC"
        elif any(state == "ERROR" for state, _ in values):
            classification = "ERROR"
        else:
            classification = "EMPTY"
        output[f"{symbol}:{field}"] = {
            "classification": classification,
            "samples": len(values),
            "presentSamples": len(present),
            "changeCount": changes,
            "firstValue": present[0] if present else None,
            "lastValue": present[-1] if present else None,
        }
    return {"sampleCount": sample_count, "series": output}


def scan_secrets(root: Path) -> dict[str, object]:
    files = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        files += 1
        payload = path.read_bytes()
        if any(pattern.search(payload) for pattern in SECRET_PATTERNS):
            raise VerificationError(f"Secret-shaped content found in {path.name}.")
    return {"status": "PASS", "filesScanned": files}


def verify(root: Path) -> dict[str, object]:
    configuration = load_json(root / "campaign-configuration.json")
    validate_configuration(configuration)
    formulas = load_json(root / "rtd-formula-manifest.json")
    validate_formula_manifest(formulas, configuration)
    checkpoint_summaries: dict[str, object] = {}
    for path in sorted(root.glob("checkpoints/*/observations.ndjson")):
        checkpoint_summaries[path.parent.name] = summarize_observations(read_observations(path))
    phase = root / "phase-a-current-session-functional-smoke" / "observations.ndjson"
    phase_summary = summarize_observations(read_observations(phase)) if phase.exists() else None
    return {
        "taskId": TASK_ID,
        "phaseA": phase_summary,
        "checkpoints": checkpoint_summaries,
        "secretScan": scan_secrets(root),
        "accountFields": 0,
        "orderFields": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(args.root.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED", "errorType": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
