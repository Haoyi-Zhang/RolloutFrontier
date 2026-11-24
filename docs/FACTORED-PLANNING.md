# Exact planning with overlapping compatibility factors

The factored route represents compatibility as a conjunction of small positive
disjunctive predicates. Factors may overlap: every occurrence of a service uses
the same physical profile catalog and directed installation chain. Recognition
enumerates each factor's own catalog, without constructing the global placement
product. It accepts a factor when its compatible rank tuples are closed under
componentwise maximum.

This route is implemented in `src/factored_planner.py`. The general planner,
positive-box checker, owner protocol, and their existing measurements retain
their original source files.

## What the certificate establishes

Write the global compatible relation as

\[
  R=\{x: x|_{P_f}\in R_f\text{ for every factor }f\}.
\]

Each owner has a finite directed chain of complete physical profiles. Rank is
position on that chain; lexical order of profile names has no semantic role.
For a compatible local tuple \(a\), the recognition certificate records

\[
  L_{f,i}(a)=\max\{t:\;a[i\leftarrow r]\in R_f
                      \text{ for every }a_i\le r\le t\}.
\]

This is a contiguous prefix. A compatible rank beyond an incompatible
intermediate profile does not extend the prefix.

For a compatible source \(s\) and target \(h\ge s\), define

\[
 U_i(s)=\min\left(h_i,\min_{f:i\in P_f}L_{f,i}(s|_{P_f})\right).
\]

If every factor is closed under componentwise maximum, so is their global
conjunction. Every point of the rectangle \([s,U(s)]\) is a componentwise maximum
of its single-coordinate axis points, which are compatible by construction.
Thus the rectangle is safe under every interleaving of the permitted local
steps. Conversely, every safe rectangle starting at \(s\) contains its own axis
points, so its endpoint is at most \(U(s)\).

The greatest endpoint is monotone on compatible states. For compatible
\(s\le z\), any point \(w\in[z,U(s)\vee z]\) can be written as
\((w\wedge U(s))\vee z\). The first operand lies in the safe rectangle
\([s,U(s)]\), and maximum closure makes their join compatible. Consequently
\(U(z)\ge U(s)\vee z\). Induction shows that successive greatest endpoints
dominate the endpoint of every other plan after the same number of phases.
The first iterate reaching the target therefore uses the fewest phases. A
fixed point before the target certifies that no forward plan reaches it.

Every forward chain plan from \(s\) to \(h\) performs exactly
\(W=\sum_i(h_i-s_i)\) installations. The result is therefore optimal for the
lexicographic objective of phases first and installations second. There are at
most \(W\) productive updates, followed by at most one fixed-point check.

## Runtime authority

The phase compiler gathers all compatibility atoms that refer to a physical
owner across its incident factors. It projects the owner's interval profiles
onto that union and reduces them to one positive antichain. An owner receives
one guard for the conjunction, including when many factors share it.

For each factor the compiler projects those same owner guards onto the factor's
atoms, maps its owner names into a local namespace, and calls the existing
positive-box checker. These checks establish the implication for arbitrary
supports satisfying the positive guards, not only for catalog profiles. The
returned local paths and installation steps retain complete physical profiles.

`validate_factored_plan` reconstructs the input model and checks the entire
execution witness: source and target compatibility, phase continuity, all
positive guard products, every local path, every chain edge, and the declared
cost. Execution safety does not rely on trusting the recognition metadata.
Optimality and refusal certificates are separately checked by the independent
finite oracle.

## Input and result interface

```python
from src.factored_planner import FactoredChainPlanner, validate_factored_plan

planner = FactoredChainPlanner(factors, candidates, transitions)
plan = planner.plan(initial, target)
if plan['status'] == 'planned':
    validate_factored_plan(plan)
```

