"""Oracle, native platform readout, and daemon-attribution tests; no live Cua."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from gui_gate import guest_probe as probe
from gui_gate import native_probe as app
from gui_gate import runner
from test_runner import config

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


class ProbeTests(unittest.TestCase):
    def test_state_publish_read_unicode_and_wrong_postcondition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'app.json'
            app.publish(path, '日本語🙂', 1)
            self.assertEqual(app.read_state(path)['text'], '日本語🙂')
            self.assertEqual(app.oracle(path, {'expected': 'wrong'}, timeout=0)['structuredContent']['text'], '日本語🙂')
            self.assertFalse(path.with_suffix('.tmp').exists())
            self.assertEqual(app.read_state(path)['pid'], os.getpid())
            with self.assertRaises(ValueError):
                app.oracle(path, {'expected': True})

    def test_state_concurrent_reads_never_see_partial_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'app.json'
            app.publish(path, '0', 0)
            done, entered = threading.Event(), threading.Event()
            errors = []
            def reader():
                try:
                    while not done.is_set():
                        state = app.read_state(path)
                        if state['text'] != str(state['revision']):
                            raise AssertionError('partial state publication')
                        entered.set()
                except Exception as error:
                    errors.append(repr(error))
            worker = threading.Thread(target=reader)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                for revision in range(1, 101):
                    app.publish(path, str(revision), revision)
            finally:
                done.set()
                worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors, errors)
            self.assertEqual(app.read_state(path)['revision'], 100)

    def test_windows_sharing_retry_is_bounded_and_not_a_permission_bypass(self):
        operation = mock.Mock(side_effect=[PermissionError('sharing'), 'ready'])
        with mock.patch.object(app.os, 'name', 'nt'), mock.patch.object(app.time, 'monotonic', return_value=0), mock.patch.object(app.time, 'sleep') as sleep:
            self.assertEqual(app._sharing_retry(operation), 'ready')
            sleep.assert_called_once_with(.01)
        for system in ('nt', 'posix'):
            with self.subTest(system=system), mock.patch.object(app.os, 'name', system), mock.patch.object(app.time, 'monotonic', side_effect=[0, 2]), self.assertRaises(PermissionError):
                app._sharing_retry(mock.Mock(side_effect=PermissionError('persistent denial')))

    def test_unicode_oracle_stdio_is_utf8_json_with_legacy_windows_codec(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'app.json'
            app.publish(path, '日本語🙂', 1)
            result = subprocess.run([sys.executable, '-m', 'gui_gate.native_probe', 'oracle', '--state', str(path)],
                                    input=b'{}', capture_output=True, timeout=5,
                                    env={**os.environ, 'PYTHONIOENCODING': 'cp1252'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.decode('utf-8'))['structuredContent']['text'], '日本語🙂')

    def test_unicode_guest_mailbox_stdio_is_utf8_json_on_legacy_codec(self):
        raw = io.BytesIO()
        with io.TextIOWrapper(raw, encoding='cp1252') as stdout:
            value = {'os': 'windows', 'window': {'title': '日本語🙂'}}
            with mock.patch.object(sys, 'argv', ['guest_probe', 'request', '--mailbox', 'unused']), mock.patch.object(sys, 'stdout', stdout), mock.patch.object(probe, 'mailbox_request', return_value=value):
                self.assertEqual(probe.main(), 0)
            stdout.flush()
            self.assertEqual(json.loads(raw.getvalue().decode('utf-8')), value)

    def test_capture_requires_intact_png_not_screenshot_ack(self):
        def result(data):
            return {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(data).decode()}]}
        self.assertTrue(probe.capture_present(result(PNG)))
        for data in (PNG[:24], PNG[:-4], PNG[:20] + b'xxxx' + PNG[24:], b'ack'):
            self.assertFalse(probe.capture_present(result(data)))
        self.assertFalse(probe.capture_present({'structuredContent': {'screenshot': 'success'}}))

    def test_release_signature_rejects_adhoc_and_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'CuaDriver.app'
            (bundle / 'Contents').mkdir(parents=True)
            with (bundle / 'Contents/Info.plist').open('wb') as stream:
                plistlib.dump({'CFBundleIdentifier': 'com.trycua.driver'}, stream)
            details = b'TeamIdentifier=SIGNEDTEAM\nAuthority=Developer ID Application: Vendor\ndesignated => identifier "com.trycua.driver"\n'
            completed = subprocess.CompletedProcess([], 0, b'', details)
            with mock.patch.object(probe, 'command', return_value=completed):
                identity, raw = probe.release_signature(bundle)
                self.assertEqual(identity['team_id'], 'SIGNEDTEAM')
                self.assertIn('designated =>', raw)
            for bad in (details + b'Signature=adhoc', details.replace(b'SIGNEDTEAM', b'not set'), details.replace(b'Developer ID Application', b'Apple Development')):
                with mock.patch.object(probe, 'command', return_value=subprocess.CompletedProcess([], 0, b'', bad)), self.assertRaises(RuntimeError):
                    probe.release_signature(bundle)
            with mock.patch.object(probe, 'command', side_effect=subprocess.CalledProcessError(1, 'codesign')), self.assertRaises(subprocess.CalledProcessError):
                probe.release_signature(bundle)

    def test_mac_permissions_must_belong_to_selected_signed_daemon(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Path, 'home') as home:
            home.return_value = Path(tmp)  # simulated guest, not the test host's profile
            bundle = Path(tmp) / 'CuaDriver.app'
            driver = bundle / 'Contents/MacOS/cua-driver'
            driver.parent.mkdir(parents=True)
            driver.write_bytes(b'test-only driver')
            path = Path(tmp) / 'app.json'
            app.publish(path, '', 0)
            spec = {'driver': str(driver), 'bundle': str(bundle), 'app_state': str(path), 'socket': '/test/socket'}
            signed = {'bundle_id': 'com.trycua.driver', 'team_id': 'SIGNEDTEAM'}
            permissions = {'structuredContent': {'accessibility': True, 'screen_recording': True,
                           'source': {'attribution': 'driver-daemon', 'bundle_id': signed['bundle_id'], 'executable': str(driver)}}}
            windows = {'structuredContent': {'windows': [{'pid': os.getpid(), 'window_id': 42, 'title': app.TITLE}]}}
            image = {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}]}
            for fault in ('none', 'host', 'wrong-bundle', 'wrong-executable', 'denied', 'integer-grant', 'locked', 'missing-capture', 'no-window'):
                value, listing, screenshot = copy.deepcopy(permissions), copy.deepcopy(windows), copy.deepcopy(image)
                if fault == 'host': value['structuredContent']['source']['attribution'] = 'host'
                if fault == 'wrong-bundle': value['structuredContent']['source']['bundle_id'] = 'spoofed'
                if fault == 'wrong-executable': value['structuredContent']['source']['executable'] = '/tmp/spoofed'
                if fault == 'denied': value['structuredContent']['accessibility'] = False
                if fault == 'integer-grant': value['structuredContent']['accessibility'] = 1
                if fault == 'missing-capture': screenshot = {}
                if fault == 'no-window': listing['structuredContent']['windows'] = []
                client = mock.Mock()
                client.call.side_effect = [value, listing, screenshot]
                with self.subTest(fault=fault), mock.patch.object(probe.platform, 'system', return_value='Darwin'), mock.patch.object(probe, 'release_signature', return_value=(signed, 'raw verified signature')), mock.patch.object(probe, 'mac_desktop_unlocked', return_value=fault != 'locked'), mock.patch.object(probe, 'command', return_value=subprocess.CompletedProcess([], 0, b'cua-driver pinned')), mock.patch.object(probe, 'DriverClient', return_value=client):
                    if fault == 'no-window':
                        with self.assertRaises(RuntimeError):
                            probe.probe(spec)
                    else:
                        proof = probe.probe(spec)
                        self.assertEqual(proof['permissions_ready'] and proof['interactive_desktop'], fault == 'none')
                    self.assertEqual(client.call.call_args_list[0].args, ('check_permissions', {'prompt': False}))
                    if fault in ('host', 'wrong-bundle', 'wrong-executable', 'denied', 'integer-grant', 'locked'):
                        self.assertEqual(client.call.call_count, 1)  # only read-only grant check
                    client.close.assert_called_once()

    def test_windows_session0_and_wrong_sid_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Path, 'home') as home:
            home.return_value = Path(tmp)
            state = Path(tmp) / 'app.json'
            app.publish(state, '', 0)
            spec = {'driver': sys.executable, 'app_state': str(state), 'socket': r'\\.\pipe\explicit-test-endpoint'}
            for fault in ('none', 'session0', 'wrong-sid', 'locked'):
                client = mock.Mock()
                client.call.side_effect = [
                    {'structuredContent': {'windows': [{'pid': os.getpid(), 'window_id': 42, 'title': app.TITLE}]}},
                    {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}]},
                ]
                users = [('S-1-5-21-1', 0 if fault == 'session0' else 1), ('S-1-5-21-2' if fault == 'wrong-sid' else 'S-1-5-21-1', 1)]
                with self.subTest(fault=fault), mock.patch.object(probe.platform, 'system', return_value='Windows'), mock.patch.object(probe, 'windows_process', side_effect=users), mock.patch.object(probe, 'windows_unlocked', return_value=fault != 'locked'), mock.patch.object(probe, 'command', return_value=subprocess.CompletedProcess([], 0, b'pinned-driver')), mock.patch.object(probe, 'DriverClient', return_value=client):
                    proof = probe.probe(spec)
                    self.assertEqual(proof['permissions_ready'] and proof['interactive_desktop'], fault == 'none')
                    self.assertEqual(proof['caller_session_id'], users[0][1])
                    self.assertEqual(client.call.call_count, 2 if fault == 'none' else 0)

    def test_linux_schema_uid_and_display_readiness(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Path, 'home') as home:
            home.return_value = Path(tmp)
            state = Path(tmp) / 'app.json'
            app.publish(state, '', 0)
            spec = {'driver': sys.executable, 'app_state': str(state), 'socket': '/test/socket'}
            proc = Path(f'/proc/{os.getpid()}')
            original_stat = Path.stat
            for fault in ('none', 'wrong-uid', 'locked', 'no-atspi', 'no-display', 'integer-grant'):
                permissions = {'x11': fault != 'no-display', 'atspi': fault != 'no-atspi'}
                if fault == 'integer-grant': permissions['atspi'] = 1
                client = mock.Mock()
                client.call.side_effect = [
                    {'structuredContent': permissions},
                    {'structuredContent': {'windows': [{'pid': os.getpid(), 'window_id': 42, 'title': app.TITLE}]}},
                    {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}]},
                ]
                def stat(path, *args, **kwargs):
                    if path == proc:
                        return SimpleNamespace(st_uid=1001 if fault == 'wrong-uid' else 1000)
                    return original_stat(path, *args, **kwargs)
                with self.subTest(fault=fault), mock.patch.object(probe.platform, 'system', return_value='Linux'), mock.patch.object(os, 'getuid', return_value=1000, create=True), mock.patch.object(Path, 'stat', autospec=True, side_effect=stat), mock.patch.object(probe, 'linux_unlocked', return_value=fault != 'locked'), mock.patch.object(probe, 'command', return_value=subprocess.CompletedProcess([], 0, b'pinned-driver')), mock.patch.object(probe, 'DriverClient', return_value=client):
                    proof = probe.probe(spec)
                    self.assertEqual(proof['permissions_ready'] and proof['interactive_desktop'], fault == 'none')
                    # The pinned Linux schema has no prompt property.
                    self.assertEqual(client.call.call_args_list[0].args, ('check_permissions', {}))
                    self.assertEqual(client.call.call_count, 3 if fault == 'none' else 1)

    def test_linux_logind_requires_local_active_unlocked_display(self):
        observed = b'Active=yes\nRemote=no\nState=active\nLockedHint=no\n'
        for value in (observed, observed.replace(b'LockedHint=no', b'LockedHint=yes'), observed.replace(b'Remote=no', b'Remote=yes')):
            with mock.patch.object(probe, 'command', side_effect=[subprocess.CompletedProcess([], 0, b'2\n'), subprocess.CompletedProcess([], 0, value)]):
                self.assertEqual(probe.linux_unlocked(1000), value == observed)
        with mock.patch.object(probe, 'command', return_value=subprocess.CompletedProcess([], 0, b'\n')):
            self.assertFalse(probe.linux_unlocked(1000))

    def test_proxy_uses_exact_selected_socket_never_direct_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'guest.json'
            spec = {'driver': sys.executable, 'socket': 'explicit-endpoint', 'app_state': str(Path(tmp) / 'app.json')}
            path.write_text(json.dumps(spec))
            with mock.patch.object(sys, 'argv', ['guest_probe', 'mcp', '--config', str(path)]), mock.patch.object(probe.subprocess, 'run', return_value=subprocess.CompletedProcess([], 3)) as run:
                self.assertEqual(probe.main(), 3)
                run.assert_called_once_with([sys.executable, 'mcp', '--embedded', '--socket', 'explicit-endpoint'], check=False)
            spec['permissions_ready'] = True
            with self.assertRaises(ValueError): probe.validate_spec(spec)

    def test_fresh_mailbox_challenge_rejects_stale_response(self):
        for wrong in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                (directory / ('response-' + '0' * 32 + '.json')).write_text('{"proof":{"permissions_ready":true}}')
                errors = []
                def responder():
                    try:
                        deadline = time.monotonic() + 2
                        while time.monotonic() < deadline:
                            requests = list(directory.glob('request-*.json'))
                            if requests:
                                nonce = requests[0].stem.removeprefix('request-')
                                value = {'request_id': 'wrong' if wrong else nonce, 'proof': {'os': 'windows'}}
                                out = directory / f'response-{nonce}.json'
                                temporary = out.with_suffix('.tmp')
                                temporary.write_text(json.dumps(value))
                                temporary.replace(out)
                                return
                            time.sleep(0.01)
                        errors.append('no request')
                    except Exception as error:
                        errors.append(str(error))
                child = threading.Thread(target=responder)
                child.start()
                if wrong:
                    with self.assertRaisesRegex(RuntimeError, 'mismatched'):
                        probe.mailbox_request(directory, timeout=2)
                else:
                    self.assertEqual(probe.mailbox_request(directory, timeout=2), {'os': 'windows'})
                child.join(timeout=3)
                self.assertFalse(errors, errors)
                self.assertFalse(list(directory.glob('request-*.json')))
                self.assertEqual(len(list(directory.glob('response-*.json'))), 1)  # unrelated stale response untouched

    def test_missing_probe_agent_does_not_reuse_old_ready_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'ready.json').write_text('{"permissions_ready":true}')
            with self.assertRaises(TimeoutError):
                probe.mailbox_request(directory, timeout=0.01)
            self.assertFalse(list(directory.glob('request-*.json')))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native read-only API')
    def test_real_windows_process_identity_api(self):
        sid, session = probe.windows_process(os.getpid())
        self.assertRegex(sid, r'^S-1-')
        self.assertIsInstance(session, int)
        self.assertIsInstance(probe.windows_unlocked(), bool)

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS native read-only API')
    def test_real_mac_session_read_api(self):
        self.assertIsInstance(probe.mac_desktop_unlocked(), bool)


class OracleIntegrationTests(unittest.TestCase):
    def test_external_oracle_rejects_ack_only_and_grades_persisted_state(self):
        for mutate in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                cfg = config()
                for name, target in cfg['targets'].items():
                    path = Path(tmp) / f'{name}.json'
                    target['reset'] = [sys.executable, '-c', f'from gui_gate.native_probe import publish; from pathlib import Path; publish(Path({str(path)!r}), "", 0)']
                    target['oracles'] = {'app': [sys.executable, '-m', 'gui_gate.native_probe', 'oracle', '--state', str(path)]}
                    from test_runner import MCP
                    program = MCP.replace("else: result =", f"else:\n        {'from gui_gate.native_probe import publish; from pathlib import Path; publish(Path(' + repr(str(path)) + '), request[\"params\"][\"arguments\"].get(\"value\", \"\"), 1)' if mutate else 'pass'}\n        result =")
                    target['mcp'] = [sys.executable, '-u', '-c', program]
                task = {'version': 1, 'steps': [
                    {'id': 'before', 'oracle': 'app', 'assert': [{'path': '/structuredContent/text', 'op': 'equals', 'value': ''}]},
                    {'id': 'write', 'tool': 'observe', 'arguments': {'value': {'$ref': '/run_id'}}},
                    {'id': 'after', 'oracle': 'app', 'assert': [{'path': '/structuredContent/text', 'op': 'equals', 'value': {'$ref': '/run_id'}}]},
                ]}
                campaign, summary = runner.run(cfg, task, Path(tmp) / 'evidence', 2)
                self.assertEqual(summary['passed'], mutate, summary)
                self.assertEqual(len(summary['runs']), 2)
                for reports in summary['runs']:
                    for report in reports:
                        self.assertIn('evidence', report['steps'][-1])
                        self.assertEqual(report['steps'][-1]['passed'], mutate)
                self.assertTrue((campaign / 'run-0000/windows/oracle-002.stdout').exists())
                owners = [report['lease_owner'] for reports in summary['runs'] for report in reports]
                self.assertEqual(len(set(owners)), 6)

    def test_invalid_oracle_configuration_rejected_before_dispatch(self):
        base = {'version': 1, 'steps': [{'id': 'read', 'oracle': 'app', 'assert': [{'path': '', 'op': 'equals', 'value': {}}]}]}
        cfg = config()
        for target in cfg['targets'].values(): target['oracles'] = {'app': [sys.executable, '-c', 'pass']}
        for fault in ('no-gui', 'both', 'missing', 'shell'):
            task, candidate = copy.deepcopy(base), copy.deepcopy(cfg)
            if fault == 'both': task['steps'][0]['tool'] = 'observe'
            if fault == 'missing': candidate['targets']['linux']['oracles'] = {}
            if fault == 'shell': candidate['targets']['windows']['oracles']['app'] = 'echo ready'
            with self.subTest(fault=fault), self.assertRaises(ValueError): runner.validate(candidate, task)


if __name__ == '__main__':
    unittest.main()
