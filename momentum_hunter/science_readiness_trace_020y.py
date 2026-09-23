"""Qualification-only trace for the first Science readiness publication."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import re
import threading


_GENERATION = re.compile(r"[0-9a-f-]{36}")


class ScienceReadinessTrace:
    def __init__(self, path: Path, generation: str):
        self.path = path
        self.generation = generation
        self.sequence = 0
        self.lost_events = 0
        self.last_error = None
        self.health_committed = False
        self._lock = threading.Lock()
        self._queue: Queue[dict[str, object]] = Queue(maxsize=128)
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, name="science-readiness-trace", daemon=True)
        try:
            self._thread.start()
        except (OSError, RuntimeError) as exc:
            self._record_loss("START:" + type(exc).__name__)
            self._thread = None

    def _record_loss(self, reason: str) -> None:
        with self._lock:
            self.lost_events += 1
            self.last_error = reason

    def _enqueue(self, event: str, detail: dict[str, object]) -> None:
        with self._lock:
            if self._closed.is_set():
                self.lost_events += 1
                self.last_error = "LATE_EVENT"
                return
            self.sequence += 1
            row = {"schema": "ARGUS_020Y_SCIENCE_READINESS_TRACE_V1",
                   "generation": self.generation, "sequence": self.sequence,
                   "observed_at": datetime.now(timezone.utc).isoformat(),
                   "event": event, **detail}
            try:
                self._queue.put_nowait(row)
            except Full:
                self.lost_events += 1
                self.last_error = "QUEUE_FULL"

    def __call__(self, event: str, **detail: object) -> None:
        self._enqueue(event, detail)

    def close(self) -> None:
        with self._lock:
            if self._closed.is_set():
                return
        self._enqueue("trace_closed", {"lost_events": self.lost_events})
        self._closed.set()
        if self._thread is not None:
            self._thread.join(timeout=0.25)

    def _run(self) -> None:
        handle = None
        digest = hashlib.sha256()
        byte_count = 0
        written = 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)
        except OSError as exc:
            self._record_loss("OPEN:" + type(exc).__name__)
        if handle is None:
            self._closed.wait()
        else:
            while True:
                try:
                    row = self._queue.get(timeout=0.05)
                except Empty:
                    if self._closed.is_set():
                        break
                    continue
                try:
                    raw = (json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
                    count = os.write(handle, raw)
                    digest.update(raw[:count])
                    byte_count += count
                    if count != len(raw):
                        raise OSError("Diagnostic trace write was incomplete.")
                    written += 1
                except Exception as exc:
                    self._record_loss("WRITE:" + type(exc).__name__)
            try:
                os.fsync(handle)
            except OSError as exc:
                self._record_loss("FLUSH:" + type(exc).__name__)
            finally:
                try:
                    os.close(handle)
                except OSError as exc:
                    self._record_loss("CLOSE:" + type(exc).__name__)
        self._write_health(byte_count, digest.hexdigest().upper(), written)

    def _write_health(self, byte_count: int, trace_sha256: str, written: int) -> None:
        path = self.path.with_name(self.path.stem + "-health.json")
        partial = path.with_name(path.name + ".partial")
        raw = json.dumps({"schema": "ARGUS_020Y_TRACE_HEALTH_V1", "generation": self.generation,
                          "enqueued_events": self.sequence, "written_events": written,
                          "lost_events": self.lost_events, "last_error": self.last_error,
                          "trace_path": str(self.path), "trace_bytes": byte_count,
                          "trace_sha256": trace_sha256}, sort_keys=True, ensure_ascii=True).encode("ascii")
        try:
            with partial.open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.rename(partial, path)
            self.health_committed = True
        except OSError as exc:
            self._record_loss("HEALTH:" + type(exc).__name__)


def open_020y_trace(config, *, generation: str):
    instance = config.get("host", {}).get("instanceId", "")
    if not isinstance(instance, str) or not instance.startswith("qual-015-020y-"):
        return None
    if not isinstance(generation, str) or _GENERATION.fullmatch(generation) is None:
        raise ValueError("Qualification trace requires a bound Science generation.")
    return ScienceReadinessTrace(Path(config["logRoot"]) / "science" /
                                 ("readiness-trace-" + generation + ".jsonl"), generation)
