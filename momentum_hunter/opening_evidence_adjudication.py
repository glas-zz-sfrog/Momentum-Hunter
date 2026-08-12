from __future__ import annotations

"""Write-once adjudication for invalid opening-evidence decisions."""

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from momentum_hunter.time_utils import now_central


ADJUDICATION_SCHEMA_VERSION = 2
DECISION_INVALID = "INVALID"
SYSTEM_DATA_CONTRACT_FAILURE = "SYSTEM_DATA_CONTRACT_FAILURE"
PROVIDER_SCHEMA_DRIFT = "PROVIDER_SCHEMA_DRIFT"
DECISION_NOT_REACHED = "DECISION_NOT_REACHED"
RAW_COUNTS_NOT_PRESERVED = "RAW_COUNTS_NOT_PRESERVED"
ROOT_CAUSE_INFERRED = "ROOT_CAUSE_INFERRED"
ROOT_CAUSE_STRONGLY_CORROBORATED = "ROOT_CAUSE_STRONGLY_CORROBORATED"
_ROOT_CAUSE_STATUSES = frozenset(
    {ROOT_CAUSE_INFERRED, ROOT_CAUSE_STRONGLY_CORROBORATED}
)
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_VULNERABLE_CHANGE_LOOKUP = 'percent_change=parse_percent(values.get("Change", ""))'


class OpeningEvidenceAdjudicationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpeningEvidenceCase:
    market_date: str
    parser_git_head: str
    capture_path: Path
    log_path: Path
    report_path: Path
    paper_decision_paths: tuple[Path, ...] = ()
    root_cause_status: str = ROOT_CAUSE_INFERRED


def adjudicate_opening_evidence(
    cases: Sequence[OpeningEvidenceCase],
    *,
    repository_root: Path,
    adjudicated_at: datetime | None = None,
    superseded_adjudication_path: Path | None = None,
) -> dict[str, object]:
    if not cases:
        raise OpeningEvidenceAdjudicationError("At least one opening case is required.")
    observed_dates: set[str] = set()
    results = []
    for case in cases:
        if case.market_date in observed_dates:
            raise OpeningEvidenceAdjudicationError("Opening case dates must be unique.")
        observed_dates.add(case.market_date)
        results.append(_adjudicate_case(case, repository_root=repository_root))

    payload: dict[str, object] = {
        "schemaVersion": ADJUDICATION_SCHEMA_VERSION,
        "classification": SYSTEM_DATA_CONTRACT_FAILURE,
        "decisionValidity": DECISION_INVALID,
        "failureClass": SYSTEM_DATA_CONTRACT_FAILURE,
        "decisionState": DECISION_NOT_REACHED,
        "rootCauseCandidate": PROVIDER_SCHEMA_DRIFT,
        "rootCauseConfirmed": False,
        "adjudicatedAt": (adjudicated_at or now_central()).isoformat(),
        "historicalArtifactsMutated": False,
        "retrospectiveTradesCreated": False,
        "rawCountStatus": RAW_COUNTS_NOT_PRESERVED,
        "cases": results,
    }
    if superseded_adjudication_path is not None:
        payload["supersedes"] = _superseded_adjudication_evidence(
            superseded_adjudication_path,
            results,
        )
    payload["fingerprint"] = _fingerprint(payload)
    return payload


def write_adjudication(
    payload: Mapping[str, object],
    *,
    json_path: Path,
    markdown_path: Path,
) -> None:
    expected = dict(payload)
    if expected.get("fingerprint") != _fingerprint_without_fingerprint(expected):
        raise OpeningEvidenceAdjudicationError("Adjudication fingerprint is invalid.")
    json_bytes = (json.dumps(expected, indent=2, sort_keys=True) + "\n").encode("utf-8")
    markdown_bytes = (_render_markdown(expected) + "\n").encode("utf-8")
    _require_same_or_available(json_path, json_bytes)
    _require_same_or_available(markdown_path, markdown_bytes)
    _write_same_or_fail(json_path, json_bytes)
    _write_same_or_fail(markdown_path, markdown_bytes)


