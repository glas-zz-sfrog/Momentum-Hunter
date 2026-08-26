"""Canonical instant identity for Continuous decision chronology."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable


class ContinuousTimeIdentityError(ValueError):
    """Raised when a decision timestamp cannot establish one exact instant."""


def parse_instant(value: datetime | str, label: str = "Timestamp") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            raise ContinuousTimeIdentityError(f"{label} is required.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContinuousTimeIdentityError(f"{label} is malformed.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContinuousTimeIdentityError(f"{label} must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def canonical_instant(value: datetime | str, label: str = "Timestamp") -> str:
    """Return one precision-preserving UTC identity for an aware instant."""

    return (
        parse_instant(value, label)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def canonical_known_at(
    values: Iterable[tuple[str, datetime | str]],
) -> tuple[tuple[str, str], ...]:
    """Normalize labeled evidence chronology for equality and fingerprints."""

    normalized: dict[str, str] = {}
    for raw_label, value in values:
        label = str(raw_label).strip()
        if not label or label in normalized:
            raise ContinuousTimeIdentityError(
                "Known-at labels are missing or duplicated."
            )
        normalized[label] = canonical_instant(value, f"{label} known-at")
    return tuple(sorted(normalized.items()))


def chronology_fingerprint(
    domain: str,
    *,
    decision_cutoff: datetime | str,
    evidence_known_at: Iterable[tuple[str, datetime | str]],
) -> str:
    payload = {
        "domain": str(domain),
        "decisionCutoff": canonical_instant(
            decision_cutoff, "Decision cutoff"
        ),
        "evidenceKnownAt": canonical_known_at(evidence_known_at),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
