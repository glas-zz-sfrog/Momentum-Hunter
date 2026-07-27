from __future__ import annotations

import hashlib
import json
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

from momentum_hunter.schwab_market_data import SCHWAB_QUOTE_SOURCE
from momentum_hunter.shadow_market_validity import (
    SHADOW_SELECTOR_ARM_REQUIRED_PROOFS,
    canonical_json,
    runtime_build_hash,
    shadow_constitution_hash,
)
from momentum_hunter.shadow_opening import build_https_clock_skew_proof
from momentum_hunter.shadow_trading import (
    SHADOW_EVIDENCE_SCHEMA_VERSION,
    SHADOW_FILL_MODEL_VERSION,
    SHADOW_SELECTION_POLICY_VERSION,
    expected_shadow_selection_policy_evidence,
)
from momentum_hunter.trade_planning import REPORT_SCHEMA_VERSION


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
        if name == "fresh_quote_boundary":
            paths[name] = write_fresh_quote_proof(
                bundle,
                seed=seed,
                sample_version=sample_version,
                activation_path=activation_path,
                verified_at=verified_at,
            )
            continue
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


def write_fresh_quote_proof(
    bundle: Path,
    *,
    seed: str,
    sample_version: str,
    activation_path: Path,
    verified_at: datetime,
) -> Path:
    task_path = bundle / "scheduled_task_definition.xml"
    task_path.write_text(
        f"<Task><SyntheticSeed>{seed}</SyntheticSeed></Task>\n",
        encoding="utf-8",
    )
    policy = expected_shadow_selection_policy_evidence()
    configuration: dict[str, object] = {
        "schemaVersion": 1,
        "proofType": "SHADOW_OPENING_CONFIGURATION_IDENTITY",
        "provider": "synthetic-test-provider",
        "scanner": "Institutional Momentum",
        "reportSchemaVersion": REPORT_SCHEMA_VERSION,
        "constitutionHash": shadow_constitution_hash(),
        "selectionPolicyVersion": SHADOW_SELECTION_POLICY_VERSION,
        "selectionPolicyFingerprint": policy[
            "selection_policy_fingerprint"
        ],
        "fillModelVersion": SHADOW_FILL_MODEL_VERSION,
        "evidenceSchemaVersion": SHADOW_EVIDENCE_SCHEMA_VERSION,
        "runtimeBuildHash": runtime_build_hash(),
        "scheduledTaskDefinitionSha256": hashlib.sha256(
            task_path.read_bytes()
        ).hexdigest(),
        "quoteSource": SCHWAB_QUOTE_SOURCE,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }
    configuration["configurationIdentitySha256"] = hashlib.sha256(
        canonical_json(configuration).encode("utf-8")
    ).hexdigest()
    configuration_path = bundle / "opening_configuration_identity.json"
    configuration_path.write_text(
        json.dumps(configuration, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    clock_proof = build_https_clock_skew_proof(
        request_started_at=verified_at,
        response_received_at=verified_at,
        remote_date_header=format_datetime(verified_at),
        source_identity="synthetic-test-https-date",
    )
    quote_path = bundle / "fresh_quote_boundary.evidence.json"
    quote_path.write_text(
        json.dumps(
            {
                "schemaVersion": 3,
                "proofType": "SCHWAB_REGULAR_MARKET_QUOTE_BOUNDARY",
                "clockSkewProof": clock_proof,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence_paths = (quote_path, configuration_path, task_path)
    path = bundle / "fresh_quote_boundary.json"
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
                        "path": item.name,
                        "sha256": hashlib.sha256(
                            item.read_bytes()
                        ).hexdigest(),
                    }
                    for item in evidence_paths
                ],
                "proof_name": "fresh_quote_boundary",
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
    return path
