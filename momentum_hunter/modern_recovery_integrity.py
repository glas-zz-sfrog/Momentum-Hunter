"""Complete local snapshot custody for modern fill/position/checkpoint recovery."""
import re
import stat

from momentum_hunter.modern_operational import (
    MAX_RETAINED_CHECKPOINTS, deny, parse_bytes, require_hash, snapshot_from_bytes,
)


_NATIVE_SNAPSHOT_TEMP = re.compile(
    r"\.(?:current\.json|pending\.json|[0-9a-f]{64}\.json)\."
    r"[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}\.tmp"
)


def _uncommitted_native_temp(path):
    # Only _replace's exact staging namespace is nonauthoritative; never follow it.
    if not _NATIVE_SNAPSHOT_TEMP.fullmatch(path.name):
        return False
    info = path.lstat()
    return stat.S_ISREG(info.st_mode) and not (
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def complete_publication_history(publication):
    """Reject missing or displaced committed evidence, never select a truncated prefix."""
    with publication.epoch.transaction(), publication.lease.transaction():
        current = publication.current()
        history = []
        while current is not None:
            if len(history) >= MAX_RETAINED_CHECKPOINTS:
                deny("Modern recovery history exceeds its existing bounded custody limit; reconciliation required.",
                     "BLOCK_RECONCILIATION_REQUIRED")
            history.append(current)
            manifest = parse_bytes(current.manifest_bytes)
            previous = manifest["predecessorSnapshotId"]
            if previous is None:
                break
            raw = (publication.root/(require_hash(previous, "Predecessor")+".json")).read_bytes()
            current = snapshot_from_bytes(raw, publication.epoch, kind=publication.kind, expected_id=previous)
            if parse_bytes(current.manifest_bytes)["sequence"] != manifest["sequence"]-1:
                deny("Modern recovery history is not contiguous.")
        expected = {snapshot.snapshot_id+".json" for snapshot in history}
        present = set()
        residue = False
        if publication.root.exists():
            for path in publication.root.iterdir():
                if path.name in {"current.json", "pending.json", ".current.json.lock"}:
                    continue
                if _uncommitted_native_temp(path):
                    residue = True
                else:
                    present.add(path.name)
        if not history and residue:
            deny("Uncommitted temporary residue cannot establish missing committed authority.")
        if present != expected:
            deny("Modern recovery reference omits or contradicts preserved snapshot evidence.")
        return tuple(history)
