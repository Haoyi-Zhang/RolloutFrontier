"""Discriminating goal-planning controls; run under normal Python and -O."""
from copy import deepcopy
from itertools import product
import unittest
from unittest.mock import patch

from src.goal_planner import GoalPlanner, GoalPlanningRefusal, plan_goal
from tests.goal_planner_oracle import relation_inputs, support_state, support_transitions, validate_plan


class GoalPlanningTests(unittest.TestCase):
    def test_all_relation_encodings_match_literal_truth_tables(self):
        checked = 0
        for shape in [(2, 2), (3, 3), (2, 2, 2)]:
            cells = list(product(*(range(size) for size in shape)))
            for mask in range(1, 1 << len(cells)):
                relation = {cell for index, cell in enumerate(cells) if mask & (1 << index)}
                branches, catalog = relation_inputs(shape, relation)
                for state in cells:
                    supports = support_state(catalog, state)
                    encoded = any(all(set(requirements) <= set(supports[node])
                                      for node, requirements in branch.items()) for branch in branches)
                    self.assertEqual(encoded, state in relation)
                    checked += 1
        self.assertEqual(checked, 6699)

    def independent(self):
        relation = {(0, 0), (0, 1), (1, 0), (1, 1)}
        branches, catalog = relation_inputs((2, 2), relation)
        return branches, catalog, support_state(catalog, (0, 0)), support_state(catalog, (1, 1))

    def test_independent_updates_share_one_phase(self):
        branches, catalog, source, target = self.independent()
        plan = plan_goal(branches, source, catalog, target)
        self.assertEqual(plan["cost"], {"phases": 1, "installations": 2, "handoffs": 0})
        self.assertTrue(validate_plan(plan))

    def test_known_one_phase_goal_does_not_expand_other_one_phase_states(self):
        branches, catalog, source, target = self.independent()
        planner = GoalPlanner(branches, catalog, max_phase_edges=3)
        plan = planner.plan(source, target)
        self.assertEqual(plan["cost"], {"phases": 1, "installations": 2, "handoffs": 0})
        self.assertEqual(planner.statistics()["frontier_calls"], 1)
        self.assertEqual(planner.statistics()["phase_candidates"], 3)
        self.assertEqual(plan["search"]["query"]["incumbent_pruned_states"], 2)

    def test_compatible_endpoints_can_be_unreachable(self):
        branches, catalog = relation_inputs((2, 2), {(0, 0), (1, 1)})
        plan = plan_goal(branches, support_state(catalog, (0, 0)), catalog, support_state(catalog, (1, 1)))
        self.assertEqual(plan["status"], "unreachable")
        self.assertIsNone(plan["cost"])
        self.assertEqual(plan["phases"], [])

    def test_directed_edges_disallow_reverse_upgrade(self):
        branches, catalog, source, target = self.independent()
        edges = support_transitions(catalog, [{(0, 1)}, {(0, 1)}])
        plan = plan_goal(branches, target, catalog, source, edges)
        self.assertEqual(plan["status"], "unreachable")

    def test_intermediate_versions_and_full_profiles_are_retained(self):
        catalog = {"0": [["version_0"], ["version_1"], ["version_2"]]}
        transitions = {"0": [{"source": catalog["0"][i], "target": catalog["0"][i + 1]} for i in (0, 1)]}
        plan = plan_goal([{"0": []}], {"0": catalog["0"][0]}, catalog,
                         {"0": catalog["0"][2]}, transitions)
        self.assertEqual(plan["cost"], {"phases": 1, "installations": 2, "handoffs": 0})
        self.assertEqual(plan["phases"][0]["local_paths"]["0"], catalog["0"])
        self.assertTrue(validate_plan(plan))

    def test_complete_transition_graph_has_shorter_local_path(self):
        catalog = {"0": [["version_0"], ["version_1"], ["version_2"]]}
        plan = plan_goal([{"0": []}], {"0": catalog["0"][0]}, catalog, {"0": catalog["0"][2]})
        self.assertEqual(plan["cost"]["installations"], 1)

    def test_phase_may_need_to_end_before_its_maximal_progress(self):
        relation = {(0, 0), (1, 0), (2, 0), (1, 1), (1, 2), (2, 2)}
        branches, catalog = relation_inputs((3, 3), relation)
        transitions = support_transitions(catalog, [{(0, 1), (1, 2)}] * 2)
        plan = plan_goal(branches, support_state(catalog, (0, 0)), catalog,
                         support_state(catalog, (2, 2)), transitions)
        self.assertEqual(plan["cost"], {"phases": 3, "installations": 4, "handoffs": 2})
        self.assertEqual(plan["phases"][0]["target"], support_state(catalog, (1, 0)))
        self.assertTrue(validate_plan(plan))

    def test_noop_needs_no_admission(self):
        branches, catalog, source, _ = self.independent()
        planner = GoalPlanner(branches, catalog)
        plan = planner.plan(source, source)
        self.assertEqual(plan["cost"], {"phases": 0, "installations": 0, "handoffs": 0})
        self.assertEqual(plan["phases"], [])
        self.assertEqual(planner.statistics()["frontier_calls"], 0)

    def test_cache_does_not_change_optimum_or_leak_mutable_results(self):
        branches, catalog, source, target = self.independent()
        planner = GoalPlanner(branches, catalog)
        first = planner.plan(source, target)
        calls = planner.statistics()["frontier_calls"]
        first["phases"][0]["box"]["0"].clear()
        first["phases"][0]["steps"].clear()
        second = planner.plan(source, target)
        self.assertTrue(validate_plan(second))
        self.assertEqual(second["cost"], {"phases": 1, "installations": 2, "handoffs": 0})
        self.assertEqual(planner.statistics()["frontier_calls"], calls)
        self.assertGreater(second["search"]["query"]["cached_state_expansions"], 0)

    def test_resource_refusals_are_not_unreachable_answers(self):
        branches, catalog, source, target = self.independent()
        with self.assertRaisesRegex(GoalPlanningRefusal, "goal placement bound"):
            GoalPlanner(branches, catalog, max_placements=3)
        planner = GoalPlanner(branches, catalog, max_phase_edges=1)
        with self.assertRaisesRegex(GoalPlanningRefusal, "goal phase-edge bound"):
            planner.plan(source, target)
        self.assertEqual(planner.statistics()["cached_state_expansions"], 0)
        with self.assertRaisesRegex(GoalPlanningRefusal, "goal phase-edge bound"):
            planner.plan(source, target)
        with self.assertRaisesRegex(GoalPlanningRefusal, "exact frontier search-state bound"):
            plan_goal(branches, source, catalog, target, max_frontier_states=1)

    def test_budget_accepts_exact_boundary(self):
        branches, catalog, source, target = self.independent()
        reference = GoalPlanner(branches, catalog)
        expected = reference.plan(source, target)
        needed = reference.statistics()["phase_candidates"]
        actual = plan_goal(branches, source, catalog, target, max_phase_edges=needed)
        self.assertEqual(actual["cost"], expected["cost"])
        with self.assertRaises(GoalPlanningRefusal):
            plan_goal(branches, source, catalog, target, max_phase_edges=needed - 1)

    def test_input_errors_and_nonresource_failures_propagate(self):
        branches, catalog, source, target = self.independent()
        with self.assertRaises(ValueError):
            GoalPlanner(branches, catalog, max_phase_edges=True)
        with self.assertRaisesRegex(ValueError, "goal state outside catalog"):
            plan_goal(branches, source, catalog, {"0": ["unknown"], "1": target["1"]})
        with patch("src.goal_planner.frontier_synthesize", side_effect=ValueError("logic failure")):
            with self.assertRaisesRegex(ValueError, "logic failure") as caught:
                plan_goal(branches, source, catalog, target)
            self.assertNotIsInstance(caught.exception, GoalPlanningRefusal)
        with patch("src.goal_planner.frontier_certificate", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "certificate rejected"):
                plan_goal(branches, source, catalog, target)

    def test_witness_checker_rejects_changed_cost_and_path(self):
        branches, catalog, source, target = self.independent()
        original = plan_goal(branches, source, catalog, target)
        changed = deepcopy(original)
        changed["cost"]["installations"] += 1
        with self.assertRaisesRegex(ValueError, "goal cost"):
            validate_plan(changed)
        changed = deepcopy(original)
        changed["phases"][0]["steps"][0]["support"] = ["not_in_catalog"]
        with self.assertRaisesRegex(ValueError, "step ordering"):
            validate_plan(changed)

    def test_witness_checker_rejects_consistently_recounted_illegal_jump(self):
        catalog = {"0": [["version_0"], ["version_1"], ["version_2"]]}
        transitions = {"0": [{"source": catalog["0"][i], "target": catalog["0"][i + 1]} for i in (0, 1)]}
        changed = plan_goal([{"0": []}], {"0": catalog["0"][0]}, catalog,
                            {"0": catalog["0"][2]}, transitions)
        changed["phases"][0]["local_paths"]["0"] = [catalog["0"][0], catalog["0"][2]]
        changed["phases"][0]["steps"] = [{"node": "0", "support": catalog["0"][2]}]
        changed["cost"]["installations"] = 1
        with self.assertRaisesRegex(ValueError, "unpermitted installation"):
            validate_plan(changed)

    def test_witness_checker_rejects_unsafe_enlargement(self):
        branches, catalog = relation_inputs((2, 2), {(0, 0), (1, 0), (1, 1)})
        changed = plan_goal(branches, support_state(catalog, (0, 0)), catalog, support_state(catalog, (1, 1)))
        changed["phases"][0]["box"] = deepcopy(catalog)
        with self.assertRaisesRegex(ValueError, "unsafe positive corner"):
            validate_plan(changed)


if __name__ == "__main__":
    unittest.main()
