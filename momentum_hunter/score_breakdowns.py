from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.models import Candidate, MarketRegime
from momentum_hunter.scoring import SCORE_ENGINE_VERSION, build_score_breakdown, load_profile
from momentum_hunter.storage import CAPTURES_DIR, candidate_from_dict
from momentum_hunter.time_utils import now_central


SCORE_BREAKDOWNS_PATH = DATA_DIR / "score-breakdowns.json"
SCORE_BREAKDOWN_STORE_SCHEMA_VERSION = 1
COMPLETE = "complete"
LEGACY = "legacy"
INCOMPLETE = "incomplete"
FAILED = "failed"


@dataclass(frozen=True)
class ScoreBreakdownRebuildResult:
    output_path: Path
    backup_path: Path | None
    total_records: int
    counts: dict[str, int] = field(default_factory=dict)
    failed_records: list[dict] = field(default_factory=list)


def rebuild_score_breakdowns(
    *,
    captures_dir: Path = CAPTURES_DIR,
    output_path: Path = SCORE_BREAKDOWNS_PATH,
    generated_at: datetime | None = None,
) -> ScoreBreakdownRebuildResult:
    ensure_app_dirs()
    generated_at = generated_at or now_central()
    records: dict[str, dict] = {}
    counts = {COMPLETE: 0, LEGACY: 0, INCOMPLETE: 0, FAILED: 0}
    failed_records: list[dict] = []
    for capture_path in sorted(captures_dir.rglob("*.json")):
        try:
            payload = json.loads(capture_path.read_text(encoding="utf-8"))
            for candidate_payload in payload.get("candidates", []):
                record = build_score_breakdown_for_raw_candidate(
                    payload,
                    candidate_payload,
                    generated_at=generated_at,
                )
                records[record["identity_key"]] = record
                counts[record["status"]] = counts.get(record["status"], 0) + 1
        except Exception as exc:
            counts[FAILED] = counts.get(FAILED, 0) + 1
            failed_records.append({"capture_path": str(capture_path), "error": str(exc), "error_type": type(exc).__name__})

    payload = {
        "schema_version": SCORE_BREAKDOWN_STORE_SCHEMA_VERSION,
        "updated_at": generated_at.isoformat(),
        "score_engine_version": SCORE_ENGINE_VERSION,
        "records": records,
        "failed_records": failed_records,
    }
    backup_path = backup_existing_store(output_path, generated_at)
    atomic_write_json(payload, output_path)
    return ScoreBreakdownRebuildResult(
        output_path=output_path,
        backup_path=backup_path,
        total_records=len(records),
        counts=counts,
        failed_records=failed_records,
    )


def build_score_breakdown_for_raw_candidate(
    capture_payload: dict,
    candidate_payload: dict,
    *,
    generated_at: datetime | None = None,
) -> dict:
    generated_at = generated_at or now_central()
    candidate = candidate_from_dict(candidate_payload)
    capture_time = parse_capture_time(capture_payload.get("capture_time", ""))
    capture_date = capture_payload.get("capture_date", capture_time.strftime("%Y-%m-%d") if capture_time else "")
    session = capture_payload.get("session", "")
    provider = capture_payload.get("provider", "")
    mode = capture_payload.get("mode", "")
    scanner = scanner_name_from_payload(capture_payload)
    score_profile = candidate_payload.get("score_profile") or capture_payload.get("scoring", {}).get("profile") or ""
    profile = load_profile(score_profile or None)
    regime = regime_from_payload(capture_payload, candidate_payload)
    stored_score = int_or_none(candidate_payload.get("score"))
    identity = score_breakdown_identity(
        capture_date=capture_date,
        capture_time=capture_payload.get("capture_time", ""),
        session=session,
        provider=provider,
        scanner=scanner,
        ticker=candidate.ticker,
        mode=mode,
    )
    breakdown = build_score_breakdown(
        candidate,
        regime=regime,
        profile=profile,
        now=capture_time,
        identity=identity,
        stored_final_score=stored_score,
        generated_at=generated_at,
    )
    incomplete_reasons = incomplete_reasons_for_raw_candidate(capture_payload, candidate_payload, score_profile)
    if incomplete_reasons:
        breakdown["status"] = INCOMPLETE
        breakdown["reconciliation_status"] = "INCOMPLETE_INPUTS"
        breakdown["incomplete_reasons"] = incomplete_reasons
        breakdown["reconciliation"]["status"] = "INCOMPLETE_INPUTS"
    add_identity_fields(breakdown, identity)
    breakdown["identity_key"] = score_breakdown_identity_key(identity)
    breakdown["source"] = {
        "kind": "raw_capture",
        "capture_path": f"captures/{capture_date}/{session}.json" if capture_date and session else "",
    }
    return breakdown