`factors` is a list of dictionaries with `id` and `branches`. Each branch maps
global owner names to required atom lists. The branches within one factor share
the same owner scope. `candidates` maps owner names to full profile lists.
`transitions` maps each owner to dictionaries containing the full `source` and
`target` profiles for its permitted edges. Initial and target states use the
same owner-to-profile format. Self loops are treated as no-operations.

Every catalog owner must appear in a factor. An explicitly unconstrained owner
can use a unary true factor with the branch `{'owner': []}`. Repeated owner
names in different factors refer to one physical state, never separate copies.

A planned result contains the canonical factors, catalog and transitions, full
initial and target states, recognition certificate, rank iterates, cost, and
the complete phase witnesses. An unreachable result carries its reason and
numeric trace, with no execution phases. Malformed inputs raise `ValueError`.
Unrecognized structure or an exhausted declared work budget raises
`FactoredPlanningRefusal`, whose `reason` and `witness` remain distinguishable
from a proved unreachable goal.

The default resource contracts admit 1,024 owners, 4,096 factors, 4,096 local
placements per factor, 262,144 local placements in total, 4,000,000 checked
maximum pairs, and 8,192 installations. Callers can lower these limits using
`max_owners`, `max_factors`, `max_factor_placements`,
`max_total_factor_placements`, `max_closure_pairs`, and `max_steps`. Each factor
still uses the existing positive-language bounds of six local owners and eight
alternatives. These are explicit implementation work contracts; they are not
global placement enumeration limits.

## Cost and applicability

Let \(N_f=\prod_{i\in P_f}q_i\), let \(r_f=|R_f|\), let \(d_f=|P_f|\),
and let \(q=\max_i q_i\). Recognition evaluates exactly \(N_f\) local
placements per factor, with the predicate's evaluation cost charged at each
placement. Maximum closure takes \(O(\sum_f r_f^2d_f)\) time, and contiguous
axis tables take \(O(\sum_f r_fd_fq)\) relation lookups. Constructing and
hashing the rank tuple for a lookup adds \(O(d_f)\) work in this implementation.
Once recognized, numeric updates
take \(O((k+1)(n+\sum_f d_f))\) time for a \(k\)-phase result. The returned
paths and steps have \(O(kn+W)\) profile occurrences. Constructing positive
guards, checking their factor-local corners, and copying or serializing the
witness incur additional output-dependent costs and are included in the scale
measurements.

Local arity remains a parameter: the method does not remove the exponential
cost of enumerating one large factor. Directed chains also exclude branches
and backward installation edges. Componentwise maximum closure is sufficient
for this exact route; minimum closure is unnecessary. Factorwise maximum
closure is sufficient but not necessary for the global conjunction: another
factor can exclude a nonclosed factor's counterexample. The recognizer reports
the local counterexample instead of assigning an unreachable result to that
input.

For example, `{00, 10, 01}` is not maximum closed because the maximum of `10`
and `01` is the missing `11`. Intersecting it with a factor admitting only `00`
makes the global relation closed, but the local recognizer still refuses the
first factor. The unary relation `{0, 2}` is maximum closed while the hole at
rank 1 blocks a chain migration from 0 to 2. The equality relation `{00, 11}`
is also maximum closed but has no productive asynchronous first phase from
`00`.

## Independent evidence

`tests/factored_planning_oracle.py` uses only the Python standard library and
does not import the planner. It reconstructs physical chains, local truth
tables, closure witnesses and axis tables. For small inputs it enumerates the
entire global phase graph from literal interval rectangles and solves it by
breadth-first search. It separately checks positive guard corners and every
installation in each returned witness.

`tests/factored_planning_study.py` collects all 511 nonempty relations on a
three-by-three pair, all 255 nonempty relations on three binary owners, and
all 225 pairs of nonempty binary relations sharing one owner. Recognized
contexts include every ordered compatible source and target. The independent
checker validates complete inventories and rejects deliberately corrupted
costs, guards, paths, certificates, and missing evidence.

