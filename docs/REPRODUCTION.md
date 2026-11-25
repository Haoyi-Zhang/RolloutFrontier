# Reproduce the research

The artifact separates checking retained observations, running fresh planning
and execution experiments, and building the paper. Choose a fresh output
directory for each experiment or verification run. The commands below preserve
the delivered observations and their exact input inventories.

The principal planning routes are complete frontiers for general directed
catalogs and greatest safe endpoints for max-closed local factors on chains.
The earlier difference-hull dispatcher, transformed pipeline and policy cohorts
remain available as separate comparisons.

## Check saved observations

From the repository root (the `artifact/` directory of the submission package):

```sh
python -B check_environment.py
python -m pip install --require-hashes -r requirements-application.lock
python -B verify.py --mode both --out /tmp/rollout-check
```

Without the sibling `../paper/` tree, the `publication` check fails; add
`--checks` with every other name from `--list` (or use `make verify`, which does
this automatically).

The retained application campaign used Python 3.12.14, protobuf 7.36.2 and
SQLite 3.53.1. `check_environment.py --strict-retained` fails when any of those
versions differs, so a host-environment rerun cannot be mislabeled as the fixed
campaign. Python 3.12 is the tested interpreter. Planning, census, scale and runtime-review
record checking use the standard library. Factored execution and session-identity
reconstruction also use protobuf descriptor and parser APIs to validate retained
wire data. These independent checkers import no production planner, owner,
transport, session or application module.
The verifier reconstructs registered inputs and replays retained results. Its
delivery controls also execute disposable SQLite and subprocess fixtures. New
research workloads, owner-process failures and timing measurements use the
separate commands below. Interrupted checks retain their logs and a terminal
report; they do not remain marked as running.

The verifier registers 32 tasks, so `--mode both` requests 64 checks. Its report
records the actual result of that invocation. `--list` displays the registered
checks. `--checks` selects a comma-separated
subset, for example `--checks factored-planning,schema-census,factored-scale`.
The default wall allowances are 900 seconds per schema-census or heterogeneous-schema check, 300 seconds
per schema-path-analysis, alternate-reader-planning or factored-execution check and 120 seconds for other
tasks, with 3,600 seconds
for the complete invocation. `--timeout` overrides per-task allowances and
`--total-timeout` sets the overall allowance. Increase these finite limits
explicitly on a slower host.

Measured-era preimages are never rewritten when an acceptance harness evolves.
`source-replacements.json` records each intentional old-to-current digest pair,
and `current-source-manifest.json` binds the current bytes. The `sources` task
requires the retained preimage, the replacement registry and the current
manifest to agree. `review_acceptance.py` runs the claim-facing subset as
separate bounded verifier invocations and keeps one report directory per check.

