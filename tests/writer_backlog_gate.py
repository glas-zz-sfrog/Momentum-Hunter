"""Engine008 finite admission gate over immutable, physically captured Engine007 trials.

This is test tooling, not runtime authority or a synthetic arrival-rate model.
Missing custody or changed runtime inputs fail closed; no trial is regenerated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from momentum_hunter import continuous_production as production
from momentum_hunter import continuous_runtime as runtime
from momentum_hunter.writer_liveness import WriterLiveness

EVIDENCE_ENV = 'MH_WRITER_BACKLOG_007_EVIDENCE_ROOT'
DEFAULT_EVIDENCE = Path('F:/ArgusQualification/Engine/ARGUS-CONTINUOUS-WRITER-PRODUCTION-ENVELOPE-QUALIFICATION-007-20260911')
ACCEPTED_FREEZE = '586f9cf3865f87d1ba11a7577958155288c6d36fe916b05ac477e73d99d6a5c2'
ACCEPTED_REVIEW = 'f328f332c662f60f0e23b199822726b51e351f2f58006e56a416003e0574c6c9'
SOURCE_HEAD = '927a032e548217fd6c921329aae2db6c98fb4b65'
CAPACITY = 256
CATCHUP_SECONDS = 120.0
BOUNDS = {'EXPECTED': 2, 'PEAK': 122, 'SAFETY_STRESS': 244,
          'TRANSIENT': 122, 'PERSISTENT': 256, 'ROLLOVER': 2}
COUNTS = {'EXPECTED': (14, 14, 0, 18), 'PEAK': (243, 243, 0, 124),
          'SAFETY_STRESS': (245, 245, 0, 123), 'TRANSIENT': (243, 243, 0, 124),
          'PERSISTENT': (795, 539, 256, 40), 'ROLLOVER': (10, 10, 0, 10)}
BOUND_PRODUCT_FILES = (
    'continuous_runtime.py', 'continuous_production.py', 'continuous_evidence_writer.py',
    'writer_liveness.py', 'windows_writer_storage.py', 'event_runtime_writer_ipc.py',
    'continuous_attempt_ledger.py', 'continuous_time_identity.py',
)


class BacklogGateError(AssertionError):
    """Required finite qualification evidence is missing or contradictory."""


def require(condition, code):
    if not condition:
        raise BacklogGateError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def checked_path(root, name):
    relative = PurePosixPath(name.replace('\\', '/'))
    require(not relative.is_absolute() and '..' not in relative.parts and ':' not in name, 'INVALID_MANIFEST_PATH')
    path = (root / relative).resolve(strict=True)
    require(path.is_relative_to(root.resolve(strict=True)), 'MANIFEST_PATH_ESCAPE')
    return path


def verify_custody(root, source_root):
    """Bind reviewed physical evidence and current Engine-owned runtime bytes."""
    require(digest((root/'REVIEW-FREEZE.json').read_bytes()) == ACCEPTED_FREEZE, 'UNACCEPTED_FREEZE')
    require(digest((root/'ASTRA-REVIEW.json').read_bytes()) == ACCEPTED_REVIEW, 'UNACCEPTED_REVIEW')
    freeze = read_json(root/'REVIEW-FREEZE.json')
    require(freeze['head'] == SOURCE_HEAD, 'WRONG_CAPTURE_SOURCE')
    seen = set()
    for entry in freeze['entries']:
        require(entry['path'] not in seen, 'DUPLICATE_MANIFEST_ENTRY')
        seen.add(entry['path'])
        raw = checked_path(root, entry['path']).read_bytes()
        require(len(raw) == entry['bytes'] and digest(raw) == entry['sha256'], 'EVIDENCE_BYTES_CHANGED:'+entry['path'])
    expected = {e['path']: e['sha256'] for e in read_json(root/'SOURCE-AFTER.json')['entries']}
    for name in BOUND_PRODUCT_FILES:
        relative = 'momentum_hunter/'+name
        require(digest((source_root/relative).read_bytes()) == expected[relative], 'RUNTIME_INPUT_CHANGED:'+relative)
    # The Engine base does not own the dormant V2 facade. When Integration adds
    # it, the accepted V2 bytes must match; absence grants no V2 runtime claim.
    for name in ('research_fact_export_v2.py', 'continuous_research_export.py', 'strategy_science_recorder.py'):
        relative = 'momentum_hunter/'+name
        if (source_root/relative).exists():
            require(digest((source_root/relative).read_bytes()) == expected[relative], 'V2_INPUT_CHANGED:'+relative)
    review = read_json(root/'ASTRA-REVIEW.json')
    require(review['ASTRA_DISPOSITION'] == 'ACCEPT_EXACT_PATH_PRODUCTION_BACKLOG_QUALIFICATION'
            and review['ASTRA_UNRESOLVED_MATERIAL_FINDINGS'] == 0, 'REVIEW_NOT_ACCEPTED')
    return len(seen)


@dataclass
class Trial:
    name: str
    events: list
    checkpoint: dict
    health: dict
    config: dict
    records: dict[str, bytes]
    acknowledgements: list[bytes]
    publications: dict[str, bytes]


def load_trial(root, name):
    base = root/'runs'/name
    artifacts = base/'runtime-artifacts'
    checkpoints = list((artifacts/'runtime'/'checkpoint').glob('writer007-*.json'))
    require(len(checkpoints) == 1, 'CHECKPOINT_NOT_SINGLETON')
    records = {p.relative_to(p.parents[3]).as_posix(): p.read_bytes()
               for p in (artifacts/'writer').glob('*/records/*/*/*.json')}
    return Trial(name, [json.loads(line) for line in (base/'ordered-trace.jsonl').read_text().splitlines()],
        read_json(checkpoints[0]), read_json(base/'terminal-health.json'), read_json(artifacts/'config.json'),
        records, [p.read_bytes() for p in (artifacts/'writer').glob('*/sessions/*/*.ack.json')],
        {p.name: p.read_bytes() for p in (artifacts/'v2-publications'/'published').glob('*.json')})


def replay_actual_queue(events, capacity):
    """Run actual BoundedWorkQueue operations and compare every measured depth.

    Service completion predicts a pop; the independently retained DEPARTURE must
    agree. These are captured clocks, never manufactured constant-rate arrivals.
    """
    require(capacity == CAPACITY, 'WRONG_QUEUE_CAPACITY')
    queue = runtime.BoundedWorkQueue(runtime.EVIDENCE_QUEUE, capacity)
    admitted, departed, services, duplicates = {}, [], [], 0
    awaiting_departure = None
    probe = False
    peak, rejected, last_time = 0, 0, float('-inf')
    snapshots = []
    for index, event in enumerate(events, 1):
        require(event['eventIndex'] == index and event['monotonic'] >= last_time, 'TRACE_CHRONOLOGY')
        last_time = event['monotonic']
        kind = event['kind']
        if kind == 'QUEUE_SNAPSHOT':
            require([w['key'] for w in queue.snapshot()] == event['intents'], 'RESTART_QUEUE_MISMATCH')
            restored = runtime.BoundedWorkQueue(runtime.EVIDENCE_QUEUE, capacity)
            for item in queue.snapshot():
                restored.restore(runtime.QueuedWork(**item))
            queue = restored
            snapshots.append(event)
        elif kind == 'IDEMPOTENCY_PROBE_START':
            probe = True
        elif kind == 'IDEMPOTENCY_PROBE_END':
            require(probe and event['runtimeResult'] == 'DUPLICATE' and event['writerResult']['status'] == 'DUPLICATE', 'IDEMPOTENCY_FAILED')
            probe = False
            duplicates += 1
        elif kind == 'ARRIVAL':
            require(event['intentId'] not in admitted or event['status'] != 'ENQUEUED', 'DUPLICATE_ADMISSION')
            work = runtime.build_work(kind=runtime.EVIDENCE_QUEUE, key=event['intentId'],
                requested_at=event['observedAt'], priority=1, payload={'intentId': event['intentId']})
            result, displaced = queue.enqueue(work, datetime.fromisoformat(event['observedAt']))
            require(result == event['status'] and displaced is None, 'ACTUAL_QUEUE_ADMISSION_MISMATCH')
            if result == 'ENQUEUED':
                admitted[event['intentId']] = event
            else:
                require(result == 'REJECTED_CAPACITY', 'UNEXPECTED_ADMISSION_REJECTION')
                rejected += 1
        elif kind == 'SERVICE_START' and not probe:
            require(queue.peek() is not None and queue.peek().key == event['intentId'], 'MISSING_ADMISSION_RECEIPT')
        elif kind == 'SERVICE_END':
            require(event['result']['status'] in ('ACCEPTED', 'DUPLICATE'), 'WRITER_DID_NOT_ACCEPT')
            require(event['serviceStart'] <= event['monotonic'] and event['duration'] >= 0, 'INVALID_SERVICE_TIME')
            services.append(event)
            if not probe:
                require(awaiting_departure is None and queue.peek() is not None and queue.peek().key == event['intentId'], 'ACK_NOT_QUEUE_HEAD')
                awaiting_departure = event['intentId']
        elif kind == 'DEPARTURE':
            require(awaiting_departure == event['intentId'], 'REPLAY_ACK_DEPARTURE_MISMATCH')
            item = queue.pop()
            require(item is not None and item.key == awaiting_departure, 'REPLAY_FIFO_MISMATCH')
            awaiting_departure = None
            departed.append(event)
        if 'metrics' in event:
            metrics = event['metrics']
            require(metrics['configured_capacity'] == capacity, 'WRONG_QUEUE_CAPACITY')
            require(metrics['current_depth'] == len(queue), 'REPLAY_DEPTH_MISMATCH')
            require(metrics['dropped_count'] == 0, 'SILENT_QUEUE_DROP')
            peak = max(peak, len(queue))
    require(awaiting_departure is None and not probe and len(snapshots) == 2, 'INCOMPLETE_RESTART_OR_ACK_TRACE')
    return {'admitted': admitted, 'departed': departed, 'services': services,
            'pending': [w['key'] for w in queue.snapshot()], 'peak': peak,
            'rejected': rejected, 'duplicateProbes': duplicates}


def qualify_trial(trial):
    require(trial.name in BOUNDS, 'UNKNOWN_FINITE_PROFILE')
    capacity = production._runtime_config(trial.config).queues.evidence
    result = replay_actual_queue(trial.events, capacity)
    require(result['peak'] <= BOUNDS[trial.name], 'FINITE_QUEUE_ENVELOPE_EXCEEDED')
    require(trial.events[0]['sourceHead'] == SOURCE_HEAD, 'WRONG_CAPTURE_SOURCE')
    require(trial.events[-1]['kind'] == 'TERMINAL' and trial.events[-1]['error'] is None, 'TRIAL_NOT_TERMINAL')
    records = {}
    for path, raw in trial.records.items():
        record = json.loads(raw)
        require(production._canonical_bytes(record) == raw, 'NONCANONICAL_RECORD')
        require(record['recordFingerprint'] == production._fingerprint('production-continuous-record-v1',
            {k:v for k,v in record.items() if k != 'recordFingerprint'}), 'RECORD_FINGERPRINT')
        require(record['authority'] == production.AUTHORITY and record['executionAuthority'] == production.EXECUTION
                and record['orderCapability'] == 'UNAVAILABLE', 'RECORD_AUTHORITY')
        intent = runtime.EvidenceWriteIntent(**record['intent'], payload_json=production._canonical_text(record['payload']))
        runtime.validate_evidence_write_intent(intent)
        require(intent.intent_id not in records, 'DUPLICATE_RECORD')
        records[intent.intent_id] = intent
    acks = sorted((json.loads(raw) for raw in trial.acknowledgements), key=lambda a:a['sequence'])
    require(len(acks) == len(result['services']), 'ACK_COUNT_MISMATCH')
    for sequence, (ack, service) in enumerate(zip(acks, result['services']), 1):
        require(ack['sequence'] == sequence and ack['fingerprint'] == production._fingerprint('production-continuous-ack-v1',
            {k:v for k,v in ack.items() if k != 'fingerprint'}), 'ACK_IDENTITY')
        require(ack['recordPath'] in trial.records, 'LOST_DURABLE_RECORD')
        raw = trial.records[ack['recordPath']]
        require(digest(raw) == ack['recordSha256'] and json.loads(raw)['intent']['intent_id'] == service['intentId']
                and ack['status'] == service['result']['status'], 'ACK_RECORD_SERVICE_MISMATCH')
    pending = result['pending']
    require(set(records) == {e['intentId'] for e in result['departed']}, 'DURABLE_DEPARTURE_MISMATCH')
    require(set(result['admitted']) == set(records) | set(pending) and not set(records) & set(pending), 'ADMISSION_ACCOUNTING_MISMATCH')
    cp = trial.checkpoint
    require(cp['checkpoint_fingerprint'] == runtime._fingerprint('continuous-runtime-checkpoint-v1',
        {k:v for k,v in cp.items() if k != 'checkpoint_fingerprint'}), 'CHECKPOINT_FINGERPRINT')
    cp_pending = [json.loads(work['payload_json'])['intent_id'] for work in cp['queues']['evidence']]
    require(cp_pending == pending and len(cp['intents']) == len(result['admitted']), 'CHECKPOINT_COUNT_MISMATCH')
    predecessor = None
    for sequence, values in enumerate(cp['intents'], 1):
        intent = runtime.EvidenceWriteIntent(**values)
        runtime.validate_evidence_write_intent(intent)
        require(intent.sequence == sequence and intent.predecessor_identity == predecessor
                and intent.intent_id in result['admitted'], 'INTENT_CHAIN_OR_RECEIPT')
        if intent.intent_id in records:
            require(intent == records[intent.intent_id], 'CHECKPOINT_RECORD_BYTES_MISMATCH')
        predecessor = intent.intent_id
    require(cp['sequence'] == len(result['admitted']), 'CHECKPOINT_COUNT_MISMATCH')
    monitor = WriterLiveness.restore(cp['writer_liveness'])
    require(monitor.arrivals == len(result['admitted']) and monitor.drains == len(records)
            and monitor.capacity_rejections == result['rejected'], 'LIVENESS_ACCOUNTING_MISMATCH')
    require(trial.health['evidence_accepted_count'] == len(records), 'HEALTH_COUNT_MISMATCH')
    require((len(result['admitted']), len(records), len(pending), len(trial.publications)) == COUNTS[trial.name], 'FINITE_PROFILE_INCOMPLETE')
    streams = {}
    for name in sorted(trial.publications):
        raw = trial.publications[name]
        publication = json.loads(raw)
        stream = publication['stream_id']
        seq, previous = streams.get(stream, (0, '0'*64))
        require(publication['source_sequence'] == seq+1 and publication['previous_record_sha256'] == previous, 'V2_CHAIN')
        require(publication['authority'] == 'RESEARCH_ONLY' and publication['execution_authority'] == 'NONE', 'V2_AUTHORITY')
        streams[stream] = (seq+1, digest(raw))
    v2 = [e for e in trial.events if e['kind'] == 'V2_END']
    require(len(v2) == len(trial.publications), 'V2_TRACE_COUNT')
    for event in v2:
        publication_result = event['result']
        if publication_result['status'] == 'FINAL_PUBLISHED':
            require(publication_result['conflict_count'] == publication_result['pending_source_events'] == publication_result['source_gap_count'] == 0, 'V2_FINAL_GAP')
            publication_result = publication_result['publication']
        require(publication_result['status'] == 'PUBLISHED', 'V2_NOT_PUBLISHED')
        name = PurePosixPath(publication_result['relative_path']).name
        require(name in trial.publications and digest(trial.publications[name]) == publication_result['raw_sha256'], 'V2_TRACE_BYTES')
    if trial.name == 'PERSISTENT':
        require(result['peak'] == CAPACITY and result['rejected'] > 0 and pending, 'OVERLOAD_NOT_EXERCISED')
        require(cp['process_state'] == trial.health['process_state'] == trial.events[-1]['state'] == 'FAILED'
                and monitor.failure == 'SUSTAINED_CAPACITY_PRESSURE', 'OVERLOAD_FAILURE_NOT_PRESERVED')
        require(monitor.rejection_last_at - monitor.rejection_started_at >= 615, 'OVERLOAD_HORIZON_NOT_REACHED')
        ticks = [e for e in trial.events if e['kind'] == 'TICK']
        require(any(e['state'] == 'DEGRADED' for e in ticks), 'OVERLOAD_NOT_DEGRADED')
    else:
        require(not pending and cp['process_state'] == trial.health['process_state'] == 'RUNNING'
                and monitor.failure is None and result['rejected'] == 0, 'BACKLOG_NOT_DRAINED')
        require(result['duplicateProbes'] == 1, 'IDEMPOTENCY_NOT_EXERCISED')
    catchup = None
    if trial.name == 'TRANSIENT':
        slow = [e for e in result['services'] if e['result']['acknowledgement_seconds'] > .5]
        require(len(slow) == 8, 'SLOW_ACK_PROFILE_INCOMPLETE')
        catchup = result['departed'][-1]['monotonic'] - slow[-1]['monotonic']
        boundary = next(e for e in trial.events if e['kind'] == 'BOUNDARY_ADMISSION_STRESS_BEGIN')
        whole = result['departed'][-1]['monotonic'] - boundary['monotonic']
        require(0 <= catchup <= whole < CATCHUP_SECONDS, 'TRANSIENT_RECOVERY_BUDGET')
    return {'workload': trial.name, 'queuePeak': result['peak'], 'queueCapacity': capacity,
        'admissions': len(result['admitted']), 'durable': len(records), 'pending': len(pending),
        'rejections': result['rejected'], 'replayMatchesActual': True, 'catchupSeconds': catchup,
        'result': 'PASS', 'scope': 'ACCEPTED_007_FINITE_CAPTURE_ONLY'}


def qualify(root=None, source_root=None):
    root = Path(root or os.environ.get(EVIDENCE_ENV, DEFAULT_EVIDENCE))
    source_root = Path(source_root or Path(__file__).resolve().parents[1])
    entries = verify_custody(root, source_root)
    trials = [qualify_trial(load_trial(root, name)) for name in BOUNDS]
    return {'status':'PASS', 'gate':'PRODUCTION_GROUNDED_FINITE_BACKLOG_007',
        'evidenceRoot':str(root), 'reviewFreezeSha256':ACCEPTED_FREEZE, 'verifiedEntries':entries,
        'primaryInput':'RETAINED_PHYSICAL_007_TRACE_PLUS_CURRENT_ACTUAL_QUEUE',
        'notNewCapacityMeasurement':True, 'installedOrUnboundedReadiness':False, 'trials':trials}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path)
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify(args.evidence_root, args.source_root), indent=2))
