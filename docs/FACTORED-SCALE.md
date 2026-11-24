# Factored planning at increasing owner counts

The scale campaign plans the measured four-stage enum-alias migration on two
families of overlapping dependency graphs. A directed ring has one incoming
and one outgoing factor per owner. A directed circulant uses outgoing offsets
1, 2, 3, and 4, giving four incoming and four outgoing factors per owner. Each
edge is one two-owner compatibility factor. Duplicate edges and self loops
are excluded. Every owner uses the same four complete physical profiles from
the actual parser probes.

All ten conditions reach the full target in three phases and perform exactly
three installations per owner. The independent checks establish the complete
positive guards and physical paths as well as this optimal cost.

The homogeneous full-migration inputs also admit an optimal stage-priority
path: advance all owners to the reader-prepared rank, then to new emission,
then to the final program. A single edge proves the matching three-phase lower
bound. The measured costs therefore concern deriving and checking complete
plans and certificates through local factors. They do not establish a phase
advantage over this stage rule or a timing speedup against it. The
[stage-baseline derivation](stage-baseline-analysis.md) and
[complete path-analysis records](../results/schema-path-analysis/README.md)
give the stronger comparator and its complete small-corpus comparisons.

## Size, density and measured cost

CPU times include reading and parsing the immutable input, model preparation,
all factor recognition, the complete goal query, guard checking, and full
result serialization. Values are the median and full range of five fresh
worker means. Resident memory is the median of the five process peaks.

| Owners | Graph | Factors | CPU median (ms) | CPU range (ms) | Peak RSS median (MiB) |
|---:|---|---:|---:|---:|---:|
| 8 | Ring | 8 | 3.667 | 3.085–4.869 | 14.125 |
| 8 | Four-offset circulant | 32 | 10.785 | 8.494–18.140 | 14.625 |
| 32 | Ring | 32 | 13.269 | 12.886–18.092 | 15.000 |
| 32 | Four-offset circulant | 128 | 48.489 | 34.663–63.546 | 17.457 |
| 128 | Ring | 128 | 48.731 | 47.301–72.365 | 19.395 |
| 128 | Four-offset circulant | 512 | 163.603 | 147.716–246.002 | 27.910 |
| 512 | Ring | 512 | 250.178 | 220.170–298.149 | 35.562 |
| 512 | Four-offset circulant | 2,048 | 1,038.099 | 918.065–1,292.043 | 71.922 |
| 1,024 | Ring | 1,024 | 682.283 | 468.559–753.475 | 60.570 |
| 1,024 | Four-offset circulant | 4,096 | 2,432.822 | 2,387.080–2,549.133 | 130.207 |

Every factor has 16 physical catalog cells, 12 compatible tuples and 78
unordered maximum-closure pairs including self pairs. Across the three phases
it requires four positive guard corners. Thus a condition with `m` factors
checks `16m` local cells, `78m` joins and `4m` positive guard corners. The
largest condition has 65,536 local cells, 319,488 join checks, 16,384 positive
guard corners and 3,072 physical installations. Its complete serialized
witness occupies 6,024,048 bytes. The original work limits remain in force,
including the 4,096-factor limit. No global placement product is constructed.

The registered graphs measure the planner's response to owner count and factor
density. The source contracts come from actual ProtoJSON executions; these
graph sizes are controlled planning inputs. Runtime process and recovery
evidence is recorded separately by the factored execution campaigns.

## Aggregation and component accounting

The campaign uses five rounds of ten serial fresh Python workers. The
condition order rotates by one position in each round. Each worker repeatedly
builds a fresh planner and serializes its full result until its accumulated
process CPU time reaches 100 milliseconds, with a maximum of 256 cohorts and
a 30-second process CPU budget. No recognized model or query result is reused.

The final campaign contains 279 cohorts. At its observable resolution, the
process CPU clock reports zero for 20 cohorts. Their positive wall
intervals and complete witness records are retained. They remain in the
worker means; every worker still accumulates at least 100 milliseconds of CPU
time. The worker is the replication unit: the reported median and range use
the five worker means, without pooling their different cohort counts.

Each raw CPU interval is partitioned into seven components:

1. Input file reading and JSON parsing.
2. Physical chain and factor normalization.
3. Local relation recognition and contiguous axis tables.
4. Query work outside phase construction, including endpoint updates, state
   conversion and certificate copying.
5. Phase construction outside positive checks, including guards and paths.
6. Positive guard checks for every factor.
7. Full result serialization.

Nested observers surround unchanged planner methods. Their measured overhead
stays in the charged total. Interpreter startup, module imports, evidence file
writes, postcondition checksums and independent validation are outside the
interval. The seven component durations sum exactly to every raw cohort's
total. Peak RSS is the Linux process maximum across all cohorts, in KiB.

Component medians are separate descriptive statistics; their sum need not
equal the median total. An additive decomposition must use the components of
one identified worker or the arithmetic means over the same worker set.

## Inputs and independent validation

`results/factored-scale/probes.json` is an exact byte copy of the final
`results/schema-census/probes.json`. The campaign records source checksums and
preserves the executed source bytes. Each condition contains its complete
immutable input and full untimed witness. Every timed cohort must reproduce
that witness's exact serialized bytes. Refused inputs retain their original
factor density and refusal record.

The checker imports no planner or producer. It reconstructs the alias classes
from the saved parser records, checks the complete graph and factor inventory,
and rederives every local relation, maximum-closure check and contiguous prefix
certificate. It checks every phase's literal factor rectangles, positive guard
corners, full local paths and individual installations.

Three small controls use an independent global phase graph: a single directed
edge on two owners, a three-owner ring and the complete directed graph on three
owners. Each has an exact three-phase optimum. The single-edge result supplies
a lower bound for every larger graph: a global phase projects to a safe phase
on any edge. The checked synchronized rank endpoints supply a matching
three-phase witness for every large condition. This establishes optimality
without enumerating their global catalogs.

Both ordinary Python and `python -O` reconstruct identical semantic and timing
results. Seven corruption controls reject changed optimal costs, rank
endpoints, installation paths, positive guards, recognition tables, component
totals and timed-witness bindings.

## Commands and records

Verify the saved campaign:

```sh
python -B -m tests.check_factored_scale --results results/factored-scale --corruption-controls
python -O -B -m tests.check_factored_scale --results results/factored-scale --corruption-controls
```

Reproduce into a new directory, running the measurement command while other
campaigns are idle:

```sh
python -B -m tests.factored_scale_study --prepare --out results/factored-scale-reproduction
python -B -m tests.check_factored_scale --results results/factored-scale-reproduction --prepared --corruption-controls
python -B -m tests.factored_scale_study --measure --out results/factored-scale-reproduction
python -B -m tests.check_factored_scale --results results/factored-scale-reproduction --corruption-controls
python -O -B -m tests.check_factored_scale --results results/factored-scale-reproduction --corruption-controls
```

`inventory.json` fixes all conditions, controls and worker order.
`conditions/` and `controls/` retain full inputs and witnesses. `workers/`
contains each cohort stream and worker summary. `summary.json` contains the
reconstructed publication statistics; `checked.json` and
`checked-optimized.json` contain the independent check results. Source and
probe bindings are recorded in `environment.json`, with source bytes in
`sources/`.
