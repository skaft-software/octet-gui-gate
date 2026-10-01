"""Independent raw-evidence audit of the bundled native calibration scenario.

This audits a trusted operator's campaign, not authenticity or a complete product
release. Rebuild, entitlement, device-state, negative live controls, and host
resource qualification still require separate retained acceptance evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import uuid

from .guest_probe import capture_present

OS_NAMES = ('macos', 'windows', 'linux')
SCENARIO = Path(__file__).resolve().parents[1] / 'examples' / 'native-probe.scenario.json'


def load(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    json.dumps(value, allow_nan=False)
    return value


def equal(left, right):
    # Deliberately independent from runner.assert_evidence/json_equal.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def audit(directory):
    checks, waves, resets, wave_intervals = [], [], [], []
    result = {'schema': 'octet.gui-gate.calibration-audit.v1', 'campaign': str(directory),
              'campaign_audit_passed': False, 'product_qualified': False, 'checks': checks,
              'release_blockers': ['live negative controls', 'rebuild/permission persistence',
                                   'coupled firmware/TPM/device state', 'Windows entitlement',
                                   'host resource/headroom measurements', 'intended application qualification']}

    def check(label, passed):
        checks.append({'check': label, 'passed': bool(passed)})

    try:
        summary, config, scenario = (load(directory / name) for name in ('summary.json', 'config.json', 'scenario.json'))
        check('exact-calibration-scenario', equal(scenario, load(SCENARIO)))
        for name in ('config', 'scenario'):
            check(f'{name}-integrity', hashlib.sha256((directory / f'{name}.json').read_bytes()).hexdigest() == summary[f'{name}_sha256'])
        check('apple-silicon-host', summary['host']['os'] == 'Darwin' and summary['host']['architecture'].lower() in ('arm64', 'aarch64'))
        check('campaign-green', summary['passed'] is True and not summary.get('cancelled'))
        check('all-platforms-configured', set(config['targets']) == set(OS_NAMES))
        count = summary['requested_repetitions']
        check('at-least-20-completed-waves', type(count) is int and count >= 20 and len(summary['runs']) == count)
        budgets = config['acceptance']
        required = {'max_wave_seconds', 'max_reset_seconds', 'max_campaign_seconds'}
        if set(budgets) != required or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in budgets.values()):
            raise ValueError('all three predeclared finite positive acceptance budgets required')
        ids, challenges, backends = set(), set(), {}
        for index, reports in enumerate(summary['runs']):
            check(f'{index}:target-coverage', [r['target'] for r in reports] == list(OS_NAMES))
            starts, finishes, ready, done, vm_ids = [], [], [], [], []
            for report in reports:
                name = report['target']
                if name not in OS_NAMES:
                    raise ValueError('unknown target')
                prefix = f'{index}:{name}'
                root = directory / f'run-{index:04d}' / name
                check(prefix + ':durable-report', equal(report, load(root / 'report.json')))
                check(prefix + ':clean-green', report['passed'] is True and not any(k in report for k in ('error', 'cleanup_error', 'close_error')))
                proof = load(root / 'verify.stdout')
                check(prefix + ':observed-proof', equal(proof, report['guest']))
                check(prefix + ':not-synthetic', not proof.get('fixture') and proof['os'] == name)
                check(prefix + ':identity', equal(proof['identity'], config['targets'][name]['identity']))
                check(prefix + ':desktop-grants', proof['permissions_ready'] is True and proof['interactive_desktop'] is True
                      and proof['desktop_session_unlocked'] is True and capture_present(proof['desktop_observation']))
                identity = proof['identity']
                check(prefix + ':pinned-artifacts', all(re.fullmatch('[0-9a-f]{64}', identity[k]) for k in ('driver_sha256', 'native_app_sha256')))
                if name == 'macos':
                    permission = proof['permission_observation']['structuredContent']
                    source = permission['source']
                    check(prefix + ':release-signed-daemon-tcc', permission['accessibility'] is True and permission['screen_recording'] is True
                          and source['attribution'] == 'driver-daemon' and source['bundle_id'] == identity['bundle_id']
                          and source['executable'] == proof['driver_path'] and bool(identity['team_id'])
                          and bool(identity['designated_requirement']) and 'Authority=Developer ID Application:' in proof['signature_evidence'])
                elif name == 'windows':
                    session = proof['app_session_id']
                    check(prefix + ':same-interactive-sid', bool(re.fullmatch(r'S-1-\d+(?:-\d+)+', identity['account_sid']))
                          and proof['app_account_sid'] == identity['account_sid'] and type(session) is int and session > 0
                          and equal(proof['caller_session_id'], session))
                else:
                    permission = proof['permission_observation']['structuredContent']
                    check(prefix + ':graphical-user-atspi', type(identity['uid']) is int and equal(proof['app_uid'], identity['uid'])
                          and permission['atspi'] is True and (permission.get('x11') is True
                          or (permission.get('wayland') is True and permission.get('wayland_enabled') is True)))
                nonce = proof['probe_request_id']
                check(prefix + ':fresh-challenge', isinstance(nonce, str) and re.fullmatch('[0-9a-f]{32}', nonce) and nonce not in challenges)
                challenges.add(nonce)
                backend = proof['backend']
                vm_id = str(uuid.UUID(backend['vm_uuid']))
                uuid.UUID(backend['snapshot_uuid'])
                check(prefix + ':utm-checkpoint', backend['name'] == 'utm' and type(backend['includes_running_state']) is bool
                      and vm_id == str(uuid.UUID(config['targets'][name]['resource']))
                      and bool(re.fullmatch('[0-9a-f]{64}', backend['utmctl_sha256'])))
                backends.setdefault(name, backend)
                check(prefix + ':unchanged-checkpoint-backend', equal(backend, backends[name]))
                vm_ids.append(vm_id)
                lease = report['lease_owner']
                check(prefix + ':distinct-lease', lease not in ids)
                ids.add(lease)
                check(prefix + ':synchronized-desktops', report['all_desktops_synchronized'] is True)
                interval = [report[k] for k in ('started_monotonic_ns', 'desktop_ready_monotonic_ns',
                                               'desktop_finished_monotonic_ns', 'finished_monotonic_ns')]
                check(prefix + ':ordered-interval', all(type(t) is int for t in interval) and interval == sorted(interval) and interval[1] < interval[2])
                starts.append(interval[0]); ready.append(interval[1]); done.append(interval[2]); finishes.append(interval[3])
                resets.append(report['timings_seconds']['reset'])
                raw = []
                expected_steps = scenario['steps']
                check(prefix + ':all-steps', len(report['steps']) == 4 and [s['id'] for s in report['steps']] == [s['id'] for s in expected_steps])
                for step_index, step in enumerate(report['steps']):
                    # Fixed filenames prevent untrusted report path traversal.
                    path = root / f'step-{step_index:03d}.json'
                    check(prefix + f':{step_index}:evidence-integrity', step['evidence'] == path.name and hashlib.sha256(path.read_bytes()).hexdigest() == step['sha256'])
                    expected = expected_steps[step_index]
                    kind = 'tool' if 'tool' in expected else 'oracle'
                    check(prefix + f':{step_index}:operation', step.get(kind) == expected[kind])
                    value = load(path)
                    check(prefix + f':{step_index}:no-tool-error', step['passed'] is True and not value['result'].get('isError') and not value['result'].get('is_error'))
                    raw.append(value)
                before, observe, write, after = raw
                marker = directory.name + f'/run-{index:04d}'
                pid, window = proof['window']['pid'], proof['window']['window_id']
                pristine = before['result']['structuredContent']
                check(prefix + ':pristine-oracle', pristine['text'] == '' and type(pristine['revision']) is int and pristine['revision'] == 0)
                check(prefix + ':capture-evidence', capture_present(observe['result']))
                check(prefix + ':action-target', equal(write['arguments'], {'pid': pid, 'window_id': window, 'text': marker, 'delivery_mode': 'foreground'}))
                check(prefix + ':capture-target', equal(observe['arguments'], {'pid': pid, 'window_id': window, 'include_screenshot': True, 'max_dimension': 512}))
                check(prefix + ':oracle-request', equal(before['arguments'], {}) and equal(after['arguments'], {'expected': marker}))
                post = after['result']['structuredContent']
                check(prefix + ':independent-native-outcome', post['text'] == marker and type(post['revision']) is int and post['revision'] > 0)
                check(prefix + ':same-visible-app-process', type(pid) is int and pid > 0 and equal(pristine['pid'], pid) and equal(post['pid'], pid))
            check(f'{index}:distinct-guests', len(set(vm_ids)) == 3)
            check(f'{index}:live-desktop-interval-overlap', max(ready) < min(done))
            wave_intervals.append((min(starts), max(finishes)))
            waves.append((max(finishes) - min(starts)) / 1e9)
        if not waves:
            raise ValueError('empty campaign')
        campaign_time = summary['campaign_seconds']
        check('finite-timing-evidence', all(type(t) in (int, float) and math.isfinite(t) and t >= 0 for t in [campaign_time, *waves, *resets]))
        check('wave-budget', max(waves) <= budgets['max_wave_seconds'])
        check('reset-budget', max(resets) <= budgets['max_reset_seconds'])
        check('serial-wave-order', all(previous[1] <= following[0]
              for previous, following in zip(wave_intervals, wave_intervals[1:])))
        span = (max(end for _, end in wave_intervals) - min(start for start, _ in wave_intervals)) / 1e9
        check('whole-campaign-budget', max(sum(waves), span) <= campaign_time <= budgets['max_campaign_seconds'])
        result['metrics'] = {'waves': len(waves), 'wave_p50_seconds': statistics.median(waves),
                             'wave_p95_seconds': sorted(waves)[math.ceil(len(waves) * .95) - 1],
                             'worst_reset_seconds': max(resets), 'campaign_seconds': campaign_time}
        result['campaign_audit_passed'] = all(c['passed'] for c in checks)
    except Exception as error:
        check('complete-valid-artifact-contract', False)
        result['error'] = f'{type(error).__name__}: {error}'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.campaign)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report['campaign_audit_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
