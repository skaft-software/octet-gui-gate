"""Requirement evals through real subprocesses, with an independent state oracle."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import uuid

from gui_gate import runner

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'evals' / 'fixture.py'
DATASET = ROOT / 'evals' / 'cases.json'
TARGETS = ('macos', 'windows', 'linux')


def inputs(root, fault='none', selected='windows', timeout=10):
    root.mkdir(parents=True)
    targets = {}
    for name in TARGETS:
        mutation = fault if selected in ('all', name) else 'none'
        command = [sys.executable, str(FIXTURE)]
        identity = {'account': name + '-account', 'driver_sha256': 'fixture-only', 'signature': 'golden'}
        if mutation == 'boolean_identity':
            identity['signature'] = 1
        targets[name] = {'resource': 'synthetic-' + name, 'identity': identity,
                         'bindings': {'marker': name + '—日本語🙂'},
                         **{phase: command + [phase, str(root), name, mutation] for phase in ('reset', 'verify', 'destroy', 'mcp')}}
    config = {'version': 1, 'targets': targets, 'timeout_seconds': timeout}
    scenario = {'version': 1, 'steps': [
        {'id': 'pristine', 'tool': 'read', 'assert': [{'path': '/structuredContent/text', 'op': 'equals', 'value': ''}]},
        {'id': 'write', 'tool': 'write', 'arguments': {'text': {'$ref': '/bindings/marker'}}},
        {'id': 'verify-write', 'tool': 'read', 'assert': [{'path': '/structuredContent/text', 'op': 'equals', 'value': {'$ref': '/bindings/marker'}}]},
    ]}
    return config, scenario


def events(root, name):
    path = root / name / 'events.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def grade(case, selected, root, campaign, summary, config):
    checks = []

    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})

    check('exact-expected-campaign-outcome', summary['passed'] is case['expected_green'])
    check('requested-repeat-count-or-cleanup-stop', len(summary['runs']) == case.get('completed_repetitions', case.get('repetitions', 1)))
    all_events = {name: events(root, name) for name in TARGETS}
    for index, reports in enumerate(summary['runs']):
        check(f'{index}:target-coverage', [r['target'] for r in reports] == list(TARGETS))
        for report in reports:
            name = report['target']
            directory = campaign / f'run-{index:04d}' / name
            disk_report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
            check(f'{index}:{name}:durable-report', json.dumps(disk_report, sort_keys=True, allow_nan=False) == json.dumps(report, sort_keys=True, allow_nan=False))
            expected_pass = case['expected_green'] or selected not in ('all', name) or (case['fault'] == 'stale_reset' and index == 0)
            check(f'{index}:{name}:expected-target-outcome', report['passed'] is expected_pass)
            for step in report['steps']:
                if 'evidence' in step:
                    raw = (directory / step['evidence']).read_bytes()
                    check(f'{index}:{name}:{step["id"]}:evidence-integrity', hashlib.sha256(raw).hexdigest() == step['sha256'])
            if report['passed']:
                # Do not use the production assertion grader or response ack as
                # the oracle. Independently inspect raw observations and disk.
                before = json.loads((directory / 'step-000.json').read_text(encoding='utf-8'))
                write = json.loads((directory / 'step-001.json').read_text(encoding='utf-8'))
                after = json.loads((directory / 'step-002.json').read_text(encoding='utf-8'))
                marker = config['targets'][name]['bindings']['marker']
                check(f'{index}:{name}:independent-pristine-oracle', before['result'].get('structuredContent', {}).get('text') == '')
                check(f'{index}:{name}:independent-action-arguments', write['arguments'] == {'text': marker})
                check(f'{index}:{name}:independent-observation-oracle', after['result'].get('structuredContent', {}).get('text') == marker)
            check(f'{index}:{name}:cleanup-attempt-logged', (directory / 'destroy.stdout').exists())
    for name in TARGETS:
        kinds = [e['kind'] for e in all_events[name]]
        check(f'{name}:cleanup-actually-invoked', kinds.count('destroy') == len(summary['runs']))
        if case.get('no_tool_calls') and selected in ('all', name):
            check(f'{name}:zero-tools-after-preflight-failure', not any(kind in ('read', 'write') for kind in kinds))
        if case['expected_green']:
            state = json.loads((root / name / 'state.json').read_text(encoding='utf-8'))
            check(f'{name}:independent-final-state', state['text'] == config['targets'][name]['bindings']['marker'])
    if case['fault'] == 'overlap':
        starts = [next(e['time_ns'] for e in all_events[n] if e['kind'] == 'reset') for n in TARGETS]
        ends = [next(e['time_ns'] for e in all_events[n] if e['kind'] == 'reset_done') for n in TARGETS]
        check('all-three-reset-process-intervals-overlap', max(starts) <= min(ends))
    return checks


def evaluate(output):
    campaign = output / ('eval-' + uuid.uuid4().hex)
    campaign.mkdir(parents=True)
    dataset = json.loads(DATASET.read_text(encoding='utf-8'))
    evaluated = [ROOT / 'extension.py', ROOT / 'extension.toml']
    for directory in ('gui_gate', 'evals', 'tests', 'vendor/octet_extension'):
        evaluated.extend(sorted((ROOT / directory).glob('*.py')))
    evaluated.append(DATASET)
    evaluated.append(ROOT / '.github/workflows/tests.yml')
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in evaluated}
    result = {'schema': 'octet.gui-gate.evaluation.v1', 'kind': 'synthetic-contract',
              'evaluated_files_sha256': hashes,
              'evaluated_tree_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
              'evaluated_at_utc': datetime.now(timezone.utc).isoformat(),
              'host': {'os': platform.system(), 'architecture': platform.machine(), 'python': platform.python_version()},
              'dataset_sha256': hashlib.sha256(DATASET.read_bytes()).hexdigest(),
              'product_qualified': False,
              'live_blockers': ['R2: no live unattended all-OS suite', 'R4: no measured real VM rollback budget',
                                'R5: no live three-OS overlap', 'R6: no rebuilt-guest permission-identity proof'],
              'cases': []}
    try:
        result['revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        result['worktree_dirty'] = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT))
    except (OSError, subprocess.CalledProcessError):
        result['revision'] = 'unavailable'
    for case in dataset:
        selections = TARGETS if case['target'] == 'each' else (case['target'],)
        for selected in selections:
            identifier = case['id'] + ':' + selected
            directory = campaign / identifier.replace(':', '-')
            started = time.monotonic()
            entry = {'id': identifier, 'requirements': case['requirements'], 'expected_green': case['expected_green'], 'category': 'fault-injection'}
            try:
                config, scenario = inputs(directory / 'fixture', case['fault'], selected, case.get('timeout_seconds', 10))
                path, summary = runner.run(config, scenario, directory / 'evidence', case.get('repetitions', 1))
                entry['observed_green'] = summary['passed']
                entry['checks'] = grade(case, selected, directory / 'fixture', path, summary, config)
                entry['passed'] = all(c['passed'] for c in entry['checks'])
                entry['artifact'] = str(path.relative_to(campaign))
                entry['run_seconds'] = [max(r['timings_seconds']['total'] for r in reports) for reports in summary['runs']]
            except Exception as error:
                entry.update(passed=False, error=f'{type(error).__name__}: {error}')
            entry['seconds'] = time.monotonic() - started
            result['cases'].append(entry)
            runner.save(campaign / 'report.json', result)
            print(f'{"PASS" if entry["passed"] else "FAIL"} {identifier}', flush=True)
    from .boundaries import evaluate_boundaries, evaluate_assertions
    from .wire import evaluate_wire
    extra = evaluate_boundaries(campaign / 'boundaries') + evaluate_assertions()
    for mode in ('approve', 'decline', 'unavailable', 'unknown-tool', 'cancel', 'shutdown'):
        started = time.monotonic()
        entry = {'id': 'extension-wire:' + mode, 'requirements': ['R1', 'R3', 'C4'], 'category': 'extension-wire'}
        try:
            entry['checks'] = evaluate_wire(campaign / ('wire-' + mode), mode)
            entry['passed'] = all(c['passed'] for c in entry['checks'])
        except Exception as error:
            entry.update(passed=False, error=f'{type(error).__name__}: {error}')
        entry['seconds'] = time.monotonic() - started
        extra.append(entry)
    for entry in extra:
        result['cases'].append(entry)
        print(f'{"PASS" if entry["passed"] else "FAIL"} {entry["id"]}', flush=True)
    negatives = [c for c in result['cases'] if c.get('category') == 'fault-injection' and not c['expected_green']]
    result['metrics'] = {'cases': len(result['cases']), 'passed': sum(c['passed'] for c in result['cases']),
                         'false_greens': sum(c.get('observed_green') is True for c in negatives),
                         'negative_cases': len(negatives)}
    result['thresholds'] = {'minimum_cases': 80, 'minimum_negative_cases': 49, 'maximum_false_greens': 0}
    result['harness_passed'] = (all(c['passed'] for c in result['cases']) and len(result['cases']) >= 80
                                and len(negatives) >= 49 and result['metrics']['false_greens'] == 0)
    repeat = next(c for c in result['cases'] if c['id'].startswith('repeatable-golden-loop:'))
    values = sorted(repeat.get('run_seconds', []))
    if values:
        result['metrics']['synthetic_slowest_target_p50_seconds'] = statistics.median(values)
        result['metrics']['synthetic_slowest_target_p95_seconds'] = values[max(0, int(len(values) * 0.95 + 0.999) - 1)]
    runner.save(campaign / 'report.json', result)
    return campaign, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-product', action='store_true', help='also require live product qualification; currently blocked')
    args = parser.parse_args()
    path, report = evaluate(args.output.resolve())
    print(path / 'report.json')
    print(json.dumps(report['metrics'], indent=2))
    return 0 if report['harness_passed'] and (not args.require_product or report['product_qualified']) else 1


if __name__ == '__main__':
    sys.exit(main())
