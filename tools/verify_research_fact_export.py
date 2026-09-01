"""Run a bounded, offline preserved-evidence rehearsal of the fact export."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from momentum_hunter.research_fact_export import (
    AUTHORITY,
    EXECUTION_AUTHORITY,
    ResearchFactExportError,
    ResearchFactExportStore,
    ZERO_SHA256,
    build_envelope,
    canonical_json_bytes,
    fingerprint,
    recorder_identity,
)


REQUIRED_BASELINE_FILES = (
    "denominator-statistics.json",
    "outcome-microstudy.json",
    "provider-health-analysis.json",
    "recurrence-analysis.json",
    "storage-baseline.json",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ResearchFactExportError(f"Preserved evidence is not an object: {path.name}")
    return value


def _verify_sidecar(root: Path, expected_sidecar_sha256: str) -> tuple[list[dict[str, Any]], str]:
    sidecar = root / "artifact-checksums.sha256"
    sidecar_bytes = sidecar.read_bytes()
    actual_sidecar_sha = _sha256(sidecar_bytes)
    if actual_sidecar_sha != expected_sidecar_sha256.lower():
        raise ResearchFactExportError("Preserved-evidence checksum sidecar identity mismatch")
    inventory: list[dict[str, Any]] = []
    for line in sidecar_bytes.decode("ascii").splitlines():
        if not line.strip():
            continue
        expected, name = line.split(None, 1)
        name = name.strip().lstrip("*")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ResearchFactExportError("Checksum sidecar contains an unsafe path")
        target = root / relative
        actual = _sha256(target.read_bytes())
        if actual != expected.lower():
            raise ResearchFactExportError(f"Preserved evidence hash mismatch: {name}")
        inventory.append(
            {
                "byte_count": target.stat().st_size,
                "name": relative.as_posix(),
                "sha256": actual,
            }
        )
    if not inventory:
        raise ResearchFactExportError("Preserved-evidence checksum inventory is empty")
    return inventory, actual_sidecar_sha


def run_rehearsal(
    *,
    source_root: Path,
    output_root: Path,
    expected_sidecar_sha256: str,
    protected_roots: Sequence[Path],
) -> dict[str, Any]:
    if not source_root.is_absolute() or not output_root.is_absolute():
        raise ResearchFactExportError("Rehearsal roots must be absolute")
    source_root = source_root.resolve()
    output_root = output_root.resolve(strict=False)
    inventory, sidecar_sha = _verify_sidecar(source_root, expected_sidecar_sha256)
    documents = {name: _read_json(source_root / name) for name in REQUIRED_BASELINE_FILES}
    denominator = documents["denominator-statistics.json"]
    outcome = documents["outcome-microstudy.json"]
    health = documents["provider-health-analysis.json"]
    storage = documents["storage-baseline.json"]
    facts = {
        "baseline_classification": outcome["classification"],
        "baseline_source_corpus": denominator["source_corpus"],
        "baseline_source_session_head": denominator["source_session_head"],
        "covered_observation_count": outcome["coverage"]["covered_observations"],
        "covered_symbol_count": outcome["coverage"]["covered_symbol_count"],
        "discovery_cycle_count": denominator["totals"]["discovery_cycles"],
        "outcome_eligibility_implementation": outcome["coverage"][
            "eligibility_implementation"
        ],
        "outcome_selection_hindsight": outcome["coverage"][
            "outcome_selection_hindsight"
        ],
        "provider_health_snapshot_count": health["population"]["snapshots"],
        "storage_optimization_recommended": storage[
            "storage_optimization_recommended"
        ],
        "total_observation_count": denominator["totals"]["total_observations"],
        "unique_symbol_count": denominator["totals"]["unique_symbols"],
    }
    source_binding = {
        "artifact_inventory": inventory,
        "bounded_facts": facts,
        "checksum_sidecar_sha256": sidecar_sha,
    }
    session = recorder_identity(
        "SESSION",
        {
            "preserved_evidence_inventory_sha256": fingerprint(source_binding),
            "rehearsal": "ARGUS_SHARED_SCIENCE_RUNTIME_FACT_EXPORT_001",
        },
    )
    session_id = session["recorder_id"]
    source_generated_at = str(denominator["generated_at"])
    store = ResearchFactExportStore(
        output_root,
        market_date="2026-08-31",
        session_id=session_id,
        protected_roots=(source_root, *protected_roots),
        science_custody_roots=(source_root,),
    )
    store.initialize(
        {
            "authority": AUTHORITY,
            "config_fingerprint_sha256": fingerprint(
                {"rehearsal_mode": "BOUNDED_OFFLINE_PRESERVED_EVIDENCE"}
            ),
            "execution_authority": EXECUTION_AUTHORITY,
            "market_calendar_id_and_version": "PRESERVED_EVIDENCE_NO_NEW_MARKET_TIME",
            "market_date": "2026-08-31",
            "policy_fingerprint_sha256": fingerprint(
                {"outcome_selection_hindsight": False, "provider_acquisition": "NONE"}
            ),
            "runtime_fingerprint_sha256": _sha256(
                (Path(__file__).parents[1] / "momentum_hunter" / "research_fact_export.py").read_bytes()
            ),
            "session_id": session_id,
        }
    )
    manifest = {
        "authority": AUTHORITY,
        "bounded_rehearsal": True,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_provider_contact": False,
        "preserved_source_binding": source_binding,
        "production_authority": False,
        "source_mutated": False,
    }
    envelope = build_envelope(
        event_type="SESSION_MANIFEST",
        stream_id="preserved-evidence-rehearsal-manifest",
        session_id=session_id,
        source_contract="ARGUS_SCIENCE_DESCRIPTIVE_BASELINE_V1",
        source_contract_version=str(denominator["schema_version"]),
        source_event_id=f"preserved-evidence:{sidecar_sha}",
        source_event_fingerprint_sha256=fingerprint(source_binding),
        source_sequence=0,
        event_time=source_generated_at,
        effective_known_at=source_generated_at,
        emitted_at=source_generated_at,
        previous_record_sha256=ZERO_SHA256,
        manifest=manifest,
    )
    append_receipt = store.append(envelope)
    verification = store.verify()
    readback = next(
        item["payload"]["manifest"]["preserved_source_binding"]
        for item in store.iter_verified_envelopes()
        if item["event_type"] == "SESSION_MANIFEST"
    )
    if readback != source_binding:
        raise ResearchFactExportError("Preserved-evidence rehearsal readback mismatch")
    return {
        "append_status": append_receipt.status,
        "authority": AUTHORITY,
        "bounded_facts": facts,
        "checksum_sidecar_sha256": sidecar_sha,
        "execution_authority": EXECUTION_AUTHORITY,
        "export_partition": str(store.partition),
        "live_provider_contact": False,
        "preserved_artifact_count": len(inventory),
        "preserved_source_mutated": False,
        "rehearsal": "PASS",
        "session_id": session_id,
        "verification": verification,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-sidecar-sha256", required=True)
    parser.add_argument("--protected-root", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    try:
        result = run_rehearsal(
            source_root=args.source_root,
            output_root=args.output_root,
            expected_sidecar_sha256=args.expected_sidecar_sha256,
            protected_roots=tuple(args.protected_root),
        )
    except (ResearchFactExportError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.buffer.write(
            canonical_json_bytes(
                {
                    "error": f"{type(exc).__name__}: {str(exc)}",
                    "execution_authority": EXECUTION_AUTHORITY,
                    "live_provider_contact": False,
                    "rehearsal": "FAIL_CLOSED",
                }
            )
        )
        return 1
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
