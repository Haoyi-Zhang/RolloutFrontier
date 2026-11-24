"""Boundary tests for certified structural planning and its exact fallback."""
from copy import deepcopy
from itertools import product
import unittest

from src.goal_planner import GoalPlanner, GoalPlanningRefusal
from src.structured_planner import CertifiedGoalPlanner
from src.rollout import validate_execution_plan
from tests.goal_planner_oracle import relation_inputs, support_state, support_transitions


def case(shape, relation, graphs=None, **budgets):
    branches, catalog = relation_inputs(shape, relation)
    if graphs is None:
        graphs = [{(i, i + 1) for i in range(size - 1)} for size in shape]
    edges = support_transitions(catalog, graphs)
    return CertifiedGoalPlanner(branches, catalog, edges, **budgets), catalog


class StructuredPlanningTests(unittest.TestCase):
    def test_independent_chains_finish_in_one_phase(self):
        planner, catalog = case((3, 3), set(product(range(3), repeat=2)))
        plan = planner.plan(support_state(catalog, (0, 0)), support_state(catalog, (2, 2)))
        self.assertTrue(planner.recognition()['recognized'])
        self.assertEqual(plan['cost'], {'phases': 1, 'installations': 4, 'handoffs': 0})
        validate_execution_plan(plan)

    def test_zero_slack_precedence_requires_three_phases(self):
        relation = {v for v in product(range(2), repeat=3) if v[2] <= v[1] <= v[0]}
        planner, catalog = case((2, 2, 2), relation)
        plan = planner.plan(support_state(catalog, (0, 0, 0)), support_state(catalog, (1, 1, 1)))
        self.assertEqual(plan['cost']['phases'], 3)
        self.assertEqual(plan['search']['rank_iterates'], [[0, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]])
        validate_execution_plan(plan)

    def test_equality_cycle_has_unreachable_fixed_point(self):
        planner, catalog = case((2, 2), {(0, 0), (1, 1)})
        plan = planner.plan(support_state(catalog, (0, 0)), support_state(catalog, (1, 1)))
        self.assertTrue(planner.recognition()['recognized'])
        self.assertEqual(plan['status'], 'unreachable')
        self.assertEqual(plan['search']['rank_iterates'], [[0, 0], [0, 0]])
        self.assertEqual(plan['phases'], [])

    def test_hull_hole_selects_complete_frontier(self):
        relation = {(0, 0), (1, 0), (2, 0), (1, 1), (1, 2), (2, 2)}
        planner, catalog = case((3, 3), relation)
        plan = planner.plan(support_state(catalog, (0, 0)), support_state(catalog, (2, 2)))
        self.assertFalse(planner.recognition()['recognized'])
        self.assertEqual(plan['strategy'], 'complete-frontier')
        self.assertEqual(plan['cost']['phases'], 3)
        validate_execution_plan(plan)

    def test_reverse_chain_is_ranked_by_edges(self):
        planner, catalog = case((3,), {(0,), (1,), (2,)}, [{(2, 1), (1, 0)}])
        plan = planner.plan(support_state(catalog, (2,)), support_state(catalog, (0,)))
        self.assertTrue(planner.recognition()['recognized'])
        self.assertEqual(plan['cost']['installations'], 2)
        self.assertEqual(plan['cost']['phases'], 1)

    def test_target_behind_directed_chain_is_unreachable(self):
        planner, catalog = case((3,), {(0,), (1,), (2,)})
        plan = planner.plan(support_state(catalog, (2,)), support_state(catalog, (0,)))
        self.assertEqual(plan['status'], 'unreachable')
        self.assertIn('precedes', plan['reason'])

    def test_missing_edge_selects_fallback(self):
        planner, catalog = case((3,), {(0,), (1,), (2,)}, [{(0, 1)}])
        self.assertFalse(planner.recognition()['recognized'])
        plan = planner.plan(support_state(catalog, (0,)), support_state(catalog, (2,)))
        self.assertEqual(plan['status'], 'unreachable')

    def test_branching_and_cycle_select_fallback(self):
        for graph in ({(0, 1), (0, 2)}, {(0, 1), (1, 2), (2, 0)}):
            planner, catalog = case((3,), {(0,), (1,), (2,)}, [graph])
            self.assertFalse(planner.recognition()['recognized'])
            plan = planner.plan(support_state(catalog, (0,)), support_state(catalog, (2,)))
            self.assertEqual(plan['status'], 'planned')
            validate_execution_plan(plan)

    def test_singleton_owner_and_self_bound(self):
        planner, catalog = case((1, 3), {(0, 0), (0, 1), (0, 2)})
        plan = planner.plan(support_state(catalog, (0, 0)), support_state(catalog, (0, 2)))
        self.assertEqual(plan['cost']['phases'], 1)
        self.assertEqual(plan['cost']['installations'], 2)

    def test_equal_projection_retains_physical_installations(self):
        branches = [{'0': ['cap']}]
        catalog = {'0': [['cap', 'physical.a'], ['cap', 'physical.b'], ['cap', 'physical.c']]}
        transitions = {'0': [{'source': a, 'target': b}
                             for a, b in zip(catalog['0'], catalog['0'][1:])]}
        planner = CertifiedGoalPlanner(branches, catalog, transitions)
        plan = planner.plan({'0': catalog['0'][0]}, {'0': catalog['0'][2]})
        self.assertEqual(plan['cost']['installations'], 2)
        self.assertEqual(plan['phases'][0]['box'], {'0': [['cap']]})
        validate_execution_plan(plan)

    def test_noop_requires_no_guards(self):
        planner, catalog = case((2, 2), {(0, 0), (1, 1)})
        plan = planner.plan(support_state(catalog, (1, 1)), support_state(catalog, (1, 1)))
        self.assertEqual(plan['cost'], {'phases': 0, 'installations': 0, 'handoffs': 0})
        self.assertEqual(plan['phases'], [])
        validate_execution_plan(plan)

    def test_incompatible_target_and_initial(self):
        planner, catalog = case((2, 2), {(0, 0), (1, 1)})
        plan = planner.plan(support_state(catalog, (0, 0)), support_state(catalog, (0, 1)))
        self.assertEqual(plan['reason'], 'target incompatible')
        with self.assertRaisesRegex(ValueError, 'initial placement incompatible'):
            planner.plan(support_state(catalog, (0, 1)), support_state(catalog, (1, 1)))

    def test_unary_hole_rejected_but_unary_interval_recognized(self):
        planner, _ = case((3,), {(0,), (2,)})
        self.assertFalse(planner.recognition()['recognized'])
        planner, catalog = case((4,), {(1,), (2,)})
        self.assertTrue(planner.recognition()['recognized'])
        plan = planner.plan(support_state(catalog, (1,)), support_state(catalog, (2,)))
        self.assertEqual(plan['cost']['phases'], 1)

    def test_placement_and_invalid_work_budgets(self):
        with self.assertRaises(GoalPlanningRefusal):
            case((2, 2), set(product(range(2), repeat=2)), max_placements=1)
        with self.assertRaises(ValueError):
            case((2,), {(0,), (1,)}, max_frontier_states=0)

    def test_seven_owner_input_preserves_executor_refusal(self):
        with self.assertRaisesRegex(ValueError, 'placement bound'):
            case((2,) * 7, {(0,) * 7, (1,) * 7})

    def test_empty_relation_rejects_initial_state(self):
        planner = CertifiedGoalPlanner([{'0': ['required']}], {'0': [['absent']]}, {'0': []})
        self.assertFalse(planner.recognition()['recognized'])
        with self.assertRaisesRegex(ValueError, 'initial placement incompatible'):
            planner.plan({'0': ['absent']}, {'0': ['absent']})

    def test_recognized_path_does_not_spend_frontier_work_budget(self):
        planner, catalog = case((3, 3), set(product(range(3), repeat=2)),
                                max_phase_edges=1, max_frontier_states=1)
        plan = planner.plan(support_state(catalog, (0, 0)), support_state(catalog, (2, 2)))
        self.assertEqual(plan['cost']['phases'], 1)
        self.assertEqual(planner.fallback.statistics()['frontier_calls'], 0)

    def test_fallback_keeps_resource_refusal(self):
        relation = {(0, 0), (1, 0), (2, 0), (1, 1), (1, 2), (2, 2)}
        planner, catalog = case((3, 3), relation, max_phase_edges=1)
        with self.assertRaises(GoalPlanningRefusal):
            planner.plan(support_state(catalog, (0, 0)), support_state(catalog, (2, 2)))

    def test_returned_certificate_and_plan_are_copies(self):
        planner, catalog = case((2,), {(0,), (1,)})
        certificate = planner.recognition()
        certificate['upper'][0] = -1
        plan = planner.plan(support_state(catalog, (0,)), support_state(catalog, (1,)))
        plan['structure']['upper'][0] = -1
        self.assertEqual(planner.recognition()['upper'], [1])

    def test_declared_no_transitions_uses_complete_graph_fallback(self):
        branches, catalog = relation_inputs((3,), {(0,), (1,), (2,)})
        planner = CertifiedGoalPlanner(branches, catalog)
        self.assertFalse(planner.recognition()['recognized'])
        plan = planner.plan(support_state(catalog, (0,)), support_state(catalog, (2,)))
        self.assertEqual(plan['cost']['installations'], 1)


if __name__ == '__main__':
    unittest.main()
