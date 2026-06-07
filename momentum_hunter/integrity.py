from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.score_breakdowns import (
    SCORE_BREAKDOWNS_PATH,
    expected_score_breakdown_identities,
    load_score_breakdown_store,
    score_breakdown_identity_key,
)
from momentum_hunter.storage import (
    ANALYSIS_CSV,
    CAPTURE_INTEGRITY_MANIFEST,
    CAPTURES_DIR,
    capture_manifest_key,
    file_sha256,
    load_capture_integrity_manifest,
)


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

OK = "OK"
MODIFIED = "MODIFIED"
MISSING = "MISSING"
UNTRACKED = "UNTRACKED"
ORPHANED_DERIVED_RECORD = "ORPHANED_DERIVED_RECORD"
QUARANTINED = "QUARANTINED"
MISSING_SCORE_BREAKDOWN = "MISSING_SCORE_BREAKDOWN"
DUPLICATE_SCORE_BREAKDOWN = "DUPLICATE_SCORE_BREAKDOWN"
SCORE_BREAKDOWN_INVALID = "SCORE_BREAKDOWN_INVALID"
SCORE_BREAKDOWN_LEGACY = "SCORE_BREAKDOWN_LEGACY"
SCORE_BREAKDOWN_INCOMPLETE = "SCORE_BREAKDOWN_INCOMPLETE"

AUDIT_CSV = DATA_DIR / "integrity" / "raw_capture_integrity_audit.csv"
AUDIT_MD = DATA_DIR / "integrity" / "raw_capture_integrity_audit.md"


@dataclass(frozen=True)
class IntegrityAuditRow:
    path: str
    kind: str
    status: str
    severity: str
    created_at: str = ""
    capture_version: str = ""
    manifest_hash: str = ""
    current_hash: str = ""
    details: str = ""


def audit_raw_captures(
    *,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    analysis_csv: Path = ANALYSIS_CSV,
    outcomes_csv: Path = OUTCOMES_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
) -> list[IntegrityAuditRow]:
    rows = audit_manifest_records(manifest_path)
    rows.extend(audit_quarantined_manifest_records(manifest_path))
    rows.extend(audit_untracked_raw_captures(captures_dir, rows))
    rows.extend(
        audit_orphaned_derived_records(
            captures_dir=captures_dir,
            manifest_path=manifest_path,
            analysis_csv=analysis_csv,
            outcomes_csv=outcomes_csv,
            review_decisions_path=review_decisions_path,
        )
    )
    return rows


def audit_manifest_records(manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST) -> list[IntegrityAuditRow]:
    manifest = load_capture_integrity_manifest(manifest_path)
    records = manifest.get("records", {})
    rows: list[IntegrityAuditRow] = []
    for key, record in sorted(records.items()):
        path = resolve_manifest_path(key)
        expected_hash = record.get("source_hash", "")
        if not path.exists():
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind=record.get("kind", ""),
                    status=MISSING,
                    severity=FAIL,
                    created_at=record.get("created_at", ""),
                    capture_version=record.get("capture_version", ""),
                    manifest_hash=expected_hash,
                    details="Manifest references a raw capture file that no longer exists.",
                )
            )
            continue
        current_hash = file_sha256(path)
        if current_hash != expected_hash:
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind=record.get("kind", ""),
                    status=MODIFIED,
                    severity=FAIL,
                    created_at=record.get("created_at", ""),
                    capture_version=record.get("capture_version", ""),
                    manifest_hash=expected_hash,
                    current_hash=current_hash,
                    details="Raw capture file hash differs from manifest.",
                )
            )
            continue
        rows.append(
            IntegrityAuditRow(
                path=key,
                kind=record.get("kind", ""),
                status=OK,
                severity=PASS,
                created_at=record.get("created_at", ""),
                capture_version=record.get("capture_version", ""),
                manifest_hash=expected_hash,
                current_hash=current_hash,
            )
        )
    return rows


