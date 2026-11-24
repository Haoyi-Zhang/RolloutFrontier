# Certified planning for chain compatibility constraints

`src.structured_planner.CertifiedGoalPlanner` accepts the same manifest,
physical catalogs, directed transitions and resource arguments as `GoalPlanner`.
It automatically recognizes a useful class of compatibility relations. The
complete frontier planner remains its exact fallback.

## Recognition

Every local transition graph must be one directed chain, including a single
isolated profile as a chain of length zero. Chain ranks are derived from edges;
version labels, owner roles and atom names carry no special authority. Distinct
physical profiles remain distinct even when their manifest projections agree.

Let R be the compatible catalog placements in these ranks. For every owner i
compute lower and upper bounds from R, and for every distinct i,j compute

    b[i,j] = max { x[i] - x[j] : x in R }.

These bounds contain R. Recognition succeeds only after checking every catalog
placement and finding that the bounds contain exactly R. A rejected hull keeps
an additional incompatible placement as a witness. A cycle, branching local
graph or disconnected local graph also selects the general fallback. There is
no numerical-policy shortcut that bypasses the original manifest.

Difference-bound representations are established mathematical tools. The
result used here concerns the greatest safe endpoint of a rollout phase and
its relation to the minimum number of durable guard admissions.

## Greatest safe endpoint theorem

Assume each owner has a finite directed chain with consecutive integer ranks.
Suppose compatibility is exactly the conjunction of unary rank intervals and
cross-owner inequalities x[i] - x[j] <= b[i,j]. Fix a compatible source s and
compatible target g with s <= g componentwise. A phase from s to t is feasible
if and only if its interval product is safe. For i != j, the largest difference
on that product is t[i] - s[j]. The maximum is attained at a Cartesian corner.
Self differences are always zero and must not constrain interval width.

Consequently its componentwise greatest target-capped endpoint is

    U[i](s) = min(g[i], upper[i], min_{j != i}(s[j] + b[i,j])).

The inner minimum is omitted for a single owner. Source compatibility gives
s <= U(s), and all coordinates of U are monotone functions of s. The product
[s,U(s)] satisfies every cross-owner bound and unary bound, so it is a safe
phase whenever it makes progress.

Let z(0)=s and z(k+1)=U(z(k)). For any feasible k-phase plan whose endpoint is
q(k), q(k) <= z(k). The induction starts at s. For its next phase, safety gives
q(k+1)[i] <= q(k)[j]+b[i,j] <= z(k)[j]+b[i,j] for every cross-owner bound,
and its endpoint cannot exceed g. Taking the minimum proves the induction.
Thus the first iterate reaching g uses the fewest phases. If an iterate is a
fixed point strictly below g, no finite phase plan can reach g. Every forward
chain path that reaches g makes exactly sum_i(g[i]-s[i]) installations, which
also establishes the secondary optimum. A target below the source at any
owner is unreachable; an identical source and target requires zero phases.

The proof holds for arbitrary connected or disconnected difference-constraint
graphs, including zero-slack cycles that prevent asynchronous progress. Given
the constraints, planning costs O(k(n+m)), where m is the number of cross-owner
bounds and k the number of successful phases, plus one fixed-point check when
needed. Automatic recognition in this implementation separately enumerates
the complete finite catalog and computes dense tight bounds; it costs
O(|P| n^2), in addition to evaluating the manifest. These costs are included
in the measured cold-cohort time.

## Original guard language and execution

For each interval, the implementation projects every visited complete profile
onto the original manifest atoms and forms the minimal antichain of these
projections. Every positive corner is a projection of a compatible physical
corner, so the guard is safe even when it accepts additional profiles. The
original guard checker checks every returned phase. The original eight-term
and 4,096-corner bounds continue to apply. The existing 4,096-placement bound
also bounds the product of the interval term counts. Neither the frontier
library-enumeration budget nor its phase-edge budget is spent by the recognized
path, because those enumeration procedures are not invoked. A rejected
structure retains the unchanged frontier limits and refusal behavior.

The output includes full local paths and ordered installations and can be
executed by `RolloutCoordinator`. The mathematical result covers finite chain
relations; the automatic recognition and execution evidence use the existing
bounded positive manifest representation.

## Evaluation design

The study is declared explicitly in the producer and independently checked. It includes all 547
existing policy tasks and all ordered compatible source/target pairs in every
nonempty relation on a 3 by 3 catalog (511 relations) and a 2 by 2 by 2 catalog
(255 relations). The latter two families use forward local chains. Every
relation is retained, including unrecognized relations that exercise the full
frontier fallback. These are finite mathematical validation families, not an
estimate of operational workload prevalence.

The original full-manifest execution path used in this difference-hull study
admits at most six owners. The separate [factored route](FACTORED-PLANNING.md)
checks overlapping local contracts and plans through 1,024 catalog owners; its
[physical execution study](factored-runtime.md) uses up to 32 owner processes.
The additional declared difference networks here include prerequisite chains with three
through six owners, four-owner fork and join stars, a four-owner diamond,
three- through six-owner equality cycles, and three-owner ternary skew,
precedence and asymmetric constraints. Every ordered compatible query is kept,
including no-ops and unreachable goals. They distinguish graph topology, rank
range, phase depth and fixed-point failure.

An independently written checker imports neither planner nor producer. It
evaluates literal compatibility, constructs the full safe interval phase graph,
solves its shortest paths, and checks recognition, emitted guards, paths, costs,
query coverage and summary totals. Corruption controls must reject a false
structure, changed cost and missing query. Regression tests separately cover
reversed and missing edges, cycles, equal projected physical profiles,
incompatible targets, no-ops and resource limits.

Timing is a separate command. Every route receives the same policy fixture and
queries; each cold cohort parses inputs, constructs the route, answers all
queries and serializes their costs. The comparison includes one-step execution,
optimally segmented shortest paths, interval exact search, literal products on
the primary domain, complete frontier search and certified structural search.
There are five independent workers per route and domain. Each worker repeats
whole cold cohorts until at least 0.1 process-CPU second has elapsed, under a
30-second process-CPU budget. Preparation and queries are reported separately,
along with their sum. Timings are run while other computational jobs are idle.

## Commands

From `artifact/`:

```sh
python -B -m tests.structured_planning_regression
python -B -m tests.structured_planning_study --out /new/output/directory
python -B -m tests.check_structured_planning --results /new/output/directory
python -O -B -m tests.check_structured_planning --results /new/output/directory
python -B -m tests.structured_planning_study --out /new/output/directory --timing
```

The constructor's recognition report is also available through
`planner.recognition()`. A successful recognition certifies an exact route;
failure chooses the general algorithm and does not assert unreachability.
