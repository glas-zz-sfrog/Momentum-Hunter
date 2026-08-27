"""Reanalyze the immutable Producer-001D packet with repaired forensic tooling."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


EXPECTED = {
    "completedBarEventCount": 259,
    "completedBarExactMatches": 259,
    "completedBarUnmatched": 0,
    "prematureCompletedBarEvents": 0,
    "naturalTradePlans": 4,
    "tradePlanOccurrences": 5,
    "planSymbols": ["BMNR", "BMNR", "CRM", "NVDA"],
    "prospectiveFloorViolations": 0,
    "endToEndRestart": True,
    "atomicity": "PASS",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="ascii")


def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        root = destination.resolve()
        for item in bundle.infolist():
            target = (destination / item.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeError("Evidence ZIP contains an escaping path.") from exc
        bundle.extractall(destination)


def _load_analyzer(repository: Path):
    os.environ["MH_CANARY_CANONICAL_ROOT"] = str(repository)
    path = repository / "tools" / "run_continuous_producer_001b_forensic_canary.py"
    spec = importlib.util.spec_from_file_location("producer_001e_repaired_analyzer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Repaired forensic analyzer could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_head(repository: Path) -> str:
    result = subprocess.run(
        ("git", "-C", str(repository), "rev-parse", "HEAD"),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "PACKAGED_SOURCE_NO_GIT"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument("--expected-evidence-sha256", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)

    evidence_zip = args.evidence_zip.resolve(strict=True)
    repository = args.repository_root.resolve(strict=True)
    output = args.output_root.resolve(strict=False)
    if output.exists():
        raise SystemExit("Output root already exists; replay is write-once.")
    before_hash = _sha256(evidence_zip)
    if before_hash != args.expected_evidence_sha256.strip().upper():
        raise SystemExit("Immutable 001D evidence ZIP hash did not match.")

    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="MomentumHunter-001E-Replay-") as directory:
        extracted = Path(directory)
        _safe_extract(evidence_zip, extracted)
        evidence = extracted / "evidence"
        if not (evidence / "campaign-config.json").is_file():
            raise RuntimeError("Immutable 001D packet omitted its evidence root.")
        analyzer = _load_analyzer(repository)
        result = analyzer._analyze(evidence)

    analysis = result["analysis"]
    timeline = result["timeline"]
    finality = analysis["completedBarFinality"]
    observed = {
        "completedBarEventCount": analysis["completedBarEventCount"],
        "completedBarExactMatches": finality["validCompletedEventCount"],
        "completedBarUnmatched": finality["unmatchedEventCount"],
        "prematureCompletedBarEvents": finality["prematureCompletedEventCount"],
        "naturalTradePlans": analysis["tradePlanCount"],
        "tradePlanOccurrences": analysis["tradePlanOccurrenceCount"],
        "planSymbols": sorted(item["symbol"] for item in timeline["tradePlans"]),
        "planIds": sorted(item["plan_id"] for item in timeline["tradePlans"]),
        "prospectiveFloorViolations": 0
        if analysis["prospectiveFloorPreserved"]
        else 1,
        "endToEndRestart": analysis["restartContinuity"],
        "atomicity": analysis["stageAccounting"]["atomicity"]["status"],
        "realProviderDiscovery": analysis["classifications"][
            "REAL_PROVIDER_DISCOVERY_PROVEN"
        ],
        "realSchwabBackfill": analysis["classifications"][
            "REAL_SCHWAB_BACKFILL_PROVEN"
        ],
        "naturalReadyAssessment": analysis["classifications"][
            "NATURAL_READY_ASSESSMENT_PROVEN"
        ],
        "naturalAcceptedComposition": analysis["classifications"][
            "ACCEPTED_COMPOSITION_CYCLE_PROVEN"
        ],
        "unknownInstrumentExecutionEligibility": analysis["classifications"][
            "UNKNOWN_INSTRUMENT_EXECUTION_ELIGIBILITY"
        ],
    }
    comparison = {
        key: {"expected": value, "observed": observed[key], "matches": observed[key] == value}
        for key, value in EXPECTED.items()
    }
    status = (
        "PASS"
        if all(item["matches"] for item in comparison.values())
        and observed["realProviderDiscovery"] == "YES"
        and observed["realSchwabBackfill"] == "YES"
        and observed["naturalReadyAssessment"] == "YES"
        and observed["naturalAcceptedComposition"] == "YES"
        and observed["unknownInstrumentExecutionEligibility"] == "BLOCKED"
        else "FAIL"
    )
    after_hash = _sha256(evidence_zip)
    summary = {
        "schemaVersion": 1,
        "status": status,
        "replayMode": "IMMUTABLE_001D_OFFLINE_REANALYSIS",
        "providerContact": False,
        "evidenceZip": str(evidence_zip),
        "evidenceZipSha256Before": before_hash,
        "evidenceZipSha256After": after_hash,
        "immutableEvidenceUnchanged": before_hash == after_hash,
        "repositoryUnderTest": str(repository),
        "repositoryGitHead": _git_head(repository),
        "observed": observed,
        "comparison": comparison,
        "stageAuthorities": {
            "discovery": "discovery evidence",
            "hotUniverse": "admission evidence",
            "backfill": "backfill ledger",
            "completedBars": "canonical candle + event evidence",
            "readiness": "attempt ledger",
            "composition": "composition records",
            "tradePlanOrNoPlan": "symbol-matched Producer records",
            "restart": "checkpoint + post-restart chronology",
            "atomicity": "atomicity proof",
            "prospectiveFloor": "provider/event chronology",
        },
    }
    _write(output / "replay-summary.json", summary)
    _write(output / "repaired-forensic-analysis.json", analysis)
    _write(output / "repaired-forensic-timeline.json", timeline)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