| Check | Main operation |
| --- | --- |
| `sources` | Compare declared inputs and executable source snapshots |
| `factored-planning` | Reconstruct local maximum closure, refusal witnesses, all recognized goals and literal phase optima |
| `schema-census` | Check all four actual schema-probe families, every registered three-owner graph/goal, all six priority paths and their optimal partitions |
| `schema-path-analysis` | Reconstruct stage-priority controls, all 15 topology classes and query orbits, and the existing finite corpus; retain all application ties |
| `priority-counterexample` | Reconstruct the declared max-closed relation, all four combined-priority paths, their exact partitions and the two-phase production witness |
| `heterogeneous-schema` | Reconstruct all field-event orders, exact event constraints, path portfolios, measured channels and the explicitly recorded production coverage |
| `alternate-reader-planning` | Reconstruct whole-record OR contracts, all compatible endpoint pairs, literal safe rectangles and both exact event comparisons |
| `alternate-reader-execution` | Replay each fixed reader choice, retained effects, guarded updates, owner recovery and final all-owner phase |
| `session-reliability` | Check concurrent complete results, text identities, initialization recovery and separately retained historical observations |
| `delivery-controls` | Execute disposable SQLite path tests and real verifier subprocess interruption/timeout controls |
| `factored-scale` | Check 8–1,024-owner factors, complete witnesses, worker inventories and preparation-through-serialization CPU accounting |
| `factored-execution` | Replay physical owner identities, admissions, dataflow wires, durable effects, recovery and target completion across the nine process cohorts |
| `factored-runtime-review` | Check retained independent normal/optimized follow-on controls and their executed source inputs |
| `session-identity` | Reconstruct saved session journals, owner audits, effects, operation bindings and post-commit cuts for six groups per interpreter mode |
| `utf8-inputs` | Reconstruct rejected-input checkpoints, corrected requests, retained effects, cached exact retries and retirement across both execution modes; check the separate historical failure captures |
| `structured-planning` | Check the earlier difference-hull recognition, emitted plans, general fallback and CPU accounting |
| `application-planning` | Check all six owner-priority paths, best-of-six segmentation and structural fallback on actual contracts |
| `application-rollout` | Replay actual application effects, handler activation, traffic and failure controls |
| `goal-planning` | Reconstruct finite relations, literal products and exact goal costs |
| `goal-policy` | Reconstruct policy tasks, directed paths, owner transitions and databases |
| `goal-baselines` | Check same-target controls, product closure, finite comparisons and CPU accounting |
| `phase-granularity` | Replay paired traces, phase authority and versioned completion; recompute RPC costs |
| `policy-read-comparison` | Compare identical plans under global and owner-local installation reads |
| `recovery` | Reconstruct retained process-cut witnesses from their durable states |
| `locality` | Replay before/after TCP traces and the unrelated-owner partition control |
| `direct` | Reconstruct supplied batches and exact completed static-selection results |
| `same-information` | Recompute matched-information policy outcomes |
| `policy-boundaries`, `kubernetes-skew` | Check declared compatibility predicates and recorded guarded transitions |
| `supporting-studies`, `inherited-records` | Check supporting static, effect, lifecycle and protocol evidence |
| `publication` | Compare generated numerical macros and tables with their scientific inputs |

Each result states what was reconstructed. Replaying a saved fault witness checks
its states and transitions; the recovery command below reexecutes the process
failure. Checkpoint and database counts refer to observations within executions.

| Status | Exit code | Meaning |
| --- | --- | --- |
| `PASS` | 0 | All registered checks passed in the requested interpreter mode(s) |
| `FAIL` | 1 | A checker rejected its inputs or a required file was missing |
| `INCOMPLETE` | 2 | A requested check exceeded its finite time allowance |
| `INCOMPLETE` | 130 | Ctrl-C interrupted verification; the checker process group was stopped and unfinished checks remain explicit |
| `PARTIAL` | 3 | The requested subset passed and other checks were not requested |

The output directory contains a report and per-command logs. These records
identify the observed outcomes of this invocation. Verification durations are
operational metadata; the paper's timing values come from the measurement
campaigns below.

## Planning and strong comparisons

Run these commands from `artifact/`:

### Factored theorem and complete schema census

```sh
python -B -m tests.factored_planning_regression
python -O -B -m tests.factored_planning_regression
python -B -m tests.factored_planning_study --out /tmp/rollout-factored-planning
python -B -m tests.check_factored_planning --results /tmp/rollout-factored-planning --corruption-controls
python -O -B -m tests.check_factored_planning --results /tmp/rollout-factored-planning --corruption-controls

python -B -m unittest tests.test_schema_contracts -v
python -O -B -m unittest tests.test_schema_contracts -v
python -B -m tests.schema_contract_study --out /tmp/rollout-schema-census
python -B -m tests.check_schema_contracts --results /tmp/rollout-schema-census --corruption-controls
python -O -B -m tests.check_schema_contracts --results /tmp/rollout-schema-census --corruption-controls
```

The factored theorem campaign contains all 991 declared relation contexts,
including refusal witnesses. The 519 recognized contexts contribute 7,835
ordered compatible goals. An independent literal phase graph checks every
optimum and unreachable result.

