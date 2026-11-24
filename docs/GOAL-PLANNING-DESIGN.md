# Reaching a rollout target with the fewest guard phases

## The objective and input

A rollout request supplies a current placement, a target placement, and the
allowed local transitions between finite candidate profiles. Success means
reaching the target. The planner minimizes the number of acquired guard phases
and, among plans with that phase count, the number of installations. This
objective does not reward toggling a profile back and forth.

Let owner `i` have a finite catalog `D_i` and a directed graph `H_i` on those
profiles. An edge of `H_i` is an installation that the deployment process permits.
For a minor-version upgrade, edges can be restricted to the next minor version;
the planner cannot replace a two-step upgrade by a direct jump. Omitting the
graph permits every change between distinct catalog profiles. These are
different planning instances and can have different installation costs.

Profiles are complete support lists. Distinct physical versions may include
distinct identity atoms that do not occur in the manifest. Their manifest
projections can be identical while their vertices and installation paths remain
different. Both current and target must appear in their owners' catalogs.

The joint state space is the finite Cartesian catalog. A state is feasible when
it satisfies the positive compatibility manifest. The admitted guard language
is the existing bounded language: conjunctions from projected candidate
profiles or branch requirements, at most eight options per owner, and at most
4,096 product corners. Current profiles are in the fixed catalog, so adding the
current anchor does not change the available conjunction library between states.
Frontier synthesis may still refuse at its declared execution bounds.

## What one phase permits

A phase fixes one safe guard product `E` that admits its starting state `s`.
For each owner, restrict `H_i` to profiles accepted by `E_i`. A phase can end at
`t` exactly when `t_i` is reachable from `s_i` in every restricted local graph.
The planner takes a shortest local path for each owner. Its emitted schedule
executes owners in increasing identity order; any interleaving preserving each
owner's local order is safe as well.

This condition concerns the entire local path, not just its endpoints. Two
versions may both pass a guard while the required intermediate version fails
it. Such endpoints do not define a one-phase edge through that guard.

The phase has cost `(1, sum of local path lengths)`. A nonempty phase changes at
least one owner. If current already equals target, the result has zero phases
and zero installations. Intermediate phases with no progress can be removed
because the next guard can be acquired at the same state.

An output phase contains:

```text
source: full-support placement
target: full-support placement
box: canonical safe positive guard product
local_paths: per-owner full-support paths, including both endpoints
steps: an interleaving of the local paths' installation edges
```

The top-level result retains the manifest, initial and target supports, catalog,
transition graphs, objective, budgets, phases and search accounting. Planning
does not create an admission certificate or authorize any installation.

## Why the frontier suffices

**Lemma 1 (phase realizability).** Fix a safe product `E`, a feasible source `s`
accepted by `E`, and catalog-covered local transition graphs. A target `t` can
be reached within that phase if and only if every owner has a path from `s_i` to
`t_i` in its accepted local subgraph. The minimum installation count within the
phase is the sum of the local shortest-path distances.

For necessity, project an execution onto each owner; every installation follows
an allowed edge and every visited local profile passes that owner's guard. For
sufficiency, interleave the local paths. At every intermediate joint state,
each coordinate passes its guard, so product safety implies compatibility.
Every execution uses at least each owner's shortest-path distance, and the
constructed interleaving attains their sum.

**Lemma 2 (frontier replacement).** If `E` and `E'` are safe products and `E'`
accepts every catalog profile accepted by `E` at each owner, any `E` phase is
also realizable under `E'`, with no greater minimum installation count.

Every permitted local path under `E` remains in the accepted subgraph under
`E'`. Adding vertices and edges cannot increase a shortest-path distance. The
initial anchor is retained, so `E'` remains eligible at the phase's source.
Equality of projected acceptance vectors also preserves every full-support
catalog profile, including profiles with different irrelevant identity atoms.

**Theorem (minimum-phase goal planning).** Suppose exact synthesis completes
where required, the phase-graph search completes within its budget, and all
permitted physical profiles are in the fixed catalogs. Searching only the
canonical frontier at each expanded state returns a plan with the fewest phases
among all plans formed from admissible safe guard products. Among plans with
that minimum phase count it returns one with the fewest installations. If the
search exhausts the reachable state space, its `unreachable` answer is exact for
these inputs and this guard language.

To prove the theorem, consider any admissible plan. Each phase product is
dominated by, or acceptance-equivalent to, a canonical frontier member at its
source. Replace it using Lemma 2, preserving the phase endpoints and not
increasing its installation count. Therefore the frontier-induced phase graph
contains a route no more expensive than the original plan. Conversely, Lemma 1
turns each graph edge into an admissible phase. Lexicographic costs are additive
and every nonempty edge has positive first coordinate, so ordinary Dijkstra
search obtains the minimum of this finite graph. The two directions equate
that graph optimum with the optimum over all admissible phase products.

The mathematical contribution here is the relation between acceptance-frontier
dominance and goal-directed phase planning. Shortest-path search is a standard
algorithmic component. A phase boundary is a coordinated operation; minimum
phase count is not a theorem about network round trips or elapsed time.

## Relation to centralized safe updates

The following additional result uses the expressiveness of this particular
guard language. It does not hold for an arbitrary restricted guard language.

**Proposition (reachability).** Suppose the language includes each projected
catalog profile as a conjunction and admits a two-option, two-corner product.
Then a target is reachable by admissible phases if and only if it is reachable
by a centralized sequence of individually permitted, compatible single-owner
updates, provided the exact searches complete.

