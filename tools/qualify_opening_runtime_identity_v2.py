from __future__ import annotations

"""Isolated physical qualification for the V2 opening runtime identity."""

import argparse
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.automation_supervisor import (
    DEFAULT_MANIFEST_PATH,
    LOADED_SUPERVISOR_SHA256,
    parse_manifest,
)
from momentum_hunter.opening_runtime_identity import (
    DEFAULT_CHANNEL,
    LOADED_RUNTIME_IDENTITY_MODULE_SHA256,
    OpeningRuntimeIdentityError,
    OpeningRuntimeReleaseStore,
    build_release_record_v2,
    current_git_identity,
    verify_execution_gate,
)
from momentum_hunter.opening_runtime_release import _context


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--release-root", type=Path)
    return parser


def qualify(
    manifest_path: Path,
    repository_root: Path,
    release_root: Path | None = None,
) -> dict[str, object]:
    manifest = parse_manifest(manifest_path)
    production_context = _context(manifest)
    task_context = replace(
        production_context,
        repository_root=repository_root.absolute(),
        config_path=(
            production_context.repository_root / "MomentumHunterData" / "config.json"
        ),
    )
    source_git_sha, worktree_status = current_git_identity(task_context.repository_root)
    if worktree_status:
        raise OpeningRuntimeIdentityError(
            "QUALIFICATION_WORKTREE_DIRTY",
            "Physical V2 qualification requires a clean task worktree.",
        )
    active_v1, _, _ = OpeningRuntimeReleaseStore(
        production_context.release_root
    ).verify_channel(DEFAULT_CHANNEL)

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if release_root is None:
        temporary = tempfile.TemporaryDirectory()
        isolated_root = Path(temporary.name) / "opening-runtime-v2"
    else:
        isolated_root = release_root.absolute()
    context = replace(task_context, release_root=isolated_root)
    try:
        record = build_release_record_v2(
            context,
            source_git_sha=source_git_sha,
            qualification_evidence=[
                "ARGUS-AUTOMATION-RUNTIME-IDENTITY-003A:ISOLATED_PHYSICAL_PROOF"
            ],
        )
        release, pointer, changed = OpeningRuntimeReleaseStore(isolated_root).promote(
            record,
            current_git_sha=source_git_sha,
        )
        result = verify_execution_gate(
            context,
            loaded_supervisor_sha256=LOADED_SUPERVISOR_SHA256,
            loaded_identity_module_sha256=LOADED_RUNTIME_IDENTITY_MODULE_SHA256,
            loaded_service_host_sha256=str(
                release["environmentIdentity"]["serviceHost"]["sha256"]
            ),
            git_identity=(source_git_sha, ""),
        )
        closure = release["dependencyClosureEvidence"]
        distributions = release["environmentIdentity"]["relevantDistributions"]
        return {
            "schemaVersion": "OpeningRuntimeIdentityV2PhysicalQualificationV1",
            "status": "PHYSICAL_PROMOTION_RUNTIME_MATCH_PROVEN",
            "sourceGitSha": source_git_sha,
            "isolatedReleaseRoot": str(isolated_root),
            "isolatedReleaseId": release["releaseId"],
            "isolatedReleaseFingerprint": release["releaseFingerprint"],
            "isolatedPointerFingerprint": pointer["pointerFingerprint"],
            "promotionChanged": changed,
            "runtimeMatch": result.runtime_match,
            "dependencyClosureFingerprint": closure[
                "dependencyClosureFingerprint"
            ],
            "runtimeSurfaceFingerprint": release["runtimeSurfaceFingerprint"],
            "configurationFingerprint": release["configurationFingerprint"],
            "environmentFingerprint": release["environmentFingerprint"],
            "runtimeComponentCount": len(release["runtimeComponents"]),
            "packagePythonCount": closure["packagePythonCount"],
            "reachablePackageCount": closure["reachablePackageCount"],
            "excludedPackageCount": closure["excludedPackageCount"],
            "relevantDistributionCount": len(distributions),
            "relevantDistributions": [item["name"] for item in distributions],
            "activeProductionReleaseId": active_v1["releaseId"],
            "activeProductionReleaseSchema": active_v1["schemaVersion"],
            "activeProductionReleaseFingerprint": active_v1["releaseFingerprint"],
            "productionReleaseRootMutated": False,
            "serviceRestarted": False,
            "manifestChanged": False,
            "schedulerChanged": False,
            "providerRequested": False,
            "accountRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }
    finally:
        if temporary is not None:
            temporary.cleanup()


def main() -> int:
    args = _parser().parse_args()
    try:
        result = qualify(args.manifest, args.repository_root, args.release_root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OpeningRuntimeIdentityError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": getattr(exc, "code", type(exc).__name__),
                    "detail": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