def audit_quarantined_manifest_records(manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST) -> list[IntegrityAuditRow]:
    manifest = load_capture_integrity_manifest(manifest_path)
    records = manifest.get("quarantined_records", {})
    rows: list[IntegrityAuditRow] = []
    for key, record in sorted(records.items()):
        quarantine_path = record.get("quarantine_path", "")
        reason = record.get("quarantine_reason", "Raw capture has been quarantined and is excluded from studies.")
        if not quarantine_path:
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind=record.get("kind", "raw_capture"),
                    status=MISSING,
                    severity=FAIL,
                    created_at=record.get("created_at", ""),
                    capture_version=record.get("capture_version", ""),
                    manifest_hash=record.get("source_hash", ""),
                    details=f"{reason} Quarantine record has no quarantine path.",
                )
            )
            continue
        path = resolve_manifest_path(quarantine_path)
        if not path.exists():
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind=record.get("kind", "raw_capture"),
                    status=MISSING,
                    severity=FAIL,
                    created_at=record.get("created_at", ""),
                    capture_version=record.get("capture_version", ""),
                    manifest_hash=record.get("quarantine_hash", ""),
                    details=f"{reason} Quarantine file is missing: {quarantine_path}.",
                )
            )
            continue
        current_hash = file_sha256(path)
        quarantine_hash = record.get("quarantine_hash", "")
        if quarantine_hash and current_hash != quarantine_hash:
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind=record.get("kind", "raw_capture"),
                    status=MODIFIED,
                    severity=FAIL,
                    created_at=record.get("created_at", ""),
                    capture_version=record.get("capture_version", ""),
                    manifest_hash=quarantine_hash,
                    current_hash=current_hash,
                    details=f"{reason} Quarantined raw capture hash differs from quarantine manifest: {quarantine_path}.",
                )
            )
            continue
        details = f"{reason} Quarantine path: {quarantine_path}."
        rows.append(
            IntegrityAuditRow(
                path=key,
                kind=record.get("kind", "raw_capture"),
                status=QUARANTINED,
                severity=WARN,
                created_at=record.get("created_at", ""),
                capture_version=record.get("capture_version", ""),
                manifest_hash=record.get("source_hash", ""),
                current_hash=current_hash,
                details=details,
            )
        )
    return rows


def audit_untracked_raw_captures(captures_dir: Path, known_rows: list[IntegrityAuditRow]) -> list[IntegrityAuditRow]:
    known = {row.path for row in known_rows}
    rows: list[IntegrityAuditRow] = []
    for path in sorted(raw_capture_files(captures_dir)):
        key = capture_manifest_key(path)
        if key in known:
            continue
        rows.append(
            IntegrityAuditRow(
                path=key,
                kind=kind_for_path(path),
                status=UNTRACKED,
                severity=WARN,
                current_hash=file_sha256(path),
                details="Raw capture exists but is not listed in the external integrity manifest.",
            )
        )
    return rows


def audit_orphaned_derived_records(
    *,
    captures_dir: Path,
    manifest_path: Path,
    analysis_csv: Path,
    outcomes_csv: Path,
    review_decisions_path: Path,
) -> list[IntegrityAuditRow]:
    rows: list[IntegrityAuditRow] = []
    rows.extend(audit_derived_csv("analysis-captures", analysis_csv, captures_dir))
    rows.extend(audit_derived_csv("analysis-outcomes", outcomes_csv, captures_dir))
    rows.extend(audit_review_decisions(review_decisions_path, captures_dir, manifest_path))
    return rows


