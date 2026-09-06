"""Complete local snapshot custody for modern fill/position/checkpoint recovery."""
from momentum_hunter.modern_operational import deny, parse_bytes, require_hash, snapshot_from_bytes


def complete_publication_history(publication):
    """Reject missing or displaced committed evidence, never select a truncated prefix."""
    with publication.epoch.transaction(), publication.lease.transaction():
        current = publication.current()
        history = []
        while current is not None:
            if len(history) >= 4096:
                deny("Modern recovery history exceeds its existing bounded custody limit.")
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
        present = {path.name for path in publication.root.iterdir()
                   if path.name not in {"current.json", "pending.json", ".current.json.lock"}} if publication.root.exists() else set()
        if present != expected:
            deny("Modern recovery reference omits or contradicts preserved snapshot evidence.")
        return tuple(history)
