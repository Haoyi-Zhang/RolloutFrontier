"""Boundary regressions for the exact factored-chain planner and its witnesses."""
from copy import deepcopy
from itertools import product
import unittest

from src.factored_planner import (FactoredChainPlanner, FactoredPlanningRefusal,
                                 validate_factored_plan)
from tests.factored_planning_oracle import Oracle
from tests.goal_planner_oracle import relation_inputs, support_state, support_transitions


def finite(shape, relation, graphs=None, **budgets):
    branches, catalog = relation_inputs(shape, relation)
    if graphs is None:
        graphs = [{(i, i + 1) for i in range(q - 1)} for q in shape]
    transitions = support_transitions(catalog, graphs)
    factors = [{'id': 'relation', 'branches': branches}]
    return FactoredChainPlanner(factors, catalog, transitions, **budgets), catalog, factors, transitions


def alias_cycle(size):
    profiles = [sorted(p) for p in [
        ['emit:old', 'parse:old', 'program:legacy'],
        ['emit:old', 'parse:old', 'parse:new', 'program:accepting'],
        ['emit:new', 'parse:old', 'parse:new', 'program:emitting'],
        ['emit:new', 'parse:new', 'program:current']]]
    catalog = {str(i): deepcopy(profiles) for i in range(size)}
    transitions = {n: [{'source': a, 'target': b} for a, b in zip(p, p[1:])]
                   for n, p in catalog.items()}
    factors = [{'id': f'edge-{i}-{(i+1)%size}', 'branches': [
        {str(i): ['emit:old'], str((i+1)%size): ['parse:old']},
        {str(i): ['emit:new'], str((i+1)%size): ['parse:new']}]} for i in range(size)]
    return factors, catalog, transitions


