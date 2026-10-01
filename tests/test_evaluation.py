"""Regressions for eval-detected defects and the grader's own sensitivity."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from evals.run import inputs, grade
from evals.boundaries import evaluate_boundaries, evaluate_assertions
from gui_gate import runner


class EvaluationTests(unittest.TestCase):
    def test_json_identity_is_type_strict_recursively(self):
        self.assertFalse(runner.json_equal({'revision': True}, {'revision': 1}))
        self.assertTrue(runner.json_equal({'a': ['日本語', 1]}, {'a': ['日本語', 1]}))
        with self.assertRaises(ValueError): runner.json_equal(float('nan'), float('nan'))

    def test_assertion_eval_table(self):
        failures = [c['id'] for c in evaluate_assertions() if not c['passed']]
        self.assertEqual(failures, [])

    def test_invalid_input_has_no_lifecycle_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            failures = [c['id'] for c in evaluate_boundaries(Path(tmp)) if not c['passed']]
            self.assertEqual(failures, [])

    def test_grader_rejects_always_red_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'fixture'
            cfg, task = inputs(root)
            campaign, summary = runner.run(cfg, task, Path(tmp) / 'evidence', 1)
            summary['passed'] = False
            checks = grade({'fault': 'none', 'expected_green': True}, 'windows', root, campaign, summary, cfg)
            self.assertFalse(all(c['passed'] for c in checks))

    def test_grader_rejects_disabled_assertions_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'fixture'
            cfg, task = inputs(root, 'false_ack', 'windows')
            with mock.patch.object(runner, 'assert_evidence'):
                campaign, summary = runner.run(cfg, task, Path(tmp) / 'evidence', 1)
            self.assertTrue(summary['passed'])
            checks = grade({'fault': 'false_ack', 'expected_green': False}, 'windows', root, campaign, summary, cfg)
            self.assertTrue(any('independent-observation-oracle' in c['check'] and not c['passed'] for c in checks))

    def test_grader_rejects_tampered_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'fixture'
            cfg, task = inputs(root)
            campaign, summary = runner.run(cfg, task, Path(tmp) / 'evidence', 1)
            evidence = campaign / 'run-0000/windows/step-002.json'
            record = json.loads(evidence.read_text(encoding='utf-8'))
            record['result']['structuredContent']['text'] = 'fabricated'
            runner.save(evidence, record)
            checks = grade({'fault': 'none', 'expected_green': True}, 'windows', root, campaign, summary, cfg)
            self.assertTrue(any('evidence-integrity' in c['check'] and not c['passed'] for c in checks))


if __name__ == '__main__':
    unittest.main()
