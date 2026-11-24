# Declared priority-path counterexample

This finite algebraic example establishes that combining the two fixed owner
priorities with the two minimum-current-rank priority paths does not solve
every max-closed chain instance. It is an existence witness, with no workload
frequency or timing claim.

The domains are ranks 0 through 4 and 0 through 6. Four implications define
compatibility: a >= 3 implies b >= 1; a >= 4 implies b >= 4; b >= 5 implies
a >= 1; b >= 6 implies a >= 2. Of 35 rank pairs, 27 are compatible. Independent
enumeration of every safe interval phase gives a two-phase optimum from (0,0)
to (4,6), with the unique intermediate endpoint (2,4). Each of the four declared
priority paths needs three phases even after exact optimal path partitioning.
Every compared path uses ten one-rank installations.

`observation.json` retains the complete relation, phase graph, phase distances,
all four paths and their optimal partitions. `model.json` retains the positive
manifest encoding and complete physical catalogs and edges. The unchanged
production planner's full witness is in `production-plan.json`. The checker
reconstructs these observations and validates that witness without importing
the production planner, controller, runtime or positive guard checker.

Run from the artifact directory:

```bash
python -B -m tests.check_priority_counterexample --check results/priority-counterexample --corruption-controls
python -O -B -m tests.check_priority_counterexample --check results/priority-counterexample --corruption-controls
python -B -m tests.check_priority_counterexample --out results/priority-counterexample-reproduction
```

Four semantic corruption controls alter the production cost, intermediate
endpoint, priority path and declared threshold. Captured sources and consumed
data are bound in `environment.json`; the checker checks both retained and
current source bytes. Fresh production requires a new output directory.
