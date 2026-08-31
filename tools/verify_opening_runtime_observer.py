from __future__ import annotations

"""Evaluate independent opening-runtime evidence against current authority."""

import argparse
import json
from pathlib import Path
from typing import Sequence

from momentum_hunter.opening_runtime_identity import DEFAULT_CHANNEL, DEFAULT_RELEASE_ROOT
from momentum_hunter.opening_runtime_observer import (
    CURRENT_AUTHORIZED_RELEASE,
    FIXED_EXPECTED_RELEASE,
    observe_opening_runtime,
)


def _read_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Observation input must be a JSON object.")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare independent opening-runtime evidence with the verified "
            "authorized release channel."
        )
    )
    parser.add_argument("--observation", required=True, type=Path)
    parser.add_argument("--expected-canonical-sha", required=True)
    parser.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument(
        "--mode",
        choices=(CURRENT_AUTHORIZED_RELEASE, FIXED_EXPECTED_RELEASE),
        default=CURRENT_AUTHORIZED_RELEASE,
    )
    parser.add_argument("--fixed-expected-release-id")
    parser.add_argument("--fixed-expected-runtime-fingerprint")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        observation = _read_object(arguments.observation)
        result = observe_opening_runtime(
            observation,
            expected_canonical_git_sha=arguments.expected_canonical_sha,
            release_root=arguments.release_root,
            channel=arguments.channel,
            mode=arguments.mode,
            fixed_expected_release_id=arguments.fixed_expected_release_id,
            fixed_expected_runtime_fingerprint=(
                arguments.fixed_expected_runtime_fingerprint
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "schemaVersion": "OpeningAuthorizedReleaseObserverResultV1",
            "observerResult": "FAIL",
            "classification": "RUNTIME_EVIDENCE_INVALID",
            "diagnosticCode": "OBSERVER_INPUT_UNREADABLE",
            "diagnosticMessage": str(exc),
            "failClosed": True,
            "mutationPerformed": False,
            "orderTransmission": "UNAVAILABLE",
        }
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0 if result.get("observerResult") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