def _adjudicate_case(
    case: OpeningEvidenceCase,
    *,
    repository_root: Path,
) -> dict[str, object]:
    if case.root_cause_status not in _ROOT_CAUSE_STATUSES:
        raise OpeningEvidenceAdjudicationError("Root-cause status is not supported.")
    if not _GIT_SHA.fullmatch(case.parser_git_head):
        raise OpeningEvidenceAdjudicationError("Each parser Git head must be a full lowercase SHA.")
    capture = _load_object(case.capture_path, "capture")
    report = _load_object(case.report_path, "trade-plan report")
    log_text = _read_text(case.log_path, "capture log")
    if capture.get("session") != "opening" or capture.get("provider") != "finviz":
        raise OpeningEvidenceAdjudicationError("The source is not a Finviz opening capture.")
    capture_candidates = capture.get("candidates")
    report_candidates = report.get("candidates")
    if not isinstance(capture_candidates, list) or capture_candidates:
        raise OpeningEvidenceAdjudicationError("The source capture is not zero-candidate evidence.")
    if not isinstance(report_candidates, list) or report_candidates:
        raise OpeningEvidenceAdjudicationError("The source report is not zero-candidate evidence.")
    if "Candidates: 0" not in log_text or "ExitCode: 0" not in log_text:
        raise OpeningEvidenceAdjudicationError("The capture log does not prove a terminal recorded zero.")
    parser_source = _git_file(
        repository_root,
        case.parser_git_head,
        "momentum_hunter/providers.py",
    )
    compact_source = "".join(parser_source.split())
    if "".join(_VULNERABLE_CHANGE_LOOKUP.split()) not in compact_source:
        raise OpeningEvidenceAdjudicationError(
            "The supplied Git head does not contain the known Change-header vulnerability."
        )

    paper_evidence = []
    for path in case.paper_decision_paths:
        payload = _load_object(path, "Paper decision")
        decision = payload.get("decision")
        if not isinstance(decision, Mapping):
            raise OpeningEvidenceAdjudicationError("Paper decision evidence is malformed.")
        decision_fingerprint = str(decision.get("fingerprint", ""))
        reasons = decision.get("reasons")
        if (
            decision.get("classification") != "NO_TRADE"
            or decision.get("candidatesEvaluated") != 0
            or decision.get("paperOrderCreated") is not False
            or reasons != ["PAPER_NO_CANDIDATES_IN_PROSPECTIVE_REPORT"]
            or decision_fingerprint != _fingerprint_without_fingerprint(decision)
        ):
            raise OpeningEvidenceAdjudicationError(
                "Paper evidence is not the affected zero-candidate no-order outcome."
            )
        paper_evidence.append(
            {
                "path": str(path.resolve()),
                "sha256": _sha256(path),
                "decisionCycleId": str(decision.get("decisionCycleId", "")),
                "sampleId": str(decision.get("sampleId", "")),
                "originalFingerprint": decision_fingerprint,
                "originalClassification": "NO_TRADE",
                "adjudicatedDecisionState": DECISION_NOT_REACHED,
                "countsTowardAnySample": False,
                "providerCalls": list(decision.get("providerCalls", [])),
                "paperOrderCreated": False,
            }
        )

    return {
        "marketDate": case.market_date,
        "classification": SYSTEM_DATA_CONTRACT_FAILURE,
        "decisionValidity": DECISION_INVALID,
        "failureClass": SYSTEM_DATA_CONTRACT_FAILURE,
        "decisionState": DECISION_NOT_REACHED,
        "rootCauseCandidate": PROVIDER_SCHEMA_DRIFT,
        "rootCauseStatus": case.root_cause_status,
        "rootCauseConfirmed": False,
        "rootCauseEvidence": _root_cause_evidence(case.root_cause_status),
        "provider": "finviz",
        "parserGitHead": case.parser_git_head,
        "parserLookup": "Change",
        "knownReplacementHeaderAtRepair": "Change %",
        "rawProviderRows": None,
        "parsedRows": None,
        "qualifiedRowsRecorded": 0,
        "qualifiedRowsAuthoritative": False,
        "missingEvidenceReason": RAW_COUNTS_NOT_PRESERVED,
        "capture": _file_evidence(case.capture_path),
        "captureLog": _file_evidence(case.log_path),
        "tradePlanReport": _file_evidence(case.report_path),
        "paperDecisions": paper_evidence,
    }


def _render_markdown(payload: Mapping[str, object]) -> str:
    lines = [
        "# Opening Evidence Adjudication",
        "",
        f"- Classification: `{payload['classification']}`",
        f"- Decision validity: `{payload['decisionValidity']}`",
        f"- Failure class: `{payload['failureClass']}`",
        f"- Decision state: `{payload['decisionState']}`",
        f"- Root-cause candidate: `{payload['rootCauseCandidate']}`",
        f"- Root cause confirmed: `{str(payload['rootCauseConfirmed']).lower()}`",
        f"- Raw count status: `{payload['rawCountStatus']}`",
        f"- Historical artifacts mutated: `{str(payload['historicalArtifactsMutated']).lower()}`",
        f"- Fingerprint: `{payload['fingerprint']}`",
        "",
        "The original artifacts remain unchanged. Missing historical raw and parsed row counts were not reconstructed.",
        "",
        "| Date | Recorded candidates | Decision state | Root-cause status | Paper decisions |",
        "| --- | ---: | --- | --- | ---: |",
    ]
    for case in payload.get("cases", []):
        assert isinstance(case, Mapping)
        lines.append(
            f"| {case['marketDate']} | {case['qualifiedRowsRecorded']} | "
            f"`{case['decisionState']}` | `{case['rootCauseStatus']}` | "
            f"{len(case.get('paperDecisions', []))} |"
        )
    return "\n".join(lines)