The schema producer executes enum-alias, field-key, field-addition and
integer-widening programs using actual protobuf descriptors. Its 74 wire strings
and 262 parser invocations supply two distinct compatibility matrices. Every
nonempty directed simple graph on three owners is retained for each family,
together with every ordered compatible source/target pair: 186,174 queries in
252 contexts. Each query stores all six fixed-priority shortest paths and each
path's best partition, not just the winning portfolio cost. The two checker
commands independently validate that same complete retained corpus.

### Alternative compatible readers

```sh
python -B -m tests.alternate_reader_study --out /tmp/rollout-alternate-planning
python -B -m tests.alternate_reader_check --results /tmp/rollout-alternate-planning --corruption-controls
python -B -m tests.alternate_reader_runtime --out /tmp/rollout-alternate-execution
python -B -m tests.alternate_reader_runtime_check --results /tmp/rollout-alternate-execution --corruption-controls
```

The [alternative-reader guide](ALTERNATE-READERS.md) defines the complete
finite inventory, both specialized exact methods, and the fixed session view
used in each physical deployment. The [session-reliability guide](SESSION-RELIABILITY.md)
and [delivery controls](DELIVERY-PORTABILITY.md) provide the other new focused
commands and distinguish fresh fixtures from historical record reconstruction.

### Stage-priority comparisons and a combined-path counterexample

```sh
python -B -m tests.analyze_schema_paths --census results/schema-census --check results/schema-path-analysis --corruption-controls
python -O -B -m tests.analyze_schema_paths --census results/schema-census --check results/schema-path-analysis --corruption-controls
python -B -m tests.analyze_schema_paths --census /tmp/rollout-schema-census --finite /tmp/rollout-factored-planning --out /tmp/rollout-schema-path-analysis --corruption-controls

python -B -m tests.check_priority_counterexample --check results/priority-counterexample --corruption-controls
python -O -B -m tests.check_priority_counterexample --check results/priority-counterexample --corruption-controls
python -B -m tests.check_priority_counterexample --out /tmp/rollout-priority-counterexample
```

The third command derives the comparison from the new census and finite-factor
directories produced above. The saved-record commands use the delivered
records. The path analyzer independently rebuilds literal phase graphs, all
fixed-owner paths, all six least-current-rank paths, exact path partitions and
graph/source/target isomorphism classes. The six-path stage portfolio matches
all 61,938 reachable application changes. The six fixed-owner paths have 64
extra-phase goals; one fixed stage order has 554. All 63 labelled graphs and
their 15 isomorphism classes remain in the denominators.

The existing finite corpus contributes 7,835 queries and 2,104 reachable
changes. The stage portfolio fails to attain the optimum on two mirror cases;
the fixed-owner and combined portfolios tie throughout that corpus. The
separate declared counterexample has 27 compatible pairs on a 5-by-7 domain:
both fixed-owner paths and both stage-priority paths need three phases, while
the exact plan uses two through `(2,4)`. Every path performs ten installations.
The counterexample checker retains the entire phase graph and production
witness. These commands do not collect timing measurements or deployment
frequency estimates. Six path-analysis and four counterexample corruption
controls test rejection of altered records.

### Heterogeneous field-event orders

```sh
python -B -m tests.check_heterogeneous_schema results/heterogeneous-schema --corruption-controls
python -O -B -m tests.check_heterogeneous_schema results/heterogeneous-schema --corruption-controls
python -B -m tests.heterogeneous_schema_study /tmp/rollout-release-orders
python -B -m tests.check_heterogeneous_schema /tmp/rollout-release-orders --corruption-controls
```

The inventory contains 394,560 local event-order contexts and 122,120 reachable
full migrations. Every release changes a real reader descriptor or activates a
nonempty emitted field. Weighted event constraints and independent serial-path
recurrences check the complete census. The first three catalogs include a
RolloutFrontier result for every context; the larger discovery catalog includes
20 separately identified checks, giving 48,980 captured planner results in
total. All owner tie orders are retained for four priority families. Their
combined portfolio and the exact event schedule match every reachable task.
See [HETEROGENEOUS-RELEASES.md](HETEROGENEOUS-RELEASES.md) for the four inventories,
individual-family gaps, shared channel probes and precise selection rules.