def audit_derived_csv(label: str, path: Path, captures_dir: Path) -> list[IntegrityAuditRow]:
    if not path.exists():
        return []
    rows: list[IntegrityAuditRow] = []
    with path.open(newline="", encoding="utf-8") as file:
        for index, row in enumerate(csv.DictReader(file), 2):
            capture_date = row.get("capture_date", "")
            session = row.get("session", "")
            ticker = row.get("ticker", "")
            if not capture_date or not session:
                continue
            raw_path = captures_dir / capture_date / f"{session}.json"
            if not raw_path.exists():
                rows.append(
                    IntegrityAuditRow(
                        path=f"{path.name}:row:{index}",
                        kind=f"derived_{label}",
                        status=ORPHANED_DERIVED_RECORD,
                        severity=FAIL,
                        details=f"Derived row references missing raw capture {raw_path}.",
                    )
                )
                continue
            if ticker and not raw_capture_contains_ticker(raw_path, ticker):
                rows.append(
                    IntegrityAuditRow(
                        path=f"{path.name}:row:{index}",
                        kind=f"derived_{label}",
                        status=ORPHANED_DERIVED_RECORD,
                        severity=FAIL,
                        details=f"Derived row references ticker {ticker}, which is not present in {raw_path}.",
                    )
                )
    return rows


def audit_review_decisions(path: Path, captures_dir: Path, manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST) -> list[IntegrityAuditRow]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return [
            IntegrityAuditRow(
                path=capture_manifest_key(path),
                kind="review_decisions",
                status=ORPHANED_DERIVED_RECORD,
                severity=FAIL,
                details="Review decision file is not valid JSON.",
            )
        ]
    decisions = payload.get("decisions", {})
    quarantined_groups = quarantined_capture_groups(manifest_path)
    rows: list[IntegrityAuditRow] = []
    for key, decision in decisions.items():
        identity = decision.get("identity", {}) if isinstance(decision, dict) else {}
        session = identity.get("session", "")
        if session not in {"morning", "evening", "preopen", "manual"}:
            continue
        capture_date = identity.get("capture_date", "")
        ticker = identity.get("ticker", "")
        if not capture_date:
            continue
        raw_path = captures_dir / capture_date / f"{session}.json"
        if not raw_path.exists():
            if decision_is_quarantined(decision, identity, quarantined_groups):
                rows.append(
                    IntegrityAuditRow(
                        path=f"{path.name}:{key}",
                        kind="review_decision",
                        status=QUARANTINED,
                        severity=WARN,
                        details=f"Review decision references quarantined raw capture {raw_path}.",
                    )
                )
                continue
            rows.append(
                IntegrityAuditRow(
                    path=f"{path.name}:{key}",
                    kind="review_decision",
                    status=ORPHANED_DERIVED_RECORD,
                    severity=FAIL,
                    details=f"Review decision references missing raw capture {raw_path}.",
                )
            )
            continue
        if ticker and not raw_capture_contains_ticker(raw_path, ticker):
            rows.append(
                IntegrityAuditRow(
                    path=f"{path.name}:{key}",
                    kind="review_decision",
                    status=ORPHANED_DERIVED_RECORD,
                    severity=FAIL,
                    details=f"Review decision references ticker {ticker}, which is not present in {raw_path}.",
                )
            )
    return rows


def quarantined_capture_groups(manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST) -> set[tuple[str, str, str, str]]:
    manifest = load_capture_integrity_manifest(manifest_path)
    groups: set[tuple[str, str, str, str]] = set()
    for record in manifest.get("quarantined_records", {}).values():
        groups.add(
            (
                record.get("capture_date", ""),
                record.get("session", ""),
                record.get("provider", ""),
                record.get("scanner", ""),
            )
        )
    return groups


def decision_is_quarantined(decision: dict, identity: dict, groups: set[tuple[str, str, str, str]]) -> bool:
    if decision.get("capture_status") == "quarantined":
        return True
    capture_date = identity.get("capture_date", "")
    session = identity.get("session", "")
    provider = identity.get("provider", "")
    scanner = identity.get("scanner", "")
    for group_date, group_session, group_provider, group_scanner in groups:
        if capture_date != group_date or session != group_session:
            continue
        if group_provider and provider and group_provider != provider:
            continue
        if group_scanner and scanner and group_scanner != scanner:
            continue
        return True
    return False


