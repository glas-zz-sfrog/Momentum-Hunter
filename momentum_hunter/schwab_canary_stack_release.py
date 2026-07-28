from __future__ import annotations

"""Read-only final release evidence for the stacked Schwab canary foundation."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Final

from momentum_hunter.pending_foundation_release_gate import (
    CommandRunner,
    PendingFoundationReleasePolicy,
    SourceCommitPolicy,
    evaluate_pending_foundation_release,
    subprocess_command_runner,
)
from momentum_hunter.schwab_canary_stack_integrity import (
    CanaryStackIntegrityError,
    build_canary_stack_integrity_manifest,
    canonical_manifest_json,
    verify_canary_stack_integrity_manifest,
)


FINAL_CANARY_STACK_RELEASE_SCHEMA: Final = (
    "FINAL_CANARY_STACK_RELEASE_V1"
)
REVIEWED_CANARY_STACK_SOURCE_COMMIT: Final = (
    "b17fa6549ea239e9d807632e1c4c77abe474ab67"
)
_COMMIT_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
_OWNED_PATHS: Final = (
    "momentum_hunter/schwab_canary_stack_release.py",
    "tests/test_schwab_canary_stack_release.py",
    "tools/verify_canary_stack_release.py",
)

DEFAULT_FINAL_CANARY_STACK_POLICY: Final = (
    PendingFoundationReleasePolicy(
        base_ref="master",
        remote_base_ref="origin/master",
        allowed_branch_prefix=(
            "codex/ARGUS-SCHWAB-004-account-shape-evidence"
        ),
        source_commits=(
            SourceCommitPolicy(
                ref=REVIEWED_CANARY_STACK_SOURCE_COMMIT,
                commit=REVIEWED_CANARY_STACK_SOURCE_COMMIT,
            ),
        ),
        integration_owned_paths=_OWNED_PATHS,
    )
)


def evaluate_final_canary_stack_release(
    repository_root: Path,
    *,
    evaluated_at: datetime,
    policy: PendingFoundationReleasePolicy = (
        DEFAULT_FINAL_CANARY_STACK_POLICY
    ),
    command_runner: CommandRunner = subprocess_command_runner,
) -> dict[str, object]:
    release_gate = evaluate_pending_foundation_release(
        repository_root,
        evaluated_at=evaluated_at,
        policy=policy,
        command_runner=command_runner,
    )
    findings = list(release_gate["findings"])
    if release_gate["branch"] != policy.allowed_branch_prefix:
        findings.append(
            "Current branch is not the exact reviewed release branch."
        )
    head = str(release_gate["head"])
    upstream_head = ""
    upstream_synchronized = False
    stack_manifest: dict[str, object] | None = None
    stack_manifest_sha256: str | None = None
    stack_manifest_verified = False

    if release_gate["status"] == "PASS":
        upstream_head = _resolve_upstream(
            Path(repository_root),
            command_runner=command_runner,
        )
        if not upstream_head:
            findings.append(
                "Current branch upstream commit is unavailable."
            )
        else:
            upstream_synchronized = upstream_head == head
            if not upstream_synchronized:
                findings.append(
                    "Current branch and its upstream are not synchronized."
                )

    if not findings:
        try:
            stack_manifest = build_canary_stack_integrity_manifest(
                repository_root=Path(repository_root),
                build_identity=head,
                created_at=evaluated_at,
            )
            stack_findings = verify_canary_stack_integrity_manifest(
                stack_manifest,
                repository_root=Path(repository_root),
                expected_build_identity=head,
                evaluated_at=evaluated_at,
            )
        except (CanaryStackIntegrityError, OSError, TypeError, ValueError):
            findings.append(
                "The V3 canary stack manifest could not be built safely."
            )
            stack_manifest = None
        else:
            findings.extend(
                f"V3 stack manifest: {finding}"
                for finding in stack_findings
            )
            if not stack_findings:
                stack_manifest_verified = True
                encoded = canonical_manifest_json(stack_manifest).encode(
                    "ascii"
                )
                stack_manifest_sha256 = hashlib.sha256(encoded).hexdigest()

    normalized_findings = list(dict.fromkeys(findings))
    passed = (
        not normalized_findings
        and release_gate["status"] == "PASS"
        and upstream_synchronized
        and stack_manifest_verified
    )
    return {
        "schemaVersion": FINAL_CANARY_STACK_RELEASE_SCHEMA,
        "status": "PASS" if passed else "FAIL",
        "evaluatedAt": evaluated_at.isoformat(),
        "branch": release_gate["branch"],
        "head": head,
        "upstreamHead": upstream_head,
        "reviewedSourceCommits": [
            source.commit for source in policy.source_commits
        ],
        "findings": normalized_findings,
        "worktreeClean": release_gate["worktreeClean"],
        "baseRemoteSynchronized": release_gate[
            "baseRemoteSynchronized"
        ],
        "branchUpstreamSynchronized": upstream_synchronized,
        "exactSourcePathUnion": release_gate[
            "exactSourcePathUnion"
        ],
        "runtimeTestEquivalent": release_gate[
            "runtimeTestEquivalent"
        ],
        "riskyPathsAbsent": release_gate["riskyPathsAbsent"],
        "secretSignaturesAbsent": release_gate[
            "secretSignaturesAbsent"
        ],
        "stackManifestVerified": stack_manifest_verified,
        "stackManifestSha256": stack_manifest_sha256,
        "stackManifest": stack_manifest,
        "releaseGate": release_gate,
        "inspectionOnly": True,
        "gitMutationPerformed": False,
        "networkAccessed": False,
        "providerEvidence": False,
        "credentialsAccessed": False,
        "executionPermit": False,
        "brokerActionAllowed": False,
        "retryAllowed": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }


def render_final_canary_stack_release(result: object) -> str:
    return json.dumps(
        result,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )


def _resolve_upstream(
    repository_root: Path,
    *,
    command_runner: CommandRunner,
) -> str:
    result = command_runner(
        (
            "git",
            "rev-parse",
            "--verify",
            "@{upstream}^{commit}",
        ),
        repository_root,
        30.0,
    )
    output = result.stdout.strip().lower()
    if result.returncode != 0 or not _COMMIT_PATTERN.fullmatch(output):
        return ""
    return output