### Factored planning scale

```sh
python -B -m tests.factored_scale_study --prepare --out /tmp/rollout-factored-scale
python -B -m tests.check_factored_scale --results /tmp/rollout-factored-scale --prepared --corruption-controls
python -B -m tests.factored_scale_study --measure --out /tmp/rollout-factored-scale
python -B -m tests.check_factored_scale --results /tmp/rollout-factored-scale --corruption-controls
python -O -B -m tests.check_factored_scale --results /tmp/rollout-factored-scale --corruption-controls
```

Preparation reads the delivered `results/schema-census/probes.json` and retains
its exact bytes with the full inputs and witnesses. The ten conditions use rings
and four-offset circulants at 8, 32, 128, 512 and 1,024 owners. The largest has
4,096 factors. Recognition and guard checking inspect local factor catalogs;
they do not enumerate the global placement product.

Run the measurement command while other experiments and builds are idle. Each
condition has five serial fresh workers. A worker repeatedly builds fresh
models, plans and full serialized witnesses until at least 100 milliseconds of
process CPU time accumulates, subject to its declared limits. Preparation,
recognition, query work, positive checks and serialization are charged. The
reported median and range use worker means; repeated cohorts within a worker
are not additional independent replicates. Raw zero-CPU deltas at the clock's
observable resolution remain in the records and means.

These are planning measurements for registered owner catalogs. The physical
execution command below creates up to 32 owner processes on one host. See
[FACTORED-SCALE.md](FACTORED-SCALE.md) for the exact interval, seven additive
components, memory measurements, lower-bound controls and complete inventory.
The homogeneous complete migrations also admit an optimal stage-priority path;
this cohort measures complete local-factor plan and certificate construction.

### General directed catalogs and earlier path comparisons

```sh
python -B -m unittest tests.goal_planner_regression tests.direct_optimizer_regression -v
python -O -B -m unittest tests.goal_planner_regression tests.direct_optimizer_regression -v

python -B -m tests.goal_planner_study --out /tmp/rollout-goal-planning
python -B -m tests.goal_planner_study --check /tmp/rollout-goal-planning

python -B -m tests.goal_baseline_study --out /tmp/rollout-baselines
python -B -m tests.check_goal_baselines /tmp/rollout-baselines
python -O -B -m tests.check_goal_baselines /tmp/rollout-baselines
python -B -m tests.check_goal_baselines /tmp/rollout-baselines --negative-controls
```

The goal campaign compares the production planner with literal-product oracles.
The baseline campaign compares alternative strategies on the same policy tasks
and on complete finite relation families. Their query inventories are separate.

To add fresh CPU measurements to the newly produced baseline directory:

```sh
python -B -m tests.goal_baseline_study --out /tmp/rollout-baselines --timing
python -B -m tests.check_goal_baselines /tmp/rollout-baselines
```

Run timing with other computational campaigns and document builds quiescent.
Every route/domain worker receives its own 30-second process-CPU budget. A worker
rebuilds complete cold cohorts until at least 0.1 CPU second has accumulated, then
reports mean CPU per cohort. Five independent workers supply descriptive medians
and ranges. Preparation and all registered queries are included; caches survive
only between queries within one cohort. Keep new host measurements separate from
the delivered observations.

## Difference-hull recognition and fallback

```sh
python -B -m tests.structured_planning_regression
python -O -B -m tests.structured_planning_regression
python -B -m tests.structured_planning_study --out /tmp/rollout-structure
python -B -m tests.check_structured_planning --results /tmp/rollout-structure --corruption-controls
python -O -B -m tests.check_structured_planning --results /tmp/rollout-structure --corruption-controls
python -B -m tests.structured_planning_study --out /tmp/rollout-structure --timing
```

