"""Task 001A offline qualification receipts; never invokes providers or test suites.

Run with the approved external interpreter. Each invocation retains a new receipt
directory, including failures. The existing approved-environment test runner owns
focused/regression/full-suite execution; this tool only checks source custody or
rehearses the new facade with explicitly synthetic canonical fixture facts.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace


BASE = "a5dfbccbb3a77a78bb80412d30f06e610ccecd43"
BRANCH = "codex/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001A-V2"
PYTHON_SHA256 = "737A7E3B71E3578F8432ACC7DD88C452E593622C544BC13DA4789D69C63DA5AE"
ENVIRONMENT_FINGERPRINT = "D462F8E205939A6B22E8E48845CD9810C87EE66F8FD0FDF4D72B814644126450"
DESIGN_SIDECAR_SHA256 = "f40207a300b0d5ea91992e4e7f03491e3de031714a8928d01118a8a9b9ec4434"
OWNED = frozenset({
    "momentum_hunter/research_fact_export_v2.py",
    "tests/test_research_fact_export_v2.py",
    "tools/verify_shared_runtime_fact_export_001a.py",
    "tools/package_shared_runtime_fact_export_001a.py",
    "docs/argus-office/reports/architecture/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001A.md",
})
FIXTURES = (
    "tests/test_strategy_science_recorder_contract.py",
    "tests/test_strategy_science_recorder_eligibility_authority.py",
    "tests/test_strategy_science_recorder_coverage.py",
    "tests/test_strategy_science_recorder_outcomes.py",
)
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, check=False,
    )
    require(result.returncode == 0, f"Git read failed: {args!r}: {result.stderr.decode(errors='replace')}")
    return result.stdout


def safe_member(name: str) -> str:
    path = PurePosixPath(name)
    require(bool(name) and "\\" not in name and ":" not in name, "Unsafe package path")
    require(not path.is_absolute() and all(part not in {"", ".", ".."} for part in name.split("/")), "Unsafe package path")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    require(all(not part.endswith((".", " ")) and part.split(".", 1)[0].upper() not in reserved
                for part in path.parts), "Ambiguous Windows package path")
    return path.as_posix()


def sealed_design(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    sidecar = root / "artifact-checksums.sha256"
    raw = sidecar.read_bytes()
    require(sha256(raw) == DESIGN_SIDECAR_SHA256, "Historical V1 sidecar identity mismatch")
    entries = []
    seen: set[str] = set()
    for line in raw.decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        require(match is not None, "Malformed historical V1 checksum line")
        assert match is not None
        expected, name = match.groups()
        name = safe_member(name)
        require(name not in seen, "Duplicate historical V1 checksum entry")
        seen.add(name)
        path = root.joinpath(*PurePosixPath(name).parts)
        require(path.resolve(strict=True).is_relative_to(root) and not path.is_symlink(), "Historical V1 path escapes sealed root")
        actual = path.read_bytes()
        require(sha256(actual) == expected, f"Historical V1 bytes differ: {name}")
        entries.append({"path": name, "bytes": len(actual), "sha256": expected})
    require(len(entries) == 12, "Historical V1 artifact count differs")
    return {"root": str(root), "sidecarSha256": sha256(raw), "entries": entries,
            "historicalBytesMutated": False, "classification": "HISTORICAL_V1_DESIGN_READ_ONLY"}


def source_descriptor() -> dict[str, object]:
    branch = git("branch", "--show-current").decode().strip()
    require(branch == BRANCH, "Qualification is not running in the admitted task branch")
    git("merge-base", "--is-ancestor", BASE, "HEAD")
    changed = git("diff", "--name-only", BASE, "--").decode().splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").decode().splitlines()
    require(set(changed + untracked) <= OWNED, "A protected or unowned worktree path differs")
    base_paths = git("ls-tree", "-r", "--name-only", BASE).decode().splitlines()
    require(not (OWNED & set(base_paths)), "Owned addition unexpectedly existed at the admitted base")
    bindings = []
    for name in sorted(set(FIXTURES) | OWNED | {
        "momentum_hunter/continuous_research_export.py",
        "momentum_hunter/strategy_science_source_reader.py",
        "tools/run_approved_environment_tests.py",
    } | {p for p in base_paths if p.startswith("momentum_hunter/strategy_science_recorder/")}):
        path = ROOT / name
        if path.is_file():
            raw = path.read_bytes()
            binding = {"path": name, "bytes": len(raw), "sha256": sha256(raw)}
            if name in base_paths:
                original = git("show", f"{BASE}:{name}")
                require(raw == original or raw.replace(b"\r\n", b"\n") == original,
                        f"Canonical dependency changed: {name}")
                binding["baseGitBlob"] = git("rev-parse", f"{BASE}:{name}").decode().strip()
                binding["baseBlobSha256"] = sha256(original)
                binding["workingTreeLineEndingOnlyDifference"] = raw != original
            bindings.append(binding)
    return {"base": BASE, "baseTree": git("rev-parse", f"{BASE}^{{tree}}").decode().strip(), "branch": branch,
            "head": git("rev-parse", "HEAD").decode().strip(),
            "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
            "changedPaths": changed, "untrackedOwnedPaths": untracked,
            "sourceBindings": bindings, "protectedTrackedPathsUnchanged": True}


def rehearse(runtime: Path) -> dict[str, object]:
    # These are accepted synthetic fixture builders, never preserved runtime data.
    from momentum_hunter.research_fact_export_v2 import ResearchFactExporterV2
    from momentum_hunter.strategy_science_recorder import StrategyScienceRecorder
    from momentum_hunter.strategy_science_recorder.contract import (
        HORIZONS, REPAIRED_EXPORT_SCHEMA_VERSION, REPAIRED_SOURCE_CONTRACT,
        REPAIRED_SOURCE_CONTRACT_VERSION, SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
        parse_export_envelope_v1, parse_export_envelope_v2,
    )
    from tests import test_strategy_science_recorder_contract as fixture
    from tests.test_strategy_science_recorder_coverage import RecorderCoverageTests
    from tests.test_strategy_science_recorder_eligibility_authority import decision_payload_v2

    cases = []
    for label, owner, truncated in (
        ("standard", "fixture-owner", False),
        ("early-close", "fixture-secondary-producer", True),
    ):
        case_root = runtime / label
        case_root.mkdir()
        custody = case_root / "science"
        export = case_root / "producer"
        manifest = fixture.start_payload(**({"regular_session_close": "2026-09-01T13:35:00Z"} if truncated else {}))
        manifest["source_owner_namespace"] = owner
        discovery = fixture.discovery_payload()
        decision = decision_payload_v2()
        market = fixture.market_bar_payload()
        health = fixture.health_payload()
        source_facts = {"classification": "SYNTHETIC_CONTRACT_REHEARSAL", "fixtureBindings": list(FIXTURES),
                        "adaptations": {"sourceOwnerNamespace": owner, "earlyCloseFixture": truncated},
                        "start": manifest, "discovery": discovery, "decision": decision,
                        "market": market, "health": health}
        write_json(case_root / "source-facts.json", source_facts)

        def open_writer():
            return ResearchFactExporterV2(
                export, session_id=fixture.SESSION_ID, source_owner_identity=owner,
                source_interface_identity=f"{owner}-v2-offline",
                source_root_identity=fixture.SOURCE_ROOT_IDENTITY,
                schema_version=REPAIRED_EXPORT_SCHEMA_VERSION,
                source_contract=REPAIRED_SOURCE_CONTRACT,
                source_contract_version=REPAIRED_SOURCE_CONTRACT_VERSION,
                offline_reference_profile=SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
                science_custody_roots=(custody,), protected_roots=(ROOT,),
            ).initialize()

        writer = open_writer()
        try:
            writer.start(manifest, stream_id="session-stream", source_event_id="session-start",
                         emitted_at=fixture.BASE_TIME,
                         event_time=fixture.BASE_TIME, effective_known_at=fixture.BASE_TIME)
            writer.discovery_cycle(discovery["discovery_cycle"], discovery["observations"],
                                   stream_id="discovery-stream", source_event_id="discovery-1", emitted_at=fixture.DISCOVERY_TIME)
            writer.decision(decision["decision_event"], reference_plan=decision["reference_plan"],
                            stream_id="decision-stream", source_event_id="decision-1", emitted_at=fixture.DECISION_TIME)
            writer.market_snapshot(market["market_snapshot"], stream_id="market-stream", source_event_id="bar-1", emitted_at=fixture.BAR_TIME)
            writer.provider_health(health["provider_health_event"], stream_id="health-stream", source_event_id="health-1", emitted_at=fixture.BAR_TIME)
            before = writer.published()
        finally:
            writer.close()
        restarted = open_writer()
        try:
            readback = restarted.published()
            require(tuple(p.raw_bytes for p in before) == tuple(p.raw_bytes for p in readback), "Restart changed exact producer bytes")
        finally:
            restarted.close()
        parsed = [parse_export_envelope_v2(p.raw_bytes) for p in readback]
        expected_payloads = [manifest, discovery, decision, market, health]
        require([p.payload for p in parsed] == expected_payloads, "Facade changed supplied facts")
        producer_decision = readback[2].raw_bytes
        recorder = StrategyScienceRecorder(custody, source_root_identity=fixture.SOURCE_ROOT_IDENTITY,
                                          writer_instance_id=f"001a-{label}", clock=fixture.FixedClock())
        try:
            accepted = [recorder.accept(p.raw_bytes) for p in readback]
            require(all(p.status == "ACCEPTED" for p in accepted), "Science did not accept exact V2 bytes")
            original_decision = fixture.stored_records(custody, "decision-event")[0]
            eligibility = fixture.stored_records(custody, "science-eligibility")[0][1]["science_eligibility"]
            context = SimpleNamespace(root=custody, eligibility_sha=eligibility["commitment_payload_sha256"])
            outcome_rows = []
            previous = "0" * 64
            semantics = ("PLUS_5M",) if truncated else tuple(HORIZONS)
            for sequence, semantic in enumerate(semantics, 1):
                payload = RecorderCoverageTests.outcome_payload(
                    context, semantic=semantic,
                    outcome_id=fixture.identity("OUTCOME_OBSERVATION_ID", f"001a-{label}-{semantic}"),
                    present_value=semantic == "PLUS_5M" and not truncated,
                    nonpresent_state="SESSION_TRUNCATED" if truncated else "UNAVAILABLE",
                )
                raw = fixture.outcome_attachment(payload, event_id=f"001a-{label}-{semantic}",
                                                 sequence=sequence, previous=previous,
                                                 observed_at="2026-09-01T20:01:00Z")
                result = recorder.append_outcome(raw)
                require(result.status == "ACCEPTED", "Science outcome attachment was rejected")
                (case_root / f"outcome-input-{sequence}.json").write_bytes(raw)
                outcome_rows.append({"semantic": semantic, "state": payload["outcome_state"],
                                     "attachmentSha256": sha256(raw), "status": result.status,
                                     "decisionPayloadSha256": payload["decision_payload_sha256"],
                                     "eligibilityCommitmentSha256": payload["eligibility_commitment_sha256"]})
                previous = sha256(raw)
            require(original_decision[0].read_bytes() == original_decision[2], "Science decision bytes changed after outcome")
            require((export / readback[2].relative_path).read_bytes() == producer_decision, "Producer decision bytes changed after outcome")
            verification = recorder.verify(fixture.SESSION_ID)
            require(verification.all_hashes_valid, "Science custody verification failed")
            families = sorted({json.loads(p.read_bytes()).get("record_type") for p in custody.rglob("*.payload.json")})
            require(set(("discovery-cycle", "candidate-observation", "decision-event", "market-snapshot",
                         "reference-plan", "provider-health-event", "outcome-observation")) <= set(families), "Seven-family custody coverage incomplete")
            cases.append({"case": label, "sourceOwner": owner, "classification": "SYNTHETIC_CONTRACT_REHEARSAL",
                          "sourcePayloadEquivalence": True, "restartExactByteEquivalence": True,
                          "discoveryCyclesSupplied": 1, "discoveryCyclesExported": 1,
                          "denominatorRowsSupplied": 1, "denominatorRowsExported": len(parsed[1].payload["observations"]),
                          "producerDecisionSha256BeforeAndAfter": sha256(producer_decision),
                          "scienceDecisionSha256BeforeAndAfter": sha256(original_decision[2]),
                          "outcomes": outcome_rows, "custodyFamilies": families,
                          "custodyVerification": asdict(verification),
                          "exports": [{"path": p.relative_path, "bytes": len(p.raw_bytes), "sha256": p.raw_sha256} for p in readback]})
        finally:
            recorder.close()
    legacy = fixture.start_envelope()
    legacy_hash = sha256(legacy)
    require(parse_export_envelope_v1(legacy).schema_version == "1.0.0" and sha256(legacy) == legacy_hash, "Canonical V1 fixture readability failed")
    return {"classification": "SYNTHETIC_CONTRACT_REHEARSAL", "cases": cases,
            "historicalV1FixtureReadabilitySha256": legacy_hash,
            "limitations": ["No natural runtime owner, provider truth, historical capture, scheduler or activation qualification.",
                            "PLUS_5M uses an existing synthetic bar; 15/30/60/close and MFE/MAE retain explicit UNAVAILABLE states.",
                            "Early-close truncation uses the existing accepted synthetic fixture; no historical identities or chronology are reconstructed.",
                            "Full-session coverage, zero/partial/failure cycle matrices, fault injection and FINAL gates belong to the separately recorded test suites."],
            "captureTiming": {"TARGET_TIME": "UNKNOWN", "ACTUAL_TIME": "UNKNOWN", "DELTA": "UNKNOWN", "CAPTURE_CLASSIFICATION": "SYNTHETIC_CONTRACT_REHEARSAL"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("sources", "compile", "rehearse"))
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--v1-design-root", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_root.resolve(strict=True)
    require(not evidence.is_relative_to(ROOT) and not ROOT.is_relative_to(evidence), "Evidence must be isolated from source")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    command_root = evidence / "commands" / f"{args.mode}-{stamp}"
    command_root.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    monotonic = time.monotonic()
    receipt: dict[str, object] = {"command": [sys.executable, *sys.argv], "startedAt": started,
                                 "mode": args.mode, "status": "FAIL", "returnCode": 1}
    stdout, stderr = io.StringIO(), io.StringIO()
    code = 1
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            sys.path.insert(0, str(ROOT))
            from tools.run_approved_environment_tests import environment_descriptor
            environment = environment_descriptor()
            receipt["approvedEnvironment"] = environment
            require(environment["executableSha256"] == PYTHON_SHA256, "Invoking Python binary is not the approved executable")
            require(environment["environmentFingerprint"] == ENVIRONMENT_FINGERPRINT, "Approved environment fingerprint changed")
            receipt["sourcesBefore"] = source_descriptor()
            receipt["sealedV1DesignBefore"] = sealed_design(args.v1_design_root)
            if args.mode == "compile":
                compiled = []
                for binding in receipt["sourcesBefore"]["sourceBindings"]:
                    path = ROOT / binding["path"]
                    if path.suffix == ".py":
                        compile(path.read_bytes(), str(path), "exec")
                        compiled.append(binding)
                from momentum_hunter import research_fact_export_v2
                imported = Path(research_fact_export_v2.__file__).resolve(strict=True)
                require(imported == ROOT / "momentum_hunter/research_fact_export_v2.py", "Facade import loaded another checkout")
                receipt["compileImport"] = {"compiledSources": compiled, "importedFacade": str(imported), "bytecodeFilesWritten": False}
            if args.mode == "rehearse":
                runtime = evidence / "runtime" / stamp
                runtime.mkdir(parents=True, exist_ok=False)
                receipt["runtimeRoot"] = str(runtime)
                receipt["rehearsal"] = rehearse(runtime)
            receipt["sourcesAfter"] = source_descriptor()
            receipt["sealedV1DesignAfter"] = sealed_design(args.v1_design_root)
            require(receipt["sourcesBefore"] == receipt["sourcesAfter"], "Source identity drifted during qualification")
            require(receipt["sealedV1DesignBefore"] == receipt["sealedV1DesignAfter"], "Historical design drifted during qualification")
            receipt["status"], receipt["returnCode"], code = "PASS", 0, 0
        except Exception:
            traceback.print_exc()
    for name, data in (("stdout", stdout.getvalue()), ("stderr", stderr.getvalue())):
        raw = data.encode("utf-8")
        (command_root / f"{name}.txt").write_bytes(raw)
        receipt[name] = {"path": f"{name}.txt", "bytes": len(raw), "sha256": sha256(raw)}
    receipt["completedAt"] = datetime.now(timezone.utc).isoformat()
    receipt["elapsedSeconds"] = round(time.monotonic() - monotonic, 6)
    write_json(command_root / "receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "receipt": str(command_root / "receipt.json")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