def build_score_breakdown_for_candidate(
    candidate: Candidate,
    *,
    capture_time: datetime,
    session: str,
    provider: str,
    scanner: str,
    mode: str,
    regime: MarketRegime,
    generated_at: datetime | None = None,
) -> dict:
    generated_at = generated_at or now_central()
    identity = score_breakdown_identity(
        capture_date=capture_time.strftime("%Y-%m-%d"),
        capture_time=capture_time.isoformat(),
        session=session,
        provider=provider,
        scanner=scanner,
        ticker=candidate.ticker,
        mode=mode,
    )
    profile = load_profile(candidate.score_profile or None)
    breakdown = build_score_breakdown(
        candidate,
        regime=regime,
        profile=profile,
        now=capture_time,
        identity=identity,
        stored_final_score=candidate.score,
        generated_at=generated_at,
    )
    add_identity_fields(breakdown, identity)
    breakdown["identity_key"] = score_breakdown_identity_key(identity)
    breakdown["source"] = {"kind": "live_or_app_capture", "capture_path": ""}
    return breakdown


def upsert_score_breakdowns_for_candidates(
    candidates: list[Candidate],
    *,
    capture_time: datetime,
    session: str,
    provider: str,
    scanner: str,
    mode: str,
    regime: MarketRegime,
    output_path: Path = SCORE_BREAKDOWNS_PATH,
) -> list[dict]:
    store = load_score_breakdown_store(output_path)
    records = store.setdefault("records", {})
    generated: list[dict] = []
    generated_at = now_central()
    for candidate in candidates:
        record = build_score_breakdown_for_candidate(
            candidate,
            capture_time=capture_time,
            session=session,
            provider=provider,
            scanner=scanner,
            mode=mode,
            regime=regime,
            generated_at=generated_at,
        )
        records[record["identity_key"]] = record
        generated.append(record)
    store["schema_version"] = SCORE_BREAKDOWN_STORE_SCHEMA_VERSION
    store["updated_at"] = generated_at.isoformat()
    store["score_engine_version"] = SCORE_ENGINE_VERSION
    atomic_write_json(store, output_path)
    return generated


def upsert_score_breakdowns_for_capture_payload(
    capture_payload: dict,
    *,
    output_path: Path = SCORE_BREAKDOWNS_PATH,
) -> list[dict]:
    store = load_score_breakdown_store(output_path)
    records = store.setdefault("records", {})
    generated: list[dict] = []
    generated_at = now_central()
    for candidate_payload in capture_payload.get("candidates", []):
        record = build_score_breakdown_for_raw_candidate(
            capture_payload,
            candidate_payload,
            generated_at=generated_at,
        )
        records[record["identity_key"]] = record
        generated.append(record)
    store["schema_version"] = SCORE_BREAKDOWN_STORE_SCHEMA_VERSION
    store["updated_at"] = generated_at.isoformat()
    store["score_engine_version"] = SCORE_ENGINE_VERSION
    atomic_write_json(store, output_path)
    return generated


