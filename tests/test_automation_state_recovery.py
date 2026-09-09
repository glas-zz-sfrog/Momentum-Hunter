from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter.automation_state_recovery import (
    DurableStateStorage, StateRecoveryError, decode, digest, encoded, RETAINED_GENERATIONS,
    prepare_quarantined_epoch,
)
from momentum_hunter.automation_supervisor import (
    AutomationJob, AutomationManifest, AutomationSupervisor, AutomationSupervisorError,
    JobReceipt, SupervisorState, SupervisorStateStore,
)

CT = timezone(timedelta(hours=-5))
NOW = datetime(2026, 9, 9, 8, 35, tzinfo=CT)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "state" / "automation-service-state.json"
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def state(self, status="PENDING", kind="opening_capture", job_id="opening-capture-20260909"):
        receipt = JobReceipt(job_id=job_id, kind=kind, status=status,
            scheduled_at=NOW.isoformat(), latest_start_at=(NOW + timedelta(minutes=5)).isoformat(),
            observed_at=NOW.isoformat(), completed_at=NOW.isoformat() if status == "COMPLETED" else "",
            exit_code=0 if status == "COMPLETED" else None)
        return SupervisorState(service_started_at=NOW.isoformat(), last_heartbeat_at=NOW.isoformat(), jobs={job_id: receipt})

    def store(self):
        return SupervisorStateStore(self.path)

    def corrupt(self, raw=b"\0" * 36072):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(raw)

    def test_01_exact_zero_02_empty_03_malformed_04_truncation_fail_custodied(self):
        for raw, code in [(b"\0" * 36072, "ALL_ZERO_STATE"), (b"", "ZERO_LENGTH_STATE"),
                          (b"not json", "MALFORMED_OR_TRUNCATED_JSON"),
                          (b'{"schema_version":1,"jobs":{', "MALFORMED_OR_TRUNCATED_JSON")]:
            with self.subTest(code=code):
                self.corrupt(raw)
                with self.assertRaisesRegex(AutomationSupervisorError, "NONE_ADMISSIBLE:" + code):
                    self.store().load(started_at=NOW, custody=True)
                custody = self.path.with_name(self.path.name + ".recovery") / "corrupt" / (digest(raw) + ".bin")
                self.assertEqual(raw, custody.read_bytes())
                self.assertEqual(raw, self.path.read_bytes())

    def test_05_missing_existing_state_fails_closed(self):
        self.path.parent.mkdir()
        with self.assertRaisesRegex(AutomationSupervisorError, "NONE_ADMISSIBLE:MISSING_STATE"):
            self.store().load(started_at=NOW, custody=True)

    def test_06_corrupt_current_latest_generation_reconciled(self):
        self.store().save(self.state("COMPLETED"))
        self.corrupt()
        store = self.store()
        recovered = store.load(started_at=NOW, custody=True)
        self.assertEqual("COMPLETED", next(iter(recovered.jobs.values())).status)
        store.save(recovered)
        self.assertEqual("COMPLETED", next(iter(decode(self.path.read_bytes())["jobs"].values()))["status"])

    def test_07_opening_08_continuous_stale_checkpoint_preserves_later_completion(self):
        # Storage-level continuous receipt proof only: no Continuous executor is added.
        for kind in ("opening_capture", "continuous_research"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                path = Path(d) / "state.json"
                storage = SupervisorStateStore(path)
                state = self.state(kind=kind, job_id=kind)
                storage.save(state)
                stale = path.read_bytes()
                state.jobs[kind].status = "COMPLETED"
                state.jobs[kind].completed_at = NOW.isoformat()
                state.jobs[kind].exit_code = 0
                storage.save(state)
                newest = sorted(storage.storage.generations.glob("*.json"))[-1]
                newest.write_bytes(b"\0")
                path.write_bytes(stale)
                recovered = SupervisorStateStore(path).load(started_at=NOW, custody=True)
                self.assertEqual("COMPLETED", recovered.jobs[kind].status)
                self.assertEqual(0, recovered.jobs[kind].exit_code)

    def test_09_10_11_failed_write_flush_sync_leave_current(self):
        for target in ("durable_new", "os.fsync"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as d:
                path = Path(d) / "state.json"
                store = SupervisorStateStore(path)
                state = self.state()
                store.save(state)
                before = path.read_bytes()
                with patch("momentum_hunter.automation_state_recovery." + target, side_effect=OSError("injected")):
                    with self.assertRaises(OSError):
                        store.save(state)
                self.assertEqual(before, path.read_bytes())
                self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_11_after_flush_before_retain_leaves_prior_good(self):
        store = self.store()
        state = self.state()
        store.save(state)
        before = self.path.read_bytes()
        with patch.object(store.storage, "_retain", side_effect=OSError("after flush")):
            with self.assertRaises(OSError):
                store.save(state)
        self.assertEqual(before, self.path.read_bytes())

    def test_09_partial_temporary_write_and_10_before_flush(self):
        for partial in (True, False):
            with self.subTest(partial=partial):
                store = self.store()
                state = self.state()
                store.save(state)
                before = self.path.read_bytes()
                def faulty_new(path, raw):
                    with path.open("xb") as stream:
                        stream.write(raw[:len(raw)//2] if partial else raw)
                        raise OSError("during write" if partial else "before explicit flush")
                with patch("momentum_hunter.automation_state_recovery.durable_new", side_effect=faulty_new):
                    with self.assertRaises(OSError):
                        store.save(state)
                self.assertEqual(before, self.path.read_bytes())
                self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_fsync_precedes_claim_generation_and_current_promotion(self):
        store = self.store()
        stages = []
        from momentum_hunter import automation_state_recovery as module
        real_sync, real_replace = module.os.fsync, store.storage.replace
        def sync(fd):
            stages.append("sync")
            return real_sync(fd)
        def replace(source, destination):
            stages.append("promote")
            self.assertGreaterEqual(stages.count("sync"), 3)
            return real_replace(source, destination)
        with patch.object(module.os, "fsync", side_effect=sync), patch.object(store.storage, "replace", side_effect=replace):
            store.save(self.state("RUNNING"))
        self.assertEqual("promote", stages[-1])

    def test_12_failed_replace_preserves_terminal_claim(self):
        store = self.store()
        state = self.state()
        store.save(state)
        old = self.path.read_bytes()
        state.jobs["opening-capture-20260909"].status = "COMPLETED"
        state.jobs["opening-capture-20260909"].completed_at = NOW.isoformat()
        state.jobs["opening-capture-20260909"].exit_code = 0
        with patch.object(store.storage, "replace", side_effect=OSError("replace")):
            with self.assertRaises(OSError):
                store.save(state)
        self.assertEqual(old, self.path.read_bytes())
        recovered = self.store().load(started_at=NOW, custody=True)
        self.assertEqual("COMPLETED", recovered.jobs["opening-capture-20260909"].status)

    def supervisor(self, now=NOW):
        job = AutomationJob("opening-capture-20260909", "opening_capture", NOW, NOW + timedelta(minutes=5))
        manifest = AutomationManifest(self.root, self.root / "python", self.root / "powershell", None,
            self.path.parent, self.root / "engine", 1, (job,))
        return AutomationSupervisor(manifest, clock=lambda: now, engine_host_probe=lambda: {},
            job_executor=lambda j, p: (self.calls.append(j.job_id) or 0, "synthetic executor"))

    def test_13_restart_completed_opening_never_reexecutes(self):
        self.supervisor().tick()
        self.supervisor().tick()
        self.assertEqual(1, len(self.calls))

    def test_f1_base_format_terminal_roundtrip_preserves_unbound_and_future_job(self):
        legacy = asdict(self.state("COMPLETED", job_id="opening-capture-20260908"))
        legacy.pop("state_version")
        legacy.pop("recovery_floor_at")
        receipt = legacy["jobs"]["opening-capture-20260908"]
        receipt.pop("job_definition_sha256")
        for name in ("scheduled_at", "latest_start_at", "observed_at", "completed_at"):
            receipt[name] = (datetime.fromisoformat(receipt[name]) - timedelta(days=1)).isoformat()
        self.corrupt(encoded(legacy))
        store = self.store()
        state = store.load(started_at=NOW)
        self.assertEqual("", state.jobs["opening-capture-20260908"].job_definition_sha256)
        store.save(state)
        self.corrupt()
        store = self.store()
        state = store.load(started_at=NOW - timedelta(seconds=1), custody=True)
        store.save(state)
        self.supervisor().tick()
        result = self.supervisor().tick()
        self.assertEqual(1, len(self.calls))
        saved = asdict(result.jobs["opening-capture-20260908"])
        self.assertEqual(receipt, {k: v for k, v in saved.items() if k != "job_definition_sha256"})
        self.assertEqual("", saved["job_definition_sha256"])
        result.jobs["opening-capture-20260908"].job_definition_sha256 = "a" * 64
        with self.assertRaisesRegex(AutomationSupervisorError, "TERMINAL_HISTORY_REWRITE"):
            self.store().save(result)

    def test_f2_obsolete_corrupt_backup_does_not_quarantine_intact_current(self):
        for offset in (0, 180, 300):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as d:
                self.path = Path(d) / "state" / "automation-service-state.json"
                self.calls = []
                store = self.store()
                state = self.state()
                store.save(state)
                store.save(state)
                oldest = sorted(store.storage.generations.glob("*.json"))[0]
                oldest.write_bytes(b"obsolete checkpoint damage")
                loaded = self.store().load(started_at=NOW + timedelta(seconds=offset), custody=True)
                self.assertEqual("", loaded.recovery_floor_at)
                result = self.supervisor(NOW + timedelta(seconds=offset)).tick()
                self.supervisor(NOW + timedelta(seconds=offset)).tick()
                self.assertEqual("COMPLETED", result.jobs["opening-capture-20260909"].status)
                self.assertEqual(1, len(self.calls))

    def test_14_restart_incomplete_never_reexecutes(self):
        self.store().save(self.state("RUNNING"))
        result = self.supervisor().tick()
        self.assertFalse(self.calls)
        self.assertEqual("FAILED", result.jobs["opening-capture-20260909"].status)

    def test_15_multiple_bounded_generations(self):
        store = self.store()
        state = self.state()
        for _ in range(20):
            store.save(state)
        self.assertEqual(RETAINED_GENERATIONS, len(list(store.storage.generations.glob("*.json"))))
        self.assertEqual(20, decode(self.path.read_bytes())["state_version"])

    def test_16_newest_bad_17_all_bad_fail_closed(self):
        store = self.store()
        store.save(self.state())
        store.save(self.state())
        latest = sorted(store.storage.generations.glob("*.json"))[-1]
        latest.write_bytes(b"bad")
        self.corrupt()
        result = self.store().load(started_at=NOW, custody=True)
        self.assertEqual(NOW.isoformat(), result.recovery_floor_at)
        for path in store.storage.generations.glob("*.json"):
            path.write_bytes(b"bad")
        with self.assertRaisesRegex(AutomationSupervisorError, "NONE_ADMISSIBLE"):
            self.store().load(started_at=NOW, custody=True)

    def test_18_schema_job_identity_mismatch(self):
        for change in (lambda p: p.update(schema_version=2),
                       lambda p: p["jobs"]["opening-capture-20260909"].update(job_id="other"),
                       lambda p: p["jobs"]["opening-capture-20260909"].update(exit_code=False)):
            value = asdict(self.state("COMPLETED"))
            change(value)
            with self.assertRaises(StateRecoveryError):
                decode(encoded(value))

    def test_unknown_past_is_quarantined_not_fabricated(self):
        store = self.store()
        store.save(self.state())
        self.corrupt()
        result = self.supervisor().tick()
        self.assertFalse(self.calls)
        self.assertEqual("PENDING", result.jobs["opening-capture-20260909"].status)
        self.assertEqual(NOW.isoformat(), result.recovery_floor_at)

    def test_changed_schedule_reusing_completed_job_id_fails(self):
        state = self.state("COMPLETED")
        state.jobs["opening-capture-20260909"].scheduled_at = (NOW - timedelta(days=1)).isoformat()
        self.store().save(state)
        with self.assertRaisesRegex(AutomationSupervisorError, "JOB_IDENTITY_MISMATCH"):
            self.supervisor().tick()
        self.assertFalse(self.calls)

    def test_two_loaded_writers_cannot_both_admit(self):
        one, two = self.supervisor(), self.supervisor()
        one.tick()
        with self.assertRaisesRegex(AutomationSupervisorError, "CONCURRENT_STATE_CHANGED"):
            two.tick()
        self.assertEqual(1, len(self.calls))

    def test_completed_receipt_cannot_be_deleted_or_rolled_back(self):
        store = self.store()
        store.save(self.state("COMPLETED"))
        with self.assertRaisesRegex(AutomationSupervisorError, "HISTORY"):
            store.save(self.state())
        with self.assertRaisesRegex(AutomationSupervisorError, "HISTORY"):
            store.save(SupervisorState())

    def test_sep09_schedule_boundaries(self):
        for offset, expected, calls in [(-1, "PENDING", 0), (0, "COMPLETED", 1),
                                       (180, "COMPLETED", 1), (300, "COMPLETED", 1),
                                       (301, "MISSED", 0)]:
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as d:
                self.path = Path(d) / "state" / "automation-service-state.json"
                self.calls = []
                state = self.supervisor(NOW + timedelta(seconds=offset)).tick()
                self.assertEqual(expected, state.jobs["opening-capture-20260909"].status)
                self.assertEqual(calls, len(self.calls))

    def test_restart_corruption_soak_no_duplicate_bounded_generations(self):
        for cycle in range(80):
            if cycle and cycle % 7 == 0:
                self.corrupt()
            state = self.supervisor().tick()
            self.assertEqual("COMPLETED", state.jobs["opening-capture-20260909"].status)
            self.assertTrue(any(self.path.read_bytes()))
            self.assertFalse(list(self.path.parent.glob("*.tmp")))
            self.assertLessEqual(len(list(self.store().storage.generations.glob("*.json"))), RETAINED_GENERATIONS)
        self.assertEqual(1, len(self.calls))

    def test_read_only_load_does_not_create_custody(self):
        self.corrupt()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaises(AutomationSupervisorError):
            self.store().load(started_at=NOW)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_prospective_proposal_keeps_past_unknown_allows_only_future(self):
        proposal = self.root / "proposal"
        floor = NOW - timedelta(days=1)
        boundary = prepare_quarantined_epoch(output=proposal, corrupt_bytes=bytes(36072),
            expected_corrupt_sha256=digest(bytes(36072)), manifest_sha256="a"*64, floor=floor)
        self.path = proposal / "state" / "automation-service-state.json"
        initial = decode(self.path.read_bytes())
        self.assertEqual({}, initial["jobs"])
        self.assertEqual("UNKNOWN", boundary["legacyHistory"])
        self.assertFalse(boundary["productionAdopted"])
        self.supervisor().tick()
        self.supervisor().tick()
        self.assertEqual(1, len(self.calls))
        # Even a newly introduced, backdated identity remains quarantined.
        supervisor = self.supervisor()
        job = AutomationJob("unknown-past", "opening_capture", floor, floor + timedelta(minutes=5))
        supervisor._evaluate_job(job, NOW)
        self.assertNotIn("unknown-past", supervisor.state.jobs)
        self.assertEqual(1, len(self.calls))

    def test_proposal_never_overwrites_or_accepts_wrong_corrupt_identity(self):
        with self.assertRaisesRegex(StateRecoveryError, "CORRUPT_SOURCE_HASH_MISMATCH"):
            prepare_quarantined_epoch(output=self.root / "proposal", corrupt_bytes=bytes(36072),
                expected_corrupt_sha256="a"*64, manifest_sha256="b"*64, floor=NOW)
        self.assertFalse((self.root / "proposal").exists())
        with self.assertRaises(FileExistsError):
            prepare_quarantined_epoch(output=self.root, corrupt_bytes=bytes(36072),
                expected_corrupt_sha256=digest(bytes(36072)), manifest_sha256="b"*64, floor=NOW)

    def test_anchor_detects_missing_admitted_terminal_claim(self):
        store = self.store()
        store.save(self.state())
        store.save(self.state("COMPLETED"))
        for path in store.storage.claims.glob("*.json"):
            path.unlink()
        self.corrupt()
        with self.assertRaisesRegex(AutomationSupervisorError, "ADMITTED_CLAIM_MISSING_OR_CORRUPT"):
            self.store().load(started_at=NOW, custody=True)

    def test_anchor_missing_or_corrupt_cannot_admit_stale_backup(self):
        store = self.store()
        store.save(self.state("COMPLETED"))
        anchor = store.storage.anchor
        raw = anchor.read_bytes()
        anchor.write_bytes(b"bad")
        with self.assertRaisesRegex(AutomationSupervisorError, "ADMISSION_ANCHOR_INVALID"):
            self.store().load(started_at=NOW, custody=True)
        anchor.unlink()
        with self.assertRaisesRegex(AutomationSupervisorError, "ADMISSION_ANCHOR_MISSING"):
            self.store().load(started_at=NOW, custody=True)


if __name__ == "__main__":
    unittest.main()
