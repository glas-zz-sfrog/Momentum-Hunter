"""Run repository tests with one explicitly fingerprinted external Python environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


class ApprovedEnvironmentError(RuntimeError):
    """Raised when the invoking Python or repository cannot be proven."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def environment_descriptor() -> dict[str, object]:
    executable = Path(sys.executable).resolve(strict=True)
    base_executable = Path(
        getattr(sys, "_base_executable", sys.executable)
    ).resolve(strict=True)
    distributions = sorted(
        {
            (
                str(item.metadata.get("Name") or "").strip().lower(),
                str(item.version),
            )
            for item in importlib.metadata.distributions()
            if str(item.metadata.get("Name") or "").strip()
        }
    )
    identity = {
        "executable": str(executable),
        "executableSha256": _sha256(executable),
        "baseExecutable": str(base_executable),
        "baseExecutableSha256": _sha256(base_executable),
        "pythonVersion": sys.version,
        "implementation": sys.implementation.name,
        "prefix": str(Path(sys.prefix).resolve()),
        "basePrefix": str(Path(sys.base_prefix).resolve()),
        "distributions": [
            {"name": name, "version": version} for name, version in distributions
        ],
    }
    identity["environmentFingerprint"] = hashlib.sha256(
        _canonical_bytes(identity)
    ).hexdigest().upper()
    return identity


def _repository_descriptor(root: Path) -> dict[str, object]:
    resolved = root.resolve(strict=True)
    if not (resolved / "momentum_hunter").is_dir() or not (resolved / "tests").is_dir():
        raise ApprovedEnvironmentError(
            "Repository under test must contain momentum_hunter and tests."
        )
    head = subprocess.run(
        ("git", "-C", str(resolved), "rev-parse", "HEAD"),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "path": str(resolved),
        "gitHead": head.stdout.strip() if head.returncode == 0 else "UNAVAILABLE",
    }


def _loaded_source(root: Path, env: dict[str, str]) -> str:
    probe = subprocess.run(
        (
            sys.executable,
            "-B",
            "-c",
            "import pathlib,momentum_hunter;print(pathlib.Path(momentum_hunter.__file__).resolve())",
        ),
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if probe.returncode != 0:
        raise ApprovedEnvironmentError(
            "Approved environment could not import the repository under test."
        )
    loaded = Path(probe.stdout.strip()).resolve(strict=True)
    try:
        loaded.relative_to(root)
    except ValueError as exc:
        raise ApprovedEnvironmentError(
            "Approved environment imported momentum_hunter outside the repository under test."
        ) from exc
    return str(loaded)


def _write_json(path: Path | None, payload: object) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(encoded, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="ascii")


def _run(args: argparse.Namespace) -> int:
    environment = environment_descriptor()
    expected = str(args.expected_environment_fingerprint).strip().upper()
    if expected != environment["environmentFingerprint"]:
        raise ApprovedEnvironmentError(
            "Invoking Python does not match the approved environment fingerprint."
        )
    repository = _repository_descriptor(args.repository_root)
    root = Path(str(repository["path"]))
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(root) + (os.pathsep + existing if existing else "")
    env["PYTHONNOUSERSITE"] = "1"
    loaded_source = _loaded_source(root, env)
    test_args = list(args.test_args)
    if test_args and test_args[0] == "--":
        test_args = test_args[1:]
    if not test_args:
        test_args = ["discover", "-s", "tests", "-p", "test_*.py", "-v"]
    command = [sys.executable, "-B", "-m", "unittest", *test_args]
    started = datetime.now().astimezone()
    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=args.timeout_seconds,
    )
    finished = datetime.now().astimezone()
    result = {
        "schemaVersion": 1,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "startedAt": started.isoformat(),
        "completedAt": finished.isoformat(),
        "elapsedSeconds": round((finished - started).total_seconds(), 3),
        "approvedEnvironment": environment,
        "repositoryUnderTest": repository,
        "loadedMomentumHunterSource": loaded_source,
        "localWorktreeVenvPresent": (root / ".venv").exists(),
        "command": [Path(command[0]).name, *command[1:]],
        "returnCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    _write_json(args.output, result)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    describe = subparsers.add_parser("describe")
    describe.add_argument("--output", type=Path)
    run = subparsers.add_parser("run")
    run.add_argument("--repository-root", type=Path, required=True)
    run.add_argument("--expected-environment-fingerprint", required=True)
    run.add_argument("--output", type=Path)
    run.add_argument("--timeout-seconds", type=int, default=7200)
    run.add_argument("test_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "describe":
            _write_json(args.output, environment_descriptor())
            return 0
        return _run(args)
    except (ApprovedEnvironmentError, OSError, subprocess.SubprocessError) as exc:
        error = {"status": "FAIL", "error": type(exc).__name__, "message": str(exc)}
        _write_json(getattr(args, "output", None), error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
