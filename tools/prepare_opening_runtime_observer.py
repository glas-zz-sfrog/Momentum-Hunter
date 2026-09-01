from __future__ import annotations

"""Prepare or execute a stable, non-scheduling opening observer activation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Sequence

from momentum_hunter.opening_runtime_identity import DEFAULT_RELEASE_ROOT
from momentum_hunter.opening_runtime_observer import (
    CURRENT_AUTHORIZED_RELEASE,
    FIXED_EXPECTED_RELEASE,
)
from momentum_hunter.opening_runtime_observer_activation import (
    OpeningObserverActivationError,
    build_observer_receipt,
    build_operational_automation_prompt,
    create_observer_activation,
    validate_observer_activation,
    write_new_json,
    write_new_text,
)


def _read_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must include timezone identity.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create and verify stable operational Opening observer payloads without "
            "creating or changing any live schedule."
        )
    )
    actions = parser.add_subparsers(dest="action", required=True)

    create = actions.add_parser("create")
    create.add_argument("--activation", required=True, type=Path)
    create.add_argument("--prompt", type=Path)
    create.add_argument("--created-at")
    create.add_argument(
        "--mode",
        choices=(CURRENT_AUTHORIZED_RELEASE, FIXED_EXPECTED_RELEASE),
        default=CURRENT_AUTHORIZED_RELEASE,
    )
    create.add_argument("--fixed-expected-release-id")
    create.add_argument("--fixed-expected-runtime-fingerprint")

    validate = actions.add_parser("validate")
    validate.add_argument("--activation", required=True, type=Path)

    observe = actions.add_parser("observe")
    observe.add_argument("--activation", required=True, type=Path)
    observe.add_argument("--observation", required=True, type=Path)
    observe.add_argument("--expected-canonical-sha", required=True)
    observe.add_argument("--observed-at")
    observe.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    observe.add_argument("--receipt", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.action == "create":
            activation = create_observer_activation(
                created_at=_timestamp(arguments.created_at),
                mode=arguments.mode,
                fixed_expected_release_id=arguments.fixed_expected_release_id,
                fixed_expected_runtime_fingerprint=(
                    arguments.fixed_expected_runtime_fingerprint
                ),
            )
            write_new_json(arguments.activation, activation)
            if arguments.prompt is not None:
                write_new_text(
                    arguments.prompt,
                    build_operational_automation_prompt(activation) + "\n",
                )
            result: dict[str, object] = {
                "status": "OBSERVER_ACTIVATION_CREATED",
                "mode": activation["mode"],
                "activation": str(arguments.activation.absolute()),
                "prompt": (
                    str(arguments.prompt.absolute())
                    if arguments.prompt is not None
                    else ""
                ),
                "scheduleCreated": False,
                "productionMutation": False,
            }
        elif arguments.action == "validate":
            activation = validate_observer_activation(
                _read_object(arguments.activation)
            )
            result = {
                "status": "OBSERVER_ACTIVATION_VALID",
                "mode": activation.mode,
                "activationFingerprint": activation.payload[
                    "activationFingerprint"
                ],
                "scheduleCreated": False,
                "productionMutation": False,
            }
        else:
            receipt = build_observer_receipt(
                _read_object(arguments.activation),
                _read_object(arguments.observation),
                expected_canonical_git_sha=arguments.expected_canonical_sha,
                observed_at=_timestamp(arguments.observed_at),
                release_root=arguments.release_root,
            )
            write_new_json(arguments.receipt, receipt)
            result = receipt
    except (
        FileExistsError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        OpeningObserverActivationError,
    ) as exc:
        result = {
            "status": "OBSERVER_ACTIVATION_REJECTED",
            "diagnosticCode": getattr(exc, "code", "OBSERVER_ACTIVATION_IO_ERROR"),
            "diagnosticMessage": str(exc),
            "failClosed": True,
            "scheduleCreated": False,
            "productionMutation": False,
            "orderTransmission": "UNAVAILABLE",
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    if arguments.action == "observe":
        return 0 if result.get("observerResult") == "PASS" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
