"""Nonmutating readiness verifier for the separately approved legacy cutover."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from momentum_hunter.alert_outcome_updater import load_minute_bars
from momentum_hunter.candle_paths import LEGACY_OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.canonical_candle_evidence import (
    CanonicalCandleEvidenceError,
    load_canonical_minute_bars,
)
from momentum_hunter.schwab_candle_store import SCHWAB_CANDLE_STORE_ROOT
from momentum_hunter.sqlite_store import SQLITE_DB_PATH
from momentum_hunter.storage import file_sha256


ENGINE_VERSION = "legacy_candle_cutover_verifier_v1"
EXPECTED_LEGACY_SHA256 = (
    "DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69"
)
EXPECTED_LEGACY_BAR_COUNT = 710
EXPECTED_LEGACY_SYMBOLS = ("CRWV",)
MAX_SCANNED_FILE_BYTES = 4 * 1024 * 1024
REFERENCE_NEEDLES = (
    "opportunity-minute-bars.json",
    "OPPORTUNITY_MINUTE_BARS_PATH",
    "LEGACY_OPPORTUNITY_MINUTE_BARS_PATH",
)
REFERENCE_ROOTS = ("momentum_hunter", "src", "tools")
REFERENCE_SUFFIXES = frozenset({".py", ".cs", ".xaml", ".ps1", ".toml", ".json"})
ALLOWED_REFERENCE_PATHS = {
    "momentum_hunter/alert_outcome_updater.py": "RETIRED_FIXTURE_GUARD",
    "momentum_hunter/candle_paths.py": "RETIRED_PATH_IDENTITY",
    "momentum_hunter/legacy_candle_cutover.py": "CUTOVER_VERIFIER",
    "momentum_hunter/offline_evidence_drill.py": "SYNTHETIC_TEMP_FIXTURE",
    "momentum_hunter/schwab_candle_store.py": "ANTI_MIXING_GUARD",
    "momentum_hunter/source_registry.py": "RETIRED_SOURCE_REGISTRY",
    "momentum_hunter/sqlite_migration.py": "EXPLICIT_HISTORICAL_IMPORT_ONLY",
    "momentum_hunter/sqlite_mirror_freshness.py": "RETIRED_MIRROR_REPORTING",
    "momentum_hunter/sqlite_store.py": "EXPLICIT_HISTORICAL_IMPORT_ONLY",
}


@dataclass(frozen=True)
class ReferenceFinding:
    path: str
    line: int
    token: str
    classification: str
    blocking: bool


def build_cutover_plan(
    *,
    repo_root: Path,
    legacy_path: Path = LEGACY_OPPORTUNITY_MINUTE_BARS_PATH,
    sqlite_path: Path = SQLITE_DB_PATH,
    minute_store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
    archive_root: Path | None = None,
    expected_legacy_sha256: str = EXPECTED_LEGACY_SHA256,
    expected_legacy_bar_count: int = EXPECTED_LEGACY_BAR_COUNT,
    expected_legacy_symbols: tuple[str, ...] = EXPECTED_LEGACY_SYMBOLS,
) -> dict[str, object]:
    """Inspect cutover prerequisites without writing source, SQLite, or reports."""

    repo_root = repo_root.resolve(strict=True)
    legacy_path = legacy_path.resolve(strict=False)
    sqlite_path = sqlite_path.resolve(strict=False)
    minute_store_root = minute_store_root.resolve(strict=False)
    archive_root = (
        archive_root.resolve(strict=False)
        if archive_root is not None
        else (legacy_path.parent / "archives" / "legacy-candles").resolve(strict=False)
    )
    before = _input_hashes(legacy_path, sqlite_path, minute_store_root)
    findings = scan_references(repo_root)
    blocking_references = [asdict(item) for item in findings if item.blocking]
    legacy = _legacy_identity(
        legacy_path,
        expected_sha256=expected_legacy_sha256,
        expected_bar_count=expected_legacy_bar_count,
        expected_symbols=expected_legacy_symbols,
    )
    sqlite = _sqlite_identity(
        sqlite_path,
        legacy_path=legacy_path,
        expected_hash=expected_legacy_sha256,
    )
    schwab = _schwab_health(minute_store_root)
    archive_name = (
        f"opportunity-minute-bars-{str(legacy.get('sha256') or 'missing')[:12].lower()}.json"
    )
    archive_path = archive_root / archive_name
    archive = {
        "destination": str(archive_path),
        "exists": archive_path.exists(),
        "existingSha256": file_sha256(archive_path).upper() if archive_path.exists() else "",
        "mustMatchLegacyBeforeDeletion": True,
        "insideActiveMinuteStore": _same_or_descendant(archive_path, minute_store_root),
    }
    after = _input_hashes(legacy_path, sqlite_path, minute_store_root)
    inputs_unchanged = before == after
    blockers = _blockers(
        legacy=legacy,
        sqlite=sqlite,
        schwab=schwab,
        archive=archive,
        blocking_references=blocking_references,
        inputs_unchanged=inputs_unchanged,
        expected_sqlite_count=expected_legacy_bar_count,
    )
    status = "READY_FOR_DESTRUCTIVE_APPROVAL" if not blockers else "BLOCKED"
    return {
        "schemaVersion": 1,
        "engineVersion": ENGINE_VERSION,
        "status": status,
        "planOnly": True,
        "networkCalled": False,
        "providerCalled": False,
        "accountCalled": False,
        "orderCalled": False,
        "databaseWritten": False,
        "sourceWritten": False,
        "repoRoot": str(repo_root),
        "legacy": legacy,
        "sqlite": sqlite,
        "schwabStore": schwab,
        "archive": archive,
        "references": [asdict(item) for item in findings],
        "blockingReferences": blocking_references,
        "rollbackConditions": [
            "Archive exists outside active candle stores and matches the legacy SHA-256 before deletion.",
            "Canonical Schwab partitions remain readable and unchanged before and after cutover.",
            "Legacy JSON can be restored byte-for-byte from the archive if post-cutover validation fails.",
            "Legacy SQLite rows can be restored only from the archived file under an explicit recovery task.",
            "No mixed legacy/Schwab chart or outcome source is allowed during rollback.",
        ],
        "inputHashesBefore": before,
        "inputHashesAfter": after,
        "inputsUnchanged": inputs_unchanged,
        "blockers": blockers,
        "nextAction": (
            "Ask Steven for the separately required R034 destructive approval."
            if status == "READY_FOR_DESTRUCTIVE_APPROVAL"
            else "Resolve every blocker and rerun this plan-only verifier."
        ),
    }


def scan_references(repo_root: Path) -> list[ReferenceFinding]:
    findings: list[ReferenceFinding] = []
    for root_name in REFERENCE_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.suffix.lower() not in REFERENCE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_SCANNED_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            relative = path.relative_to(repo_root).as_posix()
            classification = ALLOWED_REFERENCE_PATHS.get(relative, "UNCLASSIFIED_ACTIVE_REFERENCE")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for needle in REFERENCE_NEEDLES:
                    if needle in line:
                        findings.append(
                            ReferenceFinding(
                                path=relative,
                                line=line_number,
                                token=needle,
                                classification=classification,
                                blocking=relative not in ALLOWED_REFERENCE_PATHS,
                            )
                        )
    return sorted(findings, key=lambda item: (item.path, item.line, item.token))


def _legacy_identity(
    path: Path,
    *,
    expected_sha256: str,
    expected_bar_count: int,
    expected_symbols: tuple[str, ...],
) -> dict[str, object]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "sha256": "",
            "barCount": 0,
            "symbols": [],
            "identityMatches": False,
        }
    sha256 = file_sha256(path).upper()
    bars = load_minute_bars(path)
    count = sum(len(items) for items in bars.values())
    symbols = sorted(bars)
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256,
        "barCount": count,
        "symbols": symbols,
        "expectedSha256": expected_sha256.upper(),
        "expectedBarCount": expected_bar_count,
        "expectedSymbols": list(expected_symbols),
        "identityMatches": (
            sha256 == expected_sha256.upper()
            and count == expected_bar_count
            and tuple(symbols) == tuple(sorted(expected_symbols))
        ),
    }


def _sqlite_identity(
    path: Path,
    *,
    legacy_path: Path,
    expected_hash: str,
) -> dict[str, object]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "matchingRows": 0,
            "allMinuteRows": 0,
            "sourceHashes": [],
            "symbols": [],
            "readOnly": True,
        }
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='minute_bars'"
        ).fetchone()
        if table is None:
            return {
                "path": str(path),
                "exists": True,
                "tableExists": False,
                "matchingRows": 0,
                "allMinuteRows": 0,
                "sourceHashes": [],
                "symbols": [],
                "readOnly": True,
            }
        rows = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM minute_bars
            WHERE source_file_path = ? AND UPPER(source_file_hash) = ?
            """,
            (str(legacy_path), expected_hash.upper()),
        ).fetchone()
        total = connection.execute(
            "SELECT COUNT(*) AS count FROM minute_bars"
        ).fetchone()
        hashes = connection.execute(
            "SELECT DISTINCT source_file_hash FROM minute_bars WHERE source_file_path = ? ORDER BY source_file_hash",
            (str(legacy_path),),
        ).fetchall()
        symbols = connection.execute(
            "SELECT DISTINCT symbol FROM minute_bars WHERE source_file_path = ? ORDER BY symbol",
            (str(legacy_path),),
        ).fetchall()
        return {
            "path": str(path),
            "exists": True,
            "tableExists": True,
            "matchingRows": int(rows["count"]),
            "allMinuteRows": int(total["count"]),
            "sourceHashes": [str(row["source_file_hash"]) for row in hashes],
            "symbols": [str(row["symbol"]) for row in symbols],
            "readOnly": True,
        }
    finally:
        connection.close()


