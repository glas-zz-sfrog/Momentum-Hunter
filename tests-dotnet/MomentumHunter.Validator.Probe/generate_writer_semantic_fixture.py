"""Generate synthetic diagnostic fixtures using the actual producer, no native API."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from momentum_hunter import windows_writer_profile as p
from momentum_hunter import windows_writer_self_diagnostic as d


def generate(source, destination):
    destination.mkdir()
    for name in ('002-stdout.bin', '003-stderr.bin', '004-continuous-deployment.json'):
        shutil.copyfile(source / name, destination / name)
    config = json.loads((source / '004-continuous-deployment.json').read_bytes())
    output = json.loads((source / '002-stdout.bin').read_bytes())
    observation = output['observation']
    bound = p.decode_profile(config['host']['science']['custodyPolicy']['actor_profile'])

    def tuples(value):
        if isinstance(value, list):
            return tuple(tuples(v) for v in value)
        if isinstance(value, dict):
            return {k: tuples(v) for k, v in value.items()}
        return value

    observed = tuples(observation['token'])

    class SyntheticApi:
        def __init__(self, native):
            pass

        def own_token(self):
            return deepcopy(observed)

        def mandatory_policy(self, expected):
            return observed['mandatory_policy']

        def process_binding(self, binding):
            return dict(matched=True, **{key: deepcopy(observation[key]) for key in ('process', 'parent', 'scm')})

        def file(self, target, right):
            allowed = right not in target['forbidden']
            identity = dict(fileId=target['frozenIdentity'] or (1, 0, 1),
                            attributes=16 if target['directory'] else 32, links=1) if allowed else None
            return dict(d.row(right, allowed, 0 if allowed else 5, identity), metadataWin32=0 if allowed else None)

        def services(self, names, deadline, clock):
            return dict(rows=[dict(d.row(right, False, 5), service=name, api='OpenServiceW')
                              for name in names for right in p.SERVICE_CONTROL_RIGHTS])

    output_stream = io.StringIO()
    with patch.object(d, 'SelfNative', SyntheticApi), patch.object(d.sys, 'stderr', output_stream):
        report = d.collect(None, config, bound, observed, clock=lambda: 1)
        report['pid'] = observation['process']['pid']
        d.emit(report, None)
    assert report['assumptions']['A4']['status'] == 'PASS'
    assert report['assumptions']['A5']['status'] == 'PASS'
    assert report['assumptions']['A6']['status'] == 'BLOCKED'
    assert report['completed'] and report['admissionIdentical'] and not report['errors']
    (destination / 'a6-producer-report.json').write_bytes(d.canonical(report))
    (destination / 'a6-producer-stderr.bin').write_bytes(output_stream.getvalue().encode('ascii'))
    receipt = dict(status='PASS', synthetic=True, nativeCalls=0, serviceCalls=0,
                   producerSha256=hashlib.sha256(Path(d.__file__).read_bytes()).hexdigest(),
                   fileTargets=report['expectedFileTargets'], fileRecords=len(report['files']),
                   serviceRows=len(report['services']['rows']), fileProbes=report['probeCount'])
    (destination / 'FIXTURE-PROVENANCE.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    generate(Path(sys.argv[1]), Path(sys.argv[2]))
