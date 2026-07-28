"""Read-only Git release gate for the pending nontransmitting foundation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Callable, Final, Sequence


PENDING_FOUNDATION_RELEASE_GATE_SCHEMA: Final = (
    "PENDING_FOUNDATION_RELEASE_GATE_V1"
)
MAX_SCANNED_FILE_BYTES: Final = 2_000_000
_COMMIT_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
_GIT_REF_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_HIGH_RISK_SECRET_PATTERNS: Final = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
)
_RISKY_PATH_SEGMENTS: Final = frozenset(
    {
        ".env",
        "credentials",
        "momentumhunterdata",
        "secrets",
    }
)
_ALLOWED_SUFFIXES: Final = frozenset({".md", ".py"})


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path, float], CommandResult]


@dataclass(frozen=True)
class SourceCommitPolicy:
    ref: str
    commit: str


@dataclass(frozen=True)
class PendingFoundationReleasePolicy:
    base_ref: str
    remote_base_ref: str
    allowed_branch_prefix: str
    source_commits: tuple[SourceCommitPolicy, ...]
    integration_owned_paths: tuple[str, ...]
    equivalent_prefixes: tuple[str, ...] = ("momentum_hunter/", "tests/")
    governance_prefix: str = "docs/argus-office/"


DEFAULT_PENDING_FOUNDATION_POLICY: Final = PendingFoundationReleasePolicy(
    base_ref="master",
    remote_base_ref="origin/master",
    allowed_branch_prefix="codex/ARGUS-INTEGRATION-",
    source_commits=(
        SourceCommitPolicy(
            ref="codex/ARGUS-SHADOW-015-opening-failure-rehearsals",
            commit="cd828ac0df76359f223a9fe31d710e03147deb5c",
        ),
        SourceCommitPolicy(
            ref="codex/ARGUS-SHADOW-017-evidence-checkpoints",
            commit="4858d73f534dc170f6a65acf56c3dd663e5e3403",
        ),
        SourceCommitPolicy(
            ref="codex/ARGUS-CANARY-014-complete-stack-integrity",
            commit="438a392ca7b7e66ba14baaaf31a732d767861f23",
        ),
    ),
    integration_owned_paths=(
        "momentum_hunter/pending_foundation_release_gate.py",
        "tests/test_pending_foundation_release_gate.py",
        "tools/verify_pending_foundation.py",
    ),
)


class PendingFoundationReleaseGateError(ValueError):
    """Raised when the gate itself cannot safely evaluate the repository."""


def subprocess_command_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: float,
) -> CommandResult:
    normalized = tuple(str(item) for item in command)
    try:
        completed = subprocess.run(
            normalized,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(
            command=normalized,
            returncode=124,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
        )
    return CommandResult(
        command=normalized,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def evaluate_pending_foundation_release(
    repository_root: Path,
    *,
    evaluated_at: datetime,
    policy: PendingFoundationReleasePolicy = DEFAULT_PENDING_FOUNDATION_POLICY,
    command_runner: CommandRunner = subprocess_command_runner,
) -> dict[str, object]:
    root = _require_repository_root(repository_root)
    timestamp = _require_aware_datetime(evaluated_at)
    checked_policy = _require_policy(policy)
    findings: list[str] = []

    try:
        branch = _checked_git_output(
            ("branch", "--show-current"),
            root,
            command_runner,
        ).strip()
        status = _checked_git_output(
            ("status", "--porcelain=v1"),
            root,
            command_runner,
        )
        head = _resolve_commit("HEAD", root, command_runner)
        base = _resolve_commit(checked_policy.base_ref, root, command_runner)
        remote_base = _resolve_commit(
            checked_policy.remote_base_ref,
            root,
            command_runner,
        )
    except PendingFoundationReleaseGateError as exc:
        return _result(
            evaluated_at=timestamp,
            branch="",
            head="",
            base="",
            remote_base="",
            source_commits=checked_policy.source_commits,
            changed_paths=(),
            source_union=(),
            equivalent_paths=(),
            findings=(str(exc),),
            worktree_clean=False,
            base_remote_synchronized=False,
            base_ancestor=False,
            source_refs_frozen=False,
            exact_source_path_union=False,
            runtime_test_equivalent=False,
            risky_paths_absent=False,
            secret_signatures_absent=False,
        )

    worktree_clean = not status.strip()
    base_remote_synchronized = base == remote_base
    base_ancestor = _git_succeeds(
        ("merge-base", "--is-ancestor", base, head),
        root,
        command_runner,
    )
    if not branch.startswith(checked_policy.allowed_branch_prefix):
        findings.append(
            "Current branch is outside the allowed integration branch prefix."
        )
    if not worktree_clean:
        findings.append("Integration release gate requires a clean worktree.")
    if not base_remote_synchronized:
        findings.append("Local base and remote base are not synchronized.")
    if not base_ancestor:
        findings.append("Integration head is not a descendant of the base.")

    resolved_sources: list[SourceCommitPolicy] = []
    source_refs_frozen = True
    for source in checked_policy.source_commits:
        try:
            resolved = _resolve_commit(source.ref, root, command_runner)
        except PendingFoundationReleaseGateError as exc:
            findings.append(str(exc))
            source_refs_frozen = False
            continue
        if resolved != source.commit:
            findings.append(f"Source ref moved: {source.ref}.")
            source_refs_frozen = False
        resolved_sources.append(
            SourceCommitPolicy(ref=source.ref, commit=resolved)
        )

    path_evidence_available = True
    try:
        changed_paths = _changed_paths(
            base,
            head,
            root,
            command_runner,
        )
        source_path_sets = {
            source.commit: _changed_paths(
                base,
                source.commit,
                root,
                command_runner,
            )
            for source in checked_policy.source_commits
        }
    except PendingFoundationReleaseGateError as exc:
        findings.append(str(exc))
        path_evidence_available = False
        changed_paths = ()
        source_path_sets = {}

    source_union = tuple(
        sorted(
            {
                path
                for paths in source_path_sets.values()
                for path in paths
            }
        )
    )
    expected_paths = set(source_union).union(
        checked_policy.integration_owned_paths
    )
    actual_paths = set(changed_paths)
    missing_paths = sorted(expected_paths.difference(actual_paths))
    unexpected_paths = sorted(actual_paths.difference(expected_paths))
    exact_source_path_union = (
        path_evidence_available
        and not missing_paths
        and not unexpected_paths
    )
    if missing_paths:
        findings.append(
            "Expected integration paths are missing: "
            + ", ".join(missing_paths)
            + "."
        )
    if unexpected_paths:
        findings.append(
            "Unexpected integration paths are present: "
            + ", ".join(unexpected_paths)
            + "."
        )

    equivalent_paths: list[str] = []
    runtime_test_equivalent = path_evidence_available
    risky_paths_absent = path_evidence_available
    integration_owned = set(checked_policy.integration_owned_paths)
    for path in changed_paths:
        path_finding = _path_finding(path)
        if path_finding:
            findings.append(path_finding)
            risky_paths_absent = False
            continue
        if path in integration_owned:
            continue
        if path.startswith(checked_policy.governance_prefix):
            continue
        if not path.startswith(checked_policy.equivalent_prefixes):
            findings.append(
                f"Changed path is outside governed integration areas: {path}."
            )
            runtime_test_equivalent = False
            continue
        source_candidates = [
            source.commit
            for source in checked_policy.source_commits
            if path in source_path_sets.get(source.commit, ())
        ]
        if not source_candidates:
            findings.append(
                f"Runtime/test path has no reviewed source: {path}."
            )
            runtime_test_equivalent = False
            continue
        try:
            head_blob = _blob_identity(head, path, root, command_runner)
            source_blobs = {
                _blob_identity(source, path, root, command_runner)
                for source in source_candidates
            }
        except PendingFoundationReleaseGateError as exc:
            findings.append(str(exc))
            runtime_test_equivalent = False
            continue
        if head_blob not in source_blobs:
            findings.append(
                f"Runtime/test path differs from reviewed source: {path}."
            )
            runtime_test_equivalent = False
            continue
        equivalent_paths.append(path)

    secret_signatures_absent = worktree_clean and path_evidence_available
    if worktree_clean:
        for path in changed_paths:
            scan_findings = _scan_changed_file(root, path)
            findings.extend(scan_findings)
            if any("Risky path" in item for item in scan_findings):
                risky_paths_absent = False
            if any(
                "secret signature" in item for item in scan_findings
            ):
                secret_signatures_absent = False

    return _result(
        evaluated_at=timestamp,
        branch=branch,
        head=head,
        base=base,
        remote_base=remote_base,
        source_commits=tuple(resolved_sources),
        changed_paths=changed_paths,
        source_union=source_union,
        equivalent_paths=tuple(sorted(equivalent_paths)),
        findings=tuple(findings),
        worktree_clean=worktree_clean,
        base_remote_synchronized=base_remote_synchronized,
        base_ancestor=base_ancestor,
        source_refs_frozen=source_refs_frozen,
        exact_source_path_union=exact_source_path_union,
        runtime_test_equivalent=runtime_test_equivalent,
        risky_paths_absent=risky_paths_absent,
        secret_signatures_absent=secret_signatures_absent,
    )


def _result(
    *,
    evaluated_at: datetime,
    branch: str,
    head: str,
    base: str,
    remote_base: str,
    source_commits: Sequence[SourceCommitPolicy],
    changed_paths: Sequence[str],
    source_union: Sequence[str],
    equivalent_paths: Sequence[str],
    findings: Sequence[str],
    worktree_clean: bool,
    base_remote_synchronized: bool,
    base_ancestor: bool,
    source_refs_frozen: bool,
    exact_source_path_union: bool,
    runtime_test_equivalent: bool,
    risky_paths_absent: bool,
    secret_signatures_absent: bool,
) -> dict[str, object]:
    normalized_findings = list(dict.fromkeys(findings))
    return {
        "schemaVersion": PENDING_FOUNDATION_RELEASE_GATE_SCHEMA,
        "status": "PASS" if not normalized_findings else "FAIL",
        "evaluatedAt": evaluated_at.isoformat(),
        "branch": branch,
        "head": head,
        "base": base,
        "remoteBase": remote_base,
        "sourceCommits": [
            {"ref": source.ref, "commit": source.commit}
            for source in source_commits
        ],
        "changedPathCount": len(changed_paths),
        "sourceUnionPathCount": len(source_union),
        "equivalentRuntimeTestPathCount": len(equivalent_paths),
        "findings": normalized_findings,
        "worktreeClean": worktree_clean,
        "baseRemoteSynchronized": base_remote_synchronized,
        "baseAncestorOfHead": base_ancestor,
        "sourceRefsFrozen": source_refs_frozen,
        "exactSourcePathUnion": exact_source_path_union,
        "runtimeTestEquivalent": runtime_test_equivalent,
        "riskyPathsAbsent": risky_paths_absent,
        "secretSignaturesAbsent": secret_signatures_absent,
        "providerEvidence": False,
        "executionPermit": False,
        "brokerActionAllowed": False,
        "retryAllowed": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }


def _require_repository_root(value: Path) -> Path:
    candidate = Path(value)
    if candidate.is_symlink():
        raise PendingFoundationReleaseGateError(
            "Repository root cannot be a symlink."
        )
    try:
        root = candidate.expanduser().resolve(strict=True)
    except OSError as exc:
        raise PendingFoundationReleaseGateError(
            "Repository root is unavailable."
        ) from exc
    if not root.is_dir():
        raise PendingFoundationReleaseGateError(
            "Repository root must be a directory."
        )
    return root


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PendingFoundationReleaseGateError(
            "Release-gate evaluation time requires a UTC offset."
        )
    return value


def _require_policy(
    value: PendingFoundationReleasePolicy,
) -> PendingFoundationReleasePolicy:
    if not isinstance(value, PendingFoundationReleasePolicy):
        raise PendingFoundationReleaseGateError(
            "Pending-foundation release policy is malformed."
        )
    if (
        not value.base_ref
        or not value.remote_base_ref
        or not value.allowed_branch_prefix
        or not value.source_commits
        or not value.integration_owned_paths
        or not value.equivalent_prefixes
        or not value.governance_prefix
    ):
        raise PendingFoundationReleaseGateError(
            "Pending-foundation release policy is incomplete."
        )
    _require_git_ref(value.base_ref)
    _require_git_ref(value.remote_base_ref)
    if (
        not _GIT_REF_PATTERN.fullmatch(value.allowed_branch_prefix)
        or ".." in value.allowed_branch_prefix
        or "\\" in value.allowed_branch_prefix
    ):
        raise PendingFoundationReleaseGateError(
            "Allowed integration branch prefix is unsafe."
        )
    refs: set[str] = set()
    commits: set[str] = set()
    for source in value.source_commits:
        if (
            not isinstance(source, SourceCommitPolicy)
            or not source.ref
            or not _COMMIT_PATTERN.fullmatch(source.commit)
            or source.ref in refs
            or source.commit in commits
        ):
            raise PendingFoundationReleaseGateError(
                "Pending-foundation source policy is malformed."
            )
        _require_git_ref(source.ref)
        refs.add(source.ref)
        commits.add(source.commit)
    owned = tuple(
        _require_safe_relative_path(path)
        for path in value.integration_owned_paths
    )
    if len(set(owned)) != len(owned):
        raise PendingFoundationReleaseGateError(
            "Integration-owned paths contain duplicates."
        )
    for prefix in (*value.equivalent_prefixes, value.governance_prefix):
        if (
            not isinstance(prefix, str)
            or not prefix.endswith("/")
            or _require_safe_relative_path(prefix.removesuffix("/"))
            != prefix.removesuffix("/")
        ):
            raise PendingFoundationReleaseGateError(
                "Integration path prefix policy is malformed."
            )
    return value


def _checked_git_output(
    arguments: Sequence[str],
    root: Path,
    command_runner: CommandRunner,
) -> str:
    command = ("git", *arguments)
    result = command_runner(command, root, 30.0)
    if result.returncode != 0:
        raise PendingFoundationReleaseGateError(
            f"Git evidence command failed: {' '.join(command)}."
        )
    return result.stdout


def _git_succeeds(
    arguments: Sequence[str],
    root: Path,
    command_runner: CommandRunner,
) -> bool:
    result = command_runner(("git", *arguments), root, 30.0)
    return result.returncode == 0


def _resolve_commit(
    ref: str,
    root: Path,
    command_runner: CommandRunner,
) -> str:
    output = _checked_git_output(
        ("rev-parse", "--verify", f"{ref}^{{commit}}"),
        root,
        command_runner,
    ).strip().lower()
    if not _COMMIT_PATTERN.fullmatch(output):
        raise PendingFoundationReleaseGateError(
            f"Git ref did not resolve to a full commit: {ref}."
        )
    return output


def _changed_paths(
    base: str,
    head: str,
    root: Path,
    command_runner: CommandRunner,
) -> tuple[str, ...]:
    output = _checked_git_output(
        ("diff", "--name-only", "-z", f"{base}...{head}"),
        root,
        command_runner,
    )
    paths = tuple(
        sorted(
            _require_safe_relative_path(item)
            for item in output.split("\0")
            if item
        )
    )
    if len(set(paths)) != len(paths):
        raise PendingFoundationReleaseGateError(
            "Git changed-path evidence contains duplicates."
        )
    return paths


def _blob_identity(
    commit: str,
    path: str,
    root: Path,
    command_runner: CommandRunner,
) -> str:
    output = _checked_git_output(
        ("rev-parse", "--verify", f"{commit}:{path}"),
        root,
        command_runner,
    ).strip().lower()
    if not _COMMIT_PATTERN.fullmatch(output):
        raise PendingFoundationReleaseGateError(
            f"Git blob identity is invalid: {path}."
        )
    return output


def _require_safe_relative_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
    ):
        raise PendingFoundationReleaseGateError(
            "Integration path is malformed."
        )
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise PendingFoundationReleaseGateError(
            f"Integration path is unsafe: {value}."
        )
    return value


def _require_git_ref(value: str) -> str:
    if (
        not isinstance(value, str)
        or not _GIT_REF_PATTERN.fullmatch(value)
        or ".." in value
        or value.endswith(("/", ".", ".lock"))
        or "//" in value
    ):
        raise PendingFoundationReleaseGateError(
            f"Git ref is unsafe: {value}."
        )
    return value


def _path_finding(path: str) -> str:
    try:
        safe = _require_safe_relative_path(path)
    except PendingFoundationReleaseGateError as exc:
        return str(exc)
    lowered_parts = {part.casefold() for part in PurePosixPath(safe).parts}
    if lowered_parts.intersection(_RISKY_PATH_SEGMENTS):
        return f"Risky path is present in integration diff: {safe}."
    if PurePosixPath(safe).suffix.casefold() not in _ALLOWED_SUFFIXES:
        return f"Unexpected file type is present in integration diff: {safe}."
    return ""


def _scan_changed_file(root: Path, path: str) -> tuple[str, ...]:
    path_finding = _path_finding(path)
    if path_finding:
        return (path_finding,)
    candidate = root.joinpath(*PurePosixPath(path).parts)
    if candidate.is_symlink():
        return (f"Changed integration file cannot be a symlink: {path}.",)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return (f"Changed integration file is unavailable: {path}.",)
    if root not in resolved.parents:
        return (f"Changed integration file escapes repository root: {path}.",)
    try:
        size = resolved.stat().st_size
        content = resolved.read_bytes()
    except OSError:
        return (f"Changed integration file cannot be read: {path}.",)
    if size > MAX_SCANNED_FILE_BYTES or len(content) != size:
        return (f"Changed integration file is oversized or unstable: {path}.",)
    if b"\0" in content:
        return (f"Changed integration file is not text: {path}.",)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return (f"Changed integration file is not UTF-8: {path}.",)
    findings = []
    for pattern in _HIGH_RISK_SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(
                f"High-risk secret signature found in changed file: {path}."
            )
    return tuple(findings)