def audit_score_breakdowns(
    *,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
) -> list[IntegrityAuditRow]:
    expected = expected_score_breakdown_identities(captures_dir)
    store = load_score_breakdown_store(score_breakdowns_path)
    records = store.get("records", {})
    rows: list[IntegrityAuditRow] = []
    record_identity_keys = {
        record.get("identity_key") or score_breakdown_identity_key(record.get("identity", {}))
        for record in records.values()
        if isinstance(record, dict)
    }

    for key, identity in sorted(expected.items()):
        if key not in record_identity_keys:
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind="score_breakdown",
                    status=MISSING_SCORE_BREAKDOWN,
                    severity=FAIL,
                    details=f"Active raw capture candidate {identity.get('ticker', '')} has no score breakdown record.",
                )
            )

    seen_identity_keys: dict[str, str] = {}
    quarantined_groups = quarantined_capture_groups(manifest_path)
    for key, record in sorted(records.items()):
        identity = record.get("identity", {})
        record_identity_key = record.get("identity_key") or score_breakdown_identity_key(identity)
        duplicate_source = seen_identity_keys.get(record_identity_key)
        if duplicate_source:
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind="score_breakdown",
                    status=DUPLICATE_SCORE_BREAKDOWN,
                    severity=FAIL,
                    details=f"Duplicate score breakdown identity also appears at {duplicate_source}.",
                )
            )
            continue
        seen_identity_keys[record_identity_key] = key

        source_kind = record.get("source", {}).get("kind", "")
        if record_identity_key not in expected and source_kind != "live_or_app_capture":
            if identity_group_is_quarantined(identity, quarantined_groups):
                rows.append(
                    IntegrityAuditRow(
                        path=key,
                        kind="score_breakdown",
                        status=QUARANTINED,
                        severity=WARN,
                        details="Score breakdown references a quarantined raw capture and is excluded from active studies.",
                    )
                )
                continue
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind="score_breakdown",
                    status=ORPHANED_DERIVED_RECORD,
                    severity=FAIL,
                    details="Score breakdown references a missing active raw capture.",
                )
            )
            continue

        invalid_reason = score_breakdown_invalid_reason(record)
        if invalid_reason:
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind="score_breakdown",
                    status=SCORE_BREAKDOWN_INVALID,
                    severity=FAIL,
                    details=invalid_reason,
                )
            )
            continue

        status = record.get("status", "complete")
        if status == "legacy":
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind="score_breakdown",
                    status=SCORE_BREAKDOWN_LEGACY,
                    severity=WARN,
                    details="Legacy score breakdown does not reconcile to the current engine output.",
                )
            )
        elif status == "incomplete":
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind="score_breakdown",
                    status=SCORE_BREAKDOWN_INCOMPLETE,
                    severity=WARN,
                    details="Score breakdown was generated with incomplete historical inputs.",
                )
            )
        else:
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind="score_breakdown",
                    status=OK,
                    severity=PASS,
                    details="Score breakdown is present and reconciled.",
                )
            )
    return rows


def identity_group_is_quarantined(identity: dict, groups: set[tuple[str, str, str, str]]) -> bool:
    for capture_date, session, provider, scanner in groups:
        if identity.get("capture_date", "") != capture_date or identity.get("session", "") != session:
            continue
        if provider and identity.get("provider") and identity.get("provider") != provider:
            continue
        if scanner and identity.get("scanner") and identity.get("scanner") != scanner:
            continue
        return True
    return False