def _schwab_health(root: Path) -> dict[str, object]:
    try:
        bars = load_canonical_minute_bars(store_root=root)
    except CanonicalCandleEvidenceError as exc:
        return {
            "root": str(root),
            "exists": root.exists(),
            "status": "INVALID",
            "canonicalBarCount": 0,
            "symbols": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    count = sum(len(items) for items in bars.values())
    return {
        "root": str(root),
        "exists": root.exists(),
        "status": "HEALTHY" if count else "EMPTY",
        "partitionCount": sum(
            _is_session_date(path.parent.name)
            for path in root.glob("*/*.json")
        ) if root.exists() else 0,
        "canonicalBarCount": count,
        "symbols": sorted(bars),
        "sourceContract": "SCHWAB_RECONCILED_MINUTE_STORE_V1",
    }


def _blockers(
    *,
    legacy: dict[str, object],
    sqlite: dict[str, object],
    schwab: dict[str, object],
    archive: dict[str, object],
    blocking_references: list[dict[str, object]],
    inputs_unchanged: bool,
    expected_sqlite_count: int,
) -> list[str]:
    blockers: list[str] = []
    if legacy.get("identityMatches") is not True:
        blockers.append("LEGACY_IDENTITY_MISMATCH")
    if sqlite.get("tableExists") is not True:
        blockers.append("SQLITE_MINUTE_BARS_TABLE_MISSING")
    if int(sqlite.get("matchingRows") or 0) != expected_sqlite_count:
        blockers.append("SQLITE_LEGACY_ROW_COUNT_MISMATCH")
    if schwab.get("status") != "HEALTHY":
        blockers.append("SCHWAB_CANONICAL_STORE_NOT_HEALTHY")
    if archive.get("insideActiveMinuteStore") is True:
        blockers.append("ARCHIVE_DESTINATION_INSIDE_ACTIVE_STORE")
    if archive.get("exists") and archive.get("existingSha256") != legacy.get("sha256"):
        blockers.append("ARCHIVE_DESTINATION_CONFLICT")
    if blocking_references:
        blockers.append("UNCLASSIFIED_ACTIVE_LEGACY_REFERENCE")
    if not inputs_unchanged:
        blockers.append("VERIFIER_MUTATED_INPUT")
    return blockers


def _input_hashes(
    legacy_path: Path,
    sqlite_path: Path,
    minute_store_root: Path,
) -> dict[str, object]:
    partitions = {
        str(path): file_sha256(path)
        for path in sorted(minute_store_root.glob("*/*.json"))
        if path.is_file()
    } if minute_store_root.exists() else {}
    return {
        "legacy": file_sha256(legacy_path) if legacy_path.exists() else "",
        "sqlite": file_sha256(sqlite_path) if sqlite_path.exists() else "",
        "schwabPartitionsFingerprint": _mapping_fingerprint(partitions),
        "schwabPartitionCount": len(partitions),
    }


def _mapping_fingerprint(values: dict[str, str]) -> str:
    content = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest().upper()


def _is_session_date(value: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value
    except ValueError:
        return False


def _same_or_descendant(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect legacy candle cutover readiness without modifying anything."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--legacy-path", type=Path, default=LEGACY_OPPORTUNITY_MINUTE_BARS_PATH)
    parser.add_argument("--sqlite-path", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--minute-store-root", type=Path, default=SCHWAB_CANDLE_STORE_ROOT)
    parser.add_argument("--archive-root", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = build_cutover_plan(
        repo_root=args.repo_root,
        legacy_path=args.legacy_path,
        sqlite_path=args.sqlite_path,
        minute_store_root=args.minute_store_root,
        archive_root=args.archive_root,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "READY_FOR_DESTRUCTIVE_APPROVAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
