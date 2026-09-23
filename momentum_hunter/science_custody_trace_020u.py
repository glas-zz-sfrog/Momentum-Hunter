"""020U qualification-only custody object observations; never commit authority."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time


_GENERATION = re.compile(r"[0-9a-f-]{36}")


class CustodyObjectTrace:
    def __init__(self, path: Path, *, role: str):
        if role not in {"writer", "science"}:
            raise ValueError("Trace role is not a custody actor.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)
        self._role = role
        self._sequence = 0
        self.lost_events = 0

    def __call__(self, event: dict[str, object]) -> None:
        self._sequence += 1
        row = {"schema": "ARGUS_020U_CUSTODY_TRACE_V1", "role": self._role,
               "sequence": self._sequence, "observed_at": datetime.now(timezone.utc).isoformat(),
               "monotonic_ns": time.monotonic_ns(), **event}
        raw = (json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
        if self._handle is None:
            self.lost_events += 1
            return
        try:
            if os.write(self._handle, raw) != len(raw):
                self.lost_events += 1
        except OSError:
            self.lost_events += 1

    def close(self) -> None:
        if self._handle is not None:
            handle, self._handle = self._handle, None
            try:
                os.close(handle)
            except OSError:
                self.lost_events += 1


def open_020u_trace(config, *, role: str, generation: str):
    instance = config.get("host", {}).get("instanceId", "")
    if not isinstance(instance, str) or not instance.startswith("qual-015-020u-"):
        return None
    if not isinstance(generation, str) or _GENERATION.fullmatch(generation) is None:
        raise ValueError("Qualification trace requires a bound host generation.")
    return CustodyObjectTrace(Path(config["logRoot"]) / role /
                              ("custody-object-trace-" + generation + ".jsonl"), role=role)
