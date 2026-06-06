from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.storage import (
    CAPTURE_INTEGRITY_MANIFEST,
    CAPTURES_DIR,
    capture_manifest_key,
    file_sha256,
    load_capture_integrity_manifest,
    save_capture_integrity_manifest,
)
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


QUARANTINE_DIR = DATA_DIR / "quarantine" / "raw-captures"
TIMESTAMPED_QUARANTINE_RE = re.compile(r"^quarantine/raw-captures/\d{8}-\d{6}/")


@dataclass(frozen=True)
class QuarantineResult:
    capture_date: str
    session: str
    quarantine_dir: Path
    moved_paths: list[Path]
    note_path: Path
    note_json_path: Path
    manifest_records_moved: int
    batch_id: str


def quarantine_raw_capture(
    capture_date: str,
    session: str,
    *,
    reason: str,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    quarantine_root: Path = QUARANTINE_DIR,
    quarantined_at: datetime | None = None,
    batch_id: str | None = None,
) -> QuarantineResult:
    ensure_app_dirs()
    quarantined_at = quarantined_at or now_central()
    batch_id = batch_id or quarantine_batch_id(quarantined_at)
    active_dir = captures_dir / capture_date
    destination_dir = quarantine_root / batch_id
    destination_dir.mkdir(parents=True, exist_ok=True)

    source_destination_pairs = source_destination_pairs_for_capture(
        active_dir=active_dir,
        capture_date=capture_date,
        session=session,
        destination_dir=destination_dir,
    )
    moved_paths = move_quarantine_files(source_destination_pairs)
    manifest_records_moved = quarantine_manifest_records(
        source_destination_pairs=source_destination_pairs,
        manifest_path=manifest_path,
        reason=reason,
        quarantined_at=quarantined_at.isoformat(),
        batch_id=batch_id,
    )
    note_path, note_json_path = write_recovery_note(
        destination_dir=destination_dir,
        capture_date=capture_date,
        session=session,
        reason=reason,
        quarantined_at=quarantined_at.isoformat(),
        source_destination_pairs=source_destination_pairs,
        manifest_path=manifest_path,
    )
    return QuarantineResult(
        capture_date=capture_date,
        session=session,
        quarantine_dir=destination_dir,
        moved_paths=moved_paths,
        note_path=note_path,
        note_json_path=note_json_path,
        manifest_records_moved=manifest_records_moved,
        batch_id=batch_id,
    )


def normalize_existing_quarantine_layout(
    *,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    quarantine_root: Path = QUARANTINE_DIR,
) -> list[QuarantineResult]:
    manifest = load_capture_integrity_manifest(manifest_path)
    quarantined_records = manifest.setdefault("quarantined_records", {})
    groups: dict[tuple[str, str, str, str], list[tuple[Path, Path]]] = {}

    for original_key, record in list(quarantined_records.items()):
        quarantine_path = record.get("quarantine_path", "")
        if not quarantine_path:
            continue
        timestamped = bool(TIMESTAMPED_QUARANTINE_RE.match(quarantine_path))
        needs_metadata_refresh = not record.get("original_manifest_metadata") or not record.get("current_file_metadata")
        if timestamped and not needs_metadata_refresh:
            continue
        source = resolve_data_path(quarantine_path)
        if not source.exists():
            continue
        quarantined_at = record.get("quarantined_at", now_central().isoformat())
        batch_id = quarantine_batch_id_from_text(quarantined_at)
        capture_date = record.get("capture_date", Path(original_key).parent.name)
        session = record.get("session", Path(original_key).stem)
        destination_dir = quarantine_root / batch_id
        destination = source if timestamped else destination_dir / quarantine_filename(capture_date, session, source.suffix)
        groups.setdefault((capture_date, session, quarantined_at, batch_id), []).append((source, destination))

    results: list[QuarantineResult] = []
    if not groups:
        return results

    for (capture_date, session, quarantined_at, batch_id), pairs in sorted(groups.items()):
        destination_dir = quarantine_root / batch_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        moved_paths = move_quarantine_files(pairs)
        manifest = load_capture_integrity_manifest(manifest_path)
        records = manifest.setdefault("quarantined_records", {})
        for source, destination in pairs:
            original_key = original_key_for_quarantine_destination(records, source)
            if not original_key:
                continue
            record = records[original_key]
            record["quarantine_path"] = capture_manifest_key(destination)
            record["quarantine_hash"] = file_sha256(destination)
            record["quarantine_batch_id"] = batch_id
            record["original_manifest_metadata"] = record.get("original_manifest_metadata") or manifest_metadata(record)
            record["current_file_metadata"] = current_file_metadata(destination)
            record["hash_mismatch"] = {
                "manifest_hash": record.get("source_hash", ""),
                "current_hash": record.get("quarantine_hash", ""),
            }
        manifest["updated_at"] = quarantined_at
        save_capture_integrity_manifest(manifest, manifest_path)

        source_destination_pairs = [
            (DATA_DIR / record_key, destination)
            for source, destination in pairs
            for record_key in [original_key_for_quarantine_destination(load_capture_integrity_manifest(manifest_path).get("quarantined_records", {}), destination)]
            if record_key
        ]
        reason = first_quarantine_reason(manifest_path, source_destination_pairs)
        note_path, note_json_path = write_recovery_note(
            destination_dir=destination_dir,
            capture_date=capture_date,
            session=session,
            reason=reason,
            quarantined_at=quarantined_at,
            source_destination_pairs=source_destination_pairs,
            manifest_path=manifest_path,
        )
        results.append(
            QuarantineResult(
                capture_date=capture_date,
                session=session,
                quarantine_dir=destination_dir,
                moved_paths=moved_paths,
                note_path=note_path,
                note_json_path=note_json_path,
                manifest_records_moved=0,
                batch_id=batch_id,
            )
        )
    return results


