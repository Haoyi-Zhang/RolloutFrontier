"""A programming error is not a resource refusal; saved events are reconstructible."""
import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tests import batch_generalization, same_information
from tests.check_same_information import (
    accepted, check, deterministic_choices, products, replay,
)


class FailureClassification(unittest.TestCase):
    def calls(self):
        return [(batch_generalization, lambda: batch_generalization.one('diagonal', 6000)),
                (same_information, lambda: same_information.one('diagonal', 7000, 50))]

    def test_programming_error_stops_the_study(self):
        for module, call in self.calls():
            with self.subTest(module=module.__name__), patch.object(
                    module, 'frontier_synthesize', side_effect=ValueError('unexpected internal failure')):
                with self.assertRaisesRegex(ValueError, 'unexpected internal failure'):
                    call()

    def test_checker_rejection_stops_the_study(self):
        for module, call in self.calls():
            with self.subTest(module=module.__name__), patch.object(
                    module, 'choose_batch_box', side_effect=ValueError('batch frontier certificate rejected')):
                with self.assertRaisesRegex(ValueError, 'batch frontier certificate rejected'):
                    call()

    def test_declared_resource_refusals_are_retained(self):
        for module, call in self.calls():
            for reason in sorted(module.RESOURCE_REFUSALS):
                with self.subTest(module=module.__name__, reason=reason), patch.object(
                        module, 'frontier_synthesize', side_effect=ValueError(reason)):
                    context, rows = call()
                    self.assertEqual(context['status'], 'refused')
                    self.assertEqual(context['reason'], reason)
                    self.assertEqual(rows, [])

    def test_greedy_invariant_failure_is_not_a_refusal(self):
        with patch.object(same_information, 'batch_greedy',
                          side_effect=ValueError('Covered expansion reduced installation count')):
            with self.assertRaisesRegex(ValueError, 'Covered expansion'):
                same_information.one('diagonal', 7000, 50)


class SavedEvidenceControls(unittest.TestCase):
    source_directory = Path(__file__).resolve().parents[1]/'results/same-information'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'cohort'
        shutil.copytree(self.source_directory, self.directory)

    def contexts(self):
        return [json.loads(line) for line in (self.directory/'contexts.jsonl').read_text().splitlines()]

    def write_contexts(self, contexts):
        (self.directory/'contexts.jsonl').write_text(''.join(json.dumps(c)+'\n' for c in contexts))

    @staticmethod
    def encode(rectangle):
        return {str(owner): [[('left.' if owner == 0 else 'right.') + str(value)]
                            for value in values] for owner, values in enumerate(rectangle)}

    def test_registered_relation_is_reconstructed(self):
        contexts = self.contexts()
        # This extra disconnected cell left all recorded decisions unchanged
        # in the former checker; it is not the registered diagonal generator.
        contexts[0]['relation'] = sorted(contexts[0]['relation'] + [[3, 0]])
        self.write_contexts(contexts)
        with self.assertRaisesRegex(ValueError, 'Registered relation differs'):
            check(self.directory)

    def test_off_catalog_guard_term_is_rejected(self):
        contexts = self.contexts()
        contexts[0]['boxes']['mass']['0'].append(['outside.atom'])
        self.write_contexts(contexts)
        with self.assertRaisesRegex(ValueError, 'Noncanonical singleton guard'):
            check(self.directory)

    def test_another_mass_optimum_does_not_replace_the_tie_rule(self):
        contexts = self.contexts()
        changed = False
        for context in contexts:
            cells = set(map(tuple, context['relation']))
            _, frontier = products(cells, context['initial'])
            old = accepted(context['boxes']['mass'])
            old_mass = len(old[0]) * len(old[1])
            alternatives = [box for box in frontier if box != old and
                            len(box[0]) * len(box[1]) == old_mass]
            if alternatives:
                context['boxes']['mass'] = self.encode(alternatives[0])
                changed = True
                break
        self.assertTrue(changed, 'Retained fixture lacks a mass tie control')
        self.write_contexts(contexts)
        with self.assertRaisesRegex(ValueError, 'Mass tie rule differs'):
            check(self.directory)

    def test_another_training_optimum_does_not_replace_the_exact_tie_rule(self):
        contexts = self.contexts()
        # This retained context has equal training counts but different unseen
        # counts under its two frontier choices: [5,6,3] versus [5,4,7].
        context = next(c for c in contexts if
                       (c['family'], c['seed'], c['preferred_owner_percent']) == ('cycle', 7020, 50))
        cells = set(map(tuple, context['relation']))
        _, frontier = products(cells, context['initial'])
        old = accepted(context['boxes']['batch_exact'])
        count = replay(cells, context['initial'], old, context['schedules']['supplied'])['installed']
        alternative = next(box for box in frontier if box != old and
                           replay(cells, context['initial'], box,
                                  context['schedules']['supplied'])['installed'] == count)
        context['boxes']['batch_exact'] = self.encode(alternative)
        # Keep the replacement's observations internally consistent so the
        # new rejection tests the policy tie, rather than a false event count.
        for regime, schedule in context['schedules'].items():
            context['observations'][regime]['batch_exact'] = replay(
                cells, context['initial'], alternative, schedule)
        self.write_contexts(contexts)
        with self.assertRaisesRegex(ValueError, 'Exact batch tie rule differs'):
            check(self.directory)

    def test_changed_csv_count_is_rejected(self):
        path = self.directory/'observations.csv'
        with path.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        rows[0]['batch_exact_installed'] = str(int(rows[0]['batch_exact_installed'])+1)
        with path.open('w',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        with self.assertRaisesRegex(ValueError, 'CSV differs'):
            check(self.directory)

    def test_changed_endpoint_event_is_rejected(self):
        path = self.directory/'contexts.jsonl'
        contexts = [json.loads(line) for line in path.read_text().splitlines()]
        statuses = contexts[0]['observations']['supplied']['mass']['statuses']
        statuses[0] = 'blocked' if statuses[0] != 'blocked' else 'installed'
        path.write_text(''.join(json.dumps(c)+'\n' for c in contexts))
        with self.assertRaisesRegex(ValueError, 'Recorded endpoint event differs'):
            check(self.directory)

    def test_changed_greedy_forecast_is_rejected(self):
        path = self.directory/'contexts.jsonl'
        contexts = [json.loads(line) for line in path.read_text().splitlines()]
        context = next(c for c in contexts if c.get('greedy_trace'))
        context['greedy_trace'][0]['training_installed'] += 1
        path.write_text(''.join(json.dumps(c)+'\n' for c in contexts))
        with self.assertRaisesRegex(ValueError, 'Greedy expansion differs'):
            check(self.directory)


class DeterministicTieControls(unittest.TestCase):
    def test_default_and_frontier_order_are_distinct(self):
        cells = {(0,0), (0,1), (0,2), (0,3), (1,0), (1,1), (2,0), (2,2)}
        initial = [0,0]
        _, frontier = products(cells, initial)
        training = [[0,1], [0,2], [0,0], [1,1], [1,2], [1,0]]
        default, exact = deterministic_choices(cells, initial, frontier, training)
        self.assertEqual(default, ((0,), (0,1,2,3)))
        self.assertEqual(exact, ((0,1), (0,1)))
        self.assertEqual(replay(cells, initial, default, training)['installed'], 3)
        self.assertEqual(replay(cells, initial, exact, training)['installed'], 4)
        _, empty_choice = deterministic_choices(cells, initial, frontier, [])
        self.assertEqual(empty_choice, default)


if __name__ == '__main__':
    unittest.main()
