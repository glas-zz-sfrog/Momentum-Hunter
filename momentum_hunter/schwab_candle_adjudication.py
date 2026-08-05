"""Deterministic offline adjudication of one sanitized Schwab candle proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from momentum_hunter.schwab_candle_contract import MAX_INPUT_BYTES
from momentum_hunter.schwab_candle_observer import OBSERVER_MODE


ADJUDICATION_SCHEMA_VERSION = 1
ALLOWED_STATUSES = {
    "VERIFIED",
    "DISPROVEN",
    "PARTIALLY_VERIFIED",
    "UNVERIFIED",
}
ALLOWED_RECOMMENDATIONS = {
    "ACCEPTED_FOR_R032_DESIGN",
    "ACCEPTED_WITH_LIMITATIONS",
    "REQUIRES_ADDITIONAL_OBSERVATION",
    "REJECTED_BY_PROVIDER_BEHAVIOR",
}
QUESTION_TEXT = (
    "Is CHART_EQUITY entitled for this account?",
    "Is one-minute OHLCV delivered for all three symbols?",
    "Is the current minute repeated provisionally, or emitted once?",
    "What event marks minute rollover, if any?",
    "What are observed first-arrival and settled-value latencies?",
    "Does volume appear incremental, cumulative, final, or unresolved?",
    "Do Streamer OHLCV and /pricehistory agree after reconciliation?",
    "Are older minutes corrected after apparent completion?",
    "What happens on a controlled client-side disconnect/reconnect?",
    "Are extended-hours/session semantics explicit?",
    "Are subscription acknowledgements and rejections deterministic?",
    "Is a practical subscription limit proven by official response evidence?",
)


class SchwabCandleAdjudicationError(RuntimeError):
    pass


def load_observation_proof(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        raw = path.expanduser().resolve().read_bytes()
    except OSError as exc:
        raise SchwabCandleAdjudicationError(
            "Candle observation proof could not be read."
        ) from exc
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise SchwabCandleAdjudicationError(
            "Candle observation proof was empty or exceeded the size limit."
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabCandleAdjudicationError(
            "Candle observation proof was not valid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise SchwabCandleAdjudicationError(
            "Candle observation proof must be a JSON object."
        )
    _require_valid_proof(payload)
    return payload, raw


def build_adjudication(proof: Mapping[str, object]) -> dict[str, object]:
    _require_valid_proof(proof)
    requested = tuple(str(value) for value in _list(proof, "requestedSymbols"))
    candles = [row for row in _list(proof, "candles") if isinstance(row, Mapping)]
    summaries = [
        row for row in _list(proof, "minuteSummaries") if isinstance(row, Mapping)
    ]
    updates = [
        row for row in _list(proof, "updateObservations") if isinstance(row, Mapping)
    ]
    subscription = _mapping(proof, "subscription")
    reconciliation = proof.get("streamHistoryReconciliation")
    if reconciliation is not None and not isinstance(reconciliation, Mapping):
        raise SchwabCandleAdjudicationError(
            "Candle proof reconciliation evidence had an invalid shape."
        )

    questions: list[dict[str, object]] = []
    entitlement = (
        "VERIFIED"
        if subscription.get("acknowledged") is True and candles
        else "DISPROVEN"
    )
    questions.append(
        _question(
            1,
            entitlement,
            "A redacted CHART_EQUITY SUBS acknowledgement and candle evidence were preserved."
            if entitlement == "VERIFIED"
            else "No accepted CHART_EQUITY subscription with candle evidence was preserved.",
        )
    )

    passed_symbols = {
        str(row.get("symbol"))
        for row in candles
        if row.get("status") == "PASS" and row.get("ohlcvComplete") is True
    }
    if passed_symbols == set(requested) and len(requested) == 3:
        delivery_status = "VERIFIED"
    elif passed_symbols:
        delivery_status = "PARTIALLY_VERIFIED"
    else:
        delivery_status = "DISPROVEN"
    questions.append(
        _question(
            2,
            delivery_status,
            f"Complete OHLCV observed for {len(passed_symbols)} of {len(requested)} requested symbols: "
            + (", ".join(sorted(passed_symbols)) or "none"),
        )
    )

    repeated_symbols = {
        str(row.get("symbol"))
        for row in summaries
        if _integer(row.get("updateCount")) > 1
    }
    if repeated_symbols == set(requested) and requested:
        repeated_status = "VERIFIED"
    elif repeated_symbols:
        repeated_status = "PARTIALLY_VERIFIED"
    else:
        repeated_status = "UNVERIFIED"
    questions.append(
        _question(
            3,
            repeated_status,
            "Repeated same-minute versions observed for: "
            + (", ".join(sorted(repeated_symbols)) or "none"),
        )
    )

    minutes_by_symbol: dict[str, set[str]] = defaultdict(set)
    for row in summaries:
        minutes_by_symbol[str(row.get("symbol"))].add(str(row.get("candleTimestamp")))
    rollover_symbols = {
        symbol for symbol, timestamps in minutes_by_symbol.items() if len(timestamps) >= 2
    }
    if rollover_symbols == set(requested) and requested:
        rollover_status = "PARTIALLY_VERIFIED"
        rollover_evidence = (
            "A new candle timestamp marked rollover for all symbols; no explicit provider "
            "finality marker was observed."
        )
    elif rollover_symbols:
        rollover_status = "PARTIALLY_VERIFIED"
        rollover_evidence = (
            "A new candle timestamp marked rollover for some symbols only: "
            + ", ".join(sorted(rollover_symbols))
        )
    else:
        rollover_status = "UNVERIFIED"
        rollover_evidence = "No symbol produced two distinct minute timestamps."
    questions.append(_question(4, rollover_status, rollover_evidence))

    first_arrival_latencies = _first_arrival_latencies(summaries)
    latency_status = "PARTIALLY_VERIFIED" if first_arrival_latencies else "UNVERIFIED"
    questions.append(
        _question(
            5,
            latency_status,
            (
                "Observed first-arrival latency range was "
                f"{min(first_arrival_latencies):.3f} to {max(first_arrival_latencies):.3f} seconds; "
                "settled-value finality remains unproven."
                if first_arrival_latencies
                else "No valid first-arrival latency could be derived."
            ),
        )
    )

    volume_status, volume_evidence = _adjudicate_volume(updates)
    questions.append(_question(6, volume_status, volume_evidence))

    reconciliation_status, reconciliation_evidence = _adjudicate_reconciliation(
        reconciliation,
        requested,
    )
    questions.append(_question(7, reconciliation_status, reconciliation_evidence))

    older_revision = _older_revision_observed(updates)
    questions.append(
        _question(
            8,
            "VERIFIED" if older_revision else "UNVERIFIED",
            "A revision to an older minute arrived after a newer minute."
            if older_revision
            else "No late revision to an older minute was exercised or observed.",
        )
    )
    questions.append(
        _question(
            9,
            "UNVERIFIED",
            "The bounded observer did not intentionally disconnect and resubscribe.",
        )
    )
    questions.append(
        _question(
            10,
            "UNVERIFIED",
            "Session labels were derived from timestamps; no explicit provider session flag was proven.",
        )
    )
    questions.append(
        _question(
            11,
            "PARTIALLY_VERIFIED" if subscription.get("acknowledged") is True else "UNVERIFIED",
            "One accepted SUBS acknowledgement was observed; rejection repeatability was not exercised.",
        )
    )
    questions.append(
        _question(
            12,
            "UNVERIFIED",
            "Three symbols were requested; no provider limit response was exercised.",
        )
    )

    recommendation = _recommendation(questions)
    adjudication: dict[str, object] = {
        "schemaVersion": ADJUDICATION_SCHEMA_VERSION,
        "adjudicationType": "ARGUS_R031B_LIVE_CANDLE_PROOF",
        "evaluatedAt": proof.get("evaluatedAt"),
        "sourceProofFingerprint": proof.get("proofFingerprint"),
        "sourceIdentity": proof.get("sourceIdentity"),
        "candidateSource": _mapping(_mapping(proof, "observationOptions"), "candidateSource"),
        "requestedSymbols": list(requested),
        "questions": questions,
        "disprovenAssumptions": [
            row["question"] for row in questions if row["status"] == "DISPROVEN"
        ],
        "unresolvedAssumptions": [
            row["question"]
            for row in questions
            if row["status"] in {"UNVERIFIED", "PARTIALLY_VERIFIED"}
        ],
        "recommendation": recommendation,
        "productionPersistenceAuthorized": False,
        "canonicalityGranted": False,
        "serviceInvoked": False,
        "engineHostInvoked": False,
        "wpfInvoked": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
    }
    adjudication["adjudicationFingerprint"] = _fingerprint(adjudication)
    _require_sanitized(adjudication)
    return adjudication


def render_markdown(adjudication: Mapping[str, object]) -> str:
    questions = _list(adjudication, "questions")
    lines = [
        "# ARGUS-R031B Live Candle Proof Adjudication",
        "",
        f"- Recommendation: `{adjudication['recommendation']}`",
        f"- Evaluated at: `{adjudication['evaluatedAt']}`",
        f"- Source proof: `{adjudication['sourceProofFingerprint']}`",
        f"- Symbols: `{', '.join(str(value) for value in adjudication['requestedSymbols'])}`",
        "- Production persistence: `NOT AUTHORIZED`",
        "- Order transmission: `UNAVAILABLE`",
        "",
        "## Adjudication",
        "",
        "| # | Question | Status | Evidence |",
        "|---:|---|---|---|",
    ]
    for row in questions:
        if not isinstance(row, Mapping):
            continue
        evidence = str(row["evidence"]).replace("|", "\\|")
        lines.append(
            f"| {row['id']} | {row['question']} | `{row['status']}` | {evidence} |"
        )
    lines.extend(["", "## Unresolved Assumptions", ""])
    unresolved = _list(adjudication, "unresolvedAssumptions")
    lines.extend(f"- {value}" for value in unresolved)
    if not unresolved:
        lines.append("- None")
    lines.extend(["", "## Safety Boundary", ""])
    lines.extend(
        [
            "- Read-only Schwab market-data observation only.",
            "- No production candle persistence.",
            "- No service, Engine Host, WPF, positions, orders, or transactions invoked.",
            "- This result does not authorize R032 integration or canonical runtime changes.",
            "",
        ]
    )
    return "\n".join(lines)


def write_adjudication_bundle(
    proof_path: Path,
    output_directory: Path,
) -> dict[str, object]:
    proof, proof_raw = load_observation_proof(proof_path)
    output_root = _safe_output_directory(output_directory)
    base = proof_path.stem
    adjudication_path = output_root / f"{base}-adjudication.json"
    markdown_path = output_root / f"{base}-adjudication.md"
    manifest_path = output_root / f"{base}-manifest.json"
    destinations = (adjudication_path, markdown_path, manifest_path)
    if any(path.exists() for path in destinations):
        raise SchwabCandleAdjudicationError(
            "R031B adjudication output already exists; overwrite is forbidden."
        )

    adjudication = build_adjudication(proof)
    adjudication_bytes = (
        json.dumps(adjudication, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    markdown_bytes = render_markdown(adjudication).encode("utf-8")
    candidate_source = _mapping(_mapping(proof, "observationOptions"), "candidateSource")
    manifest = {
        "schemaVersion": ADJUDICATION_SCHEMA_VERSION,
        "manifestType": "ARGUS_R031B_PROOF_MANIFEST",
        "evaluatedAt": proof.get("evaluatedAt"),
        "inputs": [
            {
                "role": "OBSERVATION_PROOF",
                "name": proof_path.name,
                "sha256": hashlib.sha256(proof_raw).hexdigest().upper(),
            },
            {
                "role": "HUNTER_CANDIDATE_REPORT",
                "name": candidate_source["reportName"],
                "sha256": candidate_source["reportSha256"],
                "contentCopied": False,
            },
        ],
        "outputs": [
            {
                "role": "ADJUDICATION_JSON",
                "name": adjudication_path.name,
                "sha256": hashlib.sha256(adjudication_bytes).hexdigest().upper(),
            },
            {
                "role": "ADJUDICATION_MARKDOWN",
                "name": markdown_path.name,
                "sha256": hashlib.sha256(markdown_bytes).hexdigest().upper(),
            },
        ],
        "recommendation": adjudication["recommendation"],
        "credentialsIncluded": False,
        "fullAccountIdentityIncluded": False,
        "productionDataIncluded": False,
        "orderTransmission": "UNAVAILABLE",
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    for path, content in (
        (adjudication_path, adjudication_bytes),
        (markdown_path, markdown_bytes),
        (manifest_path, manifest_bytes),
    ):
        _write_once(path, content)
    return {
        "schemaVersion": ADJUDICATION_SCHEMA_VERSION,
        "status": "PASS",
        "recommendation": adjudication["recommendation"],
        "adjudicationPath": str(adjudication_path),
        "markdownPath": str(markdown_path),
        "manifestPath": str(manifest_path),
        "productionDataWritten": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
    }


def _require_valid_proof(proof: Mapping[str, object]) -> None:
    if proof.get("observerMode") != OBSERVER_MODE or proof.get("liveNetworkCalled") is not True:
        raise SchwabCandleAdjudicationError(
            "Input was not a completed live R031 candle observation proof."
        )
    if (
        proof.get("nonPersisting") is not True
        or proof.get("productionDataWritten") is not False
        or proof.get("orderTransmission") != "UNAVAILABLE"
    ):
        raise SchwabCandleAdjudicationError(
            "Candle proof violated the nonpersisting safety boundary."
        )
    requested = _list(proof, "requestedSymbols")
    options = _mapping(proof, "observationOptions")
    candidate_source = _mapping(options, "candidateSource")
    candidate = candidate_source.get("candidateSymbol")
    if requested != ["SPY", "IWM", candidate] or len(requested) != 3:
        raise SchwabCandleAdjudicationError(
            "Candle proof did not bind the required benchmark and Hunter symbols."
        )
    fingerprint = proof.get("proofFingerprint")
    if not isinstance(fingerprint, str) or fingerprint != _fingerprint(
        {key: value for key, value in proof.items() if key != "proofFingerprint"}
    ):
        raise SchwabCandleAdjudicationError(
            "Candle observation proof fingerprint did not verify."
        )
    _require_sanitized(proof)


def _adjudicate_reconciliation(
    reconciliation: object,
    requested: Sequence[str],
) -> tuple[str, str]:
    if not isinstance(reconciliation, Mapping):
        return "UNVERIFIED", "No valid price-history comparison was preserved."
    comparable = _integer(reconciliation.get("comparableMinuteCount"))
    differences = _integer(reconciliation.get("differentMinuteCount"))
    rows = reconciliation.get("rows")
    compared_symbols = {
        str(row.get("symbol"))
        for row in rows
        if isinstance(row, Mapping) and row.get("status") in {"MATCH", "CORRECTED_OR_DIFFERENT"}
    } if isinstance(rows, list) else set()
    if differences:
        return (
            "DISPROVEN",
            f"{differences} of {comparable} comparable minutes differed from price history.",
        )
    if comparable and compared_symbols == set(requested):
        return "VERIFIED", f"All {comparable} comparable minutes matched across all symbols."
    if comparable:
        return (
            "PARTIALLY_VERIFIED",
            f"All {comparable} comparable minutes matched, but not all symbols were comparable.",
        )
    return "UNVERIFIED", "No Streamer minute had matching price-history evidence."


def _adjudicate_volume(updates: Sequence[Mapping[str, object]]) -> tuple[str, str]:
    volumes: dict[str, list[float]] = defaultdict(list)
    for row in updates:
        candle = row.get("candle")
        if not isinstance(candle, Mapping):
            continue
        value = candle.get("volume")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            volumes[str(row.get("minuteIdentity"))].append(float(value))
    repeated = [values for values in volumes.values() if len(values) > 1]
    if not repeated:
        return "UNVERIFIED", "No same-minute volume sequence was repeated."
    if any(any(current < previous for previous, current in zip(values, values[1:])) for values in repeated):
        return "DISPROVEN", "At least one repeated minute showed decreasing volume."
    return (
        "PARTIALLY_VERIFIED",
        "Observed repeated-minute volume was nondecreasing, consistent with cumulative minute volume; finality remains unproven.",
    )


def _older_revision_observed(updates: Sequence[Mapping[str, object]]) -> bool:
    greatest: dict[str, str] = {}
    for row in updates:
        candle = row.get("candle")
        if not isinstance(candle, Mapping):
            continue
        symbol = str(candle.get("symbol"))
        timestamp = str(candle.get("timestamp"))
        previous = greatest.get(symbol)
        if previous is not None and timestamp < previous and row.get("updateKind") == "REVISION":
            return True
        if previous is None or timestamp > previous:
            greatest[symbol] = timestamp
    return False


def _first_arrival_latencies(summaries: Sequence[Mapping[str, object]]) -> list[float]:
    from datetime import datetime

    values: list[float] = []
    for row in summaries:
        try:
            candle_at = datetime.fromisoformat(str(row.get("candleTimestamp")))
            observed_at = datetime.fromisoformat(str(row.get("firstObservedAt")))
            values.append((observed_at - candle_at).total_seconds())
        except ValueError:
            continue
    return values


def _recommendation(questions: Sequence[Mapping[str, object]]) -> str:
    statuses = {int(row["id"]): str(row["status"]) for row in questions}
    if statuses[1] == "DISPROVEN" or statuses[2] == "DISPROVEN":
        return "REJECTED_BY_PROVIDER_BEHAVIOR"
    if statuses[1] != "VERIFIED" or statuses[2] != "VERIFIED":
        return "REQUIRES_ADDITIONAL_OBSERVATION"
    if statuses[7] == "UNVERIFIED":
        return "REQUIRES_ADDITIONAL_OBSERVATION"
    if all(statuses[index] == "VERIFIED" for index in range(1, 13)):
        return "ACCEPTED_FOR_R032_DESIGN"
    return "ACCEPTED_WITH_LIMITATIONS"


def _question(identifier: int, status: str, evidence: str) -> dict[str, object]:
    if status not in ALLOWED_STATUSES:
        raise SchwabCandleAdjudicationError("Adjudication status was invalid.")
    return {
        "id": identifier,
        "question": QUESTION_TEXT[identifier - 1],
        "status": status,
        "evidence": evidence,
    }


def _mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise SchwabCandleAdjudicationError(f"Candle proof omitted {key} evidence.")
    return result


def _list(value: Mapping[str, object], key: str) -> list[object]:
    result = value.get(key)
    if not isinstance(result, list):
        raise SchwabCandleAdjudicationError(f"Candle proof omitted {key} evidence.")
    return result


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _fingerprint(value: Mapping[str, object]) -> str:
    serialized = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest().upper()


def _require_sanitized(value: Mapping[str, object]) -> None:
    serialized = json.dumps(value, separators=(",", ":"), sort_keys=True).lower()
    forbidden = (
        "access_token",
        "refresh_token",
        "client_secret",
        "accountnumber",
        "account_hash",
        "hashvalue",
        "authorization",
    )
    if any(term in serialized for term in forbidden):
        raise SchwabCandleAdjudicationError(
            "R031B evidence failed credential and account-identity redaction."
        )


def _safe_output_directory(path: Path) -> Path:
    destination = path.expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[1]
    try:
        destination.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise SchwabCandleAdjudicationError(
            "R031B adjudication output must remain outside the repository."
        )
    if not destination.is_dir():
        raise SchwabCandleAdjudicationError(
            "R031B adjudication output directory does not exist."
        )
    return destination


def _write_once(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError:
        raise SchwabCandleAdjudicationError(
            "R031B adjudication output already exists; overwrite is forbidden."
        ) from None
    except OSError as exc:
        raise SchwabCandleAdjudicationError(
            "R031B adjudication output could not be written safely."
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Adjudicate one sanitized R031B candle observation proof offline."
    )
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = write_adjudication_bundle(args.proof, args.output_directory)
    except SchwabCandleAdjudicationError as exc:
        result = {
            "schemaVersion": ADJUDICATION_SCHEMA_VERSION,
            "status": "FAIL",
            "failure": f"{type(exc).__name__}: {exc}",
            "productionDataWritten": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