def score_breakdown_invalid_reason(record: dict) -> str:
    if not record.get("score_engine_version"):
        return "Score engine version is missing."
    components = record.get("components")
    if not isinstance(components, list) or not components:
        return "Component list is missing or malformed."
    for component in components:
        if not isinstance(component, dict):
            return "Component list contains a non-object item."
        for field in ("key", "label", "raw_inputs", "rule", "points_before_adjustment", "points_after_adjustment", "explanation"):
            if field not in component:
                return f"Component {component.get('key', '<unknown>')} is missing {field}."
    if not record.get("caps"):
        return "Global cap explanation is missing."
    if not record.get("floors"):
        return "Global floor explanation is missing."
    try:
        component_total = sum(int(component["points_after_adjustment"]) for component in components)
        pre_floor_total = int(record.get("pre_floor_total"))
        computed_final = int(record.get("computed_final_score"))
    except (TypeError, ValueError):
        return "Score breakdown arithmetic fields are not numeric."
    if component_total != pre_floor_total:
        return f"Component total {component_total} does not match pre_floor_total {pre_floor_total}."
    floor_output = max(0, pre_floor_total)
    cap_output = min(100, floor_output)
    if computed_final != cap_output:
        return f"Computed final score {computed_final} does not match floor/cap output {cap_output}."
    if record.get("status", "complete") == "complete":
        try:
            final_score = int(record.get("final_score"))
        except (TypeError, ValueError):
            return "Final score is not numeric."
        if final_score != computed_final:
            return f"Final score {final_score} does not match computed final score {computed_final}."
    caps = record.get("caps", [])
    floors = record.get("floors", [])
    if caps and bool(caps[0].get("applied")) != (floor_output > 100):
        return "Global cap applied flag does not match arithmetic."
    if floors and bool(floors[0].get("applied")) != (pre_floor_total < 0):
        return "Global floor applied flag does not match arithmetic."
    return ""


def overall_audit_status(rows: list[IntegrityAuditRow]) -> str:
    if any(row.severity == FAIL for row in rows):
        return FAIL
    if any(row.severity == WARN for row in rows):
        return WARN
    return PASS


def write_integrity_audit_report(
    rows: list[IntegrityAuditRow],
    *,
    csv_path: Path = AUDIT_CSV,
    markdown_path: Path = AUDIT_MD,
) -> tuple[Path, Path]:
    ensure_app_dirs()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "path",
        "kind",
        "status",
        "severity",
        "created_at",
        "capture_version",
        "manifest_hash",
        "current_hash",
        "details",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)
    markdown_path.write_text(integrity_audit_markdown(rows), encoding="utf-8")
    return csv_path, markdown_path


def integrity_audit_markdown(rows: list[IntegrityAuditRow]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    overall = overall_audit_status(rows)
    lines = [
        "# Momentum Hunter Raw Capture Integrity Audit",
        "",
        f"Overall Status: {overall}",
        "",
        "Raw capture JSON/MD files are expected to remain immutable after creation. Integrity metadata is stored outside raw captures.",
        "",
        "## Summary",
        "",
    ]
    if counts:
        for status, count in sorted(counts.items()):
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- No raw capture files found.")
    lines.extend(
        [
            "",
            "## Details",
            "",
            "| Severity | Status | Kind | Path | Details |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(f"| {row.severity} | {row.status} | {row.kind} | `{row.path}` | {row.details or ''} |")
    return "\n".join(lines)


def raw_capture_files(captures_dir: Path) -> list[Path]:
    if not captures_dir.exists():
        return []
    return [path for path in captures_dir.rglob("*") if path.suffix.lower() in {".json", ".md"} and path.is_file()]


def resolve_manifest_path(key: str) -> Path:
    path = Path(key)
    if path.is_absolute():
        return path
    return DATA_DIR / path


def kind_for_path(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "raw_capture_json"
    if path.suffix.lower() == ".md":
        return "raw_capture_markdown"
    return "raw_capture"


def raw_capture_contains_ticker(path: Path, ticker: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return ticker in {str(candidate.get("ticker", "")) for candidate in payload.get("candidates", [])}