One direction follows by expanding each phase into its local installation
paths. For the other, take a compatible one-owner transition from `s` to `t`.
Use the projected current profile as the singleton term at every unchanged
owner, and the projected source and target profiles as terms at the changing
owner. After antichain normalization there are at most two corners. Each is the
projection of `s` or `t`, so the corner criterion proves safety. These terms are
in the fixed library; their term and corner counts meet the assumed language
bounds. This gives a legal phase for each centralized update. The frontier
replacement lemma then supplies a phase in the searched graph.

The implementation's term and corner bounds satisfy these expressiveness
conditions. Library-size, frontier-size and search-work limits can nevertheless
produce an explicit refusal. A refusal says that the computation did not finish;
it does not establish that the target is unreachable.

## Why a phase cannot always run to its farthest local endpoints

Consider two owners with profiles `0,1,2`, local edges `0 -> 1 -> 2`, source
`(0,0)` and target `(2,2)`. Let the compatible relation be

`{(0,0), (1,0), (2,0), (1,1), (1,2), (2,2)}`.

The only maximal product at the source accepts `{0,1,2}` at the first owner
and `{0}` at the second. Running that phase to `(2,0)` reaches a dead end:
the required intermediate state `(2,1)` is incompatible, and reverse transitions
are forbidden. The successful optimum ends the first phase at `(1,0)`, proceeds
to `(1,2)` in a second phase, and reaches `(2,2)` in a third. It uses three phases
and four installations. The planner enumerates all reachable phase endpoints,
including these early stopping points. The regression suite fixes this example.

Compatible endpoints alone also do not imply reachability. Under the relation
`{(0,0),(1,1)}`, the two endpoints cannot be connected by any compatible
single-owner transition. No sequence of these independently safe phases can
implement an atomic two-owner switch.

## Search, caching and refusal

`src/goal_planner.py` exposes `plan_goal(...)` for one request and `GoalPlanner`
for repeated requests against a fixed manifest, catalog and transition graph.
Each expanded joint state gets its complete checked frontier once. For each
member, breadth-first searches find the accepted local paths. Their Cartesian
product gives the reachable phase endpoints. Parallel edges retain the shortest
installation count; deterministic guard and path order break remaining ties.
The resulting adjacency is cached only after the whole expansion completes.
Once a target route is known, a pending state is not expanded if its accumulated
cost plus `(1,1)` cannot improve that route. Every remaining nonempty phase must
cost at least one phase and one installation, so this pruning preserves the
optimum. In an independent two-owner goal it avoids expanding the other
one-phase states after a one-phase target route is already available.

Defaults permit 4,096 physical catalog placements, 250,000 generated phase-edge
candidates across one planner instance, and the existing 250,000 frontier search
prefixes per expansion. A candidate is a triple of expanded source, frontier
member and reachable destination; parallel candidates count separately.
Completed cached expansions do not consume that work again. Output accounting
separates new and cached expansions and retains the before/after counters.

All three bounds can be lowered for a run. They are not increased automatically.
Phase-edge exhaustion marks the instance exhausted; it cannot later present a
partial graph as an exact answer. Input errors, failed independent certificates
and unrelated implementation exceptions propagate as errors. Only the declared
resource exceptions become `GoalPlanningRefusal`.

## Execution contract

The plan's optimality concerns the fixed initial state, target, catalogs and
allowed transitions. It assumes no external writes or unrelated live holds
change the planned execution, and sufficient generation and admission sequence
headroom. Runtime admission remains authoritative if those conditions change.

At a phase boundary the source state is accepted by both consecutive products.
A coordinator can acquire the next phase before retiring the old one, preserving
continuous guard coverage. It must complete old-guard retirement before issuing
updates permitted only by the new phase. A partition may delay that retirement.
Resuming a rollout also requires durable knowledge of the selected plan and its
phase/step progress; ordinary recovery of individual admissions does not choose
which of two committed phase guards should be retired. The separate durable
rollout executor implements and tests that lifecycle.

## Independent evidence

`tests/goal_planner_oracle.py` enumerates every nonempty profile-subset product
inside a literal finite relation. It separately computes local graph paths,
phase edges and lexicographic shortest routes, without production guard search
or path routines. In the finite campaign, each such safe product has a
profile-derived positive-guard witness within the term and corner limits.

`tests/goal_planner_study.py` registers all nonempty relations over `2x2`, `3x3`
and `2x2x2` catalogs. It includes every compatible ordered source/target pair.
The `2x2` domain uses all 16 directed local-graph combinations; `3x3` uses complete,
forward-chain, reverse-chain and directed-cycle graphs; `2x2x2` uses complete,
forward-chain, reverse-chain and alternating-direction graphs. These are finite
logical domains, with no empirical frequency interpretation.

Every emitted plan is checked against the full safe-product optimum, its local
edges and positive corners are replayed literally, and reachability is compared
with an independent centralized safe-update graph. A saved-witness checker
reconstructs this registered design from the retained query stream. The unit
regressions separately exercise resource boundaries, cache isolation, invalid
inputs, zero-phase goals, directed paths and misleading endpoint shortcuts.
They also evaluate all 6,699 catalog truth-table cells of the 781 relation
encodings, checking the positive declarations against literal membership.

```sh
python -B -m unittest tests.goal_planner_regression -v
python -O -B -m unittest tests.goal_planner_regression -v
python -B -m tests.goal_planner_study --out /tmp/goal-study-new
python -B -m tests.goal_planner_study --check /tmp/goal-study-new
```
