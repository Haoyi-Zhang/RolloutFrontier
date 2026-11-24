# Paths, interruption, and a fresh execution

The artifact opens evidence databases through escaped file URIs and keeps them
read-only from the moment SQLite opens the connection. Spaces, `#`, `?`, `%`,
and non-ASCII characters are accepted in directory and file names. Interrupting
the verifier stops the active checker process group, preserves its logs, and
finishes the report with `INCOMPLETE` and exit code 130.

## Run the controls

Run these commands from `artifact/` after installing
`requirements-application.txt`:

```sh
python -B -m tests.check_delivery_controls
python -B -O -m tests.check_delivery_controls
```

Each command prints one JSON result on standard output and unittest diagnostics
on standard error. It runs four test methods: two for SQLite paths, one for an
actual verifier interruption, and one for a checker timeout. The process-group
controls require a POSIX system with `ps`; Python 3.12 on Linux is the tested
environment. Skipped controls produce an incomplete result.

The SQLite controls create fresh database fixtures under six names, each read
through both an absolute and a relative path. They exercise 60 source
connections through the evidence readers and backup helper. Every connection
must return the intended rows and reject a write with `SQLITE_READONLY`, before
a reader can enable `PRAGMA query_only`. Another 48 calls open missing sources
and must return `SQLITE_CANTOPEN`. File inventories also check that no source
changed and no truncated-path database appeared.

To keep the process-control scripts, reports, and logs, select a new directory:

```sh
ROLLOUTFRONTIER_VERIFY_CONTROL_OUTPUT=/tmp/delivery-control-observations \
  python -B -m tests.check_delivery_controls
```

The fixture driver imports the actual verifier and registers two bounded
control tasks. The first creates a worker and a descendant in the checker's
process group. The test waits until both are running, then sends `SIGINT` to
the verifier parent alone. Both child processes must stop, the current task
must be `INTERRUPTED`, and the remaining task must be `NOT_RUN`. The timeout
control checks the same group cleanup while allowing the next task to finish.

## Verifier outcomes

The verifier writes an initial report before starting a checker. Later updates
replace the report atomically, so a reader sees a complete JSON document. A
terminal report records its finish time and exit code, with stdout and stderr
kept for each task that started.

| Event | Report status | Exit code | Task records |
| --- | --- | --- | --- |
| User interruption | `INCOMPLETE` | 130 | Active task `INTERRUPTED`; remaining tasks `NOT_RUN` |
| Checker timeout | `INCOMPLETE` | 2 | Timed-out task `TIMEOUT`; later requested tasks run while time remains |
| Requested subset succeeds | `PARTIAL` | 3 | Selected tasks pass; unrequested tasks are `NOT_RUN` |

The retained pre-repair interruption demonstrates why this handling is needed:
the parent exited after `SIGINT`, its separately launched checker remained
active, and the report still said `RUNNING`. The audit explicitly stopped that
remaining process. The repaired controls retain the terminal reports and both
log streams.

## Fresh TCP and SQLite execution

A short end-to-end run creates separate owner processes and TCP relays, runs
live application work, and exercises a recovery cohort:

```sh
python -B -m tests.factored_execution --smoke \
  --output '/tmp/fresh execution #?% Ünïcödé'
python -B -m tests.check_factored_execution \
  '/tmp/fresh execution #?% Ünïcödé/smoke' --output /tmp/fresh-smoke-check.json
python -B -m tests.check_factored_execution \
  '/tmp/fresh execution #?% Ünïcödé/recovery' --output /tmp/fresh-recovery-check.json
```

Choose an unused output directory; any non-ASCII name works. Add `-O` to the independent checker commands
to repeat their checks with Python assertions disabled.

The saved run in `results/delivery-portability/execution/` used a fresh directory
containing all of these character classes. Its independent checks reconstructed
the following counts from the owner databases, session journals, and traces:

| Cohort | Completed requests | Durable effects | Conditional installations | Owner audit rows |
| --- | ---: | ---: | ---: | ---: |
| Live execution | 8 | 32 | 9 | 139 |
| Recovery | 1 | 4 | 9 | 109 |

Both cohorts passed the independent reader in normal and optimized Python. Ten
deliberate evidence alterations were rejected in each interpreter mode. The
recovery evidence includes two discarded owner replies, a selected TCP cut,
and two foreign-session controls. The captured source files were compared
before and after execution; the accompanying source-binding record identifies
the exact implementation and its match to the current files when checked.

The same isolated environment also read seven retained input-counterexample
databases and two sets of 96 effect snapshots through special-character paths.
All 199 connections per interpreter mode rejected writes at open time, and the
copied source databases were unchanged. The counterexample-loader check covers
the historical manifest, table inventories, integrity, and rows; its scope does
not include a new comparison against a later application implementation.

## Retained evidence

`results/delivery-portability/capture-inventory.json` identifies the retained
files, their original capture locations, and their assurance scope. The package
includes dependency-installation logs, the isolated interpreter record,
the pre-repair path counterexample, the fresh execution, independent checks,
and interruption controls. The initial audit also compared all 14,141 files in
the previous delivery before and after its read-only checks and found no change.

Raw records keep the original machine paths and interpreter details. Their
package directories use portable names; no path inside a database, trace, or
captured command has been rewritten. The commands above are the portable entry
points for a new run. No virtual environment binaries are included.

The final wrapper capture passed in both interpreter modes. Its 150 source
files were preserved before execution, remained unchanged, and match the
source identities in all four interruption and timeout reports. These records
are in `controls/` and `interruption/complete-controls/`; the earlier direct
control reports retain their original identities in a separate directory.

These observations establish the tested path and interruption behavior on the
recorded Linux environment. The TCP run uses separate processes on one host.
Its elapsed-time fields are retained as execution metadata and are not added
to the paper's performance samples.
