"""Synthetic gate qualification; does not prove any live GUI or VM capability."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from gui_gate import runner as gate

# A real child process exercises the shared DriverClient's explicit argv path.
MCP = '''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request: continue
    method = request['method']
    if method == 'initialize': result = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 'fake', 'version': '1'}}
    elif method == 'tools/list': result = {'tools': [{'name': 'observe', 'inputSchema': {}, 'annotations': {'readOnlyHint': True}}]}
    else: result = {'structuredContent': {'value': request['params']['arguments'].get('value', 'ready')}}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''


def config():
    targets = {}
    for name in gate.TARGETS:
        proof = {'os': name, 'identity': {'signature': 'pinned'}, 'permissions_ready': True, 'interactive_desktop': True}
        targets[name] = {
            'resource': name + '-test-guest', 'identity': proof['identity'],
            'reset': [sys.executable, '-c', 'pass'],
            'destroy': [sys.executable, '-c', 'pass'],
            'verify': [sys.executable, '-c', 'print(' + repr(json.dumps(proof)) + ')'],
            'mcp': [sys.executable, '-u', '-c', MCP],
            'bindings': {'expected': 'ready'},
        }
    return {'version': 1, 'timeout_seconds': 10, 'targets': targets}


def scenario():
    return {'version': 1, 'steps': [
        {'id': 'observe', 'tool': 'observe', 'assert': [
            {'path': '/structuredContent/value', 'op': 'equals', 'value': {'$ref': '/bindings/expected'}}]},
        {'id': 'again', 'tool': 'observe', 'arguments': {'value': {'$ref': '/results/observe/structuredContent/value'}}, 'assert': [
            {'path': '/structuredContent/value', 'op': 'contains', 'value': 'ead'}]},
    ]}


class GuiGateTests(unittest.TestCase):
    def test_real_stdio_three_targets_repeated_and_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, summary = gate.run(config(), scenario(), Path(tmp), 2)
            self.assertTrue(summary['passed'], summary)
            self.assertEqual(len(summary['runs']), 2)
            for index in range(2):
                reports = summary['runs'][index]
                self.assertTrue(all(r['all_desktops_synchronized'] is True for r in reports))
                self.assertLess(max(r['desktop_ready_monotonic_ns'] for r in reports),
                                min(r['desktop_finished_monotonic_ns'] for r in reports))
                for name in gate.TARGETS:
                    evidence = directory / f'run-{index:04d}' / name
                    report = json.loads((evidence / 'report.json').read_text())
                    self.assertTrue(report['passed'])
                    self.assertIn('destroy', report['timings_seconds'])
                    self.assertEqual(report['steps'][0]['sha256'], gate.hashlib.sha256((evidence / 'step-000.json').read_bytes()).hexdigest())
            self.assertTrue((directory / 'scenario.json').exists())

    def test_concurrent_targets(self):
        barrier = threading.Barrier(3)
        original = gate.run_target
        def synchronized(*args):
            barrier.wait(timeout=5)
            return original(*args)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gate, 'run_target', side_effect=synchronized):
            _, summary = gate.run(config(), scenario(), Path(tmp), 1)
            self.assertTrue(summary['passed'], summary)

    def test_failed_desktop_synchronization_is_not_a_green_campaign(self):
        broken = mock.Mock()
        broken.wait.side_effect = threading.BrokenBarrierError()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gate.threading, 'Barrier', return_value=broken):
            _, summary = gate.run(config(), scenario(), Path(tmp), 1)
            self.assertFalse(summary['passed'])
            self.assertTrue(all(r['passed'] for r in summary['runs'][0]))
            self.assertTrue(all(r['all_desktops_synchronized'] is False for r in summary['runs'][0]))

    def test_identity_mismatch_fails_closed_and_cleans_up(self):
        cfg = config()
        cfg['targets']['windows']['identity'] = {'signature': 'wrong'}
        with tempfile.TemporaryDirectory() as tmp:
            directory, summary = gate.run(cfg, scenario(), Path(tmp), 1)
            report = summary['runs'][0][1]
            self.assertFalse(report['passed'])
            self.assertEqual(report['steps'], [])
            self.assertIn('identity', report['error'])
            self.assertTrue((directory / 'run-0000/windows/destroy.stdout').exists())

    def test_bad_assertion_retains_evidence(self):
        task = scenario()
        task['steps'][0]['assert'][0]['value'] = 'wrong'
        with tempfile.TemporaryDirectory() as tmp:
            _, summary = gate.run(config(), task, Path(tmp), 1)
            self.assertFalse(summary['passed'])
            self.assertIn('evidence', summary['runs'][0][0]['steps'][0])

    def test_cleanup_failure_stops_repetitions(self):
        cfg = config()
        cfg['targets']['linux']['destroy'] = [sys.executable, '-c', 'raise SystemExit(3)']
        with tempfile.TemporaryDirectory() as tmp:
            _, summary = gate.run(cfg, scenario(), Path(tmp), 3)
            self.assertFalse(summary['passed'])
            self.assertEqual(len(summary['runs']), 1)
            self.assertIn('cleanup_error', summary['runs'][0][2])

    def test_missing_permission_refuses_driver(self):
        cfg = config()
        cfg['targets']['macos']['verify'] = [sys.executable, '-c', 'print(\'{"os":"macos","identity":{"signature":"pinned"},"permissions_ready":false,"interactive_desktop":true}\')']
        with tempfile.TemporaryDirectory() as tmp:
            _, summary = gate.run(cfg, scenario(), Path(tmp), 1)
            self.assertFalse(summary['runs'][0][0]['passed'])
            self.assertEqual(summary['runs'][0][0]['steps'], [])

    def test_boundary_validation(self):
        for change in ('shared', 'shell', 'assertions', 'timeout'):
            cfg, task = config(), scenario()
            if change == 'shared': cfg['targets']['windows']['resource'] = cfg['targets']['macos']['resource']
            if change == 'shell': cfg['targets']['linux']['reset'] = 'echo unsafe'
            if change == 'assertions': task['steps'] = [{'id': 'act', 'tool': 'observe'}]
            if change == 'timeout': cfg['timeout_seconds'] = float('nan')
            with self.subTest(change=change), self.assertRaises(ValueError):
                gate.validate(cfg, task)

    def test_missing_evidence_and_boolean_do_not_equal_one(self):
        with self.assertRaises(KeyError): gate.pointer({}, '/absent')
        with self.assertRaises(AssertionError):
            gate.assert_evidence({'path': '', 'op': 'equals', 'value': 1}, True, {})

    def test_requires_explicit_authorization(self):
        result = subprocess.run([sys.executable, '-m', 'gui_gate.runner', '--config', 'missing', '--scenario', 'missing', '--output', 'unused'], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'--allow-disposable-guests', result.stderr)


if __name__ == '__main__':
    unittest.main()