def source_destination_pairs_for_capture(
    *,
    active_dir: Path,
    capture_date: str,
    session: str,
    destination_dir: Path,
) -> list[tuple[Path, Path]]:
    return [
        (active_dir / f"{session}.json", destination_dir / quarantine_filename(capture_date, session, ".json")),
        (active_dir / f"{session}.md", destination_dir / quarantine_filename(capture_date, session, ".md")),
    ]


def move_quarantine_files(source_destination_pairs: list[tuple[Path, Path]]) -> list[Path]:
    moved_paths: list[Path] = []
    for source, destination in source_destination_pairs:
        if not source.exists():
            continue
        if source.resolve() == destination.resolve():
            continue
        if destination.exists():
            raise FileExistsError(f"Quarantine destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved_paths.append(destination)
    return moved_paths


def quarantine_manifest_records(
    *,
    source_destination_pairs: list[tuple[Path, Path]],
    manifest_path: Path,
    reason: str,
    quarantined_at: str,
    batch_id: str,
) -> int:
    manifest = load_capture_integrity_manifest(manifest_path)
    active_records = manifest.setdefault("records", {})
    quarantined_records = manifest.setdefault("quarantined_records", {})
    moved = 0
    for source, destination in source_destination_pairs:
        original_key = capture_manifest_key(source)
        destination_key = capture_manifest_key(destination)
        original_record = active_records.pop(original_key, None) or {}
        if not original_record and not destination.exists():
            continue
        quarantine_hash = file_sha256(destination) if destination.exists() else ""
        quarantined_records[original_key] = {
            **original_record,
            "status": "quarantined",
            "quarantined_at": quarantined_at,
            "quarantine_reason": reason,
            "original_path": original_key,
            "quarantine_path": destination_key,
            "quarantine_hash": quarantine_hash,
            "quarantine_batch_id": batch_id,
            "kind": original_record.get("kind") or kind_for_path(destination),
            "original_manifest_metadata": manifest_metadata(original_record),
            "current_file_metadata": current_file_metadata(destination),
            "hash_mismatch": {
                "manifest_hash": original_record.get("source_hash", ""),
                "current_hash": quarantine_hash,
            },
        }
        moved += 1
    manifest["updated_at"] = quarantined_at
    save_capture_integrity_manifest(manifest, manifest_path)
    return moved


def write_recovery_note(
    *,
    destination_dir: Path,
    capture_date: str,
    session: str,
    reason: str,
    quarantined_at: str,
    source_destination_pairs: list[tuple[Path, Path]],
    manifest_path: Path,
) -> tuple[Path, Path]:
    manifest = load_capture_integrity_manifest(manifest_path)
    quarantined_records = manifest.get("quarantined_records", {})
    lines = [
        f"# Quarantined Raw Capture - {capture_date} {session}",
        "",
        f"- Quarantined At: {quarantined_at}",
        f"- Reason: {reason}",
        "- User Decision: quarantine performed; restore original if available, otherwise keep excluded from studies.",
        "- Rebaseline Policy: only re-baseline with an explicit signed recovery note; never silently re-bless modified files.",
        "- Study Use: excluded from analysis-captures.csv, analysis-outcomes.csv, and Study Engine results.",
        "- Raw Capture Policy: quarantined files are retained for recovery/audit only and must not be treated as active source-of-truth captures.",
        "",
        "## File Evidence",
        "",
    ]
    files: list[dict] = []
    for source, destination in source_destination_pairs:
        original_key = capture_manifest_key(source)
        record = quarantined_records.get(original_key, {})
        file_payload = {
            "original_path": original_key,
            "quarantine_path": capture_manifest_key(destination),
            "original_manifest_metadata": record.get("original_manifest_metadata", {}),
            "current_file_metadata": record.get("current_file_metadata", {}),
            "hash_mismatch": record.get("hash_mismatch", {}),
        }
        files.append(file_payload)
        lines.extend(file_evidence_lines(file_payload))
    note_path = destination_dir / f"{capture_date}-{session}-recovery-note.md"
    note_json_path = destination_dir / f"{capture_date}-{session}-recovery-note.json"
    note_path.write_text("\n".join(lines), encoding="utf-8")
    note_json_path.write_text(
        json.dumps(
            {
                "capture_date": capture_date,
                "session": session,
                "quarantined_at": quarantined_at,
                "reason": reason,
                "user_decision": "quarantine_performed",
                "rebaseline_policy": "explicit_signed_note_required",
                "study_use": "excluded",
                "files": files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return note_path, note_json_path


def file_evidence_lines(file_payload: dict) -> list[str]:
    original = file_payload["original_path"]
    quarantine = file_payload["quarantine_path"]
    manifest_metadata = file_payload["original_manifest_metadata"]
    current_metadata = file_payload["current_file_metadata"]
    mismatch = file_payload["hash_mismatch"]
    return [
        f"### {original}",
        "",
        f"- Quarantine Path: `{quarantine}`",
        f"- Manifest Hash: `{mismatch.get('manifest_hash', '')}`",
        f"- Current/Quarantine Hash: `{mismatch.get('current_hash', '')}`",
        "- Hash Mismatch: manifest hash differs from current/quarantine hash.",
        f"- Original Manifest Metadata: `{json.dumps(manifest_metadata, sort_keys=True)}`",
        f"- Current File Metadata: `{json.dumps(current_metadata, sort_keys=True)}`",
        "",
    ]


def manifest_metadata(record: dict) -> dict:
    return {
        "created_at": record.get("created_at", ""),
        "capture_time": record.get("capture_time", ""),
        "capture_date": record.get("capture_date", ""),
        "session": record.get("session", ""),
        "provider": record.get("provider", ""),
        "scanner": record.get("scanner", ""),
        "capture_version": record.get("capture_version", ""),
        "source_hash": record.get("source_hash", ""),
    }


def current_file_metadata(path: Path) -> dict:
    payload = load_related_json_payload(path)
    stat = path.stat() if path.exists() else None
    metadata = {
        "file_name": path.name,
        "file_size": stat.st_size if stat else "",
        "file_modified_at": datetime.fromtimestamp(stat.st_mtime, tz=CENTRAL_TZ).isoformat() if stat else "",
    }
    if payload:
        scanner = payload.get("scanner", {})
        metadata.update(
            {
                "capture_time": payload.get("capture_time", ""),
                "capture_date": payload.get("capture_date", ""),
                "session": payload.get("session", ""),
                "provider": payload.get("provider", ""),
                "scanner": scanner.get("name", "") if isinstance(scanner, dict) else str(scanner),
                "capture_version": f"raw-capture-v{payload.get('schema_version', '')}" if payload.get("schema_version") else "",
            }
        )
    return metadata


def load_related_json_payload(path: Path) -> dict:
    json_path = path if path.suffix.lower() == ".json" else path.with_suffix(".json")
    if not json_path.exists():
        return {}
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def quarantine_filename(capture_date: str, session: str, suffix: str) -> str:
    return f"{capture_date}-{session}{suffix.lower()}"


def quarantine_batch_id(value: datetime) -> str:
    return value.strftime("%Y%m%d-%H%M%S")


def quarantine_batch_id_from_text(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = now_central()
    return quarantine_batch_id(parsed)


def original_key_for_quarantine_destination(records: dict, path: Path) -> str:
    key = capture_manifest_key(path)
    for original_key, record in records.items():
        if record.get("quarantine_path") == key:
            return original_key
    return ""


def first_quarantine_reason(manifest_path: Path, source_destination_pairs: list[tuple[Path, Path]]) -> str:
    manifest = load_capture_integrity_manifest(manifest_path)
    records = manifest.get("quarantined_records", {})
    for source, _ in source_destination_pairs:
        record = records.get(capture_manifest_key(source), {})
        if record.get("quarantine_reason"):
            return record["quarantine_reason"]
    return "Previously quarantined raw capture migrated to timestamped quarantine layout."


def resolve_data_path(key: str) -> Path:
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