class FactoredPlanningTests(unittest.TestCase):
    def test_actual_alias_shape_is_max_closed_and_has_three_phases(self):
        f, c, t = alias_cycle(3)
        planner = FactoredChainPlanner(f, c, t)
        plan = planner.plan({n: p[0] for n, p in c.items()}, {n: p[-1] for n, p in c.items()})
        self.assertEqual(plan['cost'], {'phases': 3, 'installations': 9, 'handoffs': 2})
        self.assertEqual(plan['search']['rank_iterates'], [[r] * 3 for r in range(4)])
        self.assertTrue(validate_factored_plan(plan)['safe'])
        oracle = Oracle(f, c, t)
        oracle.check_recognition(planner.recognition())
        oracle.check_plan(plan, (0, 0, 0), (3, 3, 3))

    def test_large_overlap_uses_local_cells_not_global_product(self):
        f, c, t = alias_cycle(32)
        planner = FactoredChainPlanner(f, c, t)
        plan = planner.plan({n: p[0] for n, p in c.items()}, {n: p[-1] for n, p in c.items()})
        self.assertEqual(planner.recognition()['checked_factor_placements'], 32 * 16)
        self.assertFalse(planner.recognition()['global_catalog_enumerated'])
        self.assertEqual(plan['cost'], {'phases': 3, 'installations': 96, 'handoffs': 2})
        self.assertEqual(validate_factored_plan(plan)['owners'], 32)

    def test_nonclosed_factor_returns_concrete_refusal(self):
        shape, relation = (2, 2), {(0, 0), (1, 0), (0, 1)}
        b, c = relation_inputs(shape, relation)
        t = support_transitions(c, [{(0, 1)}, {(0, 1)}])
        f = [{'id': 'not-closed', 'branches': b}]
        with self.assertRaises(FactoredPlanningRefusal) as caught:
            FactoredChainPlanner(f, c, t)
        Oracle(f, c, t).check_refusal({'reason': caught.exception.reason,
                                     'witness': caught.exception.witness})

    def test_factorwise_condition_is_sufficient_not_necessary(self):
        c = {'0': [['a0'], ['a1']], '1': [['b0'], ['b1']]}
        t = {n: [{'source': p[0], 'target': p[1]}] for n, p in c.items()}
        f = [{'id': 'nonclosed', 'branches': [
                  {'0': ['a0'], '1': []}, {'0': [], '1': ['b0']}]},
             {'id': 'restricting', 'branches': [{'0': ['a0'], '1': ['b0']}]}]
        # The second factor removes both witness states. Global compatibility
        # is the singleton (0,0), but local certification deliberately refuses.
        self.assertEqual(set(Oracle(f, c, t).graph()), {(0, 0)})
        with self.assertRaisesRegex(FactoredPlanningRefusal, 'not closed'):
            FactoredChainPlanner(f, c, t)

    def test_unary_hole_preserves_unreachability(self):
        p, c, f, t = finite((3,), {(0,), (2,)})
        plan = p.plan(support_state(c, (0,)), support_state(c, (2,)))
        self.assertEqual(plan['status'], 'unreachable')
        self.assertEqual(plan['search']['rank_iterates'], [[0], [0]])
        Oracle(f, c, t).check_plan(plan, (0,), (2,))

    def test_equality_cycle_has_no_spurious_progress(self):
        p, c, f, t = finite((2, 2), {(0, 0), (1, 1)})
        plan = p.plan(support_state(c, (0, 0)), support_state(c, (1, 1)))
        self.assertEqual(plan['status'], 'unreachable')
        self.assertEqual(plan['phases'], [])
        Oracle(f, c, t).check_plan(plan, (0, 0), (1, 1))

    def test_noop_has_no_guard_or_step(self):
        p, c, _, _ = finite((2, 2), {(0, 0), (1, 1)})
        plan = p.plan(support_state(c, (1, 1)), support_state(c, (1, 1)))
        self.assertEqual(plan['cost'], {'phases': 0, 'installations': 0, 'handoffs': 0})
        self.assertEqual(plan['phases'], [])
        self.assertTrue(validate_factored_plan(plan)['safe'])

    def test_target_behind_source_is_unreachable(self):
        p, c, _, _ = finite((3,), {(0,), (1,), (2,)})
        self.assertEqual(p.plan(support_state(c, (2,)), support_state(c, (0,)))['status'], 'unreachable')

    def test_incompatible_source_rejects_and_target_is_unreachable(self):
        p, c, _, _ = finite((2, 2), {(0, 0), (1, 1)})
        with self.assertRaisesRegex(ValueError, 'initial placement incompatible'):
            p.plan(support_state(c, (0, 1)), support_state(c, (1, 1)))
        self.assertEqual(p.plan(support_state(c, (0, 0)), support_state(c, (0, 1)))['reason'],
                         'target incompatible')

    def test_empty_factor_relation_cannot_authorize_a_source(self):
        p = FactoredChainPlanner([{'id': 'empty', 'branches': [{'a': ['missing']}]}],
                                 {'a': [['present']]}, {'a': []})
        with self.assertRaisesRegex(ValueError, 'initial placement incompatible'):
            p.plan({'a': ['present']}, {'a': ['present']})

    def test_missing_edge_is_structural_refusal(self):
        with self.assertRaisesRegex(FactoredPlanningRefusal, 'not a directed chain'):
            finite((3,), {(0,), (1,), (2,)}, [{(0, 1)}])

    def test_branching_is_structural_refusal(self):
        with self.assertRaisesRegex(FactoredPlanningRefusal, 'not a directed chain'):
            finite((3,), {(0,), (1,), (2,)}, [{(0, 1), (0, 2)}])

    def test_directed_cycle_is_structural_refusal(self):
        with self.assertRaisesRegex(FactoredPlanningRefusal, 'not a directed chain'):
            finite((3,), {(0,), (1,), (2,)}, [{(0, 1), (1, 2), (2, 0)}])

    def test_self_loops_do_not_create_installations(self):
        p, c, _, _ = finite((2,), {(0,), (1,)}, [{(0, 0), (0, 1), (1, 1)}])
        plan = p.plan(support_state(c, (0,)), support_state(c, (1,)))
        self.assertEqual(plan['cost']['installations'], 1)
        validate_factored_plan(plan)

    def test_chain_direction_comes_from_edges(self):
        p, c, _, _ = finite((3,), {(0,), (1,), (2,)}, [{(2, 1), (1, 0)}])
        plan = p.plan(support_state(c, (2,)), support_state(c, (0,)))
        self.assertEqual(plan['cost']['installations'], 2)
        self.assertEqual(plan['search']['rank_iterates'], [[0], [2]])

    def test_equal_contract_projection_keeps_physical_profiles(self):
        c = {'node': [['cap', f'program:{i}'] for i in range(3)]}
        t = {'node': [{'source': a, 'target': b} for a, b in zip(c['node'], c['node'][1:])]}
        p = FactoredChainPlanner([{'id': 'capability', 'branches': [{'node': ['cap']}]}], c, t)
        plan = p.plan({'node': c['node'][0]}, {'node': c['node'][-1]})
        self.assertEqual(plan['cost']['installations'], 2)
        self.assertEqual(plan['phases'][0]['box'], {'node': [['cap']]})
        validate_factored_plan(plan)

    def test_singleton_owner_needs_no_self_width_bound(self):
        p, c, _, _ = finite((1, 3), {(0, i) for i in range(3)})
        plan = p.plan(support_state(c, (0, 0)), support_state(c, (0, 2)))
        self.assertEqual(plan['cost']['phases'], 1)
        self.assertEqual(len(plan['phases'][0]['local_paths']['0']), 1)

    def test_shared_owner_uses_one_physical_catalog_and_guard(self):
        f, c, t = alias_cycle(3)
        p = FactoredChainPlanner(f, c, t)
        plan = p.plan({n: q[0] for n, q in c.items()}, {n: q[-1] for n, q in c.items()})
        self.assertEqual(set(plan['phases'][1]['box']), set(c))
        self.assertEqual(len(plan['phases'][1]['factor_checks']), 3)
        validate_factored_plan(plan)

    def test_owner_missing_from_all_factors_is_rejected(self):
        f, c, t = alias_cycle(3)
        with self.assertRaisesRegex(ValueError, 'every owner needs a factor'):
            FactoredChainPlanner([f[0]], c, t)

    def test_unconstrained_owner_is_explicit_unary_true_factor(self):
        c = {'lonely': [['program:0'], ['program:1']]}
        t = {'lonely': [{'source': c['lonely'][0], 'target': c['lonely'][1]}]}
        p = FactoredChainPlanner([{'id': 'unconstrained', 'branches': [{'lonely': []}]}], c, t)
        plan = p.plan({'lonely': c['lonely'][0]}, {'lonely': c['lonely'][1]})
        self.assertEqual(plan['phases'][0]['box'], {'lonely': [[]]})
        validate_factored_plan(plan)

    def test_factor_cannot_name_a_missing_physical_owner(self):
        f, c, t = alias_cycle(3)
        f[0]['branches'][0]['unknown'] = []
        with self.assertRaisesRegex(ValueError, 'outside physical catalog'):
            FactoredChainPlanner(f, c, t)

    def test_duplicate_factor_identity_is_rejected(self):
        f, c, t = alias_cycle(3)
        f[1]['id'] = f[0]['id']
        with self.assertRaisesRegex(ValueError, 'duplicate factor identity'):
            FactoredChainPlanner(f, c, t)

    def test_explicit_work_bounds_do_not_become_unreachable(self):
        f, c, t = alias_cycle(3)
        for limit in ({'max_owners': 2}, {'max_factors': 2}, {'max_factor_placements': 15},
                      {'max_total_factor_placements': 47}, {'max_closure_pairs': 233}):
            with self.assertRaises(FactoredPlanningRefusal):
                FactoredChainPlanner(f, c, t, **limit)
        p = FactoredChainPlanner(f, c, t, max_steps=8)
        with self.assertRaisesRegex(FactoredPlanningRefusal, 'installation budget'):
            p.plan({n: q[0] for n, q in c.items()}, {n: q[-1] for n, q in c.items()})

    def test_budget_equality_is_accepted(self):
        f, c, t = alias_cycle(3)
        p = FactoredChainPlanner(f, c, t, max_owners=3, max_factors=3, max_factor_placements=16,
                                 max_total_factor_placements=48, max_closure_pairs=234, max_steps=9)
        self.assertEqual(p.plan({n: q[0] for n, q in c.items()},
                                {n: q[-1] for n, q in c.items()})['cost']['phases'], 3)

    def test_boolean_or_unknown_budget_is_rejected(self):
        f, c, t = alias_cycle(3)
        for limit in ({'max_owners': True}, {'max_steps': 0}, {'unknown': 1}):
            with self.assertRaises(ValueError):
                FactoredChainPlanner(f, c, t, **limit)

    def test_recognition_is_detached_from_caller_mutation(self):
        f, c, t = alias_cycle(3)
        p = FactoredChainPlanner(f, c, t)
        certificate = p.recognition()
        certificate['factors'][0]['axis_limits'][0]['upper'][0] = 99
        self.assertNotEqual(certificate, p.recognition())
        f.clear(); c.clear(); t.clear()
        self.assertEqual(len(p.recognition()['factors']), 3)

    def test_execution_validator_rejects_semantic_corruption(self):
        f, c, t = alias_cycle(3)
        good = FactoredChainPlanner(f, c, t).plan({n: p[0] for n, p in c.items()},
                                                {n: p[-1] for n, p in c.items()})
        changed = deepcopy(good); changed['cost']['installations'] += 1
        variants = [changed]
        changed = deepcopy(good); changed['phases'][0]['steps'][0]['support'] = c['0'][2]
        variants.append(changed)
        changed = deepcopy(good); changed['phases'][0]['box']['0'] = [[]]
        variants.append(changed)
        changed = deepcopy(good); changed['phases'][0]['local_paths']['0'].pop(0)
        variants.append(changed)
        changed = deepcopy(good); changed['phases'][0]['factor_checks'].pop()
        variants.append(changed)
        changed = deepcopy(good); changed['phases'][1]['source'] = changed['initial']
        variants.append(changed)
        changed = deepcopy(good); changed['transitions']['0'].pop()
        variants.append(changed)
        for bad in variants:
            with self.assertRaises(ValueError):
                validate_factored_plan(bad)


if __name__ == '__main__':
    unittest.main()