```sh
python -B -m tests.factored_planning_regression
python -O -B -m tests.factored_planning_regression
python -B -m tests.factored_planning_study --out results/factored-planning-reproduction
python -B -m tests.check_factored_planning --results results/factored-planning-reproduction --corruption-controls
python -O -B -m tests.check_factored_planning --results results/factored-planning-reproduction --corruption-controls
```

The producer requires a new output directory and captures its executed source
bytes. To reproduce an existing saved campaign, choose a different output
directory. Neither the producer nor checker overwrites the registered data.

## Scale campaign

`tests/factored_scale_study.py` takes the four complete enum-alias profiles
directly from the measured `results/schema-census/probes.json` file and retains
its exact bytes. It builds directed rings with one outgoing edge per owner and
directed circulants with outgoing offsets 1, 2, 3, and 4. Both graph families
use 8, 32, 128, 512, and 1,024 owners. Each directed edge is one compatibility
factor. The largest condition therefore has 4,096 factors, with all original
resource limits still in force. Graphs are simple: duplicate edges and self
loops are excluded.

The full goal installs every owner from the first to the fourth profile. The
three synchronized endpoints, at ranks 1, 2, and 3, give safe phase rectangles
in both families. A single alias edge already needs three phases to move both
ends from rank 0 to rank 3. The independent full phase graph on that two-owner
control proves the lower bound; projecting any global plan onto its edge
preserves it. Three-owner ring and complete-digraph controls additionally
compare the entire returned witness with the global oracle. The large cases
recheck every local relation, every phase rectangle, every positive guard
corner and every full-profile installation without enumerating a global
placement product.

Preparation and measurement are separate commands. Preparation records the
complete inputs, full witnesses, source bytes and a fixed inventory before
any timings are collected. The measurement order rotates through ten
conditions across five rounds. Every condition has five fresh Python workers,
with a fixed hash seed. A worker repeats cold cohorts until their combined
process CPU time reaches 100 milliseconds, subject to a 256-cohort count limit
and a 30-second process CPU budget. Each cohort builds a fresh planner; no
recognized model or phase result is reused. Individual CPU deltas may be zero
at the runtime's observable clock resolution. Such cohorts remain in the raw
records and means; the worker must still accumulate at least 100 milliseconds
of positive CPU time. Summaries count all zero-CPU cohorts explicitly.

The charged interval starts before reading and parsing the immutable input
and ends after serializing the full returned witness. Nested observers divide
this interval into input preparation, model normalization, recognition, query
work outside phase construction, phase construction outside positive checks,
positive guard checks, and serialization. These seven mutually exclusive
components sum to the charged total. Query work includes certificate copies
and state conversion as well as numeric endpoint updates. Interpreter startup,
imports, evidence writes, postcondition checksums and independent validation
are outside the interval. Observer overhead within the interval stays charged.
Peak resident memory is the Linux process maximum across the worker's cohorts.

Every timed cohort must produce the exact same serialized witness bytes as
the prepared condition. Raw cohort measurements and worker means are retained.
Reported medians and full ranges are calculated over the five fresh-worker
means, preserving the worker as the replication unit. The independent checker
reconstructs all aggregates and rejects changed costs, endpoints, paths,
guards, recognition tables, timing totals, and measured-witness bindings.

```sh
python -B -m tests.factored_scale_study --prepare --out results/factored-scale-reproduction
python -B -m tests.check_factored_scale --results results/factored-scale-reproduction --prepared --corruption-controls
python -B -m tests.factored_scale_study --measure --out results/factored-scale-reproduction
python -B -m tests.check_factored_scale --results results/factored-scale-reproduction --corruption-controls
python -O -B -m tests.check_factored_scale --results results/factored-scale-reproduction --corruption-controls
```

Run the measurement command while other campaigns are idle. A failed worker
leaves its completed cohort records available for inspection. A refused case
retains its complete original input and refusal; the producer does not reduce
factor density to obtain a successful plan.
