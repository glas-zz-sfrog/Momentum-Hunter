"""Science004 offline qualification on the actual canonical Writer005/V2 modules.

The three fixture-only helpers below are reconciled from protected001's exact
verify tool (SHA79113744d6881b5620f5bae3b3c512915fc474262d9ca767c795ddf23cd75d3a).
They construct synthetic facts only. No old verifier, facade, performance gate,
source code or acceptance receipt is executed/imported. Measured costs separate
normal ingestion, bounded coverage, explicit history audit and process restart.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes as wt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from momentum_hunter.research_fact_export_v2 import ResearchFactExporterV2
from momentum_hunter.strategy_science_continuous_recorder import ContinuousScienceRecorder, FAMILIES
from tests import test_strategy_science_recorder_contract as fixture


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True)+'\n')


def inventory(root):
    return {p.relative_to(root).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
            for p in sorted(root.rglob('*')) if p.is_file()}


def guard(evidence):
    def audit(event, args):
        if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind', 'socket.sendto'}:
            raise RuntimeError('No provider/network authority in Science004 qualification.')
        if event == 'open':
            path, mode, flags = args
            write = ((isinstance(mode, str) and any(c in mode for c in 'wax+')) or
                (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if write and isinstance(path, (str, bytes, os.PathLike)) and not Path(os.fsdecode(path)).resolve().is_relative_to(evidence):
                raise RuntimeError('Python write outside new004 evidence root prohibited.')
    sys.addaudithook(audit)


def code_identity():
    paths = set((ROOT/'momentum_hunter/strategy_science_recorder').glob('*.py'))
    paths.update(ROOT/name for name in ('momentum_hunter/strategy_science_continuous_recorder.py',
        'momentum_hunter/strategy_science_source_reader.py', 'momentum_hunter/windows_writer_storage.py',
        'momentum_hunter/research_fact_export_v2.py', 'tools/qualify_strategy_science_recorder_004.py',
        'tests/test_strategy_science_recorder_contract.py', 'tests/test_strategy_science_recorder_coverage.py',
        'tests/test_strategy_science_recorder_eligibility_authority.py'))
    return {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in sorted(paths)}


def memory():
    class PMC(ctypes.Structure):
        _fields_ = [('cb', wt.DWORD), ('faults', wt.DWORD)] + [(n, ctypes.c_size_t) for n in
            ('peak_working_set','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
    result, handles = PMC(), wt.DWORD()
    result.cb = ctypes.sizeof(result)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wt.HANDLE
    kernel.GetProcessHandleCount.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
    require(psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(result), result.cb), 'Memory unavailable')
    require(kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ctypes.byref(handles)), 'Handle count unavailable')
    return {'peak_working_set_bytes': result.peak_working_set, 'working_set_bytes': result.working_set,
        'process_handle_count': handles.value, 'scope': 'whole process since start; not isolated allocation'}


def publish_fixture(case: Path, exporter_type, *, additional_cycles: int = 0, windows: bool = False):
    from momentum_hunter.strategy_science_recorder.contract import (
        REPAIRED_EXPORT_SCHEMA_VERSION, REPAIRED_SOURCE_CONTRACT,
        REPAIRED_SOURCE_CONTRACT_VERSION, SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
    )
    from tests import test_strategy_science_recorder_contract as fixture
    from tests.test_strategy_science_recorder_eligibility_authority import decision_payload_v2

    producer = case / "producer"
    writer = exporter_type(producer, session_id=fixture.SESSION_ID,
        source_owner_identity="fixture-owner", source_interface_identity="synthetic-continuous-v2-owner",
        source_root_identity=fixture.SOURCE_ROOT_IDENTITY,
        schema_version=REPAIRED_EXPORT_SCHEMA_VERSION, source_contract=REPAIRED_SOURCE_CONTRACT,
        source_contract_version=REPAIRED_SOURCE_CONTRACT_VERSION,
        offline_reference_profile=SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
        science_custody_roots=(case / "science",), protected_roots=(ROOT,)).initialize()
    try:
        writer.start(fixture.start_payload(), stream_id="session-stream", source_event_id="session-start",
            emitted_at="2026-09-01T10:00:00Z", event_time="2026-09-01T10:00:00Z", effective_known_at="2026-09-01T10:00:00Z")
        discovery = fixture.discovery_payload()
        discovery["observations"][0]["candidate_facts"]["rvol"] = fixture.absent("UNAVAILABLE", "SYNTHETIC_MISSING_RVOL")
        writer.discovery_cycle(discovery["discovery_cycle"], discovery["observations"], stream_id="discovery-stream",
            source_event_id="discovery-1", emitted_at=fixture.DISCOVERY_TIME)
        decision = decision_payload_v2()
        writer.decision(decision["decision_event"], reference_plan=decision["reference_plan"], stream_id="decision-stream",
            source_event_id="decision-1", emitted_at=fixture.DECISION_TIME)
        writer.market_snapshot(fixture.market_bar_payload()["market_snapshot"], stream_id="market-stream",
            source_event_id="bar-1", emitted_at=fixture.BAR_TIME)
        writer.provider_health(fixture.health_payload()["provider_health_event"], stream_id="health-stream",
            source_event_id="health-1", emitted_at=fixture.BAR_TIME)
        for index in range(additional_cycles):
            cycle_id = fixture.identity("DISCOVERY_CYCLE_ID", f"storage-cycle-{index}")
            rows = []
            for ordinal in range(5):
                row = fixture.observation(fixture.identity("OBSERVATION_ID", f"storage-{index}-{ordinal}"),
                                          ordinal=ordinal, symbol=f"SYN{ordinal}")
                row["discovery_cycle_id"] = cycle_id
                rows.append(row)
            payload = fixture.discovery_payload(rows)
            payload["discovery_cycle"]["discovery_cycle_id"] = cycle_id
            writer.discovery_cycle(payload["discovery_cycle"], rows, stream_id="discovery-stream",
                source_event_id=f"storage-cycle-{index}", emitted_at=fixture.DISCOVERY_TIME)
        if windows:
            # Explicit synthetic UTC windows, not a market calendar or historical tape.
            for label, instant in (
                ("premarket", "2026-09-01T12:00:00Z"), ("opening", "2026-09-01T13:30:00Z"),
                ("morning", "2026-09-01T15:00:00Z"), ("midday", "2026-09-01T17:00:00Z"),
                ("close", "2026-09-01T20:00:00Z"), ("after-hours", "2026-09-01T20:30:00Z"),
                ("late-morning-arrival", "2026-09-01T14:00:00Z"),
            ):
                health = fixture.health_payload(health_id=fixture.identity("PROVIDER_HEALTH_EVENT_ID", f"window-{label}"))["provider_health_event"]
                health["provider_received_at"] = fixture.time_evidence("PROVIDER_RECEIVED_AT", instant)
                health["source_event_time"] = fixture.time_evidence("SOURCE_EVENT_TIME", instant)
                writer.provider_health(health, stream_id="health-stream", source_event_id=f"window-{label}", emitted_at=instant)
        publications = writer.published()
    finally:
        writer.close()
    return publications, inventory(producer)


def deliver(publications, destination: Path, indexes: list[int]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for index in indexes:
        publication = publications[index]
        path = destination / Path(publication.relative_path).name
        if path.exists():
            require(path.read_bytes() == publication.raw_bytes, "Synthetic transport copy conflicts")
        else:
            with path.open("xb") as stream:
                stream.write(publication.raw_bytes)


def attach_outcomes(recorder, case: Path) -> list[dict[str, object]]:
    from momentum_hunter.strategy_science_recorder.contract import HORIZONS
    from tests import test_strategy_science_recorder_contract as fixture
    from tests.test_strategy_science_recorder_coverage import RecorderCoverageTests

    # Canonical fixture computes exact custody/eligibility/decision/bar links,
    # not a second outcome format or symbol-only join.
    custody = recorder.custody_root
    original = {path.relative_to(custody).as_posix(): sha(raw)
                for family in ("decision-event", "reference-plan", "candidate-observation")
                for path, _value, raw in fixture.stored_records(custody, family)}
    decisions = fixture.stored_records(custody, "decision-event")
    require(len(decisions) == 1, "This bounded fixture requires one exact decision")
    # The larger fixture has several instruments. Bind the decision's exact
    # eligibility, never the first lexicographic eligibility file.
    context = SimpleNamespace(root=custody,
        eligibility_sha=decisions[0][1]["science_eligibility_commitment_sha256"])
    previous, results = "0" * 64, []
    for sequence, horizon in enumerate(HORIZONS, 1):
        payload = RecorderCoverageTests.outcome_payload(context, semantic=horizon,
            outcome_id=fixture.identity("OUTCOME_OBSERVATION_ID", f"continuous-synthetic-{horizon}"),
            present_value=horizon == "PLUS_5M", nonpresent_state="UNAVAILABLE")
        raw = fixture.outcome_attachment(payload, event_id=f"continuous-synthetic-{horizon}",
            sequence=sequence, previous=previous, observed_at="2026-09-01T20:31:00Z")
        result = recorder.append_outcome(raw)
        require(result["status"] in {"ACCEPTED", "ADMITTED"}, "Synthetic outcome not admitted")
        with (case / f"outcome-{sequence}.json").open("xb") as stream:
            stream.write(raw)
        results.append({"horizon": horizon, "state": payload["outcome_state"], "sha256": sha(raw), "result": result})
        previous = sha(raw)
    require(all(sha((custody / name).read_bytes()) == expected for name, expected in original.items()),
            "Later outcome changed prediction custody")
    write_json(case / "prediction-byte-invariance.json", {"beforeAndAfter": original, "unchanged": True})
    return results



def opened(case):
    return ContinuousScienceRecorder(case/'delivery/published', case/'science',
        source_root_identity=fixture.SOURCE_ROOT_IDENTITY, writer_instance_id='science004-synthetic',
        clock=utc, lateness_seconds=60)


def build(case, target):
    require(target >= 13, 'Minimum all-seven-family fixture is13 scientific records')
    cycles, remainder = divmod(target-13, 6)
    publications, _ = publish_fixture(case, ResearchFactExporterV2, additional_cycles=cycles)
    if remainder:
        from momentum_hunter.strategy_science_recorder.contract import (
            REPAIRED_EXPORT_SCHEMA_VERSION, REPAIRED_SOURCE_CONTRACT,
            REPAIRED_SOURCE_CONTRACT_VERSION, SCIENCE_OFFLINE_EXPORT_PROFILE_V2)
        writer = ResearchFactExporterV2(case/'producer', session_id=fixture.SESSION_ID,
            source_owner_identity='fixture-owner', source_interface_identity='synthetic-continuous-v2-owner',
            source_root_identity=fixture.SOURCE_ROOT_IDENTITY, schema_version=REPAIRED_EXPORT_SCHEMA_VERSION,
            source_contract=REPAIRED_SOURCE_CONTRACT, source_contract_version=REPAIRED_SOURCE_CONTRACT_VERSION,
            offline_reference_profile=SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
            science_custody_roots=(case/'science',), protected_roots=(ROOT,)).initialize()
        try:
            cycle = fixture.identity('DISCOVERY_CYCLE_ID', f'science004-tail-cycle-{target}')
            rows = []
            for ordinal in range(remainder-1):
                row = fixture.observation(fixture.identity('OBSERVATION_ID', f'science004-tail-{target}-{ordinal}'),
                    ordinal=ordinal, symbol=f'SYN{ordinal}')
                row['discovery_cycle_id'] = cycle
                rows.append(row)
            payload = fixture.discovery_payload(rows)
            payload['discovery_cycle']['discovery_cycle_id'] = cycle
            writer.discovery_cycle(payload['discovery_cycle'], rows, stream_id='discovery-stream',
                source_event_id=f'science004-tail-cycle-{target}', emitted_at=fixture.DISCOVERY_TIME)
            publications = writer.published()
        finally:
            writer.close()
    return publications


def immutable_science(case):
    return {name: row for name, row in inventory(case/'science').items()
        if name.endswith(('.source.json','.payload.json','.receipt.json','.checkpoint.json','.reader-cursor.json','.event.json'))}


def counters(recorder):
    return {'support': dict(recorder._support.counters), 'custody': dict(recorder.recorder._views.counters),
        'custody_reads': dict(recorder.recorder._views.reads.counters),
        'ledger_reads': dict(recorder._ledger_reads.counters),
        'coverage_record_visits': recorder._support.coverage.record_visits,
        'coverage_dependency_visits': recorder._support.coverage.dependency_visits}


def scalar_summary(recorder):
    return recorder._support.summary(FAMILIES)


def restart(args):
    case = args.reload.resolve(strict=True)
    require(case.is_relative_to(args.evidence.resolve(strict=True)/'runtime'), 'Reload outside task synthetic root')
    before = immutable_science(case)
    tick = time.perf_counter()
    with opened(case) as recorder:
        constructor = time.perf_counter()-tick
        before_counts = counters(recorder)
        tick = time.perf_counter()
        result = recorder.poll(max_items=10000)
        empty = time.perf_counter()-tick
        after_counts = counters(recorder)
        require(result['admitted'] == result['observed'] == 0, 'Restart duplicated observations')
        require(before_counts['custody']['namespace_audits'] == after_counts['custody']['namespace_audits'], 'Restart leaked audit into normal poll')
        require(before_counts['support']['producer_full_inventories'] == after_counts['support']['producer_full_inventories'], 'Restart leaked producer scan into normal poll')
        full = recorder.coverage()
        mem = memory()
    after = immutable_science(case)
    require(all(after.get(name) == row for name, row in before.items()), 'Restart mutated prior immutable custody')
    additions = sorted(set(after)-set(before))
    require(all(name.endswith('.event.json') and json.loads((case/'science'/name).read_bytes())['type'] == 'RESTART'
        for name in additions), 'Clean restart created unexpected scientific/cursor evidence')
    return {'status': 'PASS', 'pid': os.getpid(), 'constructor_seconds': constructor, 'empty_poll_seconds': empty,
        'restart_recovery_seconds': constructor+empty, 'family_counts': full['family_counts'], 'canonical': full['canonical'],
        'immutable_custody_unchanged': True, 'appended_restart_receipts': additions,
        'counters_before': before_counts, 'counters_after': after_counts, 'memory': mem}


def restart_child(case, args):
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--evidence', str(args.evidence),
        '--reload', str(case)]
    # This watchdog diagnoses an abandoned subprocess; it is not an acceptance latency target.
    child = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=7200)
    write_json(case/'restart-invocation.json', {'command': command, 'exit_code': child.returncode,
        'stdout': child.stdout, 'stderr': child.stderr, 'watchdog_role': 'INFRASTRUCTURE_ONLY_NOT_PERFORMANCE_GATE'})
    require(child.returncode == 0, 'Fresh-process restart failed: '+child.stderr)
    result = json.loads((case/'restart-result.json').read_bytes())
    require(result['pid'] != os.getpid(), 'Restart must be a distinct process')
    return result


def measure(case, args):
    tick = time.perf_counter()
    publications = build(case, args.records)
    fixture_seconds = time.perf_counter()-tick
    producer = inventory(case/'producer')
    (case/'delivery/published').mkdir(parents=True)
    write_json(case/'fixture-plan.json', {'classification': 'SYNTHETIC_OFFLINE_NOT_MARKET_CAPTURE',
        'requested_scientific_records': args.records, 'publications': len(publications),
        'five_observations_per_repeated_cycle': True, 'separate_outcomes': 7,
        'producer_fixture_generation_seconds_excluded_from_recorder_ingest': fixture_seconds,
        'receipt_clock': 'ACTUAL_UTC', 'event_clock': 'EXPLICIT_SYNTHETIC_2026_09_01',
        'numeric_performance_gate': None})
    steps = []
    total = 0.0
    with opened(case) as recorder:
        normal_before = counters(recorder)
        for ordinal, pub in enumerate(publications):
            deliver(publications, case/'delivery/published', [ordinal])
            tick = time.perf_counter()
            result = recorder.poll(max_items=1)
            seconds = time.perf_counter()-tick
            require(result['admitted'] == result['observed'] == 1, 'Incomplete normal publication')
            total += seconds
            step = {'ordinal': ordinal+1, 'seconds': seconds,
                'scientific_records': sum(result['coverage']['family_counts'].values())}
            steps.append(step)
            if (ordinal+1) % 25 == 0:
                print(json.dumps(step), flush=True)
        tick = time.perf_counter()
        outcomes = attach_outcomes(recorder, case)
        outcome_seconds = time.perf_counter()-tick
        total += outcome_seconds
        normal_after = counters(recorder)
        require(normal_before['custody']['namespace_audits'] == normal_after['custody']['namespace_audits'], 'Normal namespace full audit')
        require(normal_before['support']['producer_full_inventories'] == normal_after['support']['producer_full_inventories'], 'Normal producer full inventory')
        tick = time.perf_counter()
        for _ in range(100):
            fast = scalar_summary(recorder)
        update_seconds = (time.perf_counter()-tick)/100
        require(sum(fast['family_counts'].values()) == args.records, 'Requested checkpoint count mismatch')
        tick = time.perf_counter()
        full = recorder.coverage()
        audit_seconds = time.perf_counter()-tick
        require(fast['canonical'] == full['canonical'], 'Incremental coverage differs from raw full audit')
        require(all(full['family_counts'].values()), 'All seven families required')
        require(not any(full[k] for k in ('pending_count','conflicts','invalid_count','rejected_count')), 'Unresolved normal fixture')
        mem = memory()
        write_json(case/'coverage.json', full)
        write_json(case/'normal-steps.json', steps)
    require(producer == inventory(case/'producer'), 'Recorder mutated producer fixture')
    saved = inventory(case/'science')
    total_bytes = sum(row['bytes'] for row in saved.values())
    write_json(case/'science-inventory.json', saved)
    write_json(case/'producer-inventory-before-after.json', {'unchanged': True, 'inventory': producer})
    child = restart_child(case, args)
    require(child['family_counts'] == full['family_counts'] and child['canonical'] == full['canonical'], 'Restart changed corpus')
    return {'status': 'PASS', 'record_count': args.records, 'total_ingest_seconds': total,
        'ingest_seconds_per_record': total/args.records, 'coverage_update_seconds': update_seconds,
        'explicit_full_audit_seconds': audit_seconds, 'restart_recovery_seconds': child['restart_recovery_seconds'],
        'total_storage_bytes': total_bytes, 'science_file_count': len(saved), 'memory': mem,
        'marginal_bytes_per_record': 'DERIVE_BETWEEN_COMPLETED_CHECKPOINTS', 'normal_before': normal_before,
        'normal_after': normal_after, 'fixture_generation_seconds': fixture_seconds,
        'separate_outcome_ingest_seconds': outcome_seconds, 'peak_handle_scope': 'observed near completion, not high-water counter',
        'raw_bytes_unchanged': True, 'full_history_rescan_per_normal_ingest': False,
        'restart': child, 'case': str(case), 'performance_gate': 'MECHANISM_AND_EMPIRICAL_TREND_NOT_ARBITRARY_LATENCY'}


def rehearsal(case, args):
    publications, producer_before = publish_fixture(case, ResearchFactExporterV2, windows=True)
    delivery = case/'delivery/published'
    deliver(publications, delivery, [0,2,3])
    with opened(case) as recorder:
        recorder.poll()
        pending = recorder.coverage()
        require(pending['pending_count'] >= 1, 'Temporary gaps missing')
        arrivals = recorder.arrivals()
        write_json(case/'coverage-with-gap.json', pending)
    with opened(case) as recorder:
        require(recorder.arrivals() == arrivals, 'Restart changed first arrivals')
        deliver(publications, delivery, [1,*range(4,len(publications))])
        recorder.poll()
        outcomes = attach_outcomes(recorder, case)
        require(recorder.poll()['admitted'] == 0, 'Duplicate scientific observations')
        # Add separately owner-authored synthetic REJECTED/NO_PLAN facts only
        # after the original plan's outcomes have been independently attached.
        # They remain new immutable decisions, never revisions of the first.
        from momentum_hunter.strategy_science_recorder.contract import (
            REPAIRED_EXPORT_SCHEMA_VERSION, REPAIRED_SOURCE_CONTRACT,
            REPAIRED_SOURCE_CONTRACT_VERSION, SCIENCE_OFFLINE_EXPORT_PROFILE_V2)
        from tests.test_strategy_science_recorder_eligibility_authority import decision_payload_v2
        writer = ResearchFactExporterV2(case/'producer', session_id=fixture.SESSION_ID,
            source_owner_identity='fixture-owner', source_interface_identity='synthetic-continuous-v2-owner',
            source_root_identity=fixture.SOURCE_ROOT_IDENTITY, schema_version=REPAIRED_EXPORT_SCHEMA_VERSION,
            source_contract=REPAIRED_SOURCE_CONTRACT, source_contract_version=REPAIRED_SOURCE_CONTRACT_VERSION,
            offline_reference_profile=SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
            science_custody_roots=(case/'science',), protected_roots=(ROOT,)).initialize()
        try:
            for state in ('REJECTED', 'NO_PLAN'):
                decision = decision_payload_v2()['decision_event']
                decision.update(decision_id=fixture.identity('DECISION_ID', 'synthetic-'+state),
                    decision_state=state, reason_codes=[{'code': 'SYNTHETIC_'+state, 'version': '1'}],
                    tradeplan_id=fixture.absent('NOT_APPLICABLE', 'NO_SYNTHETIC_PLAN'),
                    reference_plan_id=fixture.absent('NOT_APPLICABLE', 'NO_SYNTHETIC_PLAN'))
                writer.decision(decision, stream_id='decision-stream',
                    source_event_id='synthetic-'+state, emitted_at=fixture.DECISION_TIME)
            extended = writer.published()
        finally:
            writer.close()
        # The test producer intentionally appended these two facts. Recorder
        # nonmutation is measured against this fresh exact producer snapshot.
        producer_after_fixture_append = inventory(case/'producer')
        deliver(extended, delivery, list(range(len(publications), len(extended))))
        require(recorder.poll()['admitted'] == 2, 'Synthetic rejected/no-plan flow did not remain prospective facts')
        full = recorder.coverage()
        require(all(full['family_counts'].values()) and full['pending_count'] == 0, 'Incomplete seven-family rehearsal')
        windows = {}
        for label, begin, end in (('premarket','10:00:00','13:30:00'), ('opening','13:30:00','14:00:00'),
                ('morning','14:00:00','16:00:00'), ('midday','16:00:00','20:00:00'),
                ('close','20:00:00','20:01:00'), ('after-hours','20:01:00','21:00:00')):
            rows = recorder.query_window(f'2026-09-01T{begin}Z', f'2026-09-01T{end}Z', axis='event')
            require(bool(rows), 'Missing synthetic window: '+label)
            windows[label] = {'count': len(rows), 'begin': begin, 'end': end, 'boundary': 'EXPLICIT_UTC_HALF_OPEN_FIXTURE'}
        # Link every normalized V2 record to exact first raw custody and its
        # source event, producer owner/runtime and Science receipt. This is an
        # explicit audit export; its full traversal is outside normal ingest.
        trace = []
        source_paths = {sha(path.read_bytes()): path for path in recorder.custody_root.rglob('*.source.json')}
        payload_paths = {sha(path.read_bytes()): path for path in recorder.custody_root.rglob('*.payload.json')}
        normalized_by_source = {}
        for record in recorder.records():
            normalized_by_source.setdefault(record['source_envelope_sha256'], []).append(record)
        for arrival in recorder.arrivals():
            raw = recorder.raw_bytes(arrival['arrival_id'])
            require(sha(raw) == arrival['raw_sha256'], 'Trace raw hash mismatch')
            raw_path = source_paths[sha(raw)]
            for record in normalized_by_source[sha(raw)]:
                payload_hash = sha(canonical_record_bytes(record))
                trace.append({'V2_RECORD_ID': record['record_id'], 'V2_FAMILY': record['record_type'],
                    'PRODUCER_IDENTITY': arrival['metadata'], 'PRODUCER_EVENT_TIME': arrival['metadata']['event_time'],
                    'SCIENCE_RECEIPT_TIME': arrival['receipt_time'],
                    'RAW_CUSTODY_PATH': str(raw_path), 'RAW_CUSTODY_HASH': sha(raw),
                    'NORMALIZED_PAYLOAD_PATH': str(payload_paths[payload_hash]), 'NORMALIZED_PAYLOAD_SHA256': payload_hash,
                    'DERIVED_STATE_RESULT': 'ADMITTED_EXACT_RAW_AND_PAYLOAD_CUSTODY', 'ARRIVAL': arrival})
        write_json(case/'v2-science-traceability.json', trace)
        write_json(case/'coverage.json', full)
    require(all(producer_after_fixture_append.get(name) == row for name, row in producer_before.items()
        if name.startswith('published/')), 'Synthetic producer append rewrote prior publications')
    require(producer_after_fixture_append == inventory(case/'producer'), 'Rehearsal mutated final producer bytes')
    child = restart_child(case,args)
    require(child['family_counts'] == full['family_counts'], 'Fresh restart lost family')
    return {'status': 'PASS', 'classification': 'SYNTHETIC_CONTINUOUS_REHEARSAL_NOT_HISTORICAL_CAPTURE',
        'windows': windows, 'coverage': full, 'separate_outcomes': outcomes, 'restart': child,
        'traceability_rows': len(trace), 'source_bytes_unchanged': True, 'no_provider_contact': True,
        'runtime_activation': False, 'case': str(case)}


def canonical_record_bytes(record):
    from momentum_hunter.strategy_science_recorder.canonical import canonical_json_bytes
    return canonical_json_bytes(record)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--records', type=int)
    parser.add_argument('--rehearsal', action='store_true')
    parser.add_argument('--reload', type=Path)
    args = parser.parse_args()
    evidence = args.evidence.resolve(strict=True)
    require(evidence.name.startswith('ARGUS-SCIENCE-CONTINUOUS-RECORDER-FINAL-RECONCILIATION-004-'), 'Task evidence root mismatch')
    guard(evidence)
    identity = code_identity()
    require(identity['momentum_hunter/windows_writer_storage.py'] == 'e0b20e5fcd2c16c6abc52eaae08f3d9f38eb1d7843f6c54a0f6c0c15b374a86d', 'Actual canonical Writer005 mismatch')
    require(identity['momentum_hunter/research_fact_export_v2.py'] == 'a5712c9084f0aefe0d53bbac01645fcda7e735de8b9352c32116cb8425b95b81', 'Canonical V2 mismatch')
    if args.reload:
        result = restart(args)
        write_json(args.reload/'restart-result.json', result)
        return 0
    require(bool(args.records) != args.rehearsal, 'Choose exactly measurement or rehearsal')
    label = 'rehearsal' if args.rehearsal else str(args.records)
    case = evidence/'runtime'/('qual004-'+label+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    case.mkdir(parents=True)
    started = utc()
    write_json(case/'start.json', {'started_at': started, 'command': sys.argv, 'source_identity': identity})
    try:
        result = rehearsal(case,args) if args.rehearsal else measure(case,args)
        require(code_identity() == identity, 'Candidate changed during qualification')
        result.update(started_at=started, completed_at=utc(), source_identity=identity, candidate_unchanged=True)
        write_json(case/'result.json', result)
        print(json.dumps({'status': result['status'], 'receipt': str(case/'result.json')}), flush=True)
        return 0
    except BaseException:
        write_json(case/'failure.json', {'status': 'FAIL', 'started_at': started, 'completed_at': utc(),
            'traceback': traceback.format_exc(), 'source_identity_before': identity, 'source_identity_after': code_identity()})
        raise


if __name__ == '__main__':
    raise SystemExit(main())
