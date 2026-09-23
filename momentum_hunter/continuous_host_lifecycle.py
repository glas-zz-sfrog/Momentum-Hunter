"""Host-owned lifecycle adapters; canonical Science and Engine own all evidence semantics."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import uuid

from momentum_hunter.continuous_host_contract import OFFLINE, input_mode, canonical_bytes, science_custody_policy
from momentum_hunter.continuous_host_generation import (
    aggregate_health, completion, dependencies_drained, generation_path, read_record, replace_status,
)


def stdin_stop_event(enabled: bool) -> threading.Event:
    event = threading.Event()
    if enabled:
        def listen():
            for line in sys.stdin:
                if line.strip() == "STOP":
                    break
            event.set()
        threading.Thread(target=listen, name="continuous-parent-control", daemon=True).start()
    return event


def science_state(coverage):
    if any(coverage.get(k) for k in ("admission_frozen", "invalid_count", "rejected_count", "conflicts")):
        return "FAILED"
    if coverage.get("gaps") or coverage.get("pending_count") or coverage.get("audit_required"):
        return "DEGRADED"
    return "HEALTHY" if coverage.get("admitted_arrival_count", 0) else "STARTING"


def health_coverage(summary):
    keys = ("normalized_record_count", "raw_arrival_count", "admitted_arrival_count", "pending_count",
            "conflicts", "invalid_count", "rejected_count", "admission_frozen", "duplicate_deliveries", "family_counts", "proof_scope")
    result = {key: summary.get(key) for key in keys}
    result["gaps"] = summary.get("gaps", [])[:20]
    result["gapCount"] = len(summary.get("gaps", []))
    return result


def upstream_generations(config, role):
    return {key: read_record(generation_path(config, key)).get("generation")
            for key in {"writer": (), "runtime": ("writer",), "science": ("writer", "runtime")}[role]}


def open_host_science_storage(config, *, trace_hook=None):
    from momentum_hunter.windows_science_custody import open_science_custody_backend
    from momentum_hunter.science_custody_mailbox import ScienceCustodyMailboxClient
    from momentum_hunter.science_custody_readonly import ScienceCustodyStorageSet

    policy = science_custody_policy(config)
    backend = open_science_custody_backend(policy, role="science")
    try:
        client = ScienceCustodyMailboxClient(policy_sha256=policy.policy_sha256,
            source_root_identity=policy.source_root_identity, mailbox_backend=backend,
            trace_hook=trace_hook)
        return ScienceCustodyStorageSet(client,
            recovery_clock=lambda: datetime.now(timezone.utc).isoformat())
    except BaseException:
        backend.close()
        raise


def run_science(config, stop: threading.Event, host):
    from momentum_hunter.strategy_science_continuous_recorder import ContinuousScienceRecorder
    from momentum_hunter.strategy_science_recorder.namespace_changes import NamespaceRecoveryRequired

    settings = config["host"]["science"]
    published = Path(config["researchFactExportV2"]["exportRoot"]) / "published"
    recorder, storage_set, coverage, bound = None, None, {}, None
    trace = None
    readiness_trace = None
    custody_evidence = None
    quiet = 0
    stop_deadline = None
    def status(state, **extra):
        host.status(state, coverage=coverage, dependencies=bound or {},
                     custodyBoundary=custody_evidence, **extra)
        if readiness_trace is not None:
            readiness_trace("science_status", state=state,
                dependencies=bound or {},
                raw_arrival_count=coverage.get("raw_arrival_count", 0),
                normalized_record_count=coverage.get("normalized_record_count", 0),
                admitted_arrival_count=coverage.get("admitted_arrival_count", 0))
    try:
        status("STARTING")
        from momentum_hunter.science_custody_trace_020u import open_020u_trace
        trace = open_020u_trace(config, role="science", generation=host.generation)
        from momentum_hunter.science_readiness_trace_020y import open_020y_trace
        readiness_trace = open_020y_trace(config, generation=host.generation)
        while True:
            if stop.is_set() and stop_deadline is None:
                stop_deadline = time.monotonic() + config["host"]["shutdownSeconds"]
            if stop_deadline is not None and time.monotonic() >= stop_deadline:
                status("INCOMPLETE", drainComplete=False, cleanupComplete=False, reason="SCIENCE_DRAIN_TIMEOUT")
                return 2
            dependencies = upstream_generations(config, "science")
            if bound != dependencies:
                if recorder is not None:
                    recorder.close()
                    recorder = None
                if storage_set is not None:
                    storage_set.close()
                    storage_set = None
                custody_evidence = None
                bound, quiet = dependencies, 0
                if readiness_trace is not None:
                    readiness_trace("dependency_bound", dependencies=bound)
            if recorder is None:
                if not all(bound.values()) or not published.is_dir():
                    status("DEGRADED", reason="WAITING_FOR_PRODUCER_PUBLICATION", drainComplete=False)
                    time.sleep(settings["pollSeconds"])
                    continue
                status("RECOVERING", auditRequired=True)
                storage_set = open_host_science_storage(config, trace_hook=trace)
                native = storage_set.backend.security_contract_evidence
                custody_evidence = {"profile": native["profile"], "policySha256": native["policy_sha256"],
                    "role": native["role"], "token": native["token"],
                    "exactOwnerDaclLabelPolicyVerified": native["exact_owner_dacl_label_policy_verified"]}
                recorder = ContinuousScienceRecorder(publication_root=published,
                    science_root=Path(settings["stateRoot"]), source_root_identity=config["runtimeBuildHash"],
                    writer_instance_id=config["host"]["instanceId"] + "-science-" + host.generation,
                    clock=lambda: datetime.now(timezone.utc).isoformat(),
                    custody_storage_set=storage_set, readiness_trace=readiness_trace)
                # Canonical cold recovery/audit, not erasure of the earlier failure receipt.
                coverage = health_coverage(recorder.coverage())
                if readiness_trace is not None:
                    readiness_trace("recovery_snapshot", dependencies=bound,
                        raw_arrival_count=coverage.get("raw_arrival_count", 0),
                        normalized_record_count=coverage.get("normalized_record_count", 0),
                        admitted_arrival_count=coverage.get("admitted_arrival_count", 0),
                        historical_lineage="UNKNOWN_WITHOUT_PER_EVENT_TRACE")
            result = recorder.poll(max_items=settings["maxItems"])
            coverage = health_coverage(result["coverage"])
            state = science_state(coverage)
            status("DRAINING" if stop_deadline else state, auditRequired=False)
            if state == "FAILED":
                status("FAILED", drainComplete=False, reason="CANONICAL_SCIENCE_REJECTED")
                return 2
            if stop_deadline:
                # Quiet polls count only AFTER the matching producer generation has
                # closed. An early Science STOP cannot abandon future publications.
                producer_done = completion(config, "runtime")
                quiet = quiet + 1 if producer_done and result["observed"] == result["admitted"] == 0 else 0
                if quiet >= 2 and state == "HEALTHY":
                    cursor = recorder.reader.consume_available(max_items=0).cursor
                    final = {"publicationOrdinal": cursor.last_publication_ordinal,
                             "terminal": cursor.terminal, "finalDisposition": cursor.final_disposition}
                    recorder.close()
                    recorder = None
                    storage_set.close()
                    storage_set = None
                    status("STOPPED", drainComplete=True, cleanupComplete=True, pendingWork=0,
                           publicationFailure=None, cursor=final, finalAuthority="CANONICAL_PRODUCER_ONLY")
                    return 0
            time.sleep(settings["pollSeconds"])
    except Exception as exc:
        chain, value = set(), exc
        recoverable = False
        while value is not None and id(value) not in chain:
            chain.add(id(value))
            recoverable |= isinstance(value, NamespaceRecoveryRequired)
            value = value.__cause__ or value.__context__
        report = {"hostFingerprint": config["hostFingerprint"], "generation": host.generation,
            "observedAt": datetime.now(timezone.utc).isoformat(), "exceptionClass": type(exc).__name__,
            "message": str(exc), "traceback": traceback.format_exc(), "nativeOverflowRecovery": recoverable}
        path = Path(config["logRoot"]) / "science" / ("failure-" + host.generation + ".json")
        with path.open("xb") as output:
            output.write(canonical_bytes(report))
            output.flush()
            os.fsync(output.fileno())
        status("AUDIT_REQUIRED" if recoverable else "FAILED", auditRequired=True,
               drainComplete=False, cleanupComplete=False, reason=str(exc), exceptionClass=type(exc).__name__)
        return 3 if recoverable else 2
    finally:
        try:
            if recorder is not None:
                recorder.close()
        finally:
            if storage_set is not None:
                storage_set.close()
            try:
                if trace is not None:
                    trace.close()
            finally:
                if readiness_trace is not None:
                    readiness_trace.close()


def retained_inputs(config, checkpoint=None):
    if input_mode(config) != OFFLINE:
        return None
    from momentum_hunter.preserved_provider_replay import load_preserved_provider_replay
    replay = load_preserved_provider_replay(Path(config["offlineInput"]["packagePath"]))
    if checkpoint:
        for key in ("last_tick_at", "last_heartbeat_at", "last_discovery_completed_at"):
            if checkpoint.get(key):
                replay.clock.advance_to(checkpoint[key])
        seen_root = Path(config["runtimeStateRoot"]) / "session" / "source-evidence" / "finviz"
        replay.discovery_provider.index = max((i + 1 for i, snapshot in enumerate(replay.discovery_provider.snapshots)
            if (seen_root / (snapshot.snapshot_id + ".json")).exists()), default=0)
    return replay
