# Stage-priority paths and topology orbits

This analysis strengthens the path comparison without changing a recorded
application probe, production-planner result or timing measurement. It reads
the complete retained schema census and the existing finite factor corpus.
The analyzer imports only Python's standard library.

## Compared paths

The existing owner-priority comparator constructs one shortest safe path for
each of the six owner expansion orders, then finds each path's minimum-phase
partition. The best of six is retained.

The added stage-priority rule repeatedly selects an enabled target-directed
one-rank installation at the owner with the least current physical chain rank.
A fixed permutation breaks ties. The rule uses the declared ranks and safe
single-owner transitions, without calling the production planner or its
greatest-endpoint procedure. Exact dynamic programming then minimizes phases
on the chosen path. We retain one fixed tie order, the best of all six tie
orders, and the best of the existing six owner-priority paths plus that one
fixed stage-priority path.

## Complete application census

All 252 contexts and 186,174 compatible ordered source/target queries are
retained: 6,522 no-ops, 61,938 reachable changes and 117,714 unreachable goals.
An independent literal interval-phase graph reconstructs the optimum for every
query. Every saved owner-priority path and partition is replayed. No timing
comparison is made between these algorithms.

| Migration | Reachable changes | Owner-priority six gaps | Fixed stage-priority gaps | Stage-priority six gaps |
| --- | ---: | ---: | ---: | ---: |
| Enum alias | 23,238 | 30 | 277 | 0 |
| Field key | 23,238 | 30 | 277 | 0 |
| Field addition | 7,731 | 2 | 0 | 0 |
| Integer widening | 7,731 | 2 | 0 | 0 |

The same-size six-path stage-priority portfolio matches the exact optimum on
every reachable application change. The seven-path combined control also
matches throughout. Every one of the 252 complete legacy-to-final migrations
is phase-optimal under even the fixed stage-priority rule. The application
corpus therefore demonstrates priority sensitivity and exact certification,
without an observed phase advantage over the strongest added portfolio.

## Topology and query equivalence

The 63 labelled nonempty directed three-owner graphs comprise 15 graph
isomorphism classes. The complete `motifs.csv` retains every class, its number
of labelled graphs and all query/outcome denominators. Graphs and goals are
also canonically relabelled under all six owner permutations; a query orbit
includes its graph, source and target, not merely its graph motif.

For each rename mechanism, the existing owner-priority portfolio's 30 gaps
occur on two motifs: 12 gaps among 600 reachable changes on the two directed
three-cycles, and 18 among 1,596 changes on the six cycles with one reverse
edge. These form seven distinct graph/source/target orbits. All other 55
labelled graphs tie that portfolio. For each extension mechanism, the two gaps
occur among 222 changes on the two directed cycles, forming one query orbit.
All other 61 graphs tie. These are exact facts about the registered census,
not estimates of how often these motifs occur in deployed systems.

Single-stage-path failures depend on its fixed owner tie order. Accordingly,
`query_orbits_with_fixed_stage_gap` counts an orbit when at least one labelled
member fails; it does not assert that fixed-order performance is invariant
under relabelling. The portfolios that range over all permutations have no
such distinguished owner label.

## Existing finite-model control

The analyzer separately reconstructs the recorded finite factor campaign:
991 registered contexts, 519 factorwise max-closed contexts and all 7,835
ordered goals in those recognized contexts. It independently derives factor
closure from the positive manifests and physical catalogs, then checks literal
global phase graphs and both path portfolios.

The two mirror contexts `ternary-pair-311` and `ternary-pair-473` show that the
stage rule is not a general optimality result. In the first, compatibility is
`x0 <= x1` on ranks 0, 1 and 2. From `00` to `22`, both stage tie orders follow
`00, 01, 11, 12, 22`; even its optimal partition uses three phases. The exact
plan uses `00, 02, 22` in two phases. The fixed-owner portfolio contains that
better path. The retained summary reports all finite ties and unreachable
goals as well as the two counterexamples; it does not claim that the combined
portfolio fails on these examples.

The finite inventory contains 2,104 reachable changes, 1,781 no-ops and 3,950
unreachable goals. The stage portfolio needs an extra phase on exactly the two
mirror changes and ties the other 2,102. The fixed-owner and combined
portfolios tie the optimum on all 2,104 changes. These complete denominators
remain separate from the application census.

## Records and validation

`summary.json` retains every family and motif denominator, full-goal outcomes,
query-orbit representatives and multiplicities, paths for representative
single-stage failures, and the complete finite control. `inputs.json` binds
the eight consumed input files and the exact analyzer source retained in
`sources/`. The checker reconstructs all results from those inputs and also
checks the CSV against its reconstructed table.

Six derived-record corruption controls remove a genuine gap, invent a stage
gap, redistribute gaps between motifs without changing family totals, change
orbit multiplicities without changing total gaps, erase the finite
counterexamples, and alter a counterexample path without changing its cost.
All are tested against the independently reconstructed result. The controls do not
modify or replace the original scientific evidence.

From `artifact/`, verify the delivered analysis in either Python mode:

```sh
python -B -m tests.analyze_schema_paths --census results/schema-census --check results/schema-path-analysis --corruption-controls
python -O -B -m tests.analyze_schema_paths --census results/schema-census --check results/schema-path-analysis --corruption-controls
```

To reconstruct it into a new directory:

```sh
python -B -m tests.analyze_schema_paths --census results/schema-census --out results/schema-path-analysis-reproduction --corruption-controls
```

The finite corpus defaults to `factored-planning/` beside the census directory;
`--finite` selects an explicit retained corpus location when needed.
