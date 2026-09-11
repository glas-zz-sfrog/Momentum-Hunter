"""Run unchanged custody-owner assertions with verified reuse explicitly enabled.

These are synthetic offline tests, not a capture or a performance PASS. The
canonical default cold path remains independently covered by the normal suite.
"""
import os
from functools import wraps
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter.strategy_science_recorder.custody import StrategyScienceRecorder, RecorderCustodyError
from tests.test_strategy_science_recorder_contract import FixedClock, SOURCE_ROOT_IDENTITY, SESSION_ID
from tests.test_strategy_science_continuous_recorder import core_fixtures


class ScalingViewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='science-scaling003-owner-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.recorder = StrategyScienceRecorder(self.root, source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id='scaling003-test', clock=FixedClock(), reuse_verified_history=True)
        self.addCleanup(self.recorder.close)

    def populate(self):
        for raw in core_fixtures():
            self.recorder.accept(raw)
        self.recorder.verify(SESSION_ID)

    def test_repeated_verify_does_not_reread_raw_or_rebuild_channels(self):
        self.populate()
        views = self.recorder._views
        before_reads = views.reads.counters['raw_file_reads']
        before_rebuild = views.counters['channel_rebuilds']
        for _ in range(3):
            self.assertTrue(self.recorder.verify(SESSION_ID).all_hashes_valid)
        self.assertEqual(before_reads, views.reads.counters['raw_file_reads'])
        self.assertEqual(before_rebuild, views.counters['channel_rebuilds'])
        self.assertGreater(views.counters['namespace_audits'], 0)
        self.assertGreater(views.reads.counters['metadata_checks'], 0)

    def test_index_ahead_and_external_unknown_metadata_are_not_cached_away(self):
        self.populate()
        partition = self.root / Path(self.recorder.verify(SESSION_ID).partition_id)
        (partition/'unexpected-index.json').write_bytes(b'{}')
        with self.assertRaises(RecorderCustodyError):
            self.recorder.verify(SESSION_ID)

    def test_cached_receipt_corruption_fails_without_new_poll(self):
        self.populate()
        target = next(self.root.rglob('*.receipt.json'))
        old = target.stat()
        raw = target.read_bytes()
        target.write_bytes(b'X'+raw[1:])
        os.utime(target,ns=(old.st_atime_ns,old.st_mtime_ns))
        with self.assertRaises(RecorderCustodyError):
            self.recorder.verify(SESSION_ID)

    def test_removed_complete_checkpoint_fails_without_new_poll(self):
        self.populate()
        next(self.root.rglob('*.checkpoint.json')).unlink()
        with self.assertRaises(RecorderCustodyError):
            self.recorder.verify(SESSION_ID)

    def test_cold_restart_rebuilds_same_report_and_raw(self):
        self.populate()
        report = self.recorder.verify(SESSION_ID)
        before = {p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*')
                  if p.is_file() and p.name.endswith(('.source.json','.receipt.json','.payload.json','.checkpoint.json'))}
        self.recorder.close()
        with StrategyScienceRecorder(self.root, source_root_identity=SOURCE_ROOT_IDENTITY,
                writer_instance_id='scaling003-test', clock=FixedClock(), reuse_verified_history=True) as reopened:
            reopened.recover()
            self.assertEqual(report,reopened.verify(SESSION_ID))
        self.assertEqual(before,{name:(self.root/name).read_bytes() for name in before})

    def test_cold_partial_is_quarantined_with_receipt_without_poisoning_cache(self):
        (self.root/'.partial'/'cold.tmp').write_bytes(b'partial synthetic bytes')
        self.assertEqual((),self.recorder.recover())
        self.assertEqual(1,len(list((self.root/'quarantine-receipts').glob('*.quarantine.json'))))
        self.assertEqual((),self.recorder.recover())

    def test_warm_partial_inventory_is_not_reused_after_quarantine(self):
        self.assertEqual((),self.recorder.recover())
        (self.root/'.partial'/'warm.tmp').write_bytes(b'partial synthetic bytes')
        self.assertEqual((),self.recorder.recover())
        self.assertEqual(1,len(list((self.root/'quarantine-receipts').glob('*.quarantine.json'))))
        self.assertFalse((self.root/'.partial'/'warm.tmp').exists())


OWNER_MODULES = (
    'tests.test_strategy_science_recorder_contract',
    'tests.test_strategy_science_recorder_custody',
    'tests.test_strategy_science_recorder_coverage',
    'tests.test_strategy_science_recorder_outcomes',
    'tests.test_strategy_science_recorder_restart',
    'tests.test_strategy_science_recorder_boundaries',
    'tests.test_strategy_science_recorder_eligibility_authority',
    'tests.test_strategy_science_source_reader_v2',
)


class VerifiedOwnerSuite(unittest.TestSuite):
    def run(self,result,debug=False):
        original = StrategyScienceRecorder.__init__
        @wraps(original)
        def enabled(instance,*args,**kwargs):
            kwargs.setdefault('reuse_verified_history',True)
            return original(instance,*args,**kwargs)
        with patch.object(StrategyScienceRecorder,'__init__',enabled):
            return super().run(result,debug=debug)


def load_tests(loader, tests, pattern):
    if os.name != 'nt':
        @unittest.skip('Native verified-history qualification requires Windows; no silent portable fallback.')
        class NativeRequired(unittest.TestCase):
            def test_native_qualification(self):
                pass
        return loader.loadTestsFromTestCase(NativeRequired)
    suite = VerifiedOwnerSuite()
    suite.addTests(tests)
    suite.addTests(loader.loadTestsFromNames(OWNER_MODULES))
    return suite
