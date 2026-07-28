from __future__ import annotations

"""Run synthetic, nonmutating negative controls for the Shadow opening gate."""

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_opening import (
    ShadowOpeningSafetyError,
    build_https_clock_skew_proof,
    build_shadow_handoff_receipt,
    classify_opening_heartbeat,
    clock_skew_findings,
)
from momentum_hunter.time_utils import now_central


DRILL_SCHEMA_VERSION = 1
DRILL_TYPE = "SHADOW_OPENING_NEGATIVE_CONTROLS"
REPORT_BASENAME = "shadow-opening-negative-controls-latest"


@dataclass(frozen=True)
class StateFileEvidence:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ProtectedStateSnapshot:
    digest: str
    files: tuple[StateFileEvidence, ...]
    forbidden_artifacts: tuple[str, ...]


@dataclass(frozen=True)
class DrillScenarioResult:
    name: str
    status: str
    expected: str
    observed: str
    findings: tuple[str, ...]
    protected_state_unchanged: bool
    forbidden_artifacts_absent: bool
    before_digest: str
    after_digest: str


def snapshot_protected_shadow_state(
    shadow_state_directory: Path,
) -> ProtectedStateSnapshot:
    root = shadow_state_directory.resolve()
    paths = (
        [path for path in root.rglob("*") if path.is_file()]
        if root.is_dir()
        else []
    )

    evidence: list[StateFileEvidence] = []
    forbidden: list[str] = []
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        evidence.append(
            StateFileEvidence(
                path=relative,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
        if relative != "shadow-sample-activation.json":
            forbidden.append(relative)

    canonical = json.dumps(
        [asdict(item) for item in evidence],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return ProtectedStateSnapshot(
        digest=hashlib.sha256(canonical).hexdigest(),
        files=tuple(evidence),
        forbidden_artifacts=tuple(sorted(forbidden)),
    )


def run_structured_host_failure() -> tuple[bool, str, tuple[str, ...]]:
    cycle = SimpleNamespace(
        accepted=False,
        code="COLLECTION_FAILED",
        command_id="synthetic-host-failure",
        payload={"retryable": False},
        snapshot={
            "identity": {
                "hostInstanceId": "synthetic-host",
                "processId": 1,
                "protocolVersion": "1.0",
            }
        },
    )
    try:
        build_shadow_handoff_receipt(
            report_path=Path("synthetic-shadow-report.json"),
            report_sha256="a" * 64,
            capture_id="synthetic-capture",
            cycle=cycle,
            recorded_at=datetime(2026, 7, 28, 13, 35, tzinfo=UTC),
        )
    except ShadowOpeningSafetyError as exc:
        message = str(exc)
        passed = "did not accept" in message
        return (
            passed,
            "HOST_FAILURE_BLOCKED_NO_HANDOFF",
            (message,),
        )
    return (
        False,
        "UNSAFE_HANDOFF_ACCEPTED",
        ("Structured Engine Host failure unexpectedly produced a handoff.",),
    )


def run_excessive_clock_skew() -> tuple[bool, str, tuple[str, ...]]:
    request_started = datetime(2026, 7, 28, 13, 35, 6, tzinfo=UTC)
    response_received = request_started + timedelta(milliseconds=100)
    proof = build_https_clock_skew_proof(
        request_started_at=request_started,
        response_received_at=response_received,
        remote_date_header="Tue, 28 Jul 2026 13:35:00 GMT",
        source_identity="synthetic-negative-control:https-date",
    )
    findings = clock_skew_findings(
        proof,
        evaluated_at=response_received,
    )
    threshold_blocked = any(
        "five-second gate" in finding
        or "5000 milliseconds" in finding
        for finding in (*proof["findings"], *findings)
    )
    passed = (
        proof["status"] == "BLOCKED"
        and threshold_blocked
        and bool(findings)
    )
    return (
        passed,
        "CLOCK_GATE_BLOCKED"
        if passed
        else "CLOCK_GATE_DID_NOT_BLOCK",
        tuple(dict.fromkeys((*proof["findings"], *findings))),
    )


def run_still_running_observer() -> tuple[bool, str, tuple[str, ...]]:
    state = classify_opening_heartbeat(
        task_running=True,
        process_alive=True,
        retry_pending=False,
        final_result_available=False,
        final_result_succeeded=False,
        proof_complete=False,
        handoff_complete=False,
    )
    passed = state.outcome == "IN_PROGRESS" and not state.retire_heartbeat
    return (
        passed,
        f"{state.outcome}_HEARTBEAT_RETAINED"
        if passed
        else "OBSERVER_CLASSIFICATION_UNSAFE",
        (state.reason,),
    )


def run_shadow_opening_negative_controls(
    *,
    shadow_state_directory: Path = DATA_DIR / "shadow-trading",
    evaluated_at: datetime | None = None,
) -> dict[str, object]:
    evaluated_at = evaluated_at or now_central()
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("Drill evaluation time must include a UTC offset.")
    selected = (
        (
            "structured_engine_host_failure",
            "A rejected Engine Host cycle creates no semantic handoff.",
            run_structured_host_failure,
        ),
        (
            "clock_skew_over_five_seconds",
            "Clock skew plus uncertainty above five seconds blocks the gate.",
            run_excessive_clock_skew,
        ),
        (
            "observer_sees_opening_still_running",
            "A still-running opening remains IN_PROGRESS and retains its observer.",
            run_still_running_observer,
        ),
    )
    initial = snapshot_protected_shadow_state(shadow_state_directory)
    results: list[DrillScenarioResult] = []
    for name, expected, runner in selected:
        before = snapshot_protected_shadow_state(shadow_state_directory)
        try:
            scenario_passed, observed, findings = runner()
        except Exception as exc:
            scenario_passed = False
            observed = "SCENARIO_ERROR"
            findings = (f"{type(exc).__name__}: {exc}",)
        after = snapshot_protected_shadow_state(shadow_state_directory)
        state_unchanged = before.digest == after.digest
        forbidden_absent = (
            not before.forbidden_artifacts
            and not after.forbidden_artifacts
        )
        passed = (
            scenario_passed
            and state_unchanged
            and forbidden_absent
        )
        results.append(
            DrillScenarioResult(
                name=name,
                status="PASS" if passed else "FAIL",
                expected=expected,
                observed=observed,
                findings=tuple(findings),
                protected_state_unchanged=state_unchanged,
                forbidden_artifacts_absent=forbidden_absent,
                before_digest=before.digest,
                after_digest=after.digest,
            )
        )

    final = snapshot_protected_shadow_state(shadow_state_directory)
    overall_pass = (
        len(results) == 3
        and all(result.status == "PASS" for result in results)
        and initial.digest == final.digest
        and not initial.forbidden_artifacts
        and not final.forbidden_artifacts
    )
    return {
        "schemaVersion": DRILL_SCHEMA_VERSION,
        "reportType": DRILL_TYPE,
        "evaluatedAt": evaluated_at.isoformat(),
        "status": "PASS" if overall_pass else "FAIL",
        "scenarioCount": len(results),
        "passingScenarioCount": sum(
            result.status == "PASS" for result in results
        ),
        "scenarios": [asdict(result) for result in results],
        "protectedState": {
            "initialDigest": initial.digest,
            "finalDigest": final.digest,
            "unchanged": initial.digest == final.digest,
            "files": [asdict(item) for item in final.files],
            "forbiddenArtifactsBefore": list(
                initial.forbidden_artifacts
            ),
            "forbiddenArtifactsAfter": list(
                final.forbidden_artifacts
            ),
        },
        "safetyBoundary": {
            "networkCalls": "NONE",
            "engineHostCommands": "NONE",
            "brokerCalls": "NONE",
            "orderTransmission": "UNAVAILABLE",
            "selectorArmCreated": False,
            "selectionPolicyCreated": False,
            "decisionCycleCreated": False,
            "handoffCreated": False,
            "tradeCreated": False,
        },
    }


def write_shadow_opening_negative_control_report(
    report: dict[str, object],
    *,
    output_directory: Path = DATA_DIR / "reports",
) -> dict[str, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / f"{REPORT_BASENAME}.json"
    markdown_path = output_directory / f"{REPORT_BASENAME}.md"
    write_atomic(
        json_path,
        json.dumps(report, indent=2, sort_keys=True) + "\n",
    )
    write_atomic(markdown_path, format_markdown(report))
    return {"json": json_path, "markdown": markdown_path}


def format_markdown(report: dict[str, object]) -> str:
    scenarios = report.get("scenarios", [])
    lines = [
        "# Shadow Opening Negative-Control Drill",
        "",
        f"- Status: `{report.get('status', 'UNKNOWN')}`",
        f"- Evaluated: `{report.get('evaluatedAt', 'UNKNOWN')}`",
        (
            f"- Scenarios: `{report.get('passingScenarioCount', 0)} / "
            f"{report.get('scenarioCount', 0)}` passed"
        ),
        "- Network calls: `NONE`",
        "- Engine Host commands: `NONE`",
        "- Broker calls: `NONE`",
        "- Order transmission: `UNAVAILABLE`",
        "",
        "## Scenarios",
        "",
    ]
    if isinstance(scenarios, list):
        for item in scenarios:
            if not isinstance(item, dict):
                continue
            lines.extend(
                (
                    f"### {item.get('name', 'unknown')}",
                    "",
                    f"- Status: `{item.get('status', 'UNKNOWN')}`",
                    f"- Expected: {item.get('expected', '')}",
                    f"- Observed: `{item.get('observed', '')}`",
                    (
                        "- Protected state unchanged: "
                        f"`{str(item.get('protected_state_unchanged')).upper()}`"
                    ),
                    (
                        "- Forbidden artifacts absent: "
                        f"`{str(item.get('forbidden_artifacts_absent')).upper()}`"
                    ),
                    "",
                )
            )
    protected = report.get("protectedState", {})
    if not isinstance(protected, dict):
        protected = {}
    lines.extend(
        (
            "## Protected State",
            "",
            f"- Unchanged: `{str(protected.get('unchanged')).upper()}`",
            (
                "- Forbidden artifacts before: "
                f"`{len(protected.get('forbiddenArtifactsBefore', []))}`"
            ),
            (
                "- Forbidden artifacts after: "
                f"`{len(protected.get('forbiddenArtifactsAfter', []))}`"
            ),
            "",
        )
    )
    return "\n".join(lines)


def write_atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run synthetic, nonmutating Shadow opening negative controls."
        )
    )
    parser.add_argument(
        "--shadow-state-directory",
        type=Path,
        default=DATA_DIR / "shadow-trading",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DATA_DIR / "reports",
    )
    parser.add_argument(
        "--evaluated-at",
        default="",
        help="Optional offset-aware ISO timestamp for deterministic evidence.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    evaluated_at = (
        datetime.fromisoformat(args.evaluated_at)
        if args.evaluated_at
        else now_central()
    )
    report = run_shadow_opening_negative_controls(
        shadow_state_directory=args.shadow_state_directory,
        evaluated_at=evaluated_at,
    )
    paths = write_shadow_opening_negative_control_report(
        report,
        output_directory=args.output_directory,
    )
    print(f"Shadow opening negative controls: {report['status']}")
    print(f"JSON: {paths['json']}")
    print(f"Report: {paths['markdown']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
