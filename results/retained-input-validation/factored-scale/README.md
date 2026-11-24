# Factored alias scale evidence

This directory contains ten registered planning conditions: directed rings and
four-offset directed circulants at 8, 32, 128, 512 and 1,024 physical owners.
Each edge is a two-owner factor using the measured four-profile enum-alias
contract. Rings have `n` factors and circulants have `4n` factors. Each factor
has 16 catalog cells, 12 compatible tuples and 78 checked maximum pairs. Every
condition returns three phases and `3n` physical installations.

The final capture uses 50 serial fresh workers in five rotating rounds and
contains 263 cold cohorts. Fourteen ring-8 cohorts record zero CPU deltas;
all are retained, and every worker still accumulates at least 100 milliseconds
of CPU time before stopping. Medians and full ranges use the five worker means
per condition. Each raw total is the exact sum of seven components: input
reading/parsing, model normalization, recognition, query work outside phase
construction, phase construction outside positive checks, positive factor
checks, and full result serialization. RSS records the Linux process peak.

`probes.json` is byte-identical to the final schema-census probe file. The
environment record binds the source files and preserves their executed bytes.
Every measured output matches its condition's full immutable witness. No input
or density is reduced after a refusal.

The independent checker uses full global phase graphs on the two-owner edge,
three-owner ring and complete three-owner directed graph. The edge supplies a
three-phase lower bound; checked synchronized endpoints attain it on every
large graph. For all conditions it rechecks local relations, closure and prefix
tables, literal phase rectangles, positive guard corners, full physical paths,
installations, complete inventories, timing sums and aggregates. Both Python
modes pass, and seven deliberate corruptions are rejected.

From the artifact root, verify:

```sh
python -B -m tests.check_factored_scale --results results/factored-scale --corruption-controls
python -O -B -m tests.check_factored_scale --results results/factored-scale --corruption-controls
```

To recollect, select a new output directory and reserve an idle measurement
window between preparation and measurement:

```sh
python -B -m tests.factored_scale_study --prepare --out results/factored-scale-reproduction
python -B -m tests.check_factored_scale --results results/factored-scale-reproduction --prepared --corruption-controls
python -B -m tests.factored_scale_study --measure --out results/factored-scale-reproduction
python -B -m tests.check_factored_scale --results results/factored-scale-reproduction --corruption-controls
```

See `docs/FACTORED-SCALE.md` for exact denominators, timings, accounting and
validation scope. `inventory.json` fixes the conditions and worker order;
`conditions/` and `controls/` contain full inputs and witnesses; `workers/`
retains raw cohort streams and worker summaries. `summary.json`, `checked.json`
and `checked-optimized.json` give the independently reconstructed results.