This earlier dispatcher recognizes an exact finite difference-bound
representation and falls back to general frontier planning when recognition
fails. Its query corpus includes all policy goals, complete small relation
families and connected difference networks. Recognition is checked against the
entire finite relation, and every resulting plan is compared with the exact
safe-interval phase graph. The timing command measures all routes together on
the same inputs; keep other computational work quiescent until it completes.

## Factored physical execution and recovery

Install the hash-locked `requirements-application.lock` in the interpreter
environment inherited by subprocesses, and run these commands from `artifact/`:

```sh
python -B -m unittest tests.test_factored_runtime -v
python -O -B -m unittest tests.test_factored_runtime -v
python -B -m tests.factored_followon_regression --out /tmp/rollout-runtime-review/normal.json
python -O -B -m tests.factored_followon_regression --out /tmp/rollout-runtime-review/optimized.json
python -B -m tests.session_identity_regression --out /tmp/rollout-session-identity/normal
python -O -B -m tests.session_identity_regression --out /tmp/rollout-session-identity/optimized
python -B -m tests.check_session_identity --results /tmp/rollout-session-identity --corruption-controls --output /tmp/rollout-session-identity/check-normal.json
python -O -B -m tests.check_session_identity --results /tmp/rollout-session-identity --corruption-controls --output /tmp/rollout-session-identity/check-optimized.json
python -B -m tests.factored_execution --output /tmp/rollout-factored-execution
```

The focused suite launches actual owner processes and checks the protocol fixes.
The independent follow-on controls use actual Endpoint, SQLite and ProtoJSON
implementations in process. They verify new admission identities after
retirement, exact retry after a committed source effect, successive rollout
jobs, numeric-domain checks before request registration and first-completion
binding for concurrent retries. The one omitted response in that independent
suite is an explicit unit-test injection.

The session-identity suite creates actual in-process Endpoint, SQLite and
ProtoJSON instances. Its six groups cover fresh and repeatedly opened foreign
journals, precreated journals, immutable workflow binding, and cancellation
after committed acquisition, request and retirement operations. Each group has
two physical owner databases; six groups in each of two interpreter modes
retain 24 owner databases, alongside session and origin journals. Fresh or
precreated journals with the same readable label cannot adopt pending authority.
The genuine journal retains its birth identity across reopen and finishes its
exact retry before retirement. Constructor-rejection and task-cut outcomes are
producer records; the independent checker reconstructs owner audits, committed
effects, completed inputs and outputs, and operation bindings. Four evidence
mutations are applied separately to both captured modes.

Input-domain controls cover all schema and pipeline programs in both Python
modes. The saved campaign checker also reconstructs the two separately
retained failure histories. Fresh controls and their independent readers use
the following commands; details and counting units are in
[INPUT-VALIDATION.md](INPUT-VALIDATION.md).

```sh
python -B -m tests.check_utf8_campaign --results results/utf8-inputs --corruption-controls
python -B -m tests.utf8_input_regression --output /tmp/rollout-inputs/normal
python -O -B -m tests.utf8_input_regression --output /tmp/rollout-inputs/optimized
python -B -m tests.check_utf8_inputs /tmp/rollout-inputs/normal --self-test
python -O -B -m tests.check_utf8_inputs /tmp/rollout-inputs/optimized --self-test
```

The `tests.factored_execution` command launches the complete nine-cohort campaign. Its
defaults are three repetitions for each large dataflow, concurrency four and
16 steady-target requests per traffic cohort. The large cases have 32 independent owner
processes: an enum-alias cycle with 32 factors and a field-key fan-out/join with
87 factors. Each large trial completes 24 logical requests and 96 installations
through three protection phases. Five-owner field-addition and integer-widening
controls each complete 20 requests and ten installations through two phases.
A separate three-owner cohort exercises recovery with one completed request
and nine installations. The retained campaign totals 185 logical requests,
4,884 durable per-hop effects, 605 installations and 8,811 dataflow input parses.
All nine cohorts were recaptured with birth-bound sessions and strict UTF-8
validation before request binding.

