# Durable goal execution and recovery

The `src/rollout.py` executor, the atomic conditional-installation extension in
`src/controller.py`, and `tests/rollout_recovery.py` were executed in normal and
optimized Python. Both modes passed **24 test methods**, with zero failures,
errors or skips. Each mode retained **23 observations and 60 SQLite snapshots**.

Each mode includes six registered coordinator SIGKILL cuts. Two owner processes
remain alive and answer inspection requests after the coordinator exits. One
owner is then separately SIGKILLed and reopened before the coordinator resumes
solely from its job database. Thus the per-mode kill counts are six coordinator
kills and six owner kills. These six scenarios are subcases of one test method,
not twelve additional test methods.

`normal/` and `optimized/` contain summaries, observations and database images.
The adjacent stdout/stderr logs retain the full test execution. `verification.json`
binds the two summary files, verifies every retained database hash, and compares
counts and source identities. Every tested source has its exact retained bytes
under `source-preimage/`. The test driver checks source hashes before and after
execution. The accompanying documentation snapshot has a separate hash and is
not classified as an executed source.

## Phase-local progress and communication counts

Three controls exercise the selected-owner read and conditional write.
A TCP proxy closes the coordinator's connection to an owner and rejects new
streams while that owner's original server remains alive. Separate inspection
probes verify the owner's retained hold. Two planned installations complete
while an unrelated owner's route is unavailable; the phase endpoint then waits.
An unavailable selected owner instead leaves the current step pending, without
skipping ahead. A guard-respecting external update to an unselected owner is
reported at the phase boundary, with authority retained until the expected
configuration is restored.

`locality-comparison/` contains a separate source-bound replay of the retained
global-preread runtime and the current runtime. Both receive the same previously
recorded three-owner, three-phase, six-installation goal. The actual traces
contain **48 read RPCs with global pre-reads and 36 with owner-local pre-reads**. Both executions
send nine prepares, nine closes and six conditional installations. The paired
TCP partition control advances zero planned steps with global pre-reads
and two with owner-local pre-reads before the boundary blocks. Both finish after
the route heals. The comparison retains inputs, raw traces, summaries and both
runtime source images; its counts are not extra recovery test methods.

These are logical request counts from one retained goal and a controlled local
transport failure. They are not latency or fleet measurements. The executor
uses one fixed serial step order, and a partition at the selected owner can
still prevent progress to later steps.

## Recovery and target controls

The remaining controls cover safe phase overlap, phase-role recovery, four-phase
reuse of two origins, lost admission and retirement messages, an installed state
whose response was lost, an actual SQLite job-transaction abort, postcommit job
uncertainty, malformed plans and durable roles, foreign authority, delayed old
prepares, and an external update between the read and conditional installation.
Already-target reconciliation is reported separately from the job's durably
recorded installation acknowledgements.

Two controls verify target observation. A single sequential collect can assemble
a target vector that never coexisted, while two stable full collects detect the
interleaving. An ABA update is detected through its advanced generation even
when its final support equals the first observed support. Both controls remain
in both normal and optimized cohorts.

## Mechanism-removal controls

`before/manual-before-project/` contains the source subset used by the manual
handoff control, and `before/manual_handoff_crash.py` is its executed driver.
`before/manual-handoff-crash/` records an actual SIGKILL between next-phase
commitment and old-phase retirement. Generic client recovery preserves both
committed admissions, so the old guard still blocks the target. This control
isolates the need to persist phase roles and the intended next action.

`before/target-snapshot-before/` retains the single-collect control and its
observed counterexample. That collector reports completion for `(A,B)` while
the actual trace is `(A,B') -> (A',B') -> (A',B)`. The versioned double collector
returns `target-snapshot-changed`. `before/controller-input/` retains the
controller input used to introduce the conditional operation. These files
identify the executed controls and their observations.

## Reproduction

Run from `artifact/` with new output directories:

```sh
python -B -m tests.rollout_recovery --out /tmp/rollout-recovery-normal
python -O -B -m tests.rollout_recovery --out /tmp/rollout-recovery-optimized
python -B -m tests.rollout_locality_study --out /tmp/rollout-locality-comparison \
  --before-runtime results/owner-progress-control/global_preread_rollout.py \
  --goal-records results/global-preread-control/executions.json
```

The process controls require a POSIX host with SIGKILL and loopback TCP. They
exercise independent processes and SQLite recovery on one host, not physical
power loss, leader election or a WAN deployment. The executor owns only its
declared configuration updates; it does not drain arbitrary application effects.
