# Supporting protocol and static-batch studies

These four cohorts exercise the conditional-install controller and its
application-effect interface. Each retains the complete registered design,
observations and independent checking records.

| Directory | Complete design | Verification |
| --- | --- | --- |
| `semantic/` | 17 jobs, 23 deterministic outputs, 33 typed numerical bindings | Semantic decisions, certificates, CSV rows and traces agree with the reference observations. |
| `batch-generalization/` | Six families, 80 seeds each and three regimes; 480 contexts and 1,440 schedules | All 207,360 owner policy events and registered choices are reconstructed independently. |
| `effect-drain/` | 24 lifecycles: 12 commits and 12 cancellations | Guard retention, fences and stored effects are inspected in 96 SQLite snapshots. |
| `lifecycle-costs/` | Four policies, two payload sizes, two batches and three repeats; 48 lifecycles and 1,152 proposals | Costs include five owner processes, full SQLite synchronization, TCP, reopen, use and retirement. |

The cost cohort runs on its recorded pinned logical CPU, without concurrent
project benchmarks. Its records retain every invocation, environment, output
and source input. Three repetitions per cell support descriptive medians for
that environment. The semantic cohorts establish logical outcomes and are not
pooled with these timing measurements.

The batch study uses seeds 6000–6079, owner probability 0.85 and a fixed-order
greedy comparator without the supplied batch. The
[same-information study](../same-information/README.md) instead supplies both
selectors with the same sequence and contains 720 conditions. Their denominators
remain separate. Static installation counts include accepted changes and can
include rollbacks; goal completion is checked by the goal-directed cohorts.

`check-report.json` and `check-report-optimized.json` retain the independent
saved-data results. `batch-rows.tex` and `lifecycle-rows.tex` are derived from the
checked observations. Run the following commands from `artifact/`:

```sh
python -B -m tests.check_supporting_evidence
python -O -B -m tests.check_supporting_evidence
python -B -m unittest tests.supporting_evidence_regression tests.study_failure_boundaries -v
python -O -B -m unittest tests.supporting_evidence_regression tests.study_failure_boundaries -v
python -B -m tests.capture_revision_study semantic --out /tmp/semantic-new
python -B -m tests.batch_generalization --out /tmp/batch-new
python -B -m tests.capture_revision_study effects --out /tmp/effects-new
python -B -m tests.capture_revision_study costs --out /tmp/costs-new
```

The first four commands check records or acceptance boundaries. The remaining
commands execute new studies and require new output directories outside the
artifact. Run cost measurements without competing benchmark or build jobs.