Every physical process has one endpoint and SQLite store. Repeated appearances
of that owner in factors or in a finite traversal use the same authority. The
cycle returns to its first owner using a new hop identity, so its 24 requests
produce 792 effects per large trial; the fan-out/join produces 768. Logical
requests and per-hop effects are separate denominators.

The harness uses one host and an owned loopback TCP relay. The recovery cohort
records real owner/coordinator `SIGKILL`, partial phase admission and retirement,
lost replies after commits, and a selected TCP link cut while its owner process
remains alive. These observations do not measure cross-host deployment latency.
The recovery cohort also attempts same-label admission from both fresh and
precreated journals while a real request remains pending. Both are rejected
without changing the legitimate session's requests or retained owner holds.
Paused overlap requests and recovery controls are excluded from steady-target
latency summaries. Steady request timings include the actual handlers, SQLite
commits, relay and durable audit writes.

The producer invokes its independent checker for every completed cohort. To
repeat saved-record checking in both modes for every new cohort:

```sh
for cohort in /tmp/rollout-factored-execution/enum-alias-cycle/trial-* \
              /tmp/rollout-factored-execution/field-key-fanout-join/trial-* \
              /tmp/rollout-factored-execution/field-addition-control \
              /tmp/rollout-factored-execution/integer-widening-control \
              /tmp/rollout-factored-execution/recovery-controls
do
  python -B -m tests.check_factored_execution "$cohort"
  python -O -B -m tests.check_factored_execution "$cohort"
done

python -B -m tests.factored_checker_controls \
  /tmp/rollout-factored-execution/enum-alias-cycle/trial-01 \
  --output /tmp/rollout-factored-execution/corruption-controls.json
```

The checker imports the independent planning oracle and protobuf APIs, but no
production planner, controller, transport, session or handler. It verifies
physical identities, all-owner guards, conditional source generations, complete
request/hop inventories, effects and final retirement. The ten mutation
controls must reject altered semantic values, missing hops or admissions,
physical identity substitutions, historical admission changes and inconsistent
generation observations, as well as changed birth identities, readable labels
and workflows with unchanged codec obligations. See [factored-runtime.md](factored-runtime.md) for the
state machines, exact effect identity and retained files.

The preceding runtime capture, follow-on records, source snapshots and timing
observations remain under `results/retained-runtime/`. Its `retention.json`
binds all 1,341 preserved files. Those earlier samples describe their retained
implementation; current execution checking and latency tables use the sibling
`results/factored-runtime/` capture. The original reports remain available for
inspection without treating them as observations of the corrected runtime.

## Original transformed application pipeline

Install the declared dependency in the Python environment used for owner
subprocesses, then run from `artifact/`:

```sh
python -m pip install --require-hashes -r requirements-application.lock
python -B -m tests.test_application_rollout
python -O -B -m tests.test_application_rollout
python -B -m tests.application_rollout_study --out /tmp/rollout-application
python -B -m tests.check_application_rollout --results /tmp/rollout-application --corruption-controls
python -O -B -m tests.check_application_rollout --results /tmp/rollout-application --corruption-controls
python -B -m tests.application_planning_controls --application-results /tmp/rollout-application --out /tmp/rollout-application-plans
python -B -m tests.check_application_planning_controls --application-results /tmp/rollout-application --results /tmp/rollout-application-plans
```

The producer runs actual Protocol Buffers JSON parsers and serializers in three
owner processes. It migrates an enum alias across an encoder, transformer and
SQLite sink while requests execute at concurrency 1, 4 or 16. Every request
retains its input, wire data, returned value and owner receipts. The checker uses
only the standard library to reconstruct compatibility, exact planning costs,
owner transitions and durable application effects.

