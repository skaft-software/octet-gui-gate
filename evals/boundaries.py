"""Boundary and assertion evals: zero effect dispatch on invalid input."""
from copy import deepcopy

from gui_gate import runner
from .run import inputs, events, TARGETS


def evaluate_boundaries(directory):
    config, scenario = inputs(directory / 'fixture')
    cases = []
    for mutation in ('shared-resource', 'missing-target', 'shell-command', 'no-assertions', 'duplicate-step',
                     'boolean-version', 'nan-timeout', 'malformed-arguments', 'invalid-environment', 'nan-expectation', 'invalid-pointer'):
        cfg, task = deepcopy(config), deepcopy(scenario)
        if mutation == 'shared-resource': cfg['targets']['windows']['resource'] = cfg['targets']['macos']['resource']
        elif mutation == 'missing-target': del cfg['targets']['windows']
        elif mutation == 'shell-command': cfg['targets']['windows']['reset'] = 'sh -c arbitrary'
        elif mutation == 'no-assertions': task['steps'] = [{'id': 'write', 'tool': 'write'}]
        elif mutation == 'duplicate-step': task['steps'][1]['id'] = task['steps'][0]['id']
        elif mutation == 'boolean-version': task['version'] = True
        elif mutation == 'nan-timeout': cfg['timeout_seconds'] = float('nan')
        elif mutation == 'malformed-arguments': task['steps'][1]['arguments'] = 'not-an-object'
        elif mutation == 'invalid-environment': cfg['targets']['windows']['environment'] = {'KEY': 123}
        elif mutation == 'nan-expectation': task['steps'][0]['assert'][0]['value'] = float('nan')
        elif mutation == 'invalid-pointer': task['steps'][0]['assert'][0]['path'] = '/structuredContent/te~2xt'
        rejected = False
        try:
            runner.run(cfg, task, directory / mutation, 1)
        except (ValueError, KeyError, TypeError):
            rejected = True
        cases.append({'id': 'boundary:' + mutation, 'requirements': ['R3', 'C4'], 'passed': rejected and all(not events(directory / 'fixture', name) for name in TARGETS),
                      'checks': [{'check': 'invalid-input-rejected-before-lifecycle', 'passed': rejected}]})
    return cases


def evaluate_assertions():
    table = [
        ('bool-not-int', True, 'equals', 1, '', False),
        ('nested-bool-not-int', {'a': True}, 'equals', {'a': 1}, '', False),
        ('contains-bool-not-int', [True], 'contains', 1, '', False),
        ('contains-nested-bool-not-int', [{'a': True}], 'contains', {'a': 1}, '', False),
        ('unicode-exact', '日本語🙂', 'equals', '日本語🙂', '', True),
        ('unicode-corrupted', '???', 'equals', '日本語🙂', '', False),
        ('missing-evidence', {}, 'equals', '', '/absent', False),
        ('escaped-pointer', {'a/b': {'~': 'yes'}}, 'equals', 'yes', '/a~1b/~0', True),
        ('noncanonical-array-index', ['yes'], 'equals', 'yes', '/00', False),
        ('negative-array-index', ['yes'], 'equals', 'yes', '/-1', False),
        ('empty-collection', [], 'length_at_least', 1, '', False),
        ('present-collection', [1], 'length_at_least', 1, '', True),
    ]
    cases = []
    for identifier, actual, op, expected, pointer, should_pass in table:
        passed = True
        try:
            runner.assert_evidence({'path': pointer, 'op': op, 'value': expected}, actual, {})
        except (AssertionError, ValueError, KeyError, TypeError, IndexError):
            passed = False
        cases.append({'id': 'assertion:' + identifier, 'requirements': ['R3'], 'passed': passed is should_pass,
                      'checks': [{'check': 'exact-expected-assertion-outcome', 'passed': passed is should_pass}]})
    return cases
