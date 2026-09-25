"""Sealed Science005/Scaling003 checks on disposable synthetic evidence.

The shared filesystem mailbox fixture SIMULATES owner/descriptor evidence.
These tests exercise real Windows namespace notifications and exact scientific
bytes, but do not establish native account separation, ACLs, or SCM authority.
"""

from collections import Counter
from contextlib import ExitStack, contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from momentum_hunter.science_custody_mailbox import ScienceCustodyMailboxClient
from momentum_hunter.science_custody_readonly import ScienceCustodyStorageSet
from momentum_hunter.strategy_science_recorder.canonical import canonical_json_bytes
from momentum_hunter.strategy_science_continuous_recorder import (
    ContinuousScienceRecorder, ContinuousRecorderError,
)
from momentum_hunter.strategy_science_source_reader import (
    StrategyScienceSourceReaderV2, SourceReaderCursorError,
)
from tests.test_science_custody_recorder_007 import (
    FilesystemProtocolFixture, core_fixtures, publication, TickingClock,
)
from tests.test_strategy_science_namespace_closure_005 import name_storm
from tests.test_strategy_science_recorder_contract import (
    SOURCE_ROOT_IDENTITY, discovery_payload, observation, identity, health_payload,
)
from tests.test_strategy_science_recorder_eligibility_authority import export_envelope_v2


# Source-derived bounds, not throughput tolerances. A new final requires two
# claim, four receipt/completion and two raw lookups. Its staged/final/receipted bytes are
# each verified once. A receipt/checksum verification adds one dependency claim,
# receipt, completion and exact final read: 4 extra reads per verification,
# three verifications on a new commit (8 + 3*4 = 20).
# A lookup verifies once (4 + 4 = 8). Dependencies are leaves: only the two edges
# below are allowed, and no dependency may introduce another dependency.
_DEPENDENCY_ROLE = {"SCIENTIFIC_RECEIPT": "PAYLOAD", "FINAL_CHECKSUM": "FINAL_MANIFEST"}
_BASE_READ_BOUNDS = {"finalize": {"trusted_reads": 8, "claims_reads": 2, "receipts_reads": 4},
                     "lookup": {"trusted_reads": 4, "claims_reads": 1, "receipts_reads": 2}}
_DEPENDENT_READ_BOUNDS = {
    "finalize": {"trusted_reads": 20, "claims_reads": 5, "receipts_reads": 10, "custody_reads": 5},
    "lookup": {"trusted_reads": 8, "claims_reads": 2, "receipts_reads": 4, "custody_reads": 2},
}


