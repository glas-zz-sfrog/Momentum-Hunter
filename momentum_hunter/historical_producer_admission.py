"""Dormant read-only historical admission under independently provisioned pins.

No authority discovery, writer, bootstrap, environment override or caller-chosen
root exists. Tests replace these private installation constants in isolation.
Provisioning and custody separation remain separately authorized operations.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat


REGISTRY_ID = "MH_HISTORICAL_PRODUCER_ADMISSION_V1"
ARTIFACT_KIND = "CONTINUOUS_TRADEPLAN_PRODUCER_CACHE"
HISTORICAL_CONTRACT = "PRE_LIFECYCLE_PRODUCER_V1_2BCEEEA"
SOURCE_COMMIT = "2bceeeadd06f5ed85943942f1c0f81b7094620f7"
ADMITTED = "PRECONTRACT_LEGACY_ADMITTED"
NOT_ADMITTED = "NOT_ADMITTED"
MISMATCH = "ADMISSION_MISMATCH"
AMBIGUOUS = "AMBIGUOUS_ADMISSION"
REVOKED = "REVOKED"
TEST_PURPOSE = "ISOLATED_COMPATIBILITY_TEST"
PRODUCTION_PURPOSE = "PRODUCTION_LEGACY_INSPECTION"
_CHECKPOINT_PATH = Path(r"C:\ProgramData\MomentumHunter\governance\historical-producer-admission-current.json")
_SELECTOR_PATH = Path(r"C:\Users\steve\OneDrive\Documents\Investing\docs\argus-office\architecture\HISTORICAL_PRODUCER_ADMISSION_CURRENT.json")
_AUTHORITY_ROOT = Path(r"C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\HISTORICAL-PRODUCER-ADMISSION")
_PIN_LIMIT = 16 * 1024
_REGISTRY_LIMIT = 4 * 1024 * 1024
_ARTIFACT_LIMIT = 64 * 1024 * 1024
_SHA = re.compile(r"[0-9A-F]{64}\Z")
_GIT = re.compile(r"[0-9a-f]{40}\Z")


class HistoricalAdmissionError(ValueError):
    """Missing, malformed, conflicting or stale external authority."""


@dataclass(frozen=True)
class HistoricalAdmissionDecision:
    disposition: str
    reason: str
    artifact_sha256: str
    artifact_bytes: int
    generation: int | None = None
    registry_sha256: str = ""
    evidence_class: str = ""
    purpose: str = ""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest().upper()


def _object(value: object, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise HistoricalAdmissionError(f"{label} has missing or unknown fields.")
    return value


def _integer(value: object, label: str, maximum: int | None = None) -> int:
    if type(value) is not int or value < 1 or (maximum is not None and value > maximum):
        raise HistoricalAdmissionError(f"{label} must be a supported positive integer.")
    return value


def _text(value: object, label: str, limit: int = 4096) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise HistoricalAdmissionError(f"{label} must be bounded nonempty text.")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise HistoricalAdmissionError("Expected uppercase whole-byte SHA-256.")
    return value


def _locator(value: object) -> str:
    value = _text(value, "Authority locator", 2048)
    parts = value.split("/")
    if (PurePosixPath(value).is_absolute() or any(c in value for c in '\\:<>"|?*')
            or any(p in {"", ".", ".."} or p.endswith((".", " ")) for p in parts)
            or any(re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p) for p in parts)):
        raise HistoricalAdmissionError("Authority locator is unsafe.")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise HistoricalAdmissionError("Duplicate JSON object key.")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise HistoricalAdmissionError("Nonfinite authority number.")


def _parse(raw: bytes, limit: int) -> dict:
    if type(raw) is not bytes or not raw or len(raw) > limit:
        raise HistoricalAdmissionError("Authority bytes are empty or exceed their bound.")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HistoricalAdmissionError("Authority JSON is invalid.") from exc
    if type(value) is not dict:
        raise HistoricalAdmissionError("Authority must be one JSON object.")
    return value


def _identity(value: dict) -> None:
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise HistoricalAdmissionError("Unsupported authority schema.")
    if value["registryId"] != REGISTRY_ID:
        raise HistoricalAdmissionError("Unknown registry identity.")
    _integer(value["generation"], "Authority generation")


def parse_authority_checkpoint(raw: bytes) -> dict:
    value = _object(_parse(raw, _PIN_LIMIT), {"schemaVersion", "registryId", "generation", "selectorSha256", "purpose"}, "Checkpoint")
    _identity(value)
    _digest(value["selectorSha256"])
    if value["purpose"] not in (TEST_PURPOSE, PRODUCTION_PURPOSE):
        raise HistoricalAdmissionError("Unknown trusted purpose.")
    return value


def parse_canonical_selector(raw: bytes) -> dict:
    value = _object(_parse(raw, _PIN_LIMIT), {"schemaVersion", "registryId", "generation", "registrySha256", "registryBytes", "snapshotRelativePath"}, "Selector")
    _identity(value)
    _digest(value["registrySha256"])
    _integer(value["registryBytes"], "Registry byte count", _REGISTRY_LIMIT)
    _locator(value["snapshotRelativePath"])
    return value


def parse_admission_registry(raw: bytes) -> dict:
    value = _object(_parse(raw, _REGISTRY_LIMIT), {"schemaVersion", "registryId", "generation", "predecessor", "events"}, "Registry")
    _identity(value)
    predecessor = value["predecessor"]
    if value["generation"] == 1:
        if predecessor is not None:
            raise HistoricalAdmissionError("Genesis has a predecessor.")
    else:
        _object(predecessor, {"generation", "sha256", "bytes"}, "Predecessor")
        _integer(predecessor["generation"], "Predecessor generation")
        if predecessor["generation"] != value["generation"] - 1:
            raise HistoricalAdmissionError("Predecessor generation is not contiguous.")
        _digest(predecessor["sha256"])
        _integer(predecessor["bytes"], "Predecessor byte count", _REGISTRY_LIMIT)
    if type(value["events"]) is not list:
        raise HistoricalAdmissionError("Registry events must be an ordered list.")
    if value["generation"] > 1 and not value["events"]:
        raise HistoricalAdmissionError("Non-genesis registry is missing retained history.")
    by_sequence = {}
    by_artifact = {}
    unique = []
    event_keys = {"sequence", "artifactKind", "artifactSha256", "artifactBytes", "evidenceClass", "sourceCommit", "historicalContract", "disposition", "supersedesSequence", "custody", "admissionTask", "reviewTask", "reason"}
    lineage_keys = ("artifactKind", "artifactSha256", "artifactBytes", "evidenceClass", "sourceCommit", "historicalContract")
    for event in value["events"]:
        _object(event, event_keys, "Admission event")
        sequence = _integer(event["sequence"], "Event sequence", 10000)
        if event["artifactKind"] != ARTIFACT_KIND:
            raise HistoricalAdmissionError("Unsupported artifact kind.")
        _digest(event["artifactSha256"])
        _integer(event["artifactBytes"], "Artifact byte count", _ARTIFACT_LIMIT)
        if event["evidenceClass"] not in ("SYNTHETIC_OLD_CODE_FIXTURE", "HISTORICAL_CACHE"):
            raise HistoricalAdmissionError("Unsupported evidence class.")
        if (type(event["sourceCommit"]) is not str or not _GIT.fullmatch(event["sourceCommit"])
                or event["sourceCommit"] != SOURCE_COMMIT or event["historicalContract"] != HISTORICAL_CONTRACT):
            raise HistoricalAdmissionError("Unsupported exact historical source contract.")
        _object(event["custody"], {"packetSha256", "packetBytes", "packetRelativePath"}, "Custody")
        _digest(event["custody"]["packetSha256"])
        _integer(event["custody"]["packetBytes"], "Custody packet byte count")
        _locator(event["custody"]["packetRelativePath"])
        for key in ("admissionTask", "reviewTask", "reason"):
            _text(event[key], key)
        if event["disposition"] not in (ADMITTED, REVOKED):
            raise HistoricalAdmissionError("Unsupported admission disposition.")
        if event["supersedesSequence"] is not None:
            _integer(event["supersedesSequence"], "Superseded admission sequence", 10000)
        prior_sequence = by_sequence.get(sequence)
        if prior_sequence is not None:
            if prior_sequence != event:
                raise HistoricalAdmissionError("Conflicting duplicate sequence.")
            continue
        if sequence != len(unique) + 1:
            raise HistoricalAdmissionError("Complete event history is not contiguous.")
        prior = by_artifact.get(event["artifactSha256"])
        if event["disposition"] == ADMITTED:
            if prior is not None or event["supersedesSequence"] is not None:
                raise HistoricalAdmissionError("Repeated admission or terminal-revoke readmission.")
        elif (prior is None or prior["disposition"] != ADMITTED
              or event["supersedesSequence"] != prior["sequence"]
              or any(prior[key] != event[key] for key in lineage_keys)):
            raise HistoricalAdmissionError("Invalid withdrawal transition or changed lineage.")
        unique.append(event)
        by_sequence[sequence] = event
        by_artifact[event["artifactSha256"]] = event
    return {**value, "events": unique}


def _read(path: Path, limit: int) -> bytes:
    # Reject aliases at the configured authority boundary; paths cannot select trust.
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise HistoricalAdmissionError("Authority path contains a reparse/link alias.")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise HistoricalAdmissionError("Authority file is empty or oversized.")
    return raw


@dataclass(frozen=True)
class _CurrentAuthority:
    checkpoint_raw: bytes
    selector_raw: bytes
    registry_raw: bytes
    registry_path: Path
    checkpoint: dict
    registry: dict

    def revalidate(self) -> None:
        if (_read(_CHECKPOINT_PATH, _PIN_LIMIT) != self.checkpoint_raw
                or _read(_SELECTOR_PATH, _PIN_LIMIT) != self.selector_raw
                or _read(self.registry_path, _REGISTRY_LIMIT) != self.registry_raw
                or _read(_CHECKPOINT_PATH, _PIN_LIMIT) != self.checkpoint_raw):
            raise HistoricalAdmissionError("Authority changed during the operation.")


def _current_authority() -> _CurrentAuthority:
    checkpoint_raw = _read(_CHECKPOINT_PATH, _PIN_LIMIT)
    checkpoint = parse_authority_checkpoint(checkpoint_raw)
    selector_raw = _read(_SELECTOR_PATH, _PIN_LIMIT)
    if _sha(selector_raw) != checkpoint["selectorSha256"]:
        raise HistoricalAdmissionError("Current checkpoint rejects this selector.")
    selector = parse_canonical_selector(selector_raw)
    if selector["generation"] != checkpoint["generation"]:
        raise HistoricalAdmissionError("Selector is stale or contradictory.")
    path = _AUTHORITY_ROOT.joinpath(*selector["snapshotRelativePath"].split("/"))
    if not path.resolve().is_relative_to(_AUTHORITY_ROOT.resolve()):
        raise HistoricalAdmissionError("Selected snapshot escapes the fixed authority root.")
    registry_raw = _read(path, _REGISTRY_LIMIT)
    if len(registry_raw) != selector["registryBytes"] or _sha(registry_raw) != selector["registrySha256"]:
        raise HistoricalAdmissionError("Selected snapshot hash/size mismatch.")
    registry = parse_admission_registry(registry_raw)
    if registry["generation"] != checkpoint["generation"]:
        raise HistoricalAdmissionError("Snapshot generation is not current.")
    result = _CurrentAuthority(checkpoint_raw, selector_raw, registry_raw, path, checkpoint, registry)
    result.revalidate()
    return result


def _resolve(raw: bytes, expected_sequence: int | None = None) -> tuple[HistoricalAdmissionDecision, _CurrentAuthority]:
    if type(raw) is not bytes or not raw or len(raw) > _ARTIFACT_LIMIT:
        raise HistoricalAdmissionError("Artifact raw-byte boundary is invalid.")
    if expected_sequence is not None:
        _integer(expected_sequence, "Diagnostic expected admission", 10000)
    authority = _current_authority()
    digest = _sha(raw)
    events = authority.registry["events"]
    if expected_sequence is not None:
        expected = next((e for e in events if e["sequence"] == expected_sequence), None)
        if expected is None or expected["artifactSha256"] != digest or expected["artifactBytes"] != len(raw):
            decision = HistoricalAdmissionDecision(MISMATCH, "Diagnostic expected admission differs.", digest, len(raw))
            authority.revalidate()
            return decision, authority
    matches = [event for event in events if event["artifactSha256"] == digest]
    event = matches[-1] if matches else None  # Validated explicit revoke is the only transition.
    disposition, reason = NOT_ADMITTED, "No exact external admission."
    if event is not None:
        if event["artifactBytes"] != len(raw):
            disposition, reason = MISMATCH, "Whole-artifact byte count differs."
        elif event["disposition"] == REVOKED:
            disposition, reason = REVOKED, "Explicit withdrawal is current."
        elif event["evidenceClass"] == "SYNTHETIC_OLD_CODE_FIXTURE" and authority.checkpoint["purpose"] != TEST_PURPOSE:
            reason = "Synthetic fixture is ineligible for production purpose."
        else:
            disposition, reason = ADMITTED, "Exact external identity eligible for structural validation."
    decision = HistoricalAdmissionDecision(disposition, reason, digest, len(raw), authority.checkpoint["generation"], _sha(authority.registry_raw), event["evidenceClass"] if event else "", authority.checkpoint["purpose"])
    authority.revalidate()
    return decision, authority


def resolve_historical_admission(raw: bytes, *, expected_sequence: int | None = None) -> HistoricalAdmissionDecision:
    """Resolve fixed independent authority; returned diagnostics cannot grant input trust."""
    try:
        return _resolve(raw, expected_sequence)[0]
    except (HistoricalAdmissionError, OSError, ValueError, TypeError, RecursionError) as exc:
        return HistoricalAdmissionDecision(AMBIGUOUS, str(exc), _sha(raw) if type(raw) is bytes else "", len(raw) if type(raw) is bytes else 0)
