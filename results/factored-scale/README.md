# Factored planning scale

Ten conditions cover rings and four-offset circulants at 8, 32, 128, 512 and
1,024 owners. Each has five serial fresh workers. Every plan includes all
positive guards and local installations, and every timed cohort serializes
the complete witness.

The saved campaign contains 50 workers and 313 complete cohorts.
All 36 zero-CPU cohorts remain in the worker means; every worker
accumulates at least 100 milliseconds of process CPU time. Medians and ranges
use the five worker means for each condition. CPU timing includes input
preparation, model creation, recognition, the complete query, guard checks and
serialization. Resident memory is the process peak.

`summary.json` gives the retained statistics. `checked.json` and
`checked-optimized.json` contain identical independent reconstructions and
seven rejected corruption controls. `environment.json`, `inventory.json`,
`sources/`, `conditions/`, `controls/` and `workers/` retain the full
measurement inputs and records.

The homogeneous full migrations also admit an optimal synchronized stage
path. These measurements describe the cost of constructing and checking the
complete factored plans; they do not claim a phase or speed advantage over
that specialized rule. See `../../docs/FACTORED-SCALE.md` for all values and
reproduction commands.
