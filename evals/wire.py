"""Evaluate the installed extension protocol, not mocked Python handlers."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from .run import inputs, events, ROOT, TARGETS


class Host:
    def __init__(self, state):
        self.process = subprocess.Popen([sys.executable, str(ROOT / 'extension.py')], cwd=ROOT,
                                        env={**os.environ, 'OCTET_STATE_DIR': str(state),
                                             'ANTHROPIC_API_KEY': 'eval-dummy-not-a-secret',
                                             'OPENAI_API_KEY': 'eval-dummy-not-a-secret'},
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lines = queue.Queue()
        self.next_id = 0
        self.confirmations = 0
        self.transcript = []
        def read():
            for line in self.process.stdout:
                self.lines.put(json.loads(line))
            self.lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        self.request('initialize', {'api_version': '0.4', 'contributes': {'commands': ['gui-gate'], 'tools': ['gui_gate_status'], 'confirmations': True},
                                   'protocol': {'version': '0.4', 'required_features': ['request_cancellation', 'content_parts'], 'optional_features': [], 'limits': {'max_concurrent_requests': 1}}})

    def send(self, frame):
        self.transcript.append({'direction': 'host-to-extension', 'frame': frame})
        self.process.stdin.write((json.dumps(frame) + '\n').encode('utf-8'))
        self.process.stdin.flush()

    def request(self, method, params, approval=True):
        self.next_id += 1
        identifier = self.next_id
        self.send({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params})
        deadline = time.monotonic() + 15
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(method)
            frame = self.lines.get(timeout=remaining)
            if frame is None:
                raise RuntimeError('extension closed protocol output')
            self.transcript.append({'direction': 'extension-to-host', 'frame': frame})
            if frame.get('method') == 'confirmation/request':
                self.confirmations += 1
                response = {'error': {'code': -32000, 'message': 'confirmation unavailable'}} if approval == 'unavailable' else {'result': {'confirmed': approval}}
                self.send({'jsonrpc': '2.0', 'id': frame['id'], **response})
            elif frame.get('id') == identifier:
                return frame

    def status(self, job_id):
        return self.request('tool/call', {'name': 'gui_gate_status', 'arguments': {'job_id': job_id}})['result']['structured_content']

    def close(self):
        if self.process.poll() is None:
            try:
                self.request('shutdown', {})
                self.process.wait(timeout=10)
            except Exception:
                self.process.terminate()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


def evaluate_wire(directory, mode):
    directory.mkdir(parents=True)
    fixture = directory / 'fixture'
    cfg, scenario = inputs(fixture, 'slow_reset' if mode in ('cancel', 'shutdown') else 'none', 'all')
    (directory / 'config.json').write_text(json.dumps(cfg), encoding='utf-8')
    (directory / 'scenario.json').write_text(json.dumps(scenario), encoding='utf-8')
    host = Host(directory / 'state')
    checks = []
    def check(name, passed): checks.append({'check': name, 'passed': bool(passed)})
    try:
        if mode == 'unknown-tool':
            response = host.request('tool/call', {'name': 'gui_gate_run', 'arguments': {}})
            check('no-model-callable-launch-tool', 'error' in response)
            check('no-lifecycle-dispatch', all(not events(fixture, name) for name in TARGETS))
        else:
            approval = False if mode == 'decline' else 'unavailable' if mode == 'unavailable' else True
            response = host.request('command/execute', {'name': 'gui-gate', 'arguments': ['run', str(directory / 'config.json'), str(directory / 'scenario.json'), '1']}, approval)
            check('exactly-one-workflow-confirmation', host.confirmations == 1)
            if mode in ('decline', 'unavailable'):
                check('no-lifecycle-dispatch', all(not events(fixture, name) for name in TARGETS))
                check('no-background-job', not list((directory / 'state').glob('gui-gate/*/job.json')))
            else:
                started = json.loads(response['result']['text'])
                job_id = started['job_id']
                check('returns-job-before-completion', started['status'] == 'running')
                if mode in ('cancel', 'shutdown'):
                    deadline = time.monotonic() + 10
                    while not any(events(fixture, name) for name in TARGETS):
                        if time.monotonic() > deadline: raise TimeoutError('reset did not start')
                        time.sleep(0.01)
                    if mode == 'cancel':
                        host.request('command/execute', {'name': 'gui-gate', 'arguments': ['cancel', job_id]})
                    else:
                        host.request('shutdown', {})
                        host.process.wait(timeout=10)
                deadline = time.monotonic() + 20
                terminal_path = directory / 'state' / 'gui-gate' / job_id / 'terminal.json'
                while not terminal_path.exists():
                    if time.monotonic() > deadline: raise TimeoutError('no terminal evidence')
                    time.sleep(0.02)
                terminal = json.loads(terminal_path.read_text(encoding='utf-8'))
                check('expected-terminal-outcome', terminal['passed'] is (mode == 'approve'))
                if mode == 'approve':
                    observed = host.status(job_id)
                    check('read-only-tool-observes-real-terminal', observed['passed'] is True and observed['status'] == 'finished')
                    summary_path = Path(terminal['summary'])
                    summary = json.loads(summary_path.read_text(encoding='utf-8'))
                    check('three-target-suite-green', len(summary['runs']) == 1 and all(r['passed'] for r in summary['runs'][0]))
                    proofs = [json.loads((summary_path.parent / 'run-0000' / name / 'verify.stdout').read_text(encoding='utf-8')) for name in TARGETS]
                    check('provider-credentials-not-forwarded', all(p['provider_secret_present'] is False for p in proofs))
                else:
                    check('cancelled-not-green', terminal['cancelled'] is True)
                    kinds = {name: [e['kind'] for e in events(fixture, name)] for name in TARGETS}
                    check('no-actions-after-cancelled-reset', all('write' not in k and 'read' not in k for k in kinds.values()))
                    check('cleanup-for-started-targets', all('destroy_done' in k for k in kinds.values() if 'reset' in k))
    finally:
        host.close()
        (directory / 'protocol.json').write_text(json.dumps(host.transcript, indent=2), encoding='utf-8')
    return checks
