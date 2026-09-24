"""Decode is not native admission; deterministic doubles are not SCM proof."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from momentum_hunter import continuous_host_contract as host
from momentum_hunter import windows_science_custody as custody
from momentum_hunter import windows_writer_profile as actors
from tests.test_continuous_host_boundaries import configuration, seal
from tests.test_science_mutable_policy_020g import BNative, admission, policy
from tests.test_windows_writer_profile_016d import token


def configured_policy():
    value = policy()
    cfg = configuration(Path('F:/q'))
    cfg['hostStateRoot'] = 'F:/q/generations'
    cfg['runtimeIdentity'] = 'qual-016d-runtime'
    cfg['host']['instanceId'] = 'qual-016d'
    cfg['host']['services'] = host.service_names('qual-016d')
    settings = cfg['host']['science']
    settings['restrictingSid'] = host.science_service_sid('qual-016d')
    settings['principal'] = 'NT SERVICE\\' + cfg['host']['services']['science']
    settings['custodyPolicy'] = json.loads(json.dumps(asdict(value)))
    paths = actors.expected_resource_paths(cfg)
    profile = replace(value.actor_profile, resources=tuple(
        replace(row, path=str(paths[row.name])) for row in value.actor_profile.resources))
    value = replace(value, actor_profile=profile)
    settings['custodyPolicy'] = json.loads(json.dumps(asdict(value)))
    seal(cfg)
    return cfg, value


@contextmanager
def deny_finalized_paths(value, namespace=None):
    paths = {custody._path_key(row.path) for row in value.roots
             if namespace is None or row.namespace == namespace}
    original = Path.lstat
    attempted = []

    def observed(path, *args, **kwargs):
        if custody._path_key(path) in paths:
            attempted.append(str(path))
            error = PermissionError(13, 'Access denied by finalized custody policy', str(path))
            error.winerror = 5
            raise error
        return original(path, *args, **kwargs)

    with patch.object(Path, 'lstat', observed):
        yield attempted


class DecodeOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.value = configured_policy()

    def test_historical_absolute_root_call_still_reproduces_win32_5(self):
        with deny_finalized_paths(self.value) as attempts:
            with self.assertRaises(PermissionError) as caught:
                host.absolute_root(self.value.root('derived').path)
            self.assertEqual(caught.exception.winerror, 5)
            self.assertEqual(len(attempts), 1)

    def test_decode_preserves_policy_without_cross_role_filesystem_access(self):
        with deny_finalized_paths(self.value) as attempts:
            decoded = host.science_custody_policy(self.cfg)
        self.assertEqual(decoded, self.value)
        self.assertEqual(decoded.policy_sha256, self.value.policy_sha256)
        self.assertEqual(attempts, [])

    def test_exact_reader_lock_denial_does_not_break_structural_decode(self):
        self.assertTrue(self.value.root('derived').path.replace('\\', '/').endswith('/reader-lock'))
        with deny_finalized_paths(self.value, 'derived') as attempts:
            decoded = host.science_custody_policy(self.cfg)
        self.assertEqual(decoded, self.value)
        self.assertEqual(attempts, [])

    def test_validate_and_install_plan_need_no_custody_leaf_authority(self):
        with deny_finalized_paths(self.value) as attempts:
            result = host.validate_host(self.cfg)
            plan = host.install_plan(self.cfg, Path(self.cfg['configRoot']) / 'continuous-deployment.json',
                                     Path('F:/q/install/source'), Path('F:/q/install/python-base/python.exe'))
        self.assertEqual(result['inputMode'], host.OFFLINE)
        self.assertFalse(plan['windowsMutation'])
        self.assertFalse(plan['providerContact'])
        self.assertEqual(attempts, [])

    def test_decoder_never_grants_native_actor_admission(self):
        with patch.object(custody, '_Native', side_effect=AssertionError('native actor creation')):
            self.assertEqual(host.science_custody_policy(self.cfg), self.value)

    def test_v1_namespace_path_walk_is_unchanged(self):
        cfg = configuration(Path('F:/legacy'))
        binding = cfg['host']['science']['custodyPolicy']['roots'][0]['path']
        with patch.object(host, 'absolute_root', wraps=host.absolute_root) as observed:
            host.science_custody_policy(cfg)
        self.assertIn(binding, [call.args[0] for call in observed.call_args_list])

    def test_ordinary_host_root_reparse_check_is_unchanged(self):
        original = Path.is_symlink
        bad = custody._path_key(self.cfg['runtimeStateRoot'])
        with patch.object(Path, 'is_symlink', lambda p: True if custody._path_key(p) == bad else original(p)):
            with self.assertRaisesRegex(host.HostConfigurationError, 'reparse'):
                host.validate_host(self.cfg)

    def test_missing_and_corrupt_structural_security_evidence_rejected(self):
        mutations = (
            lambda p: p.pop('ancestors'),
            lambda p: p.update(ancestors=[]),
            lambda p: p.update(roots=p['roots'][:-1]),
            lambda p: p['roots'][0].pop('file_identity'),
            lambda p: p['roots'][0].update(descriptor_sha256=''),
            lambda p: p['roots'][0].update(owner_sid=p['science_sid']),
            lambda p: p.update(science_privilege_names=['SeBackupPrivilege']),
            lambda p: p.update(source_root_identity='f' * 64),
        )
        for mutate in mutations:
            cfg = deepcopy(self.cfg)
            mutate(cfg['host']['science']['custodyPolicy'])
            with self.subTest(mutation=mutate), self.assertRaises((host.HostConfigurationError, custody.ScienceCustodyNativeError)):
                host.science_custody_policy(cfg)

    def test_wrong_class_alias_and_namespace_escape_rejected(self):
        for path in ('F:/q/science/derived', 'F:/q/science/mutable-v2/owner-lease',
                     'F:/q/science/mutable-v2/../reader-lock', 'F:/other/reader-lock',
                     '//server/share/reader-lock', 'F:/q/science/mutable-v2/reader-lock:ads',
                     'F:/q/science/mutable-v2/reader-lock.'):
            cfg = deepcopy(self.cfg)
            row = next(r for r in cfg['host']['science']['custodyPolicy']['roots'] if r['namespace'] == 'derived')
            row['path'] = path
            with self.subTest(path=path), self.assertRaises((host.HostConfigurationError, custody.ScienceCustodyNativeError)):
                host.science_custody_policy(cfg)


class DecodedNativeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.value = configured_policy()
        with deny_finalized_paths(self.value):
            self.decoded = host.science_custody_policy(self.cfg)
        self.native = BNative(self.decoded)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(custody, '_Native', return_value=self.native))
        self.stack.enter_context(patch.object(custody, 'observe_actor', side_effect=admission))
        self.stack.enter_context(patch.object(custody, 'admission_identity', side_effect=lambda x: x))
        self.stack.enter_context(patch.object(custody, 'access_decisions', return_value={x: False for x in actors.MUTATION_RIGHTS}))

    def start(self):
        backend = custody.WindowsScienceCustodyBackend(self.decoded, role='science')
        self.addCleanup(backend.close)
        return backend

    def target(self):
        return self.native.objects[custody._path_key(self.decoded.root('derived').path)]

    def failed_before_creation(self):
        with self.assertRaises(custody.ScienceCustodyNativeError):
            self.start()
        self.assertFalse(any(opts.get('disposition') in (1, 4) for _, opts in self.native.opens))
        self.assertTrue(all(handle.closed for handle in self.native.handles.values()))

    def test_missing_current_handle_evidence_rejected(self):
        del self.native.objects[custody._path_key(self.decoded.root('derived').path)]
        self.failed_before_creation()

    def test_reparse_substitution_rejected(self):
        self.target().attributes |= custody.REPARSE
        self.failed_before_creation()

    def test_path_replacement_rejected(self):
        self.target().path = Path('F:/replacement')
        self.failed_before_creation()

    def test_native_object_identity_mismatch_rejected(self):
        self.target().identity = (1, 9, 987)
        self.failed_before_creation()

    def test_wrong_file_instead_of_parent_directory_rejected(self):
        self.target().attributes &= ~custody.DIRECTORY
        self.failed_before_creation()

    def test_descriptor_digest_mismatch_rejected(self):
        sec = self.target().security
        self.target().security = replace(sec, sddl=sec.sddl + 'changed')
        self.failed_before_creation()

    def test_unsafe_prefinalization_security_rejected(self):
        self.target().security = replace(self.target().security, control=0x9004)
        self.failed_before_creation()

    def test_incomplete_native_security_rejected(self):
        self.target().security = replace(self.target().security, labels=())
        self.failed_before_creation()

    def test_wrong_runtime_actor_rejected(self):
        self.native.token_override = token('writer')
        self.failed_before_creation()

    def test_stale_generation_rejected_before_transport_write(self):
        backend = self.start()
        observed = token('science')
        observed['token_id'] = (987, 123)
        self.native.token_override = observed
        with self.assertRaisesRegex(custody.ScienceCustodyNativeError, 'generation changed'):
            backend.create_transport('requests', 'request.json', b'raw')
        self.assertTrue(backend._closed)

    def test_postfinalization_drift_rejected_and_handles_closed(self):
        backend = self.start()
        self.target().security = replace(self.target().security, owner=self.decoded.science_sid)
        with self.assertRaises(custody.ScienceCustodyNativeError):
            backend.create_transport('requests', 'request.json', b'raw')
        self.assertTrue(backend._closed)
        self.assertTrue(all(h.closed for h in self.native.handles.values()))

    def test_nested_transaction_checks_version_two_root_before_transport_write(self):
        backend = self.start()
        with self.assertRaises(custody.ScienceCustodyNativeError):
            with backend.transaction():
                self.target().security = replace(self.target().security, control=0x9004)
                backend.create_transport('requests', 'request.json', b'raw')
        self.assertTrue(backend._closed)
        self.assertTrue(all(h.closed for h in self.native.handles.values()))

    def test_nested_transaction_checks_version_two_actor_before_transport_write(self):
        backend = self.start()
        with self.assertRaises(custody.ScienceCustodyNativeError):
            with backend.transaction():
                self.native.token_override = token('writer')
                backend.create_transport('requests', 'request.json', b'raw')
        self.assertTrue(backend._closed)
        self.assertTrue(all(h.closed for h in self.native.handles.values()))

    def test_valid_native_admission_preserves_role_specific_pins(self):
        backend = self.start()
        self.assertTrue(backend._fixed_keys)
        self.assertNotIn(custody._path_key(self.decoded.root('private').path), backend._fixed_keys)
        for handle, _, _, _ in backend._pins.values():
            self.assertFalse(handle.closed)
        backend._check_pins()

    def test_fixed_access_denial_reuse_requires_unchanged_token_and_descriptor(self):
        backend = self.start()
        backend._fixed_access_cache.clear()
        denied = {right: False for right in actors.MUTATION_RIGHTS}
        with patch.object(custody, 'access_decisions', return_value=denied) as access:
            backend._check_pins()
            first = access.call_count
            self.assertGreater(first, 0)
            backend._check_pins()
            self.assertEqual(access.call_count, first)

            root = self.target()
            path = Path(self.decoded.root('derived').path)
            observed = dict(backend.last_token_observation)
            observed['modified_id'] = (observed['modified_id'][0] + 1,
                                       observed['modified_id'][1])
            backend.last_token_observation = observed
            backend._forbidden_access_decisions(path, root.security)
            self.assertEqual(access.call_count, first + 1)
            backend._forbidden_access_decisions(path, replace(root.security, sddl=root.security.sddl + 'changed'))
            self.assertEqual(access.call_count, first + 2)

    def test_cached_access_denial_does_not_hide_root_security_drift(self):
        backend = self.start()
        backend._check_pins()
        self.target().security = replace(self.target().security, control=0x9004)
        with self.assertRaises(custody.ScienceCustodyNativeError):
            backend.create_transport('requests', 'request.json', b'raw')
        self.assertTrue(backend._closed)


if __name__ == '__main__':
    unittest.main()
