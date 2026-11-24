# Current physical execution evidence

These nine cohorts were executed after admission identities were bound to a
persisted session birth identity. The six large trials use 32 independent owner
processes; two extension controls use five owners, and the separate recovery
cohort uses three owners. Actual loopback TCP relays, process exits and durable
SQLite records are retained alongside the complete application inputs and
outputs.

The cohorts complete 185 requests, 4,884 durable effects, 605 installations and
8,811 input-wire parses. Only the 128 steady-target requests in the eight live
trials contribute to request-duration summaries. Deliberately paused requests
and recovery controls are excluded from that timing sample. The environment
record defines the host, concurrency and execution configuration.

`source-files.json` lists 29 executed source files. Their retained copies equal
the current artifact and remained unchanged during capture. `check-normal.json`
and `check-optimized.json` are identical independent replays of all nine cohorts,
including final SQLite/completion binding. `checker-controls.json` retains ten
rejected semantic alterations. The recovery cohort also retains fresh and
previously initialized same-label journals; each is rejected twice while the
original request and its owner obligations remain pending.

From the artifact directory, replay without rerunning processes or timings:

```sh
python -B -m tests.check_factored_campaign
python -O -B -m tests.check_factored_campaign
```

To execute a fresh campaign, choose a new output directory:

```sh
python -B -m tests.factored_execution --output /tmp/rollout-physical-execution
```

The producer records every process and socket control anew. Saved-record replay
checks the retained operations and their durable consequences; it does not
re-execute those faults. Earlier captures and their original source files remain
unchanged in `../retained-runtime/` and are excluded from current timing tables.
