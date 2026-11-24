"""Literal small-domain optimality and refusal controls for direct search."""
from copy import deepcopy
from dataclasses import replace
from itertools import product
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.direct_batch import (prepare_problem, choose_direct, prepare_frontier,
                             choose_frontier, DirectSearchLimit, PreparedProblem,
                             FrontierQueries)
from src.envelope import frontier_synthesize


def atoms(owner, value):
    return [f'o{owner}.v{value}']


def literal_count(initial, domains, batch):
    state = list(initial)
    count = 0
    for owner, value in batch:
        if value != state[owner] and value in domains[owner]:
            state[owner] = value
            count += 1
    return count


def literal_optimum(cells, initial, batch, width=3):
    domains = [[frozenset(i for i in range(width) if mask & (1 << i))
                for mask in range(1, 1 << width) if mask & (1 << initial[owner])]
               for owner in range(2)]
    return max(literal_count(initial, rectangle, batch) for rectangle in product(*domains)
               if all((a, b) in cells for a in rectangle[0] for b in rectangle[1]))


def encoded(cells, initial, width=3):
    branches = [{'0': atoms(0, a), '1': atoms(1, b)} for a, b in sorted(cells)]
    if len(cells) == width * width:
        branches = [{'0': [], '1': []}]
    current = {str(i): atoms(i, v) for i, v in enumerate(initial)}
    candidates = {str(i): [atoms(i, v) for v in range(width)] for i in range(2)}
    return branches, current, candidates


def supplied(batch):
    return [{'node': str(i), 'support': atoms(i, v)} for i, v in batch]


