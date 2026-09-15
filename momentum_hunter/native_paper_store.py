"""Explicit-root, atomic execution audit transactions for offline Paper.

This is not Science custody or an installed writer. Each transaction binds its
complete state and canonical ExecutionLedgerEvent to the preceding transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from momentum_hunter.automation_state_recovery import durable_new, sync_directory
from momentum_hunter.autonomy.ledger import ExecutionLedgerEvent
from momentum_hunter.path_transaction import PathTransactionLease


class NativePaperError(ValueError):
    pass


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def fingerprint(value: object) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def identity(kind: str, *parts: str) -> str:
    return kind + "-" + fingerprint(list(parts))


class NativePaperStore:
    """Single path lease covers read, decision, side-effect fence and commit."""

    def __init__(self, root: Path, *, binding: dict, require_existing: bool = False) -> None:
        self.root = Path(root)
        if not self.root.is_absolute():
            raise NativePaperError("EXPLICIT_ABSOLUTE_OFFLINE_ROOT_REQUIRED")
        self.binding = json.loads(encoded(binding))
        if require_existing and not (self.root / "head.anchor").is_file():
            raise NativePaperError("EXECUTION_RECOVERY_CUSTODY_MISSING")
        self.root.mkdir(parents=True, exist_ok=True)
        self.lease = PathTransactionLease(self.root / "transactions")
        self.anchor = self.root / "head.anchor"
        with self.lease.transaction():
            if not self.anchor.exists():
                if any(self.root.glob("*.json")):
                    raise NativePaperError("EXECUTION_RECOVERY_ANCHOR_MISSING")
                durable_new(self.anchor, encoded({"binding": fingerprint(self.binding), "sequence": 0, "head": ""}))

    def load(self) -> tuple[dict, list[dict]]:
        with self.lease.transaction():
            previous = ""
            records = []
            for sequence, path in enumerate(sorted(self.root.glob("*.json")), 1):
                try:
                    record = json.loads(path.read_bytes())
                    claimed = record.pop("fingerprint")
                    if (path.name != f"{sequence:08d}.json"
                            or record["sequence"] != sequence
                            or record["previous"] != previous
                            or record["binding"] != self.binding
                            or fingerprint(record) != claimed):
                        raise ValueError
                    record["fingerprint"] = claimed
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise NativePaperError("EXECUTION_AUDIT_CORRUPT_OR_BINDING_DRIFT") from exc
                previous = claimed
                records.append(record)
            state = records[-1]["state"] if records else {
                "trades": {}, "disabled_intents": {}, "hooks": {}, "quarantined": False,
            }
            try:
                anchor = json.loads(self.anchor.read_bytes())
                count = anchor["sequence"]
                if (anchor["binding"] != fingerprint(self.binding) or type(count) is not int
                        or count < 0 or not count <= len(records) <= count + 1
                        or anchor["head"] != (records[count - 1]["fingerprint"] if count else "")):
                    raise ValueError
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise NativePaperError("EXECUTION_CUSTODY_ANCHOR_CONFLICT") from exc
            return state, records

    def commit(self, state: dict, event: ExecutionLedgerEvent) -> None:
        with self.lease.transaction():
            _, records = self.load()
            if len(records) >= 4096:
                raise NativePaperError("OFFLINE_AUDIT_CAPACITY_EXHAUSTED")
            sequence = len(records) + 1
            record = {"sequence": sequence,
                      "previous": records[-1]["fingerprint"] if records else "",
                      "binding": self.binding, "event": asdict(event), "state": state}
            record["fingerprint"] = fingerprint(record)
            destination = self.root / f"{sequence:08d}.json"
            temporary = self.root / ("." + uuid.uuid4().hex + ".partial")
            durable_new(temporary, encoded(record))
            if destination.exists():
                raise NativePaperError("EXECUTION_TRANSACTION_COLLISION")
            os.rename(temporary, destination)
            sync_directory(self.root)
            anchor_temporary = self.root / ("." + uuid.uuid4().hex + ".anchor-partial")
            durable_new(anchor_temporary, encoded({"binding": fingerprint(self.binding),
                                                   "sequence": sequence, "head": record["fingerprint"]}))
            os.replace(anchor_temporary, self.anchor)
            sync_directory(self.root)
