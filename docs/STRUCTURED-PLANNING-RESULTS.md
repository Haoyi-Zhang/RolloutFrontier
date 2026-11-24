# Certified structural planning results

Automatic recognition eliminates complete-frontier enumeration on the declared
version-policy inputs while preserving its exact phase-first objective. The
general frontier route remains active on relations whose difference-bound
hull contains additional incompatible states.

## Exact planning and recognition

The saved corpus contains actual `CertifiedGoalPlanner` outputs for every query.
An independent checker reconstructs each compatibility relation and solves its
full safe interval phase graph. All 17,710 status and cost answers agree, and
every planned execution passes literal directed-edge and positive-guard checks.

| Input family | Contexts | Exactly recognized | Queries | Structured queries | Frontier fallback queries |
|---|---:|---:|---:|---:|---:|
| Declared version policy | 4 | 4 | 547 | 547 | 0 |
| All nonempty 3 by 3 relations | 511 | 68 | 11,520 | 1,060 | 10,460 |
| All nonempty 2 by 2 by 2 relations | 255 | 73 | 4,608 | 916 | 3,692 |
| Connected difference networks | 15 | 15 | 1,035 | 1,035 | 0 |
| Total | 785 | 160 | 17,710 | 3,558 | 14,152 |

The 15 connected networks include precedence chains, fork and join stars, a
diamond, equality cycles, and ternary skew, precedence and asymmetric bounds.
Their 1,035 queries contain 384 nontrivial plans, 105 no-ops and 546 unreachable
goals. Successful plans use as many as six phases. Equality cycles exercise the
greatest-endpoint fixed-point certificate. The finite-relation families also
exercise exact rejection of non-zone relations and the existing complete
frontier fallback. These counts describe declared mathematical test families.

The original policy cohort remains unchanged: 214 nontrivial goals, 23 no-ops
and 310 unreachable targets. Its nontrivial plans use 345 phases and 710
installations, equal to the complete frontier and interval optima. Optimal
segmentation of the selected shortest safe path also achieves those costs.

Twenty boundary regressions cover reverse chains, branching or cyclic local
graphs, missing edges, equal projected physical profiles, singleton owners,
self bounds, no-ops, incompatible endpoints, zero-slack cycles, empty
relations, and resource refusals. They pass under normal and optimized Python.
The independent checker produces identical reports in both modes and rejects
false structural bounds, a changed optimal cost and an omitted query.

## Planning time

All routes were freshly measured in one comparison. A cold cohort includes
input parsing, common domain materialization, route construction, every query,
and cost serialization. There are five independent workers per table row;
each worker repeats whole cold cohorts until at least 0.1 process-CPU second
has accumulated. The table reports the median worker mean in milliseconds per
complete cohort. The primary cohort has 529 queries; each larger cohort has six.

| Owners | Queries | Shortest path with optimal partition | Interval exact | Complete frontier | Certified structure |
|---|---:|---:|---:|---:|---:|
| 3 | 529 | 62.799 | 51.982 | 355.430 | 117.042 |
| 4 | 6 | 2.363 | 3.249 | 121.356 | 4.038 |
| 5 | 6 | 4.834 | 8.927 | 521.657 | 6.954 |
| 6 | 6 | 10.355 | 35.874 | 2,246.969 | 13.334 |

Recognizing the chain/difference structure reduces median complete-frontier
CPU time by factors of 3.04, 30.05, 75.01 and 168.51 on these four cohorts.
The shortest-path segmentation control remains faster in each cohort and has
the same observed target costs. The certified route supplies a checked class
condition and a phase-optimality theorem for that class; it is not a universal
speed improvement over a policy-specific control.

For the certified route, the minimum and maximum worker means are
104.086–144.613 ms, 3.466–4.834 ms, 6.083–20.100 ms and 11.108–18.571 ms for
three through six owners. Every route's complete observed range, preparation
and query components, worker identity, cohort count and raw cost vector are in
`results/structured-planning/timing-summary.json` and its `timing/` directory.
Ranges describe five worker means rather than confidence intervals.

The 105 workers contain 1,190 cold cohorts. The process-CPU readings are equal
at both ends of 174 short subcohorts; these raw zero deltas are retained, and
they do not imply zero work. Every worker accumulated at least 0.100033544 CPU
second before averaging. Short preparation components can likewise be
unresolved. The numerical comparison uses complete worker intervals; the
underlying accounting cause of equal short-interval readings has not been
established. Component medians need not add to a total median because each is
taken separately across workers.

An earlier complete timing pass overlapped jobs that had already started; the
entire pass is excluded. The delivered pass started only after the other work
had stopped. After measurement, the independent checker was corrected to allow
nonnegative individual subcohort deltas while requiring the positive accumulated
interval, and to check unique context and worker identities. The measured
planners and timing producer were unchanged. `measurement-notes.json` records
these distinct roles; the final checker is not represented as having been
frozen before the measurements.

## Reading the evidence

`contexts.json.gz` contains every input, task inventory and recognition result.
`plans.jsonl.gz` contains the actual complete plans and unreachable answers.
`summary.json` contains their totals. `checked.json` and
`checked-optimized.json` contain the independent acceptance reports. The
planning theorem, recognition procedure, API and reproduction commands are in
`docs/STRUCTURED-PLANNING.md`.
