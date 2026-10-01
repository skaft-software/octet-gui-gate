"""Lease-fenced lifecycle for pre-provisioned UTM VMs on Apple Silicon.

Only explicit pinned VM/snapshot UUIDs are addressed. No OS permission grants,
VM deletion, image download, daemon installation, or snapshot overwrite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid

from .runner import argv, json_equal, save


class UTM:
    def __init__(self, descriptor, lease, owner, timeout=120):
        self.spec = descriptor
        self.lease = Path(lease).resolve()
        self.timeout = timeout
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be finite and positive')
        self.deadline = None
        if not isinstance(owner, str) or not owner:
            raise ValueError('OCTET_GUI_GATE_OWNER fencing token is required')
        self.owner = owner
        self.vm = str(uuid.UUID(descriptor['vm_uuid']))
        self.snapshot = str(uuid.UUID(descriptor['snapshot_uuid']))
        self.binary = descriptor['utmctl']
        if not Path(self.binary).is_absolute():
            raise ValueError('utmctl must be an absolute executable path')
        with Path(self.binary).open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        self.binary_sha256 = digest.hexdigest()
        if self.binary_sha256 != descriptor['utmctl_sha256']:
            raise ValueError('utmctl hash differs from the pinned backend')
        if descriptor['os'] not in ('macos', 'windows', 'linux'):
            raise ValueError('unsupported guest OS')
        argv(descriptor['probe'])
        if not isinstance(descriptor['identity'], dict) or not descriptor['identity']:
            raise ValueError('pinned guest identity required')
        if type(descriptor.get('require_running_state', True)) is not bool:
            raise ValueError('require_running_state must be boolean')

    def remaining(self):
        if self.deadline is None:
            return self.timeout
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('UTM operation exceeded its total deadline; lease retained')
        return remaining

    def command(self, *args):
        result = subprocess.run([self.binary, *args], capture_output=True, timeout=self.remaining(), check=True)
        return result.stdout.decode('utf-8').strip()

    def status(self):
        return self.command('status', self.vm)

    def wait_stopped(self):
        deadline = time.monotonic() + self.timeout
        while self.status() != 'stopped':
            if time.monotonic() >= deadline:
                raise TimeoutError('VM did not stop; lease retained')
            time.sleep(0.2)

    def snapshot_info(self):
        snapshots = json.loads(self.command('snapshot', 'list', self.vm, '--json'))
        matches = [row for row in snapshots if str(uuid.UUID(row['id'])) == self.snapshot]
        if len(matches) != 1 or matches[0]['dataMissing'] is not False:
            raise RuntimeError('pinned checkpoint is missing or incomplete')
        if self.spec.get('require_running_state', True) and matches[0]['includesRunningState'] is not True:
            raise RuntimeError('checkpoint lacks running state; refusing a silent cold-boot fallback')
        return matches[0]

    def acquire(self):
        # mkdir is an atomic, cross-process claim. Never steal a stale lease;
        # recovery is explicit and must inspect the UTM instance first.
        self.lease.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lease.mkdir(mode=0o700)
        save(self.lease / 'owner.json', {'vm_uuid': self.vm, 'snapshot_uuid': self.snapshot,
                                       'owner': self.owner, 'owner_pid': os.getpid(),
                                       'claimed_at_unix_ns': time.time_ns()})

    def owned(self):
        record = json.loads((self.lease / 'owner.json').read_text(encoding='utf-8'))
        if record['vm_uuid'] != self.vm or record['snapshot_uuid'] != self.snapshot:
            raise RuntimeError('lease does not belong to this VM/checkpoint')
        return record['owner'] == self.owner

    def probe(self):
        result = subprocess.run(argv(self.spec['probe']), capture_output=True, timeout=self.remaining(), check=True)
        proof = json.loads(result.stdout.decode('utf-8'))
        json.dumps(proof, allow_nan=False)
        if proof.get('fixture') or proof.get('os') != self.spec['os'] or not json_equal(proof.get('identity'), self.spec['identity']):
            raise RuntimeError('real guest OS/identity does not match baseline')
        if proof.get('permissions_ready') is not True or proof.get('interactive_desktop') is not True:
            raise RuntimeError('desktop/permission probe is not ready')
        return proof

    def reset(self):
        self.deadline = time.monotonic() + self.timeout
        self.acquire()
        snapshot = self.snapshot_info()
        if self.status() != 'stopped':
            self.command('stop', self.vm)
            self.wait_stopped()
        self.command('snapshot', 'restore', self.vm, '--snapshot', self.snapshot)
        self.wait_stopped()
        self.command('start', self.vm)
        deadline = self.deadline
        last_error = None
        while time.monotonic() < deadline:
            try:
                proof = self.probe()
                proof['backend'] = {'name': 'utm', 'vm_uuid': self.vm, 'snapshot_uuid': self.snapshot,
                                    'includes_running_state': snapshot['includesRunningState'],
                                    'utmctl_sha256': self.binary_sha256}
                save(self.lease / 'ready.json', proof)
                return proof
            except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
                last_error = error
                time.sleep(0.2)
        raise TimeoutError(f'guest readiness timed out: {last_error}')

    def verify(self):
        self.deadline = time.monotonic() + self.timeout
        if not self.owned():
            raise RuntimeError('another campaign owns this VM')
        # Do not trust a stale ready.json or echo pinned configuration.
        proof = self.probe()
        snapshot = self.snapshot_info()
        proof['backend'] = {'name': 'utm', 'vm_uuid': self.vm, 'snapshot_uuid': self.snapshot,
                            'includes_running_state': snapshot['includesRunningState'],
                            'utmctl_sha256': self.binary_sha256}
        return proof

    def destroy(self):
        self.deadline = time.monotonic() + self.timeout
        if not self.lease.exists():
            return
        if not self.owned():
            # reset may have failed before claiming: never clean up its owner.
            return
        if self.status() != 'stopped':
            self.command('stop', self.vm)
            self.wait_stopped()
        # Restore state covered by UTM's checkpoint before releasing ownership.
        # A restore failure keeps the lease and blocks future campaigns.
        self.snapshot_info()
        self.command('snapshot', 'restore', self.vm, '--snapshot', self.snapshot)
        self.wait_stopped()
        (self.lease / 'ready.json').unlink(missing_ok=True)
        (self.lease / 'owner.json').unlink()
        self.lease.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('reset', 'verify', 'destroy'))
    parser.add_argument('--descriptor', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine().lower() not in ('arm64', 'aarch64'):
        parser.error('this backend requires the operator-owned Apple Silicon macOS host')
    try:
        spec = json.loads(args.descriptor.read_text(encoding='utf-8'))
        lease = Path.home() / 'Library' / 'Application Support' / 'octet-gui-gate' / 'leases' / str(uuid.UUID(spec['vm_uuid']))
        backend = UTM(spec, lease, os.environ.get('OCTET_GUI_GATE_OWNER'), spec.get('timeout_seconds', 120))
        proof = getattr(backend, args.action)()
        if proof is not None:
            print(json.dumps(proof, ensure_ascii=False, allow_nan=False))
    except Exception as error:
        print(f'UTM lifecycle failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