The fixed and migrating conditions each have three repetitions at every
concurrency, with 96 requests per trial. Reported latency spans
request invocation through durable origin completion, including origin
input/output commits and admission-gate waiting; it excludes batch admission
and retirement. Run these trials without competing benchmark or build jobs.
Drain, authority-removal and committed-effect/lost-reply controls are separate
from those 18 traffic trials. [APPLICATION-STUDY.md](APPLICATION-STUDY.md) gives
the exact lifetimes, handler activation rule and data checks.

## Execute goals and recovery

Retained input documents and raw records keep their collected file identities.
The verifier resolves those identities to the control files in this project;
the reproduction commands supply their locations explicitly.
The global pre-read location named in the bound policy input,
`results/goal-policy-development/global-preread/`, is delivered here as
`results/global-preread-control/`. Its runtime is
`results/owner-progress-control/global_preread_rollout.py`.

```sh
python -B -m tests.goal_policy_study --out /tmp/rollout-policy
python -B -m tests.check_goal_policy --root /tmp/rollout-policy

python -B -m tests.phase_granularity_study --out /tmp/rollout-phase-pairs
python -B -m tests.check_phase_granularity --results /tmp/rollout-phase-pairs
python -O -B -m tests.check_phase_granularity --results /tmp/rollout-phase-pairs
python -B -m tests.check_phase_granularity --results /tmp/rollout-phase-pairs --corruption-controls

python -B -m tests.rollout_recovery --out /tmp/rollout-recovery
python -O -B -m tests.rollout_recovery --out /tmp/rollout-recovery-optimized

python -B -m tests.rollout_locality_study --out /tmp/rollout-locality \
  --before-runtime results/owner-progress-control/global_preread_rollout.py \
  --goal-records results/global-preread-control/executions.json
```

The policy producer hosts its TCP owners in one asynchronous process. The paired
phase study launches a separate process for every owner and uses fresh SQLite
stores for each execution. It fixes installation order and compares phase
boundaries. The recovery suite uses actual POSIX process kills, TCP failures and
durable reopen operations. These commands require Linux/POSIX process facilities
and permission to open loopback connections.

The locality comparison runs an all-owner-preread control and the owner-local
executor on an identical plan. Its partition control blocks an unrelated owner's
TCP stream while that owner's process remains alive. The source and inputs of
the control are retained with the corresponding observations.

## Supporting studies

```sh
python -B -m tests.direct_optimizer_study --out /tmp/rollout-direct
python -B -m tests.check_direct_optimizer --results /tmp/rollout-direct
python -B reproduce.py --out /tmp/rollout-supporting \
  --check-reference results/reproduction-baseline-2026-11-21
```

The direct study measures complete static-batch preparation and repeated query
costs under independent route budgets. `reproduce.py` runs the supporting semantic
suite. The current retained cohort is
`results/reproduction-baseline-2026-11-21/`; it records all 45 discovered test
IDs and hashes the six discovered test modules. Its `unit.json` and the
`results/reproduction-acceptance-2026-11-21/` record were refreshed on 2026-11-24
with the shipped code, after a fresh run differed from the earlier reference only
in the registered digest of `tests/test_factored_runtime.py` (see the README). Those modules execute in fresh
subprocesses, while the parent aggregates exact test IDs and fails closed on a
nonzero exit, timeout, duplicate ID or malformed result. The historical files directly
under `results/` retain the earlier five-test record and are not the current
comparison target. The unit job has a 300-second wall allowance; the other 16
jobs retain 120 seconds. Timing and host-resource fields are excluded from
semantic equality. Design notes under this directory describe the remaining
individual experiments and their input inventories.

## Build and inspect the article

The manuscript sources are not part of this repository. In the full
submission package, from the package root (the parent of `artifact/`):

```sh
sh paper/build.sh
```

Publication dependencies and figure sources are listed in `paper/README.md`.
The build derives numerical rows from checked observations. Statistical figures
are regenerated in Python, and the build then rebuilds the atlas from the actual
placements in the compiled article and supplement. Review the resulting PDFs and both color and grayscale
figures at their printed width.
