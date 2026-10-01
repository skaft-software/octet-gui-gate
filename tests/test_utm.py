"""UTM protocol/state-machine tests. These are NOT live VM qualification."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gui_gate.utm import UTM

VM = '16fd2706-8baf-433b-82eb-8c7fada847da'
SNAPSHOT = '16fd2706-8baf-433b-82eb-8c7fada847db'


class FakeUTM:
    def __init__(self):
        self.state = 'stopped'
        self.disk = ''
        self.golden = ''
        self.memory = True
        self.missing = False
        self.calls = []
        self.restore_fails = False
        self.restore_stuck = False

    def command(self, *args):
        self.calls.append(args)
        if args[:2] == ('snapshot', 'list'):
            return json.dumps([{'id': SNAPSHOT.upper(), 'dataMissing': self.missing, 'includesRunningState': self.memory}])
        if args[:2] == ('snapshot', 'restore'):
            if self.restore_fails:
                raise RuntimeError('simulated restore failure')
            if self.state != 'stopped':
                raise RuntimeError('cannot restore while running')
            self.disk = self.golden
            if self.restore_stuck:
                self.state = 'restoring'
            return ''
        if args[0] == 'status':
            return self.state
        if args[0] == 'start':
            self.state = 'started'
        elif args[0] == 'stop':
            self.state = 'stopped'
        else:
            raise AssertionError(args)
        return ''


class UTMTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lease = Path(self.tmp.name) / 'lease'
        self.spec = {'vm_uuid': VM, 'snapshot_uuid': SNAPSHOT, 'os': 'windows',
                     'utmctl': sys.executable, 'utmctl_sha256': hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                     'probe': [sys.executable, '-c', 'pass'],
                     'identity': {'sid': 'pinned'}}
        self.proof = {'os': 'windows', 'identity': self.spec['identity'],
                      'permissions_ready': True, 'interactive_desktop': True}
        self.backend = UTM(self.spec, self.lease, 'first', timeout=5)
        self.fake = FakeUTM()
        self.backend.command = self.fake.command
        self.backend.probe = mock.Mock(side_effect=lambda: copy.deepcopy(self.proof))

    def test_rollback_ownership_and_repeated_loop(self):
        for index in range(20):
            proof = self.backend.reset()
            self.assertEqual(self.fake.disk, '')
            self.assertTrue(proof['backend']['includes_running_state'])
            self.fake.disk = f'marker-{index}'
            self.assertEqual(self.backend.verify()['identity'], self.spec['identity'])
            self.backend.destroy()
            self.assertEqual(self.fake.disk, '')
            self.assertEqual(self.fake.golden, '')
            self.assertFalse(self.lease.exists())
        self.assertFalse(any('delete' in args or 'overwrite' in args for args in self.fake.calls))

    def test_foreign_campaign_cannot_clean_up_current_owner(self):
        self.backend.reset()
        before = list(self.fake.calls)
        other = UTM(self.spec, self.lease, 'other')
        other.command = self.fake.command
        with self.assertRaises(FileExistsError):
            other.reset()
        other.destroy()  # runner always tries cleanup after failed reset
        self.assertEqual(self.fake.calls, before)
        self.assertTrue(self.lease.exists())
        with self.assertRaises(RuntimeError):
            other.verify()
        self.backend.destroy()

    def test_interrupted_claim_is_not_stolen(self):
        self.lease.mkdir()
        with self.assertRaises(FileExistsError):
            self.backend.reset()
        with self.assertRaises(FileNotFoundError):
            self.backend.destroy()
        self.assertEqual(self.fake.calls, [])
        self.assertTrue(self.lease.exists())

    def test_disk_only_checkpoint_not_silently_accepted(self):
        self.fake.memory = False
        with self.assertRaisesRegex(RuntimeError, 'running state'):
            self.backend.reset()
        self.assertEqual(self.fake.state, 'stopped')
        self.assertTrue(self.lease.exists())

    def test_explicit_cold_boot_does_not_claim_memory_snapshot(self):
        self.spec['require_running_state'] = False
        self.fake.memory = False
        self.assertFalse(self.backend.reset()['backend']['includes_running_state'])
        self.backend.destroy()

    def test_incomplete_checkpoint_is_rejected(self):
        self.fake.missing = True
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            self.backend.reset()
        self.assertFalse(any(args[0] == 'start' for args in self.fake.calls))

    def test_cleanup_failure_keeps_lease(self):
        self.backend.reset()
        self.fake.restore_fails = True
        with self.assertRaisesRegex(RuntimeError, 'restore failure'):
            self.backend.destroy()
        self.assertTrue(self.lease.exists())
        self.assertEqual(self.fake.state, 'stopped')
        self.fake.restore_fails = False
        self.backend.destroy()
        self.backend.destroy()  # idempotent

    def test_failed_readiness_can_be_reconciled(self):
        self.backend.timeout = 0.01
        self.backend.probe.side_effect = RuntimeError('desktop locked')
        with self.assertRaises(TimeoutError):
            self.backend.reset()
        self.assertTrue(self.lease.exists())
        self.backend.timeout = 5
        self.backend.destroy()
        self.assertFalse(self.lease.exists())

    def test_probe_reads_observed_identity_not_pin(self):
        real = UTM(self.spec, self.lease, 'test')
        for change in ('os', 'identity', 'permissions_ready', 'interactive_desktop', 'fixture'):
            proof = copy.deepcopy(self.proof)
            proof[change] = {'sid': 'different'} if change == 'identity' else ('linux' if change == 'os' else (True if change == 'fixture' else 1))
            with self.subTest(change=change), mock.patch('gui_gate.utm.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(proof).encode())), self.assertRaises(RuntimeError):
                real.probe()

    def test_explicit_argv_protocol_and_timeout(self):
        real = UTM(self.spec, self.lease, 'test', timeout=7)
        with mock.patch('gui_gate.utm.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'stopped\n')) as run:
            self.assertEqual(real.status(), 'stopped')
            run.assert_called_once_with([sys.executable, 'status', VM], capture_output=True, timeout=7, check=True)

    def test_restore_ack_without_completed_state_keeps_lease(self):
        for phase in ('reset', 'destroy'):
            with self.subTest(phase=phase):
                if phase == 'destroy': self.backend.reset()
                self.fake.restore_stuck = True
                self.backend.timeout = .01
                before = len(self.fake.calls)
                with self.assertRaises(TimeoutError): getattr(self.backend, phase)()
                self.assertTrue(self.lease.exists())
                self.assertFalse(any(call[0] == 'start' for call in self.fake.calls[before:]))
                self.fake.restore_stuck = False
                self.fake.state = 'stopped'
                self.backend.timeout = 5
                self.backend.destroy()

    def test_total_deadline_prevents_another_subprocess(self):
        real = UTM(self.spec, self.lease, 'test', timeout=7)
        real.deadline = 9
        with mock.patch('gui_gate.utm.time.monotonic', return_value=10), mock.patch('gui_gate.utm.subprocess.run') as run:
            with self.assertRaises(TimeoutError): real.status()
            run.assert_not_called()

    def test_owner_and_uuid_required(self):
        with self.assertRaises(ValueError):
            UTM(self.spec, self.lease, None)
        self.spec['vm_uuid'] = 'an ambiguous VM name'
        with self.assertRaises(ValueError):
            UTM(self.spec, self.lease, 'test')

    def test_host_platform_is_not_guessed(self):
        if sys.platform == 'darwin':
            return
        result = subprocess.run([sys.executable, '-m', 'gui_gate.utm', 'reset', '--descriptor', 'missing'], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'Apple Silicon', result.stderr)


if __name__ == '__main__':
    unittest.main()
