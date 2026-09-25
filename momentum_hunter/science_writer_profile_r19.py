"""Bounded disposable Writer profiling; never custody or readiness authority."""

from __future__ import annotations

import cProfile
from pathlib import Path
import re
import time

from momentum_hunter.continuous_host_contract import OFFLINE
from momentum_hunter.science_readiness_trace_020y import ScienceReadinessTrace


class WriterStartupProfile:
    MAX_RESULTS = 32
    MAX_POLLS = 4096
    MAX_SECONDS = 180
    MAX_FUNCTIONS = 4096

    def __init__(self, trace):
        self.trace = trace
        self.profile = cProfile.Profile()
        self.polls = 0
        self.results = 0
        self.poll_seconds = 0.0
        self.between_poll_seconds = 0.0
        self.started = None
        self.last_return = None
        self.finished = False
        self.errors = []

    def poll(self, operation):
        if self.finished:
            return operation()
        before = time.perf_counter()
        if self.started is None:
            self.started = before
        if self.last_return is not None:
            self.between_poll_seconds += before - self.last_return
        enabled = False
        try:
            self.profile.enable()
            enabled = True
        except Exception as exc:
            self.errors.append("ENABLE:" + type(exc).__name__)
        try:
            result = operation()
            self.results += int(result is not None)
            return result
        except BaseException as exc:
            # Type only: no request content, exception message or credentials.
            if len(self.errors) < 32:
                self.errors.append("POLL:" + type(exc).__name__)
            raise
        finally:
            if enabled:
                try:
                    self.profile.disable()
                except Exception as exc:
                    self.errors.append("DISABLE:" + type(exc).__name__)
            self.last_return = time.perf_counter()
            self.poll_seconds += self.last_return - before
            self.polls += 1
            if (not enabled or self.results >= self.MAX_RESULTS or self.polls >= self.MAX_POLLS
                    or self.last_return - self.started >= self.MAX_SECONDS):
                self.finish()

    def finish(self):
        if self.finished:
            return
        self.finished = True
        try:
            entries = self.profile.getstats()
            rows = []
            for item in entries[:self.MAX_FUNCTIONS]:
                code = item.code
                rows.append({"file": code.co_filename if not isinstance(code, str) else None,
                             "line": code.co_firstlineno if not isinstance(code, str) else None,
                             "function": code.co_name if not isinstance(code, str) else code,
                             "calls": item.callcount, "recursive_calls": item.reccallcount,
                             "self_seconds": item.inlinetime, "cumulative_seconds": item.totaltime})
            self.trace("WRITER_STARTUP_PROFILE", polls=self.polls, results=self.results,
                       poll_seconds=self.poll_seconds, between_poll_seconds=self.between_poll_seconds,
                       elapsed_seconds=None if self.started is None else time.perf_counter() - self.started,
                       errors=list(self.errors), truncated=len(entries) > self.MAX_FUNCTIONS,
                       functions=rows, diagnostic_only=True, timing_includes_profiler_overhead=True)
        except Exception as exc:
            self.errors.append("REPORT:" + type(exc).__name__)

    def close(self):
        self.finish()
        try:
            self.trace.close()
        except Exception as exc:
            self.errors.append("CLOSE:" + type(exc).__name__)


def open_writer_startup_profile(config, *, generation):
    instance = config.get("host", {}).get("instanceId", "")
    if (config.get("inputMode") != OFFLINE or not isinstance(instance, str)
            or not instance.startswith("qual-015-013b-sc19-")):
        return None
    if not isinstance(generation, str) or re.fullmatch(r"[0-9a-f-]{36}", generation) is None:
        raise ValueError("Disposable Writer profile requires its bound generation.")
    path = Path(config["logRoot"]) / "writer" / ("startup-profile-" + generation + ".jsonl")
    return WriterStartupProfile(ScienceReadinessTrace(path, generation))
