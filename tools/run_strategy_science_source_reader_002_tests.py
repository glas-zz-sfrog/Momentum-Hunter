"""Run approved-environment suites for Science Source Reader 002."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


SCIENCE_CUSTODY_MODULES = (
    "tests.test_strategy_science_recorder_contract",
    "tests.test_strategy_science_recorder_custody",
    "tests.test_strategy_science_recorder_coverage",
    "tests.test_strategy_science_recorder_outcomes",
    "tests.test_strategy_science_recorder_restart",
    "tests.test_strategy_science_recorder_boundaries",
    "tests.test_strategy_science_recorder_eligibility_authority",
    "tests.test_strategy_science_source_reader_v2",
)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _continuous_modules(repository: Path) -> tuple[str, ...]:
    return tuple(
        f"tests.{path.stem}"
        for path in sorted((repository / "tests").glob("test_continuous*.py"))
    )


def _command(repository: Path, suite: str) -> list[str]:
    base = [sys.executable, "-B", "-m", "unittest"]
    if suite == "focused":
        return [*base, "-v", "tests.test_strategy_science_source_reader_v2"]
    if suite == "exporter-compatibility":
        return [
            *base,
            "-v",
            "tests.test_continuous_research_export_v2",
            "tests.test_strategy_science_source_reader_v2",
        ]
    if suite == "science-custody-compatibility":
        return [*base, "-v", *SCIENCE_CUSTODY_MODULES]
    if suite == "continuous-adjacent":
        return [*base, "-v", *_continuous_modules(repository)]
    if suite == "full":
        return [*base, "discover", "-s", "tests", "-p", "test_*.py", "-v"]
    raise ValueError(f"Unsupported suite: {suite}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--suite",
        required=True,
        choices=(
            "focused",
            "exporter-compatibility",
            "science-custody-compatibility",
            "continuous-adjacent",
            "full",
        ),
    )
    args = parser.parse_args(argv)
    repository = args.repository_root.resolve()
    output = args.output.resolve()
    command = _command(repository, args.suite)
    started_at = datetime.now().astimezone()
    monotonic = time.monotonic()
    transcript_path = output.with_suffix(".transcript.txt")
    output.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("wb") as transcript_handle:
        process = subprocess.Popen(
            command,
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None
        while True:
            block = process.stdout.read1(65536)
            if not block:
                break
            transcript_handle.write(block)
            transcript_handle.flush()
        return_code = process.wait()
    finished_at = datetime.now().astimezone()
    transcript = transcript_path.read_bytes()
    transcript_text = transcript.decode("utf-8", errors="replace")
    match = re.search(r"Ran ([0-9]+) tests? in", transcript_text)
    tests_run = int(match.group(1)) if match else None
    skip_match = re.search(r"skipped=([0-9]+)", transcript_text)
    expected_skips = int(skip_match.group(1)) if skip_match else 0
    evidence = {
        "approvedPython": {
            "executable": sys.executable,
            "executableSha256": hashlib.sha256(
                Path(sys.executable).read_bytes()
            ).hexdigest().upper(),
            "version": sys.version,
        },
        "command": command,
        "completedAt": finished_at.isoformat(),
        "elapsedSeconds": round(time.monotonic() - monotonic, 3),
        "expectedSkips": expected_skips,
        "gitHead": _git(repository, "rev-parse", "HEAD"),
        "gitStatusPorcelain": _git(repository, "status", "--porcelain=v1"),
        "returnCode": return_code,
        "schemaVersion": 1,
        "startedAt": started_at.isoformat(),
        "status": "PASS" if return_code == 0 else "FAIL",
        "suite": args.suite,
        "task": "ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002",
        "testsPassed": tests_run if return_code == 0 else None,
        "testsRun": tests_run,
        "transcriptPath": str(transcript_path),
        "transcriptSha256": hashlib.sha256(transcript).hexdigest().upper(),
    }
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
