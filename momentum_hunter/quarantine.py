from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
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
from momentum_hunter.time_utils import now_central


QUARANTINE_DIR = DATA_DIR / "quarantine" / "raw-captures"


@dataclass(frozen=True)
class QuarantineResult:
    capture_date: str
    session: str
    quarantine_dir: Path
    moved_paths: list[Path]
    note_path: Path
    manifest_records_moved: int


def quarantine_raw_capture(
    capture_date: str,
    session: str,
    *,
    reason: str,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    quarantine_root: Path = QUARANTINE_DIR,
) -> QuarantineResult:
    ensure_app_dirs()
    quarantined_at = now_central()
    active_dir = captures_dir / capture_date
    destination_dir = quarantine_root / capture_date / session
    destination_dir.mkdir(parents=True, exist_ok=True)

    moved_paths: list[Path] = []
    source_destination_pairs = [
        (active_dir / f"{session}.json", destination_dir / f"{session}.json"),
        (active_dir / f"{session}.md", destination_dir / f"{session}.md"),
    ]
    for source, destination in source_destination_pairs:
        if source.exists():
            if destination.exists():
                raise FileExistsError(f"Quarantine destination already exists: {destination}")
            shutil.move(str(source), str(destination))
            moved_paths.append(destination)

    manifest_records_moved = quarantine_manifest_records(
        source_destination_pairs=source_destination_pairs,
        manifest_path=manifest_path,
        reason=reason,
        quarantined_at=quarantined_at.isoformat(),
    )
    note_path = write_recovery_note(
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
        manifest_records_moved=manifest_records_moved,
    )


def quarantine_manifest_records(
    *,
    source_destination_pairs: list[tuple[Path, Path]],
    manifest_path: Path,
    reason: str,
    quarantined_at: str,
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
            "kind": original_record.get("kind") or kind_for_path(destination),
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
) -> Path:
    manifest = load_capture_integrity_manifest(manifest_path)
    quarantined_records = manifest.get("quarantined_records", {})
    lines = [
        f"# Quarantined Raw Capture - {capture_date} {session}",
        "",
        f"- Quarantined At: {quarantined_at}",
        f"- Reason: {reason}",
        "- Study Use: excluded from analysis-captures.csv, analysis-outcomes.csv, and Study Engine results.",
        "- Raw Capture Policy: quarantined files are retained for recovery/audit only and must not be treated as active source-of-truth captures.",
        "",
        "## Files",
        "",
    ]
    for source, destination in source_destination_pairs:
        original_key = capture_manifest_key(source)
        record = quarantined_records.get(original_key, {})
        lines.extend(
            [
                f"- Original: `{original_key}`",
                f"  Quarantine: `{capture_manifest_key(destination)}`",
                f"  Manifest Hash: `{record.get('source_hash', '')}`",
                f"  Quarantine Hash: `{record.get('quarantine_hash', '')}`",
                "",
            ]
        )
    note_path = destination_dir / "recovery-note.md"
    note_path.write_text("\n".join(lines), encoding="utf-8")
    (destination_dir / "recovery-note.json").write_text(
        json.dumps(
            {
                "capture_date": capture_date,
                "session": session,
                "quarantined_at": quarantined_at,
                "reason": reason,
                "study_use": "excluded",
                "files": [
                    {
                        "original_path": capture_manifest_key(source),
                        "quarantine_path": capture_manifest_key(destination),
                    }
                    for source, destination in source_destination_pairs
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return note_path


def kind_for_path(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "raw_capture_json"
    if path.suffix.lower() == ".md":
        return "raw_capture_markdown"
    return "raw_capture"
