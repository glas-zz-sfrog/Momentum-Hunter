"""Explicit, dormant Continuous source-to-V2 publication adapter.

The native runtime owns source production and scheduling. This adapter receives
immutable facts only. RuntimeCheckpointStore holds captured source bytes and
their observation clock; the canonical exporter owns publication clocks/bytes,
sequence/cursor recovery, duplicate conflicts and FINAL. No Science callback,
provider client, decision callback, or execution capability is accepted here.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.continuous_runtime import RuntimeCheckpointStore
from momentum_hunter.continuous_time_identity import canonical_instant
from momentum_hunter.continuous_v2_projection import OWNER, fingerprint, project
from momentum_hunter.continuous_v2_native_custody import native_inventory, recovered_sources
from momentum_hunter.research_fact_export_v2 import ResearchFactExporterV2
from momentum_hunter.strategy_science_recorder.canonical import parse_rfc3339, sha256_hex
from momentum_hunter.strategy_science_recorder.contract import (
    REPAIRED_EXPORT_SCHEMA_VERSION, REPAIRED_SOURCE_CONTRACT,
    REPAIRED_SOURCE_CONTRACT_VERSION, SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
)


class ContinuousV2ProducerError(ValueError):
    """Only the publication claim fails; no source decision is rewritten."""


def _native_fingerprint(value):
    value = {key: item for key, item in value.items() if key != "checkpoint_fingerprint"}
    return sha256_hex(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=True, allow_nan=False).encode("ascii"))


class ContinuousV2Producer:
    def __init__(self, *, export_root: Path, manifest: dict, source_root_identity: str,
                 runtime_fingerprint: str, science_custody_roots: tuple[Path, ...],
                 protected_roots: tuple[Path, ...], allow_persistent: bool = False, clock=None):
        self.root = Path(export_root)
        self.manifest = deepcopy(manifest)
        self.runtime_fingerprint = runtime_fingerprint
        self.binding = fingerprint({"manifest": manifest, "source_root": source_root_identity,
                                    "runtime_fingerprint": runtime_fingerprint, "producer": OWNER})
        self.exporter = ResearchFactExporterV2(
            self.root, session_id=manifest["session_id"], source_owner_identity=OWNER,
            source_interface_identity="continuous-native-runtime-facts-v1",
            source_root_identity=source_root_identity, schema_version=REPAIRED_EXPORT_SCHEMA_VERSION,
            source_contract=REPAIRED_SOURCE_CONTRACT, source_contract_version=REPAIRED_SOURCE_CONTRACT_VERSION,
            offline_reference_profile=SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
            science_custody_roots=science_custody_roots, protected_roots=protected_roots)
        self.allow_persistent = allow_persistent
        self.store = None
        self.failure = None
        self.initialized = False
        self.terminal = False
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.native_sources = None

    def now(self):
        return self.clock().isoformat()

    def initialize(self, now: datetime):
        self.exporter.initialize()
        try:
            self.store = RuntimeCheckpointStore(self.root / "producer-source", allow_persistent=self.allow_persistent)
            path = self.store.path_for("start")
            if path.exists():
                start = self._load("start")
            else:
                if self.exporter.published():
                    raise ContinuousV2ProducerError("Published bytes have lost their source checkpoint.")
                if self.store.path_for("native-handoff").exists():
                    raise ContinuousV2ProducerError("Incomplete initial producer control must not be rebaselined.")
                self.store.save("native-handoff", {"binding": self.binding, "state": "IDLE",
                    "baseline_sha256": None, "coverage": None, "source_checksums": {}, "failure": None})
                start = {"binding": self.binding, "observed_at": now.isoformat(), "manifest": self.manifest}
                self.store.save("start", start)
            if start["manifest"] != self.manifest:
                raise ContinuousV2ProducerError("START source identity changed.")
            self.failure = self._control()["failure"]
            observed = start["observed_at"]
            prior_start = next((p for p in self.exporter.published()
                                if p.source_event_id == "start:" + self.binding), None)
            published_at = json.loads(prior_start.raw_bytes)["emitted_at"] if prior_start else now.isoformat()
            self.exporter.start(self.manifest, stream_id="continuous", source_event_id="start:" + self.binding,
                                emitted_at=published_at, event_time=observed, effective_known_at=observed)
            self.initialized = True
            self.recover()
            if self.store.path_for("failure").exists():
                self.failure = self._load("failure")["failure"]
        except BaseException:
            self.exporter.close()
            raise
        return self

    def _load(self, key):
        value = self.store.load(key)
        if value.get("binding") != self.binding:
            raise ContinuousV2ProducerError("Producer checkpoint binding changed.")
        return value

    def _records(self):
        expected = self._control()["source_checksums"]
        if set(expected) != {path.stem for path in self.store.root.glob("source-*.json")}:
            raise ContinuousV2ProducerError("SOURCE_CUSTODY_INDEX_INCOMPLETE")
        records = [self._load(key) for key in sorted(expected)]
        if any(record["source_sha256"] != expected[key] for key, record in zip(sorted(expected), records)):
            raise ContinuousV2ProducerError("SOURCE_CUSTODY_INDEX_CONFLICT")
        if any(sha256_hex(record["source_json"].encode("ascii")) != record["source_sha256"] for record in records):
            raise ContinuousV2ProducerError("Captured source bytes changed.")
        return records

    def _control(self):
        control = self._load("native-handoff")
        if control["baseline_sha256"] is not None:
            if _native_fingerprint(self._load("native-baseline")) != control["baseline_sha256"]:
                raise ContinuousV2ProducerError("NATIVE_BASELINE_CHANGED")
        return control

    def bind_native_sources(self, sources):
        control = self._control()
        current = {stage: native_inventory(stage, source) for stage, source in sources.items()}
        if control["baseline_sha256"] is None:
            if control["state"] != "IDLE" or self.store.path_for("native-baseline").exists():
                raise ContinuousV2ProducerError("NATIVE_BASELINE_CANNOT_BE_REPLACED")
            baseline = {"binding": self.binding, "inventories": current}
            self.store.save("native-baseline", baseline)
            control.update(baseline_sha256=_native_fingerprint(baseline), coverage=current)
            self.store.save("native-handoff", control)
        elif any(value["identity"] != control["coverage"][stage]["identity"] for stage, value in current.items()):
            raise ContinuousV2ProducerError("NATIVE_SOURCE_ROOT_CHANGED")
        self.native_sources = sources

    def _project(self, record):
        source = json.loads(record["source_json"])
        dates = []
        if record["stage"] == "NATIVE_PRODUCER_RECORD":
            dates = [source["session_date"]]
        elif record["stage"] == "COMPOSITION":
            dates = [step["producerRecord"]["compositionCycle"]["session_date"] for step in source["naturalSteps"]]
        elif record["stage"] == "DISCOVERY":
            dates = [source["sourceEvidence"]["snapshot"]["sessionDate"]]
        if any(value != self.manifest["exchange_market_date"] for value in dates):
            raise ContinuousV2ProducerError("NATIVE_SOURCE_SESSION_MISMATCH")
        projections = project(record["stage"], source,
                              record["observed_at"], self.runtime_fingerprint)
        control = self._control()
        if control["baseline_sha256"]:
            baseline = self._load("native-baseline")["inventories"]
            excluded = {"evaluation:" + key for key in baseline["COMPOSITION"]["records"]}
            excluded.update("discovery:" + key for key in baseline["DISCOVERY"]["records"])
            projections = [p for p in projections if not any(
                p["source_event_id"] == key or p["source_event_id"].startswith(key + ":") for key in excluded)]
        return projections

    def _dispatch(self, projected, observed):
        event_type = projected["event_type"]
        payload = projected["payload"]
        key = projected["source_event_id"]
        # Replay must compare payload/source clocks but retain the clock of an
        # already durable publication, not today's recovery time.
        existing = next((p for p in self.exporter.published() if p.source_event_id == key), None)
        if existing is not None:
            observed = json.loads(existing.raw_bytes)["emitted_at"]
        kwargs = {"stream_id": "continuous", "source_event_id": key, "emitted_at": observed}
        if event_type == "DISCOVERY_CYCLE":
            return self.exporter.discovery_cycle(payload["discovery_cycle"], payload["observations"], **kwargs)
        if event_type == "DECISION_FACT":
            return self.exporter.decision(payload["decision_event"], reference_plan=payload.get("reference_plan"), **kwargs)
        if event_type == "MARKET_FACT":
            return self.exporter.market_snapshot(payload["market_snapshot"], **kwargs)
        if event_type == "PROVIDER_HEALTH":
            return self.exporter.provider_health(payload["provider_health_event"], **kwargs)
        raise ContinuousV2ProducerError("Non-producer event type is prohibited.")

    def _publish_source(self, record, published_at):
        raw = record["source_json"]
        if sha256_hex(raw.encode("ascii")) != record["source_sha256"]:
            raise ContinuousV2ProducerError("Captured source bytes changed.")
        projections = self._project(record)
        return [self._dispatch(item, published_at) for item in projections]

    def capture(self, *, stage, source_id, source, observed_at):
        if not self.initialized or self.terminal:
            raise ContinuousV2ProducerError("Producer is not in an active admitted session.")
        try:
            return self._capture(stage=stage, source_id=source_id, source=source, observed_at=observed_at)
        except Exception as exc:
            self.record_failure(self.failure or type(exc).__name__)
            raise

    def _capture(self, *, stage, source_id, source, observed_at):
        parse_rfc3339(observed_at, "producer observation")
        raw = json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        key = "source-" + fingerprint({"stage": stage, "source_id": source_id})
        control = self._control()
        if control["state"] == "PENDING" and key not in control["captured_source_keys"]:
            control["captured_source_keys"].append(key)
            self.store.save("native-handoff", control)
        if self.store.path_for(key).exists():
            record = self._load(key)
            if record["source_json"] != raw:
                self.record_failure("CONFLICTING_SOURCE_IDENTITY")
                raise ContinuousV2ProducerError(self.failure)
        else:
            record = {"binding": self.binding, "source_id": source_id, "stage": stage,
                      "observed_at": observed_at, "source_json": raw,
                      "source_sha256": sha256_hex(raw.encode("ascii"))}
            control = self._control()
            control["source_checksums"][key] = record["source_sha256"]
            self.store.save("native-handoff", control)
            self.store.save(key, record)
        return self._publish_source(record, observed_at)

    def capture_symbol_failure(self, failure, observed_at):
        source = {"stage": failure["stage"],
                  "event_class": "READINESS_FAILURE" if failure["stage"] == "READINESS" else "PARTIAL",
                  "reason": "RUNTIME_" + failure["stage"] + "_FAILURE",
                  "source_observed_at": canonical_instant(failure["observed_at"]),
                  "symbol": failure["symbol"], "source_fingerprint": failure["source_fingerprint"],
                  "attempt_event_id": failure["attempt_event_id"]}
        key = "symbol-failure:" + (failure["attempt_event_id"] or fingerprint(source))
        source["event_id"] = key
        return self.capture(stage="HEALTH", source_id=key, source=source, observed_at=observed_at)

    def record_failure(self, reason):
        self.failure = reason
        control = self._control()
        control["failure"] = reason
        self.store.save("native-handoff", control)
        self.store.save("failure", {"binding": self.binding, "failure": reason})

    def begin_native_operation(self, stage, work_id, source, request_context=None):
        if self.terminal or self.failure:
            return
        control = self._control()
        if control["state"] == "PENDING":
            raise ContinuousV2ProducerError("NATIVE_HANDOFF_STILL_PENDING")
        before = native_inventory(stage, source)
        if control["coverage"] is not None and before != control["coverage"][stage]:
            raise ContinuousV2ProducerError("UNEXPLAINED_NATIVE_CUSTODY_CHANGE")
        control.update(state="PENDING", stage=stage, work_id=work_id, before=before,
                       observed_at=self.now(), captured_source_keys=[],
                       request_context={key: value for key, value in (request_context or {}).items()
                                        if key in {"symbol", "opportunity_id", "decision_cutoff"}})
        self.store.save("native-handoff", control)

    def finish_native_operation(self, sources, *, recovered=False):
        handoff = self._control()
        if handoff["state"] != "PENDING":
            return
        try:
            # An interrupted adapter with no native custody cannot be declared
            # complete. Normal-return fixture adapters use their captured facts.
            if recovered or handoff["before"]["identity"] is not None:
                rows = recovered_sources(handoff["stage"], sources[handoff["stage"]], handoff["before"])
                if recovered and not rows and not handoff["captured_source_keys"]:
                    raise ContinuousV2ProducerError("INTERRUPTED_NATIVE_HANDOFF_COMPLETION_UNPROVEN")
                for stage, key, raw in rows:
                    if stage == "NATIVE_PRODUCER_RECORD":
                        context = handoff["request_context"]
                        for requested, actual in (("symbol", "symbol"), ("opportunity_id", "member_id")):
                            if context.get(requested) and context[requested] != raw[actual]:
                                raise ContinuousV2ProducerError("NATIVE_HANDOFF_REQUEST_IDENTITY_MISMATCH")
                        if context.get("decision_cutoff") and canonical_instant(context["decision_cutoff"]) != canonical_instant(raw["evidence_cutoff"]):
                            raise ContinuousV2ProducerError("NATIVE_HANDOFF_CUTOFF_MISMATCH")
                    self.capture(stage=stage, source_id=key, source=raw, observed_at=self.now())
                handoff["native_source_ids"] = [key for _, key, _ in rows]
            native_source_ids = handoff.get("native_source_ids", [])
            handoff = self._control()
            if self.failure or handoff["failure"]:
                raise ContinuousV2ProducerError("NATIVE_HANDOFF_HAS_FAILED_PUBLICATION")
            if not handoff["captured_source_keys"]:
                raise ContinuousV2ProducerError("NATIVE_HANDOFF_HAS_NO_DURABLE_RESULT")
            if handoff["coverage"] is not None:
                handoff["coverage"][handoff["stage"]] = native_inventory(handoff["stage"], sources[handoff["stage"]])
            handoff.update(state="COMPLETED", recovery=recovered, completed_at=self.now(), native_source_ids=native_source_ids)
            key = "handoff-" + fingerprint({"stage": handoff["stage"], "work_id": handoff["work_id"],
                                           "observed_at": handoff["observed_at"]})
            self.store.save(key, {k: v for k, v in handoff.items() if k not in {"source_checksums", "coverage"}})
            self.store.save("native-handoff", handoff)
        except Exception as exc:
            self.record_failure(str(exc) if isinstance(exc, ValueError) else "NATIVE_HANDOFF_CUSTODY_UNAVAILABLE")
            raise

    def capture_intent(self, intent, observed_at):
        if intent.payload_json is None:
            return
        payload = json.loads(intent.payload_json)
        if intent.evidence_type == "DISCOVERY_CYCLE":
            # Exclude the runtime's pre-acquisition tick clock and IPC identity;
            # source snapshot clocks/identity are immutable and authoritative.
            source = {"sourceEvidence": payload["sourceEvidence"]}
            return self.capture(stage="DISCOVERY", source_id=intent.record_identity,
                                source=source, observed_at=observed_at)
        if intent.evidence_type == "COMPOSITION_CYCLE":
            return self.capture(stage="COMPOSITION", source_id=intent.record_identity,
                                source=payload, observed_at=observed_at)
        if intent.evidence_type in {"SYSTEM_FAILURE", "READINESS_DEFERRED"}:
            source = {"event_id": intent.record_identity, "stage": intent.evidence_type,
                      "event_class": "READINESS_FAILURE" if intent.evidence_type == "READINESS_DEFERRED" else "SOURCE_OUTAGE",
                      "reason": intent.evidence_type, "source_observed_at": payload["knownAt"],
                      "source_fingerprint": intent.payload_fingerprint}
            return self.capture(stage="HEALTH", source_id=intent.record_identity,
                                source=source, observed_at=observed_at)

    def recover(self):
        records = self._records()
        expected = {"start:" + self.binding}
        for record in records:
            for item in self._project(record):
                expected.add(item["source_event_id"])
        for publication in self.exporter.published():
            if publication.source_event_id == "final:" + self.binding:
                self.terminal = True
            elif publication.source_event_id not in expected:
                raise ContinuousV2ProducerError("Published cursor has no captured source provenance.")
        for record in sorted(records, key=lambda r: (parse_rfc3339(r["observed_at"], "observed_at"), r["source_id"])):
            self._publish_source(record, self.now())

    def finalize(self, now, *, terminal_proven, pending_source_events, source_gap_count=0):
        control = self._control()
        # A hard interruption can leave durable source custody without a failed
        # callback or a native handoff. FINAL must verify publication, not intent.
        expected = {}
        conflicts = 0
        for record in self._records():
            for item in self._project(record):
                key = item["source_event_id"]
                if key in expected and expected[key] != item:
                    conflicts += 1
                expected[key] = item
        actual = {p.source_event_id: json.loads(p.raw_bytes) for p in self.exporter.published()
                  if p.source_event_id not in {"start:" + self.binding, "final:" + self.binding}}
        missing = len(expected.keys() - actual.keys())
        conflicts += len(actual.keys() - expected.keys())
        conflicts += sum(actual[key]["event_type"] != item["event_type"]
                         or actual[key]["payload"] != item["payload"]
                         for key, item in expected.items() if key in actual)
        pending_handoff = control["state"] == "PENDING"
        native_gap = bool(control["coverage"] is not None and (self.native_sources is None or any(
            native_inventory(stage, source) != control["coverage"][stage]
            for stage, source in (self.native_sources or {}).items())))
        result = self.exporter.finalize(stream_id="continuous", source_event_id="final:" + self.binding,
            closed_at=now.isoformat(), close_reason="CONTINUOUS_SESSION_SOURCE_TERMINAL",
            terminal_proven=terminal_proven, pending_source_events=pending_source_events,
            source_gap_count=source_gap_count + int(self.failure is not None or control["failure"] is not None)
                + int(pending_handoff) + int(native_gap) + missing,
            upstream_conflict_count=conflicts)
        self.terminal = result.publication is not None
        return result

    def status(self):
        return {"binding": self.binding, "state": "FAILED" if self.failure else "FINAL" if self.terminal else "ACTIVE",
                "failure": self.failure, "authority": "RESEARCH_ONLY", "executionAuthority": "NONE"}

    def close(self):
        self.exporter.close()