class DirectOptimizerRegression(unittest.TestCase):
    def setUp(self):
        self.cells = {(0, 0), (0, 1), (0, 2), (1, 0), (2, 0)}
        self.inputs = encoded(self.cells, (0, 0))

    def test_all_511_relations_against_literal_products(self):
        universe = list(product(range(3), repeat=2))
        for mask in range(1, 512):
            cells = {cell for i, cell in enumerate(universe) if mask & (1 << i)}
            initial = min(cells)
            problem = prepare_problem(*encoded(cells, initial))
            for seed in (0, 1, 2):
                rng = random.Random(mask * 1009 + seed)
                batch = [(rng.randrange(2), rng.randrange(3)) for _ in range(24)]
                result = choose_direct(problem, supplied(batch))
                self.assertEqual(result['forecast']['installed'],
                                 literal_optimum(cells, initial, batch), (mask, seed))

    def test_cached_frontier_and_direct_have_same_optimum(self):
        problem = prepare_problem(*self.inputs)
        plan = frontier_synthesize(*self.inputs)
        compiled = prepare_frontier(problem, plan)
        for owner in range(2):
            batch = [(owner, v) for _ in range(8) for v in (1, 2)] + [(1-owner, 1)]
            self.assertEqual(choose_direct(problem, supplied(batch))['forecast']['installed'],
                choose_frontier(problem, compiled, supplied(batch))['forecast']['installed'])

    def test_catalog_coverage_and_strict_bounds(self):
        problem = prepare_problem(*self.inputs)
        with self.assertRaisesRegex(ValueError, 'catalog coverage'):
            choose_direct(problem, [{'node': '0', 'support': []}])
        for limit in (True, 1.0, 0, 250001):
            with self.assertRaises(ValueError):
                choose_direct(problem, [], limit)
        with self.assertRaises(DirectSearchLimit):
            choose_direct(problem, supplied([(0, 1)]), max_states=1)

    def test_no_partial_optimum_and_exact_budget_boundary(self):
        problem = prepare_problem(*self.inputs)
        batch = supplied([(0, 1), (0, 0), (1, 2)])
        result = choose_direct(problem, batch)
        states = result['search']['states']
        self.assertEqual(choose_direct(problem, batch, states), result)
        with self.assertRaises(DirectSearchLimit) as cm:
            choose_direct(problem, batch, states-1)
        self.assertEqual(cm.exception.search['states'], states)

    def test_input_snapshot_and_output_isolation(self):
        original = deepcopy(self.inputs)
        problem = prepare_problem(*self.inputs)
        self.inputs[0][0]['0'].clear()
        self.inputs[1]['0'].append('later')
        self.inputs[2]['0'].clear()
        batch = supplied([(0, 1), (0, 2)])
        a = choose_direct(problem, batch)
        b = choose_direct(prepare_problem(*original), batch)
        self.assertEqual(a, b)
        a['box']['0'].clear()
        self.assertEqual(choose_direct(problem, batch), b)

    def test_irrelevant_atom_changes_still_count_as_full_installs(self):
        branches = [{'0': ['a']}]
        p = prepare_problem(branches, {'0': ['a']}, {'0': [['a']]})
        batch = [{'node': '0', 'support': ['a', 'irrelevant']},
                 {'node': '0', 'support': ['a']}, {'node': '0', 'support': ['a']}]
        self.assertEqual(choose_direct(p, batch)['forecast'],
            {'installed': 2, 'blocked': 0, 'unchanged': 1, 'proposals': 3,
             'final': {'0': ['a']}})

    def test_empty_batch_zero_weight_duplicates(self):
        b, c, d = self.inputs
        d['0'].append(d['0'][0][:])
        weights = {'0': [0, 0, 0, 0], '1': [0, 0, 0]}
        p = prepare_problem(b, c, d, weights)
        r = choose_direct(p, [])
        self.assertEqual(r['forecast']['installed'], 0)
        self.assertEqual(r['forecast']['final'], c)

    def test_corrupt_or_cross_context_frontier_refused(self):
        p = prepare_problem(*self.inputs)
        plan = frontier_synthesize(*self.inputs)
        broken = deepcopy(plan)
        broken['frontier'].pop()
        with self.assertRaisesRegex(ValueError, 'completeness'):
            prepare_frontier(p, broken)
        compiled = prepare_frontier(p, plan)
        with self.assertRaises(ValueError):
            choose_frontier(prepare_problem(*self.inputs), compiled, [])

    def test_preparation_cannot_be_bypassed_by_public_construction_or_replace(self):
        p = prepare_problem(*self.inputs)
        compiled = prepare_frontier(p, frontier_synthesize(*self.inputs))
        self.assertGreater(len(compiled.members), 1)
        with self.assertRaisesRegex(TypeError, 'prepare_frontier'):
            replace(compiled, members=compiled.members[:1])
        with self.assertRaisesRegex(TypeError, 'prepare_frontier'):
            FrontierQueries(problem=p, members=compiled.members[:1])
        with self.assertRaisesRegex(TypeError, 'prepare_problem'):
            replace(p, current=())
        with self.assertRaisesRegex(TypeError, 'prepare_problem'):
            PreparedProblem()

    def test_frontier_timeout_leaves_direct_route_available(self):
        from tests import direct_optimizer_study as study
        import json
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'worker.json'
            with patch.object(study, 'frontier_synthesize', side_effect=study.RouteWallBudget):
                study.worker(output, 2, 2, 0)
            record = json.loads(output.read_text())
        self.assertEqual(record['frontier_construction']['status'], 'wall-budget')
        self.assertTrue(all(q['direct']['status'] == 'completed' for q in record['queries']))
        self.assertTrue(all(q['frontier']['status'] == 'unavailable' for q in record['queries']))
        self.assertEqual(len(record['queries']), 32)

    def test_completed_prefix_survives_later_worker_failure(self):
        from tests.direct_optimizer_study import cumulative
        from tests.check_direct_optimizer import cumulative as checked_cumulative
        record = {'status': 'wall-time-limit',
            'language_preparation': {'status': 'completed', 'timing': {'wall_ns': 10}},
            'queries': [{'direct': {'status': 'completed', 'timing': {'wall_ns': 3}}},
                        {'direct': {'status': 'wall-budget', 'timing': {'wall_ns': 7}}}]}
        for function in (cumulative, checked_cumulative):
            self.assertEqual(function(record, 1, 'direct', 'wall_ns'), 13)
            self.assertIsNone(function(record, 2, 'direct', 'wall_ns'))

    def test_wall_budget_interrupts_without_a_partial_answer(self):
        from tests.direct_optimizer_study import measured
        def unfinished():
            while True:
                pass
        answer, record = measured(unfinished, remaining_ns=1_000_000)
        self.assertIsNone(answer)
        self.assertEqual(record['status'], 'wall-budget')
        self.assertEqual(record['budget_available_ns'], 1_000_000)


if __name__ == '__main__':
    unittest.main()
