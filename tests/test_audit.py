"""Fabricated artifact contracts for auditor testing, NOT live qualification."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from gui_gate import audit
from gui_gate.runner import save
from test_probe import PNG
import base64


def artifact(directory, fault='none'):
    directory.mkdir()
    scenario = audit.load(audit.SCENARIO)
    image = {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}]}
    config = {'version': 1, 'acceptance': {'max_wave_seconds': 2, 'max_reset_seconds': 1, 'max_campaign_seconds': 50}, 'targets': {}}
    identities = {}
    resources = {name: str(uuid.uuid4()) for name in audit.OS_NAMES}
    snapshots = {name: str(uuid.uuid4()) for name in audit.OS_NAMES}
    for name in audit.OS_NAMES:
        identity = {'driver_sha256': 'a' * 64, 'native_app_sha256': 'b' * 64, 'driver_version': 'artifact-fixture'}
        if name == 'macos': identity.update(bundle_id='com.trycua.driver', team_id='FAKETEAM', designated_requirement='fake-requirement')
        if name == 'windows': identity['account_sid'] = 'S-1-5-21-1-2-3-1001'
        if name == 'linux': identity['uid'] = 1000
        identities[name] = identity
        config['targets'][name] = {'resource': resources[name], 'identity': identity}
    summary = {'passed': True, 'requested_repetitions': 20, 'host': {'os': 'Darwin', 'architecture': 'arm64'},
               'campaign_seconds': 40, 'runs': []}
    if fault == 'wrong-host': summary['host']['os'] = 'Windows'
    if fault == 'zero-runs': summary['requested_repetitions'] = 0
    if fault == 'cancelled': summary['cancelled'] = True
    if fault == 'underreported-campaign': summary['campaign_seconds'] = 25
    if fault == 'campaign-budget': config['acceptance']['max_campaign_seconds'] = 20
    if fault == 'reset-budget': config['acceptance']['max_reset_seconds'] = .01
    if fault == 'boolean-budget': config['acceptance']['max_reset_seconds'] = True
    if fault == 'wrong-scenario': scenario['steps'][2]['tool'] = 'launch_app'
    for index in range(20 if fault != 'zero-runs' else 0):
        reports = []
        for name in audit.OS_NAMES:
            root = directory / f'run-{index:04d}' / name
            root.mkdir(parents=True)
            marker = directory.name + f'/run-{index:04d}'
            proof = {'os': name, 'identity': copy.deepcopy(identities[name]), 'permissions_ready': True,
                     'interactive_desktop': True, 'desktop_session_unlocked': True, 'driver_path': '/app/cua-driver',
                     'probe_request_id': uuid.uuid4().hex, 'desktop_observation': copy.deepcopy(image),
                     'window': {'pid': 42, 'window_id': 84},
                     'backend': {'name': 'utm', 'vm_uuid': resources[name], 'snapshot_uuid': snapshots[name],
                                 'includes_running_state': True, 'utmctl_sha256': 'c' * 64}}
            if name == 'macos':
                proof['signature_evidence'] = 'Authority=Developer ID Application: Fabricated test fixture'
                proof['permission_observation'] = {'structuredContent': {'accessibility': True, 'screen_recording': True,
                                                   'source': {'attribution': 'driver-daemon', 'bundle_id': 'com.trycua.driver', 'executable': '/app/cua-driver'}}}
            if name == 'windows': proof.update(app_account_sid=identities[name]['account_sid'], app_session_id=1, caller_session_id=1)
            if name == 'linux': proof.update(app_uid=1000, permission_observation={'structuredContent': {'x11': True, 'atspi': True}})
            if fault == 'synthetic': proof['fixture'] = True
            if fault == 'changed-identity': proof['identity']['driver_version'] = 'changed'
            if fault == 'integer-grant': proof['permissions_ready'] = 1
            if fault == 'host-tcc' and name == 'macos': proof['permission_observation']['structuredContent']['source']['attribution'] = 'host'
            if fault == 'session0' and name == 'windows': proof['caller_session_id'] = 0
            if fault == 'no-atspi' and name == 'linux': proof['permission_observation']['structuredContent']['atspi'] = False
            if fault == 'stale-challenge': proof['probe_request_id'] = 'a' * 32
            if fault == 'changed-checkpoint' and index > 0: proof['backend']['snapshot_uuid'] = str(uuid.uuid4())
            if fault == 'changed-backend' and index > 0: proof['backend']['utmctl_sha256'] = 'd' * 64
            if fault == 'unhashed-backend': proof['backend']['utmctl_sha256'] = 'not-an-observed-hash'
            if fault == 'shared-vm': proof['backend']['vm_uuid'] = resources['macos']
            report = {'target': name, 'passed': True, 'guest': proof, 'lease_owner': uuid.uuid4().hex,
                      'all_desktops_synchronized': True, 'started_monotonic_ns': index * 2_000_000_000,
                      'desktop_ready_monotonic_ns': index * 2_000_000_000 + 100_000_000,
                      'desktop_finished_monotonic_ns': index * 2_000_000_000 + 900_000_000,
                      'finished_monotonic_ns': index * 2_000_000_000 + 1_000_000_000,
                      'timings_seconds': {'reset': .1}, 'steps': []}
            if fault == 'no-overlap' and name == 'linux': report['desktop_ready_monotonic_ns'] += 850_000_000
            if fault == 'out-of-order-waves':
                for key in ('started_monotonic_ns', 'desktop_ready_monotonic_ns', 'desktop_finished_monotonic_ns', 'finished_monotonic_ns'):
                    report[key] -= index * 2_000_000_000
            if fault == 'cleanup': report['cleanup_error'] = 'failed'
            before = {'pid': 42, 'text': '', 'revision': 0}
            after = {'pid': 42, 'text': marker, 'revision': 1}
            if fault == 'ack-only': after['text'] = ''
            if fault == 'stale-reset': before['text'] = 'previous-marker'
            if fault == 'boolean-revision': before['revision'] = False
            if fault == 'wrong-process': after['pid'] = 43
            raws = [
                {'arguments': {}, 'result': {'structuredContent': before}},
                {'arguments': {'pid': 42, 'window_id': 84, 'include_screenshot': True, 'max_dimension': 512}, 'result': copy.deepcopy(image)},
                {'arguments': {'pid': 42, 'window_id': 84, 'text': marker, 'delivery_mode': 'foreground'}, 'result': {'structuredContent': {'effect': 'unverifiable'}}},
                {'arguments': {'expected': marker}, 'result': {'structuredContent': after}},
            ]
            if fault == 'no-image': raws[1]['result'] = {}
            if fault == 'wrong-window': raws[2]['arguments']['window_id'] = 85
            for step_index, raw in enumerate(raws):
                path = root / f'step-{step_index:03d}.json'
                save(path, raw)
                report['steps'].append({'id': scenario['steps'][step_index]['id'], 'passed': True,
                                        'evidence': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                        **{k: scenario['steps'][step_index][k] for k in ('tool', 'oracle') if k in scenario['steps'][step_index]}})
                if fault == 'tampered' and step_index == 2: path.write_text('{}')
            save(root / 'verify.stdout', proof)
            save(root / 'report.json', report)
            reports.append(report)
        summary['runs'].append(reports)
    save(directory / 'config.json', config)
    save(directory / 'scenario.json', scenario)
    for name in ('config', 'scenario'):
        summary[f'{name}_sha256'] = hashlib.sha256((directory / f'{name}.json').read_bytes()).hexdigest()
    save(directory / 'summary.json', summary)


class AuditTests(unittest.TestCase):
    def test_artifact_contract_positive_never_product_qualifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'fabricated-campaign'
            artifact(root)
            report = audit.audit(root)
            self.assertTrue(report['campaign_audit_passed'], report)
            self.assertFalse(report['product_qualified'])
            self.assertEqual(report['metrics']['waves'], 20)

    def test_false_green_controls(self):
        faults = ('wrong-host', 'zero-runs', 'cancelled', 'campaign-budget', 'reset-budget', 'boolean-budget',
                  'wrong-scenario', 'synthetic', 'changed-identity', 'integer-grant', 'host-tcc', 'session0',
                  'no-atspi', 'stale-challenge', 'shared-vm', 'no-overlap', 'cleanup', 'ack-only',
                  'stale-reset', 'boolean-revision', 'wrong-process', 'no-image', 'wrong-window', 'tampered',
                  'underreported-campaign', 'changed-checkpoint', 'changed-backend', 'unhashed-backend', 'out-of-order-waves')
        for fault in faults:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'fabricated-campaign'
                artifact(root, fault)
                report = audit.audit(root)
                self.assertFalse(report['campaign_audit_passed'], report)
                self.assertFalse(report['product_qualified'])

    def test_vm_uuid_resource_case_is_canonicalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'fabricated-campaign'
            artifact(root)
            config = audit.load(root / 'config.json')
            for target in config['targets'].values():
                target['resource'] = target['resource'].upper()
            save(root / 'config.json', config)
            summary = audit.load(root / 'summary.json')
            summary['config_sha256'] = hashlib.sha256((root / 'config.json').read_bytes()).hexdigest()
            save(root / 'summary.json', summary)
            report = audit.audit(root)
            self.assertTrue(report['campaign_audit_passed'], report)

    def test_missing_evidence_is_red_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = audit.audit(Path(tmp))
            self.assertFalse(report['campaign_audit_passed'])
            self.assertIn('error', report)


if __name__ == '__main__':
    unittest.main()
