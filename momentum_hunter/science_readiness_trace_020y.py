"""Qualification-only trace for the first Science readiness publication."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re


_GENERATION = re.compile(r"[0-9a-f-]{36}")


class ScienceReadinessTrace:
    def __init__(self, path: Path, generation: str):
        self.path = path
        self.generation = generation
        self.sequence = 0
        self.lost_events = 0
        self.last_error = None
        self._handle = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)
        except OSError as exc:
            self.lost_events += 1
            self.last_error = "OPEN:" + type(exc).__name__

    def __call__(self, event: str, **detail: object) -> None:
        self.sequence += 1
        row = {"schema": "ARGUS_020Y_SCIENCE_READINESS_TRACE_V1",
               "generation": self.generation, "sequence": self.sequence,
               "observed_at": datetime.now(timezone.utc).isoformat(),
               "event": event, **detail}
        try:
            raw = (json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
            if self._handle is None:
                raise OSError("Diagnostic trace is unavailable.")
            if os.write(self._handle, raw) != len(raw):
                raise OSError("Diagnostic trace write was incomplete.")
        except Exception as exc:
            self.lost_events += 1
            self.last_error = "WRITE:" + type(exc).__name__

    def close(self) -> None:
        if self._handle is not None:
            self("trace_closed", lost_events=self.lost_events)
            handle, self._handle = self._handle, None
            try:
                os.fsync(handle)
            except OSError as exc:
                self.lost_events += 1
                self.last_error = "FLUSH:" + type(exc).__name__
            finally:
                try:
                    os.close(handle)
                except OSError as exc:
                    self.lost_events += 1
                    self.last_error = "CLOSE:" + type(exc).__name__
        self._write_health()

    def _write_health(self) -> None:
        path = self.path.with_name(self.path.stem + "-health.json")
        raw = json.dumps({"schema": "ARGUS_020Y_TRACE_HEALTH_V1", "generation": self.generation,
                          "lost_events": self.lost_events, "last_error": self.last_error,
                          "trace_path": str(self.path)}, sort_keys=True, ensure_ascii=True).encode("ascii")
        try:
            with path.open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        except OSError:
            pass


def open_020y_trace(config, *, generation: str):
    instance = config.get("host", {}).get("instanceId", "")
    if not isinstance(instance, str) or not instance.startswith("qual-015-020y-"):
        return None
    if not isinstance(generation, str) or _GENERATION.fullmatch(generation) is None:
        raise ValueError("Qualification trace requires a bound Science generation.")
    return ScienceReadinessTrace(Path(config["logRoot"]) / "science" /
                                 ("readiness-trace-" + generation + ".jsonl"), generation)