def _root_cause_evidence(root_cause_status: str) -> list[str]:
    evidence = [
        "ZERO_CANDIDATE_OUTPUT_PRESERVED",
        "PINNED_VULNERABLE_PARSER_CONFIRMED",
        "RAW_PROVIDER_PAYLOAD_NOT_PRESERVED",
    ]
    if root_cause_status == ROOT_CAUSE_STRONGLY_CORROBORATED:
        evidence.append("SAME_DAY_NONPERSISTING_AB_PROOF")
    else:
        evidence.append("RETROSPECTIVE_SEQUENCE_INFERENCE")
    return evidence


def _superseded_adjudication_evidence(
    path: Path,
    corrected_cases: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    original = _load_object(path, "superseded adjudication")
    fingerprint = str(original.get("fingerprint", ""))
    if fingerprint != _fingerprint_without_fingerprint(original):
        raise OpeningEvidenceAdjudicationError(
            "The superseded adjudication fingerprint is invalid."
        )
    original_cases = original.get("cases")
    if not isinstance(original_cases, list):
        raise OpeningEvidenceAdjudicationError("The superseded adjudication has no cases.")
    original_bindings = {
        _case_source_binding(case) for case in original_cases if isinstance(case, Mapping)
    }
    corrected_bindings = {_case_source_binding(case) for case in corrected_cases}
    if original_bindings != corrected_bindings or len(original_bindings) != len(original_cases):
        raise OpeningEvidenceAdjudicationError(
            "The superseded adjudication does not bind the same source evidence."
        )
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "schemaVersion": original.get("schemaVersion"),
        "fingerprint": fingerprint,
        "reason": "ROOT_CAUSE_CERTAINTY_OVERSTATED",
    }


def _case_source_binding(case: Mapping[str, object]) -> tuple[object, ...]:
    paper = case.get("paperDecisions", [])
    paper_hashes = tuple(
        sorted(
            str(item.get("sha256", ""))
            for item in paper
            if isinstance(item, Mapping)
        )
    )
    return (
        case.get("marketDate"),
        _nested_value(case, "capture", "sha256"),
        _nested_value(case, "captureLog", "sha256"),
        _nested_value(case, "tradePlanReport", "sha256"),
        case.get("parserGitHead"),
        paper_hashes,
    )


def _nested_value(payload: Mapping[str, object], key: str, nested_key: str) -> object:
    nested = payload.get(key)
    return nested.get(nested_key) if isinstance(nested, Mapping) else None


def _load_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OpeningEvidenceAdjudicationError(f"{label} could not be read.") from exc
    if not isinstance(payload, dict):
        raise OpeningEvidenceAdjudicationError(f"{label} must be a JSON object.")
    return payload


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise OpeningEvidenceAdjudicationError(f"{label} could not be read.") from exc


def _git_file(repository_root: Path, git_head: str, relative_path: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "show", f"{git_head}:{relative_path}"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise OpeningEvidenceAdjudicationError("Parser source identity could not be verified.")
    return completed.stdout


def _file_evidence(path: Path) -> dict[str, object]:
    return {"path": str(path.resolve()), "sha256": _sha256(path), "bytes": path.stat().st_size}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _fingerprint(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()


def _fingerprint_without_fingerprint(payload: Mapping[str, object]) -> str:
    return _fingerprint({key: value for key, value in payload.items() if key != "fingerprint"})


def _write_same_or_fail(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_same_or_available(path, content)
    if path.exists():
        return
    path.write_bytes(content)


def _require_same_or_available(path: Path, content: bytes) -> None:
    if path.exists() and path.read_bytes() != content:
        raise OpeningEvidenceAdjudicationError(f"Conflicting write-once output exists: {path}.")


def _case(value: str) -> OpeningEvidenceCase:
    parts = value.split("|", 6)
    if len(parts) != 7:
        raise argparse.ArgumentTypeError(
            "Case must be DATE|GIT_HEAD|CAPTURE|LOG|REPORT|PAPER_PATHS|ROOT_CAUSE_STATUS."
        )
    paper = tuple(Path(item) for item in parts[5].split(";") if item)
    return OpeningEvidenceCase(
        parts[0],
        parts[1],
        Path(parts[2]),
        Path(parts[3]),
        Path(parts[4]),
        paper,
        parts[6],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--case", type=_case, action="append", required=True)
    parser.add_argument("--supersedes", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = adjudicate_opening_evidence(
            args.case,
            repository_root=args.repository_root,
            superseded_adjudication_path=args.supersedes,
        )
        write_adjudication(payload, json_path=args.json_output, markdown_path=args.markdown_output)
    except OpeningEvidenceAdjudicationError as exc:
        print(f"Opening evidence adjudication stopped safely: {exc}")
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
