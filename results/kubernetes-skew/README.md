# Documented role-slice version constraints

The cohort checks all 36 vectors across three declared role slices, including
24 compatible seeds and 31 frontier members summed across those seeds. Three
loopback TCP/SQLite lifecycles execute 21 proposals, followed by owner and origin
reopening, authorization, retirement and delayed-prepare checks.

`results.json` retains the arithmetic rows and lifecycle observations.
`source-preimage/` preserves the 13 declared input and source files;
`execution.json`, `invocation.json`, `stdout.log` and `stderr.log` retain the
execution record. Independent saved-data checks pass in normal and optimized
Python.

The public policy supplies numerical constraints for declared support profiles.
The [boundary cohort](../policy-boundaries/README.md) tests a broader crossed
domain, and the goal-policy cohort checks target planning and execution.

Run from `artifact/`:

```sh
python -B -m tests.check_kubernetes_evidence
python -O -B -m tests.check_kubernetes_evidence
python -B -m tests.kubernetes_skew_study --out /tmp/skew-new
```

The final command executes a fresh study and requires a new output directory.
