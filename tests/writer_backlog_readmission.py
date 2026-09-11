"""Explicit dual-custody qualification of changed Engine010 source.

The original Engine007/008 gate is untouched. Accepted preimages are verified
against its immutable physical evidence; a separately pinned candidate manifest
binds the executable postimages used to replay every original finite trial.
This grants neither inherited physical capacity proof nor runtime authority.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from tests import writer_backlog_gate as original

MANIFEST_ENV = "MH_WRITER_BACKLOG_010_READMISSION_MANIFEST"
PIN_ENV = "MH_WRITER_BACKLOG_010_READMISSION_SHA256"
PROFILE = "ENGINE010_ACCEPTED007_TRACE_READMISSION"


def source_inventory(root):
    return {path.relative_to(root).as_posix() for directory in ("momentum_hunter", "tests", "tools")
            for path in (root / directory).rglob("*.py") if "__pycache__" not in path.parts}


def verify_candidate(root, manifest):
    original.require(manifest.get("profile") == PROFILE, "WRONG_READMISSION_PROFILE")
    original.require(Path(manifest["candidate_root"]).resolve(strict=True) == root, "WRONG_CANDIDATE_ROOT")
    entries = manifest["candidate_files"]
    original.require(isinstance(entries, list), "INVALID_CANDIDATE_INVENTORY")
    names = [entry["path"] for entry in entries]
    original.require(len(set(name.casefold() for name in names)) == len(names), "DUPLICATE_CANDIDATE_PATH")
    original.require(set(names) == source_inventory(root), "CANDIDATE_CLOSURE_CHANGED")
    for entry in entries:
        raw = original.checked_path(root, entry["path"]).read_bytes()
        original.require(len(raw) == entry["bytes"] and original.digest(raw) == entry["sha256"],
                         "CANDIDATE_BYTES_CHANGED:" + entry["path"])
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        filename = getattr(module, "__file__", None)
        if filename and (name in {"momentum_hunter", "tests"} or name.startswith("momentum_hunter.") or name.startswith("tests.")):
            path = Path(filename).resolve(strict=True)
            original.require(path.is_relative_to(root), "MIXED_CANDIDATE_IMPORT:" + name)
            original.require(path.relative_to(root).as_posix() in names, "UNBOUND_CANDIDATE_IMPORT:" + name)


def verify_for_current_source(root, source_root):
    path, pin = os.environ.get(MANIFEST_ENV), os.environ.get(PIN_ENV)
    if not path and not pin:
        return original.verify_custody(root, source_root)
    original.require(bool(path and pin), "INCOMPLETE_READMISSION_OPT_IN")
    raw = Path(path).read_bytes()
    original.require(original.digest(raw) == pin, "READMISSION_PIN_MISMATCH")
    manifest = json.loads(raw)
    candidate = Path(source_root).resolve(strict=True)
    verify_candidate(candidate, manifest)
    preimage = Path(manifest["accepted_preimage_root"]).resolve(strict=True)
    original.require(not preimage.is_relative_to(candidate) and not candidate.is_relative_to(preimage),
                     "PREIMAGE_CANDIDATE_OVERLAP")
    entries = original.verify_custody(Path(root), preimage)
    changed = []
    for name in original.BOUND_PRODUCT_FILES:
        relative = "momentum_hunter/" + name
        if (candidate / relative).read_bytes() != (preimage / relative).read_bytes():
            changed.append(relative)
    original.require(sorted(changed) == manifest["changed_bound_paths"], "READMISSION_DELTA_CHANGED")
    original.require(manifest["capacity"] == original.CAPACITY, "READMISSION_CAPACITY_CHANGED")
    return entries


def qualify(root=None, source_root=None):
    root = Path(root or os.environ.get(original.EVIDENCE_ENV, original.DEFAULT_EVIDENCE))
    source_root = Path(source_root or Path(__file__).resolve().parents[1])
    if not os.environ.get(MANIFEST_ENV) and not os.environ.get(PIN_ENV):
        return original.qualify(root, source_root)
    entries = verify_for_current_source(root, source_root)
    trials = [original.qualify_trial(original.load_trial(root, name)) for name in original.BOUNDS]
    verify_for_current_source(root, source_root)
    return {"status": "PASS", "gate": PROFILE, "verifiedEntries": entries,
            "candidateManifestSha256": os.environ[PIN_ENV],
            "primaryInput": "RETAINED_PHYSICAL_007_TRACE_PLUS_EXACT_ENGINE010_QUEUE",
            "notNewCapacityMeasurement": True, "installedOrUnboundedReadiness": False,
            "freshNaturalProducerInteractionRequiredSeparately": True, "trials": trials}


if __name__ == "__main__":
    print(json.dumps(qualify(), indent=2))