class _MeasuredFilesystemFixture(FilesystemProtocolFixture):
    """Count bounded work per operation; retain no per-poll history."""

    def __init__(self, root):
        self._measurement = threading.local()
        self._measurement_lock = threading.Lock()
        self.operation_counts = Counter()
        self.maximum = {}
        self.totals = Counter()
        self.verification_depths = Counter()
        self.verification_edges = Counter()
        super().__init__(root)
        self.worker.poll_once = self.measured("poll", self.worker.poll_once)
        self.finalizer.finalize = self.measured("finalize", self.finalizer.finalize, by_role=True)
        self.instrument_reader(self.finalizer)

    def instrument_reader(self, reader):
        reader.lookup = self.measured("lookup", reader.lookup, by_role=True)
        original = reader._verify_final

        def verify_dependency(request, final, **kwargs):
            roles = getattr(self._measurement, "verifying_roles", ())
            role = request.identity.artifact_role
            if roles and (len(roles) != 1 or _DEPENDENCY_ROLE.get(roles[0]) != role):
                raise AssertionError("Custody verification exceeded its one-level leaf dependency contract")
            top_role = roles[0] if roles else role
            with self._measurement_lock:
                self.verification_depths[top_role] = max(self.verification_depths[top_role], len(roles))
                if roles:
                    self.verification_edges[roles[0] + "->" + role] += 1
            self._measurement.verifying_roles = (*roles, role)
            try:
                return original(request, final, **kwargs)
            finally:
                self._measurement.verifying_roles = roles

        reader._verify_final = verify_dependency

    def measured(self, kind, operation, *, by_role=False):
        def counted(*args, **kwargs):
            scopes = getattr(self._measurement, "scopes", [])
            own = Counter()
            keys = [kind]
            if by_role:
                keys.append(kind + ":" + args[0].identity.artifact_role)
            self._measurement.scopes = [*scopes, own]
            try:
                return operation(*args, **kwargs)
            finally:
                self._measurement.scopes = scopes
                with self._measurement_lock:
                    for key in keys:
                        self.operation_counts[key] += 1
                        maximum = self.maximum.setdefault(key, Counter())
                        for name, count in own.items():
                            maximum[name] = max(maximum[name], count)
        return counted

    def counted(self, name, amount=1):
        for scope in getattr(self._measurement, "scopes", ()):
            scope[name] += amount
        with self._measurement_lock:
            self.totals[name] += amount

    def read_request(self, name, *, maximum):
        self.counted("request_reads")
        return super().read_request(name, maximum=maximum)

    def read_staged(self, name, *, maximum):
        self.counted("staging_reads")
        return super().read_staged(name, maximum=maximum)

    def read_trusted(self, namespace, relative, *, maximum):
        self.counted("trusted_reads")
        self.counted(namespace + "_reads")
        return super().read_trusted(namespace, relative, maximum=maximum)

    def bounded_names(self, namespace, limit):
        self.counted("namespace_probes")
        self.counted("namespace_probe_budget", limit)
        result = super().bounded_names(namespace, limit)
        self.counted("namespace_entries", len(result))
        if limit > 3 or len(result) > limit:
            raise AssertionError("Mailbox enumeration exceeded declared slot plus sentinel bounds")
        return result

    def snapshot(self):
        with self._measurement_lock:
            return {"operation_counts": dict(self.operation_counts),
                    "maximum": {name: dict(counts) for name, counts in self.maximum.items()},
                    "totals": dict(self.totals),
                    "verification_depths": dict(self.verification_depths),
                    "verification_edges": dict(self.verification_edges)}


