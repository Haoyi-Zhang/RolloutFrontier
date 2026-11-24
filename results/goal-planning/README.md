# Exact goal-planning evidence

This cohort tests the goal planner against an independent finite-product oracle.
The objective is lexicographic: fewest nonempty guard phases, then fewest
installations needed to reach the specified target along permitted local edges.
The result does not count unrelated successful updates as goal completion.

## Registered domains

| Profile domain | Nonempty relations | Transition families | Endpoint queries |
| --- | ---: | --- | ---: |
| 2 by 2 | 15 | All 16 combinations of directed two-vertex local graphs | 1,280 |
| 3 by 3 | 511 | Complete, forward chain, reverse chain, directed cycle | 46,080 |
| 2 by 2 by 2 | 255 | Complete, forward chain, reverse chain, alternating direction | 18,432 |

Every compatible ordered source/target pair is included in its context. The
3,304 relation/transition contexts yield 65,792 queries: 40,517 reachable and
25,275 unreachable. Of the reachable queries, 13,824 already start at their
target and require no phase. These are finite logical cases, not independent
deployment observations.

Across contexts, the literal oracle enumerates 29,656 safe products and 18,614
directed phase edges. Every optimum agrees with the production planner, and
phase-graph reachability agrees with an independent centralized safe-update
graph. The 40,517 planned witnesses contain 36,405 phases and 43,930
installations in total. Counts summed across contexts include reuse of the same
underlying relation under different directed transition graphs.

`queries.jsonl.gz` retains each ordered query and every planned phase witness.
The checker reconstructs relation, encoding, transition graph and endpoint order
from the registered design, recomputes the all-safe-product optimum, and checks
positive corners, allowed local paths, emitted steps, phase connections and
reported costs. It does not invoke the production frontier or planner.

## Execution and controls

`summary.json` binds six source files to the result. Normal and optimized Python
produced byte-identical summaries and compressed witness streams. The original
invocations did not record wall-clock durations; no timing comparison is claimed.
`execution.json` records both successful invocations and the later normal and
optimized saved-data checks and regression runs.

The 16 regression methods per mode cover goal semantics, directed paths,
irrelevant identity atoms, early phase termination, cache isolation, exact
resource boundaries, error propagation and altered witnesses. They also check
all 6,699 catalog truth-table cells of the 781 relation encodings against literal
relation membership.

`incumbent-control.json` retains a concrete search-work control. With a budget of
three phase candidates, the prior implementation needlessly expanded another
one-phase state and refused a directly achievable independent two-owner goal.
The current planner uses the already known target cost to prune that expansion,
finishing with one frontier call, three candidates, one phase and two installs.
The old source is retained in `before-pruning/`. The complete 65,792-query witness
stream is unchanged by this optimization.

`source-preimage/` preserves the exact source files used by the current cohort.
The checks require live source equality; these copies establish provenance and
do not silently substitute historical code during a current-source check.

## Commands

Run from `artifact/`:

```sh
python -B -m tests.goal_planner_study --check results/goal-planning
python -O -B -m tests.goal_planner_study --check results/goal-planning
python -B -m unittest tests.goal_planner_regression -v
python -O -B -m unittest tests.goal_planner_regression -v
python -B -m tests.goal_planner_study --out /tmp/goal-study-new
```

The full design and proofs are in `docs/GOAL-PLANNING-DESIGN.md`. Public-policy
goal tasks and durable phase handoff use separate cohorts; they are not included
in the logical counts above.
