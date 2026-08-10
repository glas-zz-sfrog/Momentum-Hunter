from __future__ import annotations

"""Load one frozen provider probe and emit a midweek-labeled write-once proof."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _load_source(root: Path) -> None:
    if not root.is_dir():
        raise RuntimeError("The frozen probe source root is unavailable.")
    sys.path.insert(0, str(root))


def _run_schwab(root: Path, output: Path, duration: int) -> dict[str, object]:
    _load_source(root)
    import momentum_hunter.schwab_overnight_probe as probe

    probe.PROBE_SCHEMA = "SCHWAB_MIDWEEK_OVERNIGHT_FIDELITY_PROBE_V1"
    probe.PROBE_MODE = "READ_ONLY_MIDWEEK_OVERNIGHT_CONTEXT_RESEARCH"
    result = probe.SchwabOvernightFidelityProbe().observe(duration_seconds=duration)
    result["replicationContext"] = {
        "task": "ARGUS-OVERNIGHT-002",
        "session": "MIDWEEK_TRUE_OVERNIGHT",
        "frozenProbeReused": True,
    }
    result["evidenceFingerprint"] = probe._fingerprint(result)
    proof_hash = probe.write_proof(result, output=output)
    return {"provider": "SCHWAB", "output": str(output), "sha256": proof_hash}


def _run_alpaca(root: Path, output_dir: Path, phase: str, delay: float) -> dict[str, object]:
    _load_source(root)
    import momentum_hunter.alpaca_overnight_probe as probe

    probe.LATEST_FEEDS = ("overnight",)
    result = probe.run_probe(repeat_delay_seconds=delay)
    result["schemaVersion"] = "ALPACA_MIDWEEK_OVERNIGHT_CAPABILITY_PROBE_V1"
    result["replicationContext"] = {
        "task": "ARGUS-OVERNIGHT-002",
        "session": "MIDWEEK_TRUE_OVERNIGHT",
        "phase": phase,
        "frozenProbeReused": True,
        "directLatestBoatsRequested": False,
        "boundedBoatsHistoryRequested": True,
    }
    result["evidenceFingerprint"] = probe._fingerprint(result)
    json_path = output_dir / f"alpaca-midweek-{phase}.json"
    markdown_path = output_dir / f"alpaca-midweek-{phase}.md"
    json_hash, markdown_hash = probe.write_proof(
        result,
        json_path=json_path,
        markdown_path=markdown_path,
    )
    return {
        "provider": "ALPACA",
        "phase": phase,
        "jsonPath": str(json_path),
        "jsonSha256": json_hash,
        "markdownPath": str(markdown_path),
        "markdownSha256": markdown_hash,
        "directLatestBoatsRequested": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a frozen read-only overnight probe.")
    subparsers = parser.add_subparsers(dest="provider", required=True)
    schwab = subparsers.add_parser("schwab")
    schwab.add_argument("--source-root", type=Path, required=True)
    schwab.add_argument("--output", type=Path, required=True)
    schwab.add_argument("--duration-seconds", type=int, default=300)
    alpaca = subparsers.add_parser("alpaca")
    alpaca.add_argument("--source-root", type=Path, required=True)
    alpaca.add_argument("--output-dir", type=Path, required=True)
    alpaca.add_argument("--phase", choices=("start", "end"), required=True)
    alpaca.add_argument("--repeat-delay-seconds", type=float, default=5.0)
    args = parser.parse_args()
    if args.provider == "schwab":
        result = _run_schwab(args.source_root, args.output, args.duration_seconds)
    else:
        result = _run_alpaca(
            args.source_root,
            args.output_dir,
            args.phase,
            args.repeat_delay_seconds,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
