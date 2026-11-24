# Same-target baseline results

The added controls close the gap between a target-planning claim and the older
static-batch comparison. They keep the original implementation and measurements
unchanged. All new records are under `results/goal-baselines/`; the design and
measurement procedure are in `docs/GOAL-BASELINE-DESIGN.md`.

## Policy tasks

The inventory contains all 529 ordered primary tasks and the same 18 selected
larger tasks. The primary domain has 196 nontrivial reachable tasks, 23 no-ops,
and 310 unreachable tasks. Every baseline agrees on those statuses.

| Domain | Nontrivial reachable tasks | One-step phases | Optimally segmented shortest-path phases | Frontier phases | Installations for each route |
|---|---:|---:|---:|---:|---:|
| Three owners | 196 | 587 | 309 | 309 | 587 |
| Four owners | 6 | 32 | 12 | 12 | 32 |
| Five owners | 6 | 41 | 12 | 12 | 41 |
| Six owners | 6 | 50 | 12 | 12 | 50 |
| Total | 214 | 710 | 345 | 345 | 710 |

Optimal segmentation of the deterministic shortest safe installation path ties
the frontier planner on every policy task. This result supports phase batching
and exactness within this policy; it does not demonstrate a target-cost
advantage over that stronger baseline. The independent interval phase graph
also agrees everywhere. On the complete primary domain, literal enumeration
visits 1,519 raw physical products, finds 147 safe products, and constructs 525
phase candidates reducing to 93 unique directed phase edges.

The physical-product to positive-guard mapping is checked for all 147 products.
In 118 cases it accepts additional physical profiles. All closures remain safe
and retain the original profiles and paths; normalized guards have at most two
terms per owner and four corners. Equal optimal values do not require exact
representability of every physical subset by positive guards.

## When a shortest installation path loses phases

The complete finite sweep retains 2,044 relation/transition contexts and 46,080
ordered queries. Of these, 20,654 are nontrivial reachable, 9,216 are no-ops,
and 16,210 are unreachable. The deterministic shortest installation path needs
more phases than the exact goal optimum in 48 nontrivial queries: two for
forward chains, two for reverse chains, eight for bidirectional chains, and 36
for complete directed local graphs. These finite-family counts are not a
workload prevalence estimate.

Two examples were selected after the initial exploration, and the record says
so. `counterexamples.json` retains every shortest path for each example, its
optimal partition, an optimal goal witness and a fresh production-planner plan.
The independent checker enumerates all cut masks and all minimum-length walks.

For the phase/write tradeoff, the relation is
`{00,01,02,10,12,20,21}`, both local graphs permit every distinct directed edge,
and the task is `12 -> 21`. The only three-installation paths are
`12 -> 02 -> 01 -> 21` and `12 -> 10 -> 20 -> 21`; both need three phases.
The path `12 -> 02 -> 00 | 00 -> 20 -> 21` uses two phases and four installations.
One phase would require the absent source/target cross corners `11` and `22`.
Consequently the exact phase-first optimum is `(2,4)` while every
minimum-installation path costs `(3,3)`.

## CPU measurements

The final file contains 85 independent worker runs. Each worker is pinned to
the same logical CPU and has a separate 30-second CPU budget. Each complete
cohort includes fresh input parsing, fresh algorithm construction, every query,
plan construction and cost serialization. Repeated queries within that cohort
may use caches; the next cold cohort constructs a new algorithm instance.
Workers repeat the entire cohort until at least 0.1 process-CPU second has
accumulated, then report mean CPU seconds per complete cohort. There are five
independent workers per table row.

| Domain | Queries per cohort | Planning route | Median CPU seconds | Observed minimum | Observed maximum |
|---|---:|---|---:|---:|---:|
| Three owners | 529 | One step per phase | 0.059673 | 0.044511 | 0.069044 |
| Three owners | 529 | Shortest path, optimal partition | 0.056627 | 0.045007 | 0.074762 |
| Three owners | 529 | Interval exact | 0.059646 | 0.045063 | 0.063167 |
| Three owners | 529 | Literal products exact | 0.052610 | 0.048918 | 0.067033 |
| Three owners | 529 | Frontier goal | 0.286538 | 0.254164 | 0.310478 |
| Four owners | 6 | One step per phase | 0.001990 | 0.001874 | 0.007774 |
| Four owners | 6 | Shortest path, optimal partition | 0.001896 | 0.001727 | 0.002313 |
| Four owners | 6 | Interval exact | 0.002492 | 0.002174 | 0.005042 |
| Four owners | 6 | Frontier goal | 0.126710 | 0.109594 | 0.134424 |
| Five owners | 6 | One step per phase | 0.003238 | 0.002576 | 0.003781 |
| Five owners | 6 | Shortest path, optimal partition | 0.002642 | 0.002324 | 0.003063 |
| Five owners | 6 | Interval exact | 0.006884 | 0.005219 | 0.008432 |
| Five owners | 6 | Frontier goal | 0.480884 | 0.336704 | 0.523401 |
| Six owners | 6 | One step per phase | 0.005045 | 0.004292 | 0.005957 |
| Six owners | 6 | Shortest path, optimal partition | 0.005191 | 0.004049 | 0.008114 |
| Six owners | 6 | Interval exact | 0.033436 | 0.024617 | 0.039412 |
| Six owners | 6 | Frontier goal | 2.076691 | 1.969070 | 2.392041 |

These observations show the additional computation used by the general
frontier route on the declared tasks. They do not establish a speed advantage.
The ranges describe five worker means, not confidence intervals. The full raw
records include all cold-batch durations and work counters.

The earlier single-cohort pilot remains in `timing-pilot/`. Some short cohorts
produced identical CPU-clock readings despite positive wall durations, and a
figure job overlapped the initial measurements. The clock advertises a
one-nanosecond resolution, so that nominal resolution does not explain the
observed zero deltas. The underlying accounting cause was not established.
None of those pilot records contributes to the final table.

## Independent verification and reproduction

The checker reconstructs the numerical domains and task inventory, checks
2,717 policy plans including frozen production references, verifies every
positive corner and admitted physical product, independently enumerates
fixed-path partitions, and checks all 46,080 finite-relation costs. It also
checks all final timed task-cost digests, work counters, route order, batch
charges and per-worker budgets. Normal and optimized Python produce identical
reports. Cost corruption, an omitted task, guard weakening and a false finite
optimum are all rejected even after the corrupted file hashes are recomputed.

From `artifact/`, verify the delivered records with:

```sh
python -B -m tests.check_goal_baselines results/goal-baselines
python -O -B -m tests.check_goal_baselines results/goal-baselines
python -B -m tests.check_goal_baselines results/goal-baselines --negative-controls
```

To create a new run, use a previously nonexistent output directory and perform
the timing step while other computational jobs are quiescent:

```sh
python -B -m tests.goal_baseline_study --out /tmp/goal-baselines-new
python -B -m tests.goal_baseline_study --out /tmp/goal-baselines-new --timing
python -B -m tests.check_goal_baselines /tmp/goal-baselines-new
```

`tests.goal_path_baselines.policy_plan(domain, source, target, route=...)`
returns a full `rollout-goal-plan-v1` execution plan. For multiple queries,
construct `PolicyGoalBaselines(domain, route)` once and call its `plan` method.
The `shortest-path-segmented` route is optimal only for its selected path;
`interval-optimal` is exact for the declared interval policy; and
`literal-products-optimal` performs complete physical-product enumeration within
its explicit product-count bound.
