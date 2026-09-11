"""Bounded writer health; latency is not a durability verdict."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields

ACK_SLOW_HEALTH_THRESHOLD_SECONDS = 0.500
WRITER_LIVENESS_FAILED = "WRITER_LIVENESS_FAILED"
WRITER_CORRECTNESS_FAILED = "WRITER_CORRECTNESS_FAILED"


@dataclass
class WriterLiveness:
    arrivals: int = 0
    capacity_rejections: int = 0
    drains: int = 0
    attempts: int = 0
    slow_acks: int = 0
    over_one_second: int = 0
    consecutive_slow_acks: int = 0
    maximum_ack_seconds: float = 0.0
    latencies: list[float] = field(default_factory=list)
    slow_events: list[dict] = field(default_factory=list)
    queue_peak: int = 0
    oldest_pending_max_age_seconds: float = 0.0
    last_progress: float | None = None
    pending_since: float | None = None
    window_start: float | None = None
    window_depth: int = 0
    window_arrivals: int = 0
    window_drains: int = 0
    window_rejections: int = 0
    rejection_started_at: float | None = None
    rejection_last_at: float | None = None
    observed_rejections: int = 0
    recovery_seconds: float = 0.0
    last_observation: float | None = None
    failure: str | None = None
    classification: str = "HEALTHY"
    recent_arrival_rate: float = 0.0
    recent_offered_rate: float = 0.0
    recent_drain_rate: float = 0.0

    def record_ack(self, elapsed: float | None, *, intent_id: str | None = None,
                   observed_at: str | None = None) -> None:
        if elapsed is None:
            return
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Invalid writer latency measurement")
        self.attempts += 1
        slow = elapsed > ACK_SLOW_HEALTH_THRESHOLD_SECONDS
        self.slow_acks += int(slow)
        self.over_one_second += int(elapsed > 1.0)
        self.consecutive_slow_acks = self.consecutive_slow_acks + 1 if slow else 0
        self.maximum_ack_seconds = max(self.maximum_ack_seconds, elapsed)
        self.latencies = (self.latencies + [elapsed])[-128:]
        if slow:
            self.slow_events = (self.slow_events + [{
                "classification": "DURABLE_ACK_LATENCY_HEALTH_WARNING",
                "intentId": intent_id, "observedAt": observed_at,
                "acknowledgementSeconds": elapsed,
                "thresholdSeconds": ACK_SLOW_HEALTH_THRESHOLD_SECONDS,
            }])[-128:]

    def observe(self, *, now: float, depth: int, capacity: int,
                oldest_age: float, horizon: float) -> str | None:
        if (any(not math.isfinite(x) for x in (now, oldest_age, horizon))
                or horizon <= 0 or oldest_age < 0 or capacity < 1 or not 0 <= depth <= capacity):
            raise ValueError("Writer liveness observation is outside its bounded contract")
        rejection_time = now
        if self.last_observation is not None:
            now = max(now, self.last_observation)
        self.last_observation = now
        self.queue_peak = max(self.queue_peak, depth)
        self.oldest_pending_max_age_seconds = max(self.oldest_pending_max_age_seconds, oldest_age)
        if self.failure:
            return self.failure
        if self.capacity_rejections > self.observed_rejections:
            rejection_time = max(rejection_time, self.rejection_last_at or rejection_time)
            # Completion clocks may run ahead of same-tick admissions. Retain
            # the old episode until recorded rejection times prove a quiet gap.
            if self.rejection_last_at is not None and rejection_time - self.rejection_last_at >= horizon:
                self.rejection_started_at = self.rejection_last_at = None
            self.rejection_started_at = self.rejection_started_at if self.rejection_started_at is not None else rejection_time
            self.rejection_last_at = rejection_time
            self.observed_rejections = self.capacity_rejections
            if now - self.rejection_started_at >= horizon:
                self.failure = "SUSTAINED_CAPACITY_PRESSURE"
                self.classification = WRITER_LIVENESS_FAILED
                return self.failure
        if depth == 0:
            if self.pending_since is not None:
                self.recovery_seconds = max(0.0, now - self.pending_since)
            self.pending_since = self.window_start = None
            self.classification = "ONE_OFF_JITTER" if self.consecutive_slow_acks == 1 else (
                "TRANSIENT_BURST" if self.consecutive_slow_acks else "HEALTHY")
            return None
        if self.pending_since is None:
            self.pending_since = now
        if self.window_start is None:
            self.window_start = now
            self.window_depth = depth
            self.window_arrivals, self.window_drains = self.arrivals, self.drains
            self.window_rejections = self.capacity_rejections
        duration = max(0.0, now - self.window_start)
        arrived, drained = self.arrivals - self.window_arrivals, self.drains - self.window_drains
        if duration:
            self.recent_arrival_rate = arrived / duration
            self.recent_offered_rate = (arrived + self.capacity_rejections - self.window_rejections) / duration
            self.recent_drain_rate = drained / duration
        progress_floor = max(self.pending_since, self.last_progress or self.pending_since)
        if now - progress_floor >= horizon:
            self.failure = "NO_PROGRESS"
        elif (duration >= horizon and oldest_age >= horizon
              and depth >= self.window_depth and arrived >= drained):
            self.failure = "SUSTAINED_BACKPRESSURE"
        if self.failure:
            self.classification = WRITER_LIVENESS_FAILED
            return self.failure
        self.classification = (
            "CAPACITY_PRESSURE" if depth >= max(1, capacity - 1) else
            "SUSTAINED_DEGRADATION" if oldest_age >= horizon or self.consecutive_slow_acks > 1 else
            "ONE_OFF_JITTER" if self.consecutive_slow_acks else "PENDING")
        if duration >= horizon:
            self.window_start, self.window_depth = now, depth
            self.window_arrivals, self.window_drains = self.arrivals, self.drains
            self.window_rejections = self.capacity_rejections
        return None

    def snapshot(self) -> dict:
        return asdict(self)

    def validate_rejection_history(self, timestamps: list[float], *, horizon: float) -> None:
        """Reject contradictions in retained evidence; do not invent lost history."""
        if not timestamps:
            return
        times = sorted(timestamps)
        if (self.last_observation is None or times[-1] > self.last_observation
                or self.capacity_rejections < len(times)):
            raise ValueError("Writer rejection count/time contradicts retained admission evidence")
        first = times[-1]
        for prior in reversed(times[:-1]):
            if first - prior >= horizon:
                break
            first = prior
        if self.last_observation - times[-1] < horizon:
            if (self.rejection_started_at is None or self.rejection_last_at is None
                    or self.rejection_started_at > first or self.rejection_last_at < times[-1]):
                raise ValueError("Writer rejection episode contradicts retained admission evidence")

    def health(self, *, now: float, depth: int, capacity: int, oldest_age: float) -> dict:
        return {**self.snapshot(), "queueDepth": depth, "queueCapacity": capacity,
                "oldestPendingAgeSeconds": oldest_age,
                "secondsSinceWriterProgress": (max(0.0, now - (self.last_progress or self.pending_since))
                    if self.last_progress is not None or self.pending_since is not None else None),
                "recentSlowAckRate": (sum(x > ACK_SLOW_HEALTH_THRESHOLD_SECONDS for x in self.latencies)
                                      / len(self.latencies) if self.latencies else 0.0),
                "healthThresholdSeconds": ACK_SLOW_HEALTH_THRESHOLD_SECONDS}

    @classmethod
    def restore(cls, value: dict) -> WriterLiveness:
        if not isinstance(value, dict) or set(value) != {item.name for item in fields(cls)}:
            raise ValueError("Writer monitor checkpoint is incomplete or unsupported")
        result = cls(**value)
        count_fields = {
            "arrivals", "capacity_rejections", "drains", "attempts", "slow_acks",
            "over_one_second", "consecutive_slow_acks", "queue_peak", "window_depth",
            "window_arrivals", "window_drains", "window_rejections", "observed_rejections",
        }
        time_fields = {"last_progress", "pending_since", "window_start", "last_observation", "rejection_started_at", "rejection_last_at"}
        for name in count_fields:
            if type(value[name]) is not int or value[name] < 0:
                raise ValueError(f"Invalid writer monitor counter: {name}")
        for name in time_fields | {
            "maximum_ack_seconds", "oldest_pending_max_age_seconds", "recovery_seconds",
            "recent_arrival_rate", "recent_offered_rate", "recent_drain_rate",
        }:
            item = value[name]
            if item is None and name in time_fields:
                continue
            if type(item) not in (int, float) or not math.isfinite(item) or item < 0:
                raise ValueError(f"Invalid writer monitor time/rate: {name}")
        if (type(result.latencies) is not list or type(result.slow_events) is not list
                or len(result.latencies) > 128 or len(result.slow_events) > 128):
            raise ValueError("Writer latency history exceeds its bound")
        if result.drains > result.arrivals:
            raise ValueError("Writer drain count exceeds admission count")
        if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in result.latencies):
            raise ValueError("Invalid writer latency history")
        if not (0 <= result.over_one_second <= result.slow_acks <= result.attempts
                and 0 <= result.consecutive_slow_acks <= result.slow_acks):
            raise ValueError("Contradictory writer latency counters")
        if (result.window_arrivals > result.arrivals or result.window_drains > result.drains
                or result.window_rejections > result.capacity_rejections
                or result.observed_rejections != result.capacity_rejections):
            raise ValueError("Contradictory writer window counters")
        terminal = result.classification in {WRITER_LIVENESS_FAILED, WRITER_CORRECTNESS_FAILED}
        if (type(result.classification) is not str
                or result.classification not in {"HEALTHY", "PENDING", "ONE_OFF_JITTER", "TRANSIENT_BURST",
                    "CAPACITY_PRESSURE", "SUSTAINED_DEGRADATION", WRITER_LIVENESS_FAILED, WRITER_CORRECTNESS_FAILED}
                or (result.failure is not None and (type(result.failure) is not str or not result.failure))
                or terminal != (result.failure is not None)):
            raise ValueError("Contradictory writer terminal state")
        for name in time_fields - {"last_observation"}:
            item = value[name]
            if item is not None and (result.last_observation is None or item > result.last_observation):
                raise ValueError("Writer monitor time exceeds its last observation")
        if ((result.pending_since is None) != (result.window_start is None)
                or (result.rejection_started_at is None) != (result.rejection_last_at is None)
                or (result.rejection_started_at is not None and (
                    result.rejection_started_at > result.rejection_last_at or not result.observed_rejections))):
            raise ValueError("Writer pending/window history is contradictory")
        for event in result.slow_events:
            if (type(event) is not dict or set(event) != {"classification", "intentId", "observedAt",
                    "acknowledgementSeconds", "thresholdSeconds"}
                    or event["classification"] != "DURABLE_ACK_LATENCY_HEALTH_WARNING"
                    or event["thresholdSeconds"] != ACK_SLOW_HEALTH_THRESHOLD_SECONDS
                    or type(event["acknowledgementSeconds"]) not in (int, float)
                    or not math.isfinite(event["acknowledgementSeconds"])
                    or event["acknowledgementSeconds"] <= ACK_SLOW_HEALTH_THRESHOLD_SECONDS
                    or any(event[k] is not None and type(event[k]) is not str for k in ("intentId", "observedAt"))):
                raise ValueError("Writer slow event is invalid")
        return result
