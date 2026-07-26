from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from momentum_hunter.shadow_market_validity import (
    SHADOW_SELECTOR_ARM_REQUIRED_PROOFS,
    runtime_build_hash,
    shadow_constitution_hash,
)


def write_synthetic_proof_artifacts(
    root: Path,
    seed: str,
    *,
    sample_version: str,
    activation_path: Path,
    verified_at: datetime,
) -> dict[str, Path]:
    bundle_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    bundle = root / f"selector-proof-fixtures-{bundle_id}"
    bundle.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name in SHADOW_SELECTOR_ARM_REQUIRED_PROOFS:
        evidence_path = bundle / f"{name}.evidence.txt"
        evidence_path.write_text(
            f"synthetic test evidence only\nproof={name}\nseed={seed}\n",
            encoding="utf-8",
        )
        path = bundle / f"{name}.json"
        path.write_text(
            json.dumps(
                {
                    "activation_hash": hashlib.sha256(
                        activation_path.read_bytes()
                    ).hexdigest(),
                    "build_hash": runtime_build_hash(),
                    "constitution_hash": shadow_constitution_hash(),
                    "evidence": [
                        {
                            "path": evidence_path.name,
                            "sha256": hashlib.sha256(
                                evidence_path.read_bytes()
                            ).hexdigest(),
                        }
                    ],
                    "proof_name": name,
                    "schema_version": 1,
                    "sample_version": sample_version,
                    "status": "PASS",
                    "summary": "Synthetic test-only prerequisite proof.",
                    "verified_at": verified_at.isoformat(),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        paths[name] = path
    return paths
