# Static-batch finite checks

The normal and optimized executions produce identical semantic summaries for
147,420 monotonicity comparisons, 599,040 all-product/frontier batch comparisons
and 1,024 integrated selector calls, with zero mismatches. The checks also
exercise coverage, full-support no-ops, irrelevant atoms and off-catalog inputs.

`execution.json` identifies the canonical `summary.json`, both invocations and
their exit codes. Complete outputs are retained as `stdout.log` and
`optimized-stdout.log`, together with five exact source inputs. These finite
checks validate the static-batch mechanism; the goal-planning and structural
recognition cohorts address directed paths and target costs separately.

Run from `artifact/` with fresh output directories:

```sh
python -B -m tests.static_batch_optimality --out /tmp/theory-normal
python -O -B -m tests.static_batch_optimality --out /tmp/theory-optimized
```
