# Same-target planning controls

This additive study compares planning routes on the frozen goal-policy inputs.
It does not change the implementation or any earlier measurements. The finite
counterexample exploration described below preceded this document; its selected
examples are explanatory witnesses, not a prospectively selected test set.

## Cohort and routes

Use all 529 ordered compatible source/target pairs of the primary 3-owner domain
and all 18 previously declared tasks from the 4-, 5-, and 6-owner domains. Keep
the 23 no-op and 310 unreachable primary tasks in the saved records. Compare
phase and installation costs separately on the 196 + 18 nontrivial reachable
tasks. All methods receive the same full catalog, directed +1 transitions,
positive compatibility formula, initial state, and target.

* `one-step` finds a shortest safe installation path by breadth-first search,
  expanding owners in numeric order, and uses one guard phase per installation.
* `shortest-path-segmented` uses that same deterministic path. A dynamic program
  examines every contiguous path segment and minimizes its number of legal
  phases. This is optimal for the selected path; it does not optimize over
  alternative shortest paths or longer installation paths.
* `interval-optimal` constructs every ordered compatible state pair satisfying
  the exact independent-coordinate interval-hull policy predicate, then finds
  the fewest-phase route. Every forward path between fixed endpoints has the
  same installation count, so this also minimizes the lexicographic (phase,
  installation) objective. This is a policy-specific exact control.
* `literal-products-optimal` enumerates all nonempty physical-profile products
  in the primary domain: (2^3-1)^2(2^5-1) = 1,519 raw products. It tests every
  product for safety, restricts each owner's directed transitions to that
  product, and enumerates reachable endpoint pairs. The resulting explicit
  phase graph solves the same lexicographic goal objective. The enumeration is
  limited to 2,000 raw products; larger domains use the interval control.
* `frontier-goal` is the frozen production GoalPlanner, with its existing limits
  and complete-frontier expansion. Recorded goal-policy costs are independently
  checked, and fresh timing runs also reproduce their status and cost.

### Physical products and positive guards

A physical-profile subset need not be represented exactly by positive terms:
projecting each included profile onto formula atoms and taking their disjunction
can admit additional catalog profiles. Nevertheless a safe product yields a
safe positive guard. Each corner of the projected terms is a projection of a
safe physical corner and therefore satisfies a branch of the same positive
formula; all accepted extensions remain compatible by monotonicity. The guard
contains every original local path. Conversely, the finite catalog accepted by
any safe guard is itself a safe physical product. Thus both searches have the
same optimum in these domains, without a one-to-one product/guard correspondence.
The primary construction uses at most five terms per owner and at most 45 term
corners before antichain reduction, within the deployed bounds. Saved phase
guards are checked literally, including any extra catalog profiles they accept.

## General finite relations and selected witnesses

Enumerate every nonempty relation on a 3 by 3 catalog (511 relations), under
four identical per-owner graph families: forward chain, reverse chain,
bidirectional chain, and complete directed graph. Keep all ordered compatible
source/target queries, including no-ops and unreachable pairs. Compare the same
deterministic shortest path plus exact contiguous segmentation to exhaustive
safe-product phase-graph optimization. Save every result, not just gaps.

Two examples found in an earlier exploratory pass are retained with full
witnesses. A forward-chain relation exhibits dependence on which shortest path
is selected. A complete-transition relation exhibits a stronger tradeoff: every
minimum-installation path needs three phases, whereas the phase-first optimum
uses two phases and four installations. Enumerate every shortest installation
path for both examples; independently check every possible phase partition of
those paths. Also run the frozen GoalPlanner on the examples.

## Timing and budgets

Timing is a separate command, run after the algorithm sources and non-time
records have been frozen. Use five repetitions and rotate route order each repetition;
each (domain, route, repetition) starts a fresh process pinned to the same
available CPU. Use a separate 30-second process-CPU budget per run. Include input
parsing, catalog/edge preparation, all declared queries, plan construction, and
cost serialization. Report preparation and query CPU time as well as the sum;
do not give one route a free precomputed graph. Reuse caches only within the
same cold cohort. To resolve observed zero CPU deltas on short cohorts, repeat
the entire cold cohort in each worker until at least 0.1 process-CPU second has
accumulated, with a maximum of 256 cohorts and the same 30-second CPU budget.
Reload the input and reconstruct the planner on every cohort; save every batch
duration, the repetition count, and the total charged CPU. Report the mean CPU
per complete cohort in each of the five independent repetitions. The retained
single-cohort timing pilot motivated this measurement-range correction; its
zero-duration records and an initially overlapping figure job are archived,
and none enters the final timing summaries.
The clock reports a nominal one-nanosecond resolution, so the observed equal
CPU readings are not attributed to that advertised resolution. They are kept
with the corresponding positive wall durations; the environment's CPU-accounting
cause was not established. The final measurement uses the same process clock
over longer intervals and makes no claim of zero computational work.
These modest finite-domain measurements compare
the actual declared algorithms, including the policy-specific shortcut, and do
not imply a universal speed advantage or large-deployment capacity.

## Independent acceptance

The checker imports neither the new baseline producer nor the production
planner. It rebuilds the task inventory and policy relation, checks full-profile
identity, directed edges, literal positive corners, guard-accepted catalog
products, and execution path continuity. It computes fixed-path segmentation
by enumerating every cut mask, separately from the producer's dynamic program.
It uses an independently built integer interval graph for policy optima and a
separate finite relation graph construction for the general sweep. Hashes bind
inputs, source preimages, raw rows, summaries, and timing records. Normal and
optimized-Python checks must agree. Semantic mutation controls exercise cost,
task inventory, and witness corruption after recomputing file hashes.

`timing-provenance.json` separates the frozen measured algorithm sources from
the final acceptance checker. The timed worker does not import the baseline
checker. After the final measurements, that checker was revised to compare the
numeric 30-second budget without confusing JSON `30.0` and `30`, and to verify
timed work counters, query counts and route order. The delivered manifest and
source preimages identify this final acceptance version; they do not assert
that its bytes were frozen before the measurements. The measured producer,
baseline algorithms and production components were unchanged by that revision.
