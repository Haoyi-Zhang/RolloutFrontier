# Same-information supplied-batch comparison

This cohort compares exact frontier selection with a greedy policy that has the
same complete supplied sequence and the same installed-change objective. Starting
from the current singleton rectangle, the greedy policy considers every safe
one-profile extension, replays the whole supplied sequence and selects the best
extension by the registered tie rule. It continues through zero-gain extensions
until none is possible. This is an independently specified comparison, not a
reimplementation of Homeostasis or another external system.

## Design and denominators

Six relation families and seeds 7000–7039 give 240 shared structural contexts.
The registered owner probabilities 0.50, 0.70 and 0.90 produce 720 conditions.
Each has a supplied sequence, an independent same-demand sequence and an
independent swapped-owner sequence, each containing 48 proposals. All 720
conditions completed, with 2,160 schedules, 103,680 proposals per policy and
311,040 observed owner policy events. The three probabilities reuse structural
contexts; they are not 720 independent structural samples.

The 480-context study under `results/supporting-studies/batch-generalization/`
uses different seeds, one probability (0.85) and a fixed-order batch-blind greedy
baseline. Its results and denominators must not be combined with this cohort.

## Results

Each aggregate row below contains 720 schedules. Static hindsight independently
enumerates every seeded safe rectangle using that row's evaluation sequence.

| Evaluation batch | Mass | Batch-aware greedy | Exact batch choice | Static hindsight |
| --- | ---: | ---: | ---: | ---: |
| Supplied | 5,529 | 6,653 | 6,711 | 6,711 |
| Same demand | 5,383 | 6,353 | 6,374 | 6,592 |
| Swapped owner | 5,607 | 4,343 | 4,468 | 6,558 |

On the supplied sequences, exact choice improves over batch-aware greedy in
14 conditions, ties in 706 and loses in none. The aggregate increase is 58
installed changes. Both policies obtain most of the gains over mass selection;
the additional complete search removes the remaining supplied-sequence static
regret in this registered cohort. This comparison does not isolate information
alone when contrasted with mass, because the objective also changes.

The same-demand totals are 6,374 exact versus 6,353 greedy, with nine wins,
704 ties and seven losses. At probability 0.70, exact has 2,141 installs versus
2,157 for greedy on the independent same-demand sequence. At probability 0.90,
the two policies tie on every condition in all three regimes. At probability
0.50, swapping the preferred owner leaves the demand distribution unchanged;
that regime is a second independent sample, not a distribution reversal.

The separate 22-proposal mechanism control records 20 exact installs and two
greedy installs. Its first greedy extension is strictly better under one-step
lookahead, but it excludes the rectangle that supports the repeated other-owner
changes. The complete control input, choices, forecasts and events are retained
in `mechanism-control.json` and checked independently.

## Verification and provenance

`registration.json` preserves the predeclared design and eight source hashes;
`source-preimage/` preserves the exact source bytes. `contexts.jsonl` contains all
inputs, guards, greedy extension traces and per-event observations;
`observations.csv` and `summary.json` retain their aggregates. `stdout.log`,
`stderr.log` and `execution.json` record this execution. The independent normal and optimized results are retained in `check-normal.json`
and `check-optimized.json`. The commands below recheck this cohort and exercise
the study's twelve failure-boundary methods.

Run from `artifact/`, using a new directory for the final command:

```sh
python -B -m tests.check_same_information
python -O -B -m tests.check_same_information
python -B -m unittest tests.study_failure_boundaries -v
python -O -B -m unittest tests.study_failure_boundaries -v
python -B -m tests.same_information --out /tmp/rollout-same-information-new
```

The data-only checker reconstructs the registered generators and random streams,
canonical guards, both exact tie orders, every greedy extension, each event and
all CSV/summary cells. The observations concern finite generated schedules and
in-memory owners, not production traffic or deployment timing.
