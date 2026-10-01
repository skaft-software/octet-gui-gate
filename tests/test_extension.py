import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import extension
from gui_gate.job import Jobs
from gui_gate import runner
from test_runner import config, scenario


def initialize():
    return {'api_version': '0.4', 'contributes': {'commands': ['gui-gate'], 'tools': ['gui_gate_status'], 'confirmations': True},
            'protocol': {'version': '0.4', 'required_features': ['request_cancellation', 'content_parts'], 'optional_features': [], 'limits': {'max_concurrent_requests': 1}}}


class ExtensionTests(unittest.TestCase):
    def test_manifest_and_protocol_handshake(self):
        # Exercise actual framed SDK initialization through the executable.
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': initialize()},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'command/execute', 'params': {'name': 'gui-gate', 'arguments': []}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            child = subprocess.run([sys.executable, 'extension.py'], input='\n'.join(json.dumps(m) for m in messages) + '\n', text=True, capture_output=True, timeout=10, env={**os.environ, 'OCTET_STATE_DIR': tmp})
        self.assertEqual(child.returncode, 0, child.stderr)
        frames = [json.loads(line) for line in child.stdout.splitlines()]
        hello = next(f['result'] for f in frames if f.get('id') == 1)
        self.assertEqual(hello['api_version'], '0.4')
        self.assertEqual([t['name'] for t in hello['tools']], ['gui_gate_status'])
        self.assertEqual([c['name'] for c in hello['commands']], ['gui-gate'])
        usage = next(f['result'] for f in frames if f.get('id') == 2)
        self.assertIn('/gui-gate run', usage['text'])

    def test_declined_command_never_starts_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext, jobs = extension.create_extension(Path(tmp) / 'state')
            cfg, task = Path(tmp) / 'cfg.json', Path(tmp) / 'task.json'
            runner.save(cfg, config())
            runner.save(task, scenario())
            with mock.patch.object(type(ext), 'cancellation', new_callable=mock.PropertyMock, return_value=mock.Mock()), mock.patch.object(ext, 'confirm', return_value=False) as confirm, mock.patch.object(jobs, 'start') as start:
                result = ext._commands['gui-gate'].handler(['run', str(cfg), str(task)], {})
            confirm.assert_called_once()
            start.assert_not_called()
            self.assertIn('declined', result['text'])

    def test_command_returns_job_and_status_tool_declares_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext, jobs = extension.create_extension(tmp)
            with mock.patch.object(type(ext), 'cancellation', new_callable=mock.PropertyMock, return_value=mock.Mock()), mock.patch.object(jobs, 'load', return_value=(config(), scenario(), 2)), mock.patch.object(ext, 'confirm', return_value=True), mock.patch.object(jobs, 'start', return_value={'job_id': 'a' * 32}) as start:
                result = ext._commands['gui-gate'].handler(['run', 'cfg', 'task', '2'], {})
            self.assertEqual(json.loads(result['text'])['job_id'], 'a' * 32)
            start.assert_called_once()
            self.assertEqual(ext._tools['gui_gate_status'].output_schema, {'type': 'object'})

    def test_status_never_executes_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext, jobs = extension.create_extension(tmp)
            with mock.patch('subprocess.Popen') as process:
                result = ext._tools['gui_gate_status'].handler({'job_id': '../escape'}, {})
            self.assertTrue(result['is_error'])
            process.assert_not_called()


class JobTests(unittest.TestCase):
    def test_background_campaign_and_restart_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Jobs(tmp)
            status = jobs.start(config(), scenario(), 1)
            child = jobs.children[status['job_id']]
            self.assertEqual(child.wait(timeout=20), 0)
            status = Jobs(tmp).status(status['job_id'])
            self.assertEqual(status['status'], 'finished')
            self.assertTrue(status['passed'], status)
            self.assertTrue(Path(status['summary']).exists())

    def test_cancel_before_run_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cancel = Path(tmp) / 'cancel'
            cancel.touch()
            with mock.patch.object(runner, 'run_target') as dispatch:
                _, summary = runner.run(config(), scenario(), Path(tmp), 4, cancel)
            self.assertTrue(summary['cancelled'])
            self.assertFalse(summary['passed'])
            dispatch.assert_not_called()

    def test_cancellation_during_reset_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            cancel = Path(tmp) / 'cancel'
            cfg = config()['targets']['windows']
            original = runner.hook
            phases = []
            def cancel_reset(command, directory, phase, timeout):
                phases.append(phase)
                if phase == 'reset': cancel.touch()
                return original(command, directory, phase, timeout)
            with mock.patch.object(runner, 'hook', side_effect=cancel_reset):
                report = runner.run_target('windows', cfg, scenario(), Path(tmp) / 'windows', 10, cancel)
            self.assertFalse(report['passed'])
            self.assertEqual(phases, ['reset', 'destroy'])

    def test_shutdown_requests_cleanup_not_process_kill(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Jobs(tmp)
            job_id = 'b' * 32
            directory = Path(tmp) / job_id
            directory.mkdir()
            runner.save(directory / 'job.json', {'job_id': job_id})
            child = mock.Mock()
            child.poll.return_value = None
            jobs.children[job_id] = child
            jobs.shutdown()
            self.assertTrue((directory / 'cancel').exists())
            child.kill.assert_not_called()
            child.terminate.assert_not_called()

    def test_unknown_worker_is_not_reported_green_or_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_id = 'c' * 32
            directory = Path(tmp) / job_id
            directory.mkdir()
            runner.save(directory / 'job.json', {'job_id': job_id})
            self.assertEqual(Jobs(tmp).status(job_id)['status'], 'unknown')

    def test_second_campaign_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Jobs(tmp)
            child = mock.Mock()
            child.poll.return_value = None
            jobs.children['owned'] = child
            with self.assertRaises(RuntimeError): jobs.start(config(), scenario(), 1)


if __name__ == '__main__':
    unittest.main()
