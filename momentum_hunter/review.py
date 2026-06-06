from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.time_utils import now_central


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    INTERESTED = "interested"
    REJECTED = "rejected"
    WATCHLIST = "watchlist"


@dataclass(frozen=True)
class CandidateIdentity:
    capture_id: str
    capture_date: str
    session: str
    provider: str
    scanner: str
    ticker: str

    @property
    def key(self) -> str:
        parts = [self.capture_id, self.capture_date, self.session, self.provider, self.scanner, self.ticker]
        return "|".join(part.replace("|", "/") for part in parts)


@dataclass
class ReviewDecision:
    identity: CandidateIdentity
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    decision_timestamp: datetime | None = None
    decision_note: str = ""


REVIEW_DECISIONS_PATH = DATA_DIR / "review-decisions.json"


def make_capture_id(capture_date: str, session: str, provider: str, scanner: str) -> str:
    return f"{capture_date}|{session}|{provider}|{scanner}"


def load_review_decisions(path: Path | None = None) -> dict[str, ReviewDecision]:
    path = path or REVIEW_DECISIONS_PATH
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    decisions = payload.get("decisions", payload if isinstance(payload, dict) else {})
    return {
        key: review_decision_from_dict(item)
        for key, item in decisions.items()
        if isinstance(item, dict) and item.get("identity")
    }


def save_review_decisions(decisions: dict[str, ReviewDecision], path: Path | None = None) -> Path:
    path = path or REVIEW_DECISIONS_PATH
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": now_central().isoformat(),
        "decisions": {key: review_decision_to_dict(value) for key, value in sorted(decisions.items())},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def upsert_review_decision(
    decisions: dict[str, ReviewDecision],
    identity: CandidateIdentity,
    status: ReviewStatus,
    *,
    note: str = "",
    decision_timestamp: datetime | None = None,
    path: Path | None = None,
) -> ReviewDecision:
    decision = ReviewDecision(
        identity=identity,
        review_status=status,
        decision_timestamp=decision_timestamp or now_central(),
        decision_note=note,
    )
    decisions[identity.key] = decision
    save_review_decisions(decisions, path=path)
    return decision


def review_decision_to_dict(decision: ReviewDecision) -> dict:
    return {
        "identity": asdict(decision.identity),
        "review_status": decision.review_status.value,
        "decision_timestamp": decision.decision_timestamp.isoformat() if decision.decision_timestamp else None,
        "decision_note": decision.decision_note,
    }


def review_decision_from_dict(payload: dict) -> ReviewDecision:
    identity_payload = payload["identity"]
    timestamp = payload.get("decision_timestamp")
    status_text = payload.get("review_status", ReviewStatus.UNREVIEWED.value)
    try:
        status = ReviewStatus(status_text)
    except ValueError:
        status = ReviewStatus.UNREVIEWED
    return ReviewDecision(
        identity=CandidateIdentity(
            capture_id=identity_payload.get("capture_id", ""),
            capture_date=identity_payload.get("capture_date", ""),
            session=identity_payload.get("session", ""),
            provider=identity_payload.get("provider", ""),
            scanner=identity_payload.get("scanner", ""),
            ticker=identity_payload.get("ticker", ""),
        ),
        review_status=status,
        decision_timestamp=datetime.fromisoformat(timestamp) if timestamp else None,
        decision_note=payload.get("decision_note", ""),
    )