@unittest.skipUnless(os.name == "nt", "Science005 namespace proof requires Windows")
class SealedScienceScaling007Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="S007-scaling-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.publication = self.root / "producer" / "published"
        self.publication.mkdir(parents=True)
        self.backend = _MeasuredFilesystemFixture(self.root)
        self.addCleanup(self.backend.close)
        self.clock = TickingClock()

    def storage_set(self):
        client = ScienceCustodyMailboxClient(policy_sha256=self.backend.policy_sha256,
            source_root_identity=SOURCE_ROOT_IDENTITY, mailbox_backend=self.backend)
        self.backend.instrument_reader(client._reader)
        return ScienceCustodyStorageSet(client, timeout_seconds=3, recovery_clock=self.clock)

    def opened(self):
        recorder = ContinuousScienceRecorder(self.publication, self.backend.science,
            source_root_identity=SOURCE_ROOT_IDENTITY, writer_instance_id="S007-scaling",
            clock=self.clock, custody_storage_set=self.storage_set())
        self.addCleanup(recorder.close)
        return recorder

    def started(self):
        publication(self.publication, core_fixtures()[0], 1)
        recorder = self.opened()
        self.assertEqual(1, recorder.poll(max_items=1)["admitted"])
        return recorder

    def health(self, ordinal):
        raw = export_envelope_v2("PROVIDER_HEALTH", health_payload(
            health_id=identity("PROVIDER_HEALTH_EVENT_ID", f"S007-{ordinal}")),
            stream_id=f"S007-health-{ordinal}", event_id=f"S007-health-{ordinal}")
        publication(self.publication, raw, ordinal)
        return raw

    @staticmethod
    def guards(recorder):
        return {"custody": recorder.recorder._views.changes,
                "arrivals": recorder._support.ledger_changes,
                "cursors": recorder.reader._cursor_changes}

    @contextmanager
    def forbid_normal_history(self, recorder):
        views = recorder.recorder._views
        with ExitStack() as stack:
            for target, name in (
                (views, "_inventory"), (views.reads, "audit_known"),
                (recorder._ledger_reads, "audit_known"), (recorder.recorder, "verify"),
                (recorder, "records"), (recorder._support, "_baseline_producer"),
                (StrategyScienceSourceReaderV2, "_load_state"),
            ):
                stack.enter_context(patch.object(target, name,
                    side_effect=AssertionError("Normal history scan: " + name)))
            original = self.backend.iter_trusted

            def bounded_history(alias, relative="", *, suffix):
                if (alias in ("claims", "receipts") or
                        (alias == "custody" and relative in ("", ".", "sessions")) or
                        (alias == "arrivals" and relative in ("", ".", "ledger")) or
                        (alias == "cursors" and relative in ("", "."))):
                    raise AssertionError("Normal whole-history backend enumeration")
                return original(alias, relative, suffix=suffix)

            stack.enter_context(patch.object(self.backend, "iter_trusted", side_effect=bounded_history))
            yield

    def immutable(self):
        result = {}
        for alias in ("arrivals", "custody", "cursors"):
            base = self.backend.roots[alias]
            for path in base.rglob("*"):
                if path.is_file() and (path.name.endswith(".json") or path.name.endswith(".sha256")):
                    result[(alias, path.relative_to(base).as_posix())] = path.read_bytes()
        return result

    def assert_old_bytes(self, before):
        for (alias, relative), raw in before.items():
            self.assertEqual(raw, (self.backend.roots[alias] / relative).read_bytes())

    def assert_role_work_bounds(self, sample):
        self.assertLessEqual(sample["maximum"]["poll"]["request_reads"], 1)
        self.assertLessEqual(sample["maximum"]["poll"]["namespace_probe_budget"], 5)
        self.assertLessEqual(sample["maximum"]["finalize"]["staging_reads"], 1)
        for name, measured in sample["maximum"].items():
            if ":" not in name:
                continue
            operation, role = name.split(":")
            bounds = (_DEPENDENT_READ_BOUNDS if role in _DEPENDENCY_ROLE else _BASE_READ_BOUNDS)[operation]
            for metric, bound in bounds.items():
                self.assertLessEqual(measured.get(metric, 0), bound, (operation, role, metric))
        for role, depth in sample["verification_depths"].items():
            self.assertLessEqual(depth, 1 if role in _DEPENDENCY_ROLE else 0, role)
        self.assertLessEqual(set(sample["verification_edges"]),
                             {role + "->" + leaf for role, leaf in _DEPENDENCY_ROLE.items()})

    def test_1_10_100_normal_publications_use_bounded_direct_commit_work(self):
        recorder = self.started()
        audits = recorder.recorder._views.counters["namespace_audits"]
        producer_inventories = recorder._support.counters["producer_full_inventories"]
        milestones = {}
        with self.forbid_normal_history(recorder):
            for ordinal in range(2, 102):
                self.health(ordinal)
                result = recorder.poll(max_items=1)
                self.assertEqual(1, result["admitted"])
                self.assertEqual(0, recorder.poll(max_items=1)["admitted"])
                if ordinal - 1 in (1, 10, 100):
                    self.assertEqual(ordinal - 1,
                        result["coverage"]["family_counts"]["provider-health-event"])
                    milestones[ordinal - 1] = self.backend.snapshot()
        self.assertFalse(self.backend.errors, self.backend.errors)
        self.assertEqual(audits, recorder.recorder._views.counters["namespace_audits"])
        self.assertEqual(producer_inventories, recorder._support.counters["producer_full_inventories"])
        for sample in milestones.values():
            self.assert_role_work_bounds(sample)
            self.assertEqual(_DEPENDENT_READ_BOUNDS['finalize']['trusted_reads'],
                             sample["maximum"]["finalize:SCIENTIFIC_RECEIPT"]["trusted_reads"])
            self.assertEqual(_DEPENDENT_READ_BOUNDS['lookup']['trusted_reads'],
                             sample["maximum"]["lookup:SCIENTIFIC_RECEIPT"]["trusted_reads"])
            self.assertEqual(1, sample["verification_depths"]["SCIENTIFIC_RECEIPT"])
        self.assertEqual(result["coverage"]["canonical"], recorder.coverage()["canonical"])
        print("SCIENCE007_BOUNDED_WORK=" + json.dumps(milestones, sort_keys=True))

    def test_checksum_uses_one_manifest_dependency_without_history_enumeration(self):
        # A bounded protocol fixture, not a scientific FINAL admission. The
        # manifest inventory is explicit input; checksum work may scale with
        # those supplied bytes, but never discovers historical filesystem data.
        storage = self.storage_set()
        session = "sessions/2026-09-15/s-" + hashlib.sha256(b"logical-session").hexdigest()
        manifest_path = f"{session}/manifests/{'e' * 64}.final.json"
        manifest_raw = canonical_json_bytes({"session_id": {"recorder_id": "logical-session"},
                                             "artifact_inventory": []})
        checksum_path = manifest_path.removesuffix(".final.json") + ".sha256"
        checksum_raw = (hashlib.sha256(manifest_raw).hexdigest() + "  " + manifest_path + "\n").encode("ascii")
        with patch.object(self.backend, "iter_trusted", side_effect=AssertionError("Dependency history scan")):
            for path, raw in ((manifest_path, manifest_raw), (checksum_path, checksum_raw)):
                storage.publish("custody", path, raw)
                storage.publication_verified("custody", path, raw)
        sample = self.backend.snapshot()
        self.assert_role_work_bounds(sample)
        self.assertEqual(_DEPENDENT_READ_BOUNDS['finalize']['trusted_reads'],
                         sample["maximum"]["finalize:FINAL_CHECKSUM"]["trusted_reads"])
        self.assertEqual(_DEPENDENT_READ_BOUNDS['lookup']['trusted_reads'],
                         sample["maximum"]["lookup:FINAL_CHECKSUM"]["trusted_reads"])
        self.assertEqual(1, sample["verification_depths"]["FINAL_CHECKSUM"])
        self.assertEqual(0, sample["verification_depths"]["FINAL_MANIFEST"])
        self.assertFalse(self.backend.errors, self.backend.errors)
        print("SCIENCE007_CHECKSUM_DEPENDENCY=" + json.dumps(sample, sort_keys=True))

    def test_large_fanout_registers_and_drains_each_singleton_before_next_final(self):
        recorder = self.started()
        rows = [observation(identity("OBSERVATION_ID", f"S007-fanout-{number}"),
                            ordinal=number, symbol=f"SYN{number}") for number in range(120)]
        raw = export_envelope_v2("DISCOVERY_CYCLE", discovery_payload(rows),
            stream_id="S007-fanout", event_id="S007-fanout")
        publication(self.publication, raw, 2)
        guards = self.guards(recorder)
        drains = Counter()
        outstanding = []
        verified = Counter()
        create = self.backend.create_trusted
        storage = recorder.recorder._storage.storage_set
        acknowledge = storage.publication_verified

        def created(alias, relative, data):
            if alias in guards:
                self.assertFalse(outstanding, "Next final preceded prior singleton registration/drain")
            result = create(alias, relative, data)
            if alias in guards:
                self.assertTrue(result[0], "Fan-out unexpectedly reused an existing final")
                outstanding.append((alias, relative, drains[alias]))
            return result

        def acknowledged(alias, relative, data):
            alias_before, path_before, drains_before = outstanding[0]
            self.assertEqual((alias_before, path_before), (alias, Path(relative).as_posix()))
            self.assertGreater(drains[alias], drains_before)
            path = self.backend.roots[alias] / relative
            known = {"custody": recorder.recorder._views.namespace,
                     "arrivals": recorder._support.ledger_names,
                     "cursors": recorder.reader._cursor_paths}[alias]
            self.assertIn(path, known)
            self.assertEqual(data, path.read_bytes())
            result = acknowledge(alias, relative, data)
            outstanding.clear()
            verified[alias] += 1
            return result

        with ExitStack() as stack:
            for alias, guard in guards.items():
                original = guard.drain

                def drained(original=original, alias=alias):
                    result = original()
                    drains[alias] += 1
                    return result

                stack.enter_context(patch.object(guard, "drain", side_effect=drained))
            stack.enter_context(patch.object(self.backend, "create_trusted", side_effect=created))
            stack.enter_context(patch.object(storage, "publication_verified", side_effect=acknowledged))
            stack.enter_context(self.forbid_normal_history(recorder))
            result = recorder.poll(max_items=1)
        self.assertEqual(1, result["admitted"])
        self.assertEqual(120, result["coverage"]["canonical"]["candidate_observations"])
        self.assertGreater(verified["custody"], 240)
        self.assertGreater(verified["arrivals"], 0)
        self.assertEqual(1, verified["cursors"])
        self.assertFalse(outstanding)
        self.assertFalse(self.backend.errors, self.backend.errors)

    def test_sealed_and_legacy_ingress_preserve_exact_semantic_bytes(self):
        baseline_root = self.root / "legacy-science"
        baseline = ContinuousScienceRecorder(self.publication, baseline_root,
            source_root_identity=SOURCE_ROOT_IDENTITY, writer_instance_id="S007-scaling",
            clock=TickingClock())
        self.addCleanup(baseline.close)
        sealed = self.opened()
        for ordinal, raw in enumerate(core_fixtures(), 1):
            publication(self.publication, raw, ordinal)
            old = baseline.poll(max_items=1)
            new = sealed.poll(max_items=1)
            self.assertEqual(old["coverage"]["canonical"], new["coverage"]["canonical"])
        baseline_aliases = {"arrivals": baseline_root / "arrivals",
                           "custody": baseline_root / "custody",
                           "cursors": baseline_root / "reader" / "cursors"}
        before = self.immutable()
        self.assertTrue(before)
        for (alias, relative), raw in before.items():
            self.assertEqual(raw, (baseline_aliases[alias] / relative).read_bytes(), (alias, relative))
        self.assertEqual(tuple(core_fixtures()), tuple(sealed.raw_bytes(item["arrival_id"])
                                                      for item in sealed.arrivals()))
        sealed.close()
        reopened = self.opened()
        self.assertEqual(0, reopened.poll()["admitted"])
        self.assert_old_bytes(before)

    def test_unknown_transient_names_preserve_baseline_audited_recovery(self):
        recorder = self.started()
        before = self.immutable()
        for alias in ("custody", "arrivals", "cursors"):
            with self.subTest(alias=alias):
                path = self.guards(recorder)[alias].root / "unowned-transient.json"
                path.write_bytes(b"{}")
                path.unlink()
                with self.assertRaises((ContinuousRecorderError, SourceReaderCursorError)):
                    recorder.poll()
                if alias == "cursors":
                    # Delivered cursor names are not native notification loss.
                    # Canonical behavior rejects this call, then performs a full
                    # audited recovery if the harmless transient has disappeared.
                    self.assertFalse(recorder.reader._cursor_changes.failed)
                    self.assertTrue(recorder._support.needs_recovery)
                    recoveries = recorder._support.counters["recovery_operations"]
                    self.assertEqual(0, recorder.poll()["admitted"])
                    self.assertEqual(recoveries + 1,
                                     recorder._support.counters["recovery_operations"])
                    self.assertFalse(recorder._support.needs_recovery)
                    self.assert_old_bytes(before)
                else:
                    with self.assertRaises(ContinuousRecorderError):
                        recorder.poll()
                recorder.close()
                recorder = self.opened()
                self.assertEqual(0, recorder.poll()["admitted"])
                self.assert_old_bytes(before)

    def test_real_ledger_overflow_preserves_committed_raw_and_requires_reopen(self):
        recorder = self.started()
        self.health(2)
        callback = recorder._support.ledger_published

        def overflow(path):
            name_storm(recorder._support.ledger_changes.root)
            return callback(path)

        with patch.object(recorder._support, "ledger_published", side_effect=overflow):
            with self.assertRaises(ContinuousRecorderError):
                recorder.poll(max_items=1)
        self.assertTrue(recorder._support.ledger_changes.failed)
        self.assertFalse(recorder._rejected)
        with self.assertRaisesRegex(ContinuousRecorderError, "close/reopen"):
            recorder.poll()
        before = self.immutable()
        recorder.close()
        reopened = self.opened()
        result = reopened.poll()
        self.assertEqual(2, result["coverage"]["admitted_arrival_count"])
        self.assertEqual(1, result["coverage"]["family_counts"]["provider-health-event"])
        self.assertEqual(0, reopened.poll()["admitted"])
        self.assert_old_bytes(before)
        self.assertFalse(self.backend.errors, self.backend.errors)

    def test_separate_mutable_staging_churn_does_not_consume_raw_namespace_buffers(self):
        recorder = self.started()
        before = self.immutable()
        # This is another explicit disposable mutable root, not active mailbox
        # staging: unknown entries in the real mailbox must still be rejected.
        churn = self.root / "separate-mutable-staging"
        churn.mkdir()
        name_storm(churn)
        self.assertEqual(0, recorder.poll()["admitted"])
        for guard in self.guards(recorder).values():
            self.assertFalse(guard.failed)
            self.assertEqual(65536, ctypes.sizeof(guard.buffer))
        self.assert_old_bytes(before)


if __name__ == "__main__":
    unittest.main()
