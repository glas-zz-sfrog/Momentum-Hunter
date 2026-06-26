from __future__ import annotations

import argparse
import json
from typing import Any


TEST_PLAN_VERSION = "autonomous_test_plan_v1"


SUITES: dict[str, dict[str, Any]] = {
    "storage-safe": {
        "purpose": "File-backed storage, raw-capture integrity, derived stores, and source mutation checks.",
        "command": ".\\.venv\\Scripts\\python.exe -B tools\\run_bounded_tests.py --group backend --timeout 60",
        "notes": [
            "Use focused --only selections for large backend changes.",
            "Do not include broad Qt unittest modules.",
        ],
    },
    "sqlite-safe": {
        "purpose": "SQLite mirror, read model, validation, maintenance, and migration slices.",
        "command": ".\\.venv\\Scripts\\python.exe -B tools\\run_bounded_tests.py --group storage --timeout 60",
        "notes": [
            "SQLite remains additive and non-authoritative.",
            "Run sqlite_validation after import or schema changes.",
        ],
    },
    "evidence-safe": {
        "purpose": "Active monitor, alerts, outcomes, evidence health, reliability, and report analytics.",
        "command": ".\\.venv\\Scripts\\python.exe -B tools\\run_bounded_tests.py --group evidence --timeout 60",
        "notes": [
            "Does not fetch live data unless an individual test explicitly mocks or requests it.",
            "Stop immediately on timeout and inspect the exact module.",
        ],
    },
    "provider-safe": {
        "purpose": "Provider error handling, market-tape health, and provider field-quality diagnostics.",
        "command": ".\\.venv\\Scripts\\python.exe -B -m unittest tests.test_provider_errors tests.test_market_tape_health tests.test_provider_field_quality",
        "notes": [
            "Diagnostic only; do not alter scanner/provider ranking from this suite.",
            "Live provider probes require explicit operator intent and may need network escalation.",
        ],
    },
    "replay-safe": {
        "purpose": "Replay, Candidate Story, data-view state, and point-in-time read-only behavior.",
        "command": ".\\.venv\\Scripts\\python.exe -B tools\\run_bounded_tests.py --group backend --only tests.test_candidate_story_view_model --only tests.test_data_view_state --timeout 30",
        "notes": [
            "Use pure view-model tests first.",
            "Escalate to isolated offscreen Qt probes only when UI behavior itself changed.",
        ],
    },
    "ui-bounded-safe": {
        "purpose": "Small isolated offscreen Qt probes for one UI behavior at a time.",
        "command": "Use a one-off QT_QPA_PLATFORM=offscreen probe with timers/startup patched out.",
        "notes": [
            "Do not run full Qt unittest modules unattended.",
            "Print one *_OK marker and run a process check afterward.",
        ],
    },
    "do-not-run-unattended": {
        "purpose": "Known risky broad Qt unittest modules and visual harnesses.",
        "command": "Do not run as an autonomous suite.",
        "modules": [
            "tests.test_gui_states",
            "tests.test_daily_workflow",
            "tests.test_morning_review_workspace",
            "tests.test_review_workflow",
        ],
        "notes": [
            "Run only one exact test or replace with an isolated probe.",
            "Kill only stuck test python.exe processes after a timeout.",
        ],
    },
}


def build_test_plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "engine_version": TEST_PLAN_VERSION,
        "default_policy": "Run bounded non-Qt suites first; use isolated Qt probes only when necessary.",
        "suites": SUITES,
    }


def format_text(plan: dict[str, Any]) -> str:
    lines = [
        "Momentum Hunter Autonomous Test Plan",
        f"Engine: {plan['engine_version']}",
        "",
        plan["default_policy"],
        "",
    ]
    for name, suite in plan["suites"].items():
        lines.extend(
            [
                f"[{name}]",
                f"Purpose: {suite['purpose']}",
                f"Command: {suite['command']}",
            ]
        )
        modules = suite.get("modules") or []
        if modules:
            lines.append("Modules:")
            lines.extend(f"  - {module}" for module in modules)
        notes = suite.get("notes") or []
        if notes:
            lines.append("Notes:")
            lines.extend(f"  - {note}" for note in notes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List Momentum Hunter autonomous test suites.")
    parser.add_argument("--list", action="store_true", help="List suites in human-readable form.")
    parser.add_argument("--json", action="store_true", help="Print suites as JSON.")
    args = parser.parse_args(argv)

    plan = build_test_plan()
    if args.json:
        print(json.dumps(plan, indent=2))
        return 0
    print(format_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