def load_score_breakdown_store(path: Path = SCORE_BREAKDOWNS_PATH) -> dict:
    if not path.exists():
        return {"schema_version": SCORE_BREAKDOWN_STORE_SCHEMA_VERSION, "records": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"schema_version": SCORE_BREAKDOWN_STORE_SCHEMA_VERSION, "records": {}}
    payload.setdefault("schema_version", SCORE_BREAKDOWN_STORE_SCHEMA_VERSION)
    payload.setdefault("records", {})
    return payload


def find_score_breakdown(identity: dict, path: Path = SCORE_BREAKDOWNS_PATH) -> dict | None:
    return load_score_breakdown_store(path).get("records", {}).get(score_breakdown_identity_key(identity))


def score_breakdown_identity(
    *,
    capture_date: str,
    capture_time: str,
    session: str,
    provider: str,
    scanner: str,
    ticker: str,
    mode: str = "",
    score_engine_version: str = SCORE_ENGINE_VERSION,
) -> dict:
    capture_id = f"{capture_date}|{session}|{provider}|{scanner}"
    return {
        "capture_id": capture_id,
        "capture_date": capture_date,
        "capture_time": capture_time,
        "session": session,
        "provider": provider,
        "scanner": scanner,
        "mode": mode,
        "ticker": ticker,
        "score_engine_version": score_engine_version,
    }


def score_breakdown_identity_key(identity: dict) -> str:
    parts = [
        identity.get("capture_id", ""),
        identity.get("capture_time", ""),
        identity.get("ticker", ""),
        identity.get("score_engine_version", SCORE_ENGINE_VERSION),
    ]
    return "|".join(str(part).replace("|", "/") for part in parts)


def add_identity_fields(record: dict, identity: dict) -> None:
    record["identity"] = identity
    for key, value in identity.items():
        record[key] = value


def expected_score_breakdown_identities(captures_dir: Path = CAPTURES_DIR) -> dict[str, dict]:
    identities: dict[str, dict] = {}
    for capture_path in sorted(captures_dir.rglob("*.json")):
        try:
            payload = json.loads(capture_path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        capture_time = payload.get("capture_time", "")
        capture_date = payload.get("capture_date", capture_time[:10] if capture_time else "")
        session = payload.get("session", "")
        provider = payload.get("provider", "")
        scanner = scanner_name_from_payload(payload)
        mode = payload.get("mode", "")
        for candidate in payload.get("candidates", []):
            identity = score_breakdown_identity(
                capture_date=capture_date,
                capture_time=capture_time,
                session=session,
                provider=provider,
                scanner=scanner,
                ticker=candidate.get("ticker", ""),
                mode=mode,
            )
            identities[score_breakdown_identity_key(identity)] = identity
    return identities


def backup_existing_store(path: Path, generated_at: datetime) -> Path | None:
    if not path.exists():
        return None
    backup_dir = DATA_DIR / "backups" / "score-breakdowns" / generated_at.strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / path.name
    shutil.copy2(path, backup_path)
    return backup_path


def atomic_write_json(payload: dict, output_path: Path) -> None:
    ensure_app_dirs()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(output_path)


def parse_capture_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def scanner_name_from_payload(payload: dict) -> str:
    scanner = payload.get("scanner", {})
    return scanner.get("name", "") if isinstance(scanner, dict) else str(scanner)


def regime_from_payload(capture_payload: dict, candidate_payload: dict) -> MarketRegime:
    raw = candidate_payload.get("score_regime") or capture_payload.get("scoring", {}).get("regime") or capture_payload.get("market", {}).get("regime")
    try:
        return MarketRegime(raw)
    except ValueError:
        return MarketRegime.UNKNOWN


def incomplete_reasons_for_raw_candidate(capture_payload: dict, candidate_payload: dict, score_profile: str) -> list[str]:
    reasons: list[str] = []
    if not capture_payload.get("capture_time"):
        reasons.append("capture_time missing")
    if not score_profile:
        reasons.append("score_profile missing; active profile was used for reconstruction")
    for field in ("price", "percent_change", "volume", "relative_volume", "market_cap", "score"):
        if field not in candidate_payload:
            reasons.append(f"{field} missing")
    return reasons


def int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
