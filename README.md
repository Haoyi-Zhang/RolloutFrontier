# RolloutFrontier artifact

Code, inputs, saved results and checkers for the IEEE TPDS article
**Joint Safe-Region and Path Planning for Durable API Rollouts**.
In the full submission package the article, supplement and figure atlas are in
the sibling `../paper/` directory; this repository is self-contained without it.

A rollout target specifies complete physical profiles at every owner.
RolloutFrontier minimizes the number of safe guard phases and then the number
of installations. Its general route uses complete acceptance frontiers while
retaining every directed local path and possible phase endpoint. Its factored
route recognizes componentwise-maximum closure in small overlapping contracts
on directed chains. Greatest safe endpoints then give an exact plan without
constructing the global product of owner catalogs.

The runtime records new phase authority before retiring its predecessor,
conditions each installation on the observed owner state, and checks a common
target through matching versioned collections. Application sessions retain
actual emitter and parser obligations until their requests have durably
completed. Each shared physical owner has one support state and one set of
holds, regardless of how many factors mention it.

## Repository layout

| Path | Content |
| --- | --- |
| `src/` | Planner, checker, owner protocol, rollout executors, schema programs and session runtime |
| `tests/` | Regression tests, experiment producers and independent checkers |
| `data/` | Published version constraints and Android/Kubernetes inputs (`data/SOURCE-NOTES.md`) |
| `results/` | Saved raw observations, source snapshots and checker records behind every table and figure |
| `figures/` | Figure generators and the statistical-data map |
| `docs/` | Design notes, experiment guides and the full [reproduction guide](docs/REPRODUCTION.md) |
| `verify.py`, `reproduce.py`, `review_acceptance.py` | Saved-result verifier, fresh semantic reproduction, claim-facing subset |
| `Makefile` | Single entry point (`make install env test verify reproduce`) |
| `claim_bindings.json`, `claim_evidence_ledger.csv`, `source-replacements.json`, `current-source-manifest.json` | Claim-to-evidence bindings and the registry of intentionally updated harness files |

## Requirements

- Linux x86-64 (tested: Ubuntu 24.04 under WSL2). The process-recovery code
  uses POSIX signals, process groups and the `resource` module, so native
  Windows is not supported; WSL2 works. macOS was not tested.
- Python 3.12 with the standard `sqlite3` module, plus `make` and `ps`.
- `protobuf==7.36.2`, hash-locked in `requirements-application.lock`
  (`requirements-application.txt` has the version-only pin). No other package.
- Permission to open loopback TCP connections. About 0.7 GB of disk for the
  repository and less than 1 GB for outputs; 4 GB RAM; one CPU core suffices.
- Time: `make test` about 1 minute, `make verify` about 8 minutes,
  `make reproduce` about 3 minutes.
- Only for `make paper` and the figure atlas in the full submission package:
  a recent TeX Live (tested: TeX Live 2026 `scheme-full`, installed in user
  space with `install-tl`), Poppler (`pdfinfo`, `pdffonts`, `pdftotext`; tested
  from conda-forge via micromamba), and
  `pip install matplotlib pillow pymupdf pypdf reportlab` in the same venv
  (see `../paper/README.md`). Run `make paper` first, then
  `python -B paper/build_figure_atlas.py` from the package root.

## Installation

From the repository root:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
make install                  # pip install --require-hashes -r requirements-application.lock
make env                      # prints interpreter, protobuf and SQLite versions
```

`make env` reports `DIFFERENT` unless the interpreter is exactly the retained
campaign environment (Python 3.12.14, protobuf 7.36.2, SQLite 3.53.1, recorded in
`environment-retained.json`); this is informational. The original
campaign interpreter was built from upstream sources; that build is not
needed, and the online `pip` install above is the supported route.

## Quick check and reproduction

All targets write only into new directories under `OUT` (default
`/tmp/rolloutfrontier`; delete it or pass `OUT=/another/new/dir` before
re-running). Saved results are never modified.

| Command | What it does | Expected result |
| --- | --- | --- |
| `make test` | Factored-planning regression plus the six `test_*.py` modules | `Ran 27 tests ... OK` then `Ran 61 tests ... OK` |
| `make verify` | Read-only reconstruction of all saved results: 32 checks in normal and optimized (`-O`) Python | `PASS`, 64/64 with `../paper` present. Standalone (no `../paper`): the `publication` check is skipped, `PARTIAL` with `PASS: 62, NOT_RUN: 2`, exit 0 |
| `make reproduce` | Re-runs the 17 bounded semantic jobs and compares them with `results/reproduction-baseline-2026-11-21/` (timing fields excluded) | All 17 jobs complete, 23 outputs match semantically, 33 numeric claim bindings verify; `[complete] execution.json written`, exit 0 |
| `python -B review_acceptance.py --out /tmp/rf-review --checks sources,goal-planning,priority-counterexample,factored-planning,factored-scale,application-planning,application-rollout,phase-granularity,direct,recovery,kubernetes-skew` | Claim-facing checks as separate invocations | 11/11 `PASS` (add `publication` when `../paper` is present) |
| `make paper` | Regenerates paper tables/figures and compiles `../paper` | Only in the full submission package; otherwise prints a notice |

**Reference refresh (2026-11-24).** The reference `unit.json` was first
captured with the earlier bytes of `tests/test_factored_runtime.py`
(`9731c17d...`); the shipped file is `f782a1d9...`, a change registered in
`source-replacements.json` (explicit SQLite connection closing for Python 3.13;
expected outcomes unchanged). A fresh `reproduce.py` run with the shipped code
differed from the old reference only in that one recorded digest
(`test_source_sha256["tests/test_factored_runtime.py"]`): all 45 test IDs and
outcomes, every other job record, CSV file and trace (22 files) and the 33
numeric claim bindings agreed. `results/reproduction-baseline-2026-11-21/unit.json`
was therefore replaced by that fresh `unit.json`, and
`results/reproduction-acceptance-2026-11-21/` was regenerated with
`make reproduce` against it (its `execution.json` binds the refreshed digest).
No other baseline file changed.

These results were re-checked on Ubuntu 24.04 (WSL2), Python 3.12.3,
SQLite 3.45.1 and protobuf 7.36.2. Fresh `summary.json` files of
`tests.factored_planning_study` and `tests.goal_planner_study` (65,792 queries)
were byte-identical to `results/factored-planning/summary.json` and
`results/goal-planning/summary.json`. The long timing campaigns, live
fault-injection suites and full physical execution campaigns were not rerun;
their saved observations are checked by `make verify`, and the commands to rerun
them are in [docs/REPRODUCTION.md](docs/REPRODUCTION.md).

The verifier's `--list` option shows every check and `--checks a,b` selects a
subset. Focused saved-record checks, for example:

```sh
python -B -m tests.check_schema_contracts --results results/schema-census --corruption-controls
python -B -m tests.check_factored_scale --results results/factored-scale --corruption-controls
```

Measured-era source preimages are immutable. Harness files that intentionally
changed after those measurements are listed in `source-replacements.json` with
both the retained and current digest; `current-source-manifest.json` binds the
current bytes. The `sources` check requires all three links instead of either
rejecting legitimate harness maintenance or silently accepting an unregistered
source mismatch. Raw records under `results/` keep the original capture paths and
interpreter details of the machines that produced them.

**Code Ocean.** For the reproducibility badge, use a Python 3.12 Ubuntu base
image with `protobuf==7.36.2` (from `requirements-application.lock`) and run
`make test verify reproduce OUT=/results/rolloutfrontier`
from this directory as the entry command; outputs then appear under `/results`.

## Components

| Component | Code | Purpose |
| --- | --- | --- |
| Safe-product synthesis | `src/envelope.py`, `src/checker.py` | Complete bounded acceptance frontiers and independent positive-guard checking |
| General goal planning | `src/goal_planner.py` | Directed physical paths, all phase endpoints and lexicographic target cost |
| Factored exact planning | `src/factored_planner.py` | Local max-closure recognition, greatest safe endpoints and shared-owner guard compilation |
| Difference-hull comparison | `src/structured_planner.py` | Earlier exact finite difference-bound recognizer and complete-frontier fallback |
| Guarded owner protocol | `src/controller.py`, `src/network.py` | Durable holds, nonreused admission sequences, retirement and conditional installation |
| General rollout execution | `src/rollout.py` | Durable phase roles, step recovery and coherent completion |
| Factored rollout execution | `src/factored_runtime.py` | Immutable physical registry and global composition of one-owner admissions |
| Executable schema programs | `src/schema_contracts.py`, `src/schema_runtime.py` | Four actual ProtoJSON migrations and durable physical owner effects |
| Heterogeneous release contracts | `src/heterogeneous_contracts.py`, `tests/heterogeneous_schema_study.py` | Real field preparations and activations, complete event orders and exact precedence comparisons |
| Alternative compatible readers | `tests/alternate_reader_study.py`, `tests/alternate_reader_runtime.py` | Whole-record reader choices, exact disjunctive schedules and fixed-choice recovery |
| Durable dataflow sessions | `src/factored_session.py` | Finite traversals, fan-out/join, exact request binding and pending-request guard retention |
| Strong path comparisons | `tests/goal_path_baselines.py`, `tests/schema_contract_study.py` | Shortest safe paths, optimal fixed-path partitions and the complete six-priority portfolio |
| Phase-granularity execution | `tests/phase_granularity_study.py`, `tests/check_phase_granularity.py` | Paired execution with identical installations and different phase boundaries |
| Original transformed pipeline | `src/application.py` | Three-process enum migration with an exact integer transform and durable sink |
| Static batch selection | `src/batch.py`, `src/direct_batch.py` | Frontier selection and exact branch-and-bound comparison for a supplied batch |
| Owned application effects | `src/effect_ledger.py` | Transaction-interface drain and fencing |

The [documentation index](docs/README.md) links each component to its exact
inputs, proof obligations and experiments. Complete mathematical arguments are
also included in the article's supplement.

## Primary evidence

| Question | Recorded evidence | Location under `results/` |
| --- | --- | --- |
| Does the general planner attain its declared optimum? | 65,792 queries over 3,304 finite contexts; zero independent optimum or reachability discrepancies | `goal-planning/` |
| Does factor recognition support the greatest-endpoint theorem? | 991 complete relation contexts; 519 recognized and 472 refused with witnesses; all 7,835 compatible ordered goals in recognized contexts agree with literal phase graphs | `factored-planning/` |
| Do executable schema changes expose a path-selection gap? | Four migrations, two relation matrices, 63 nonempty three-owner graphs per migration and 186,174 queries; the fixed-owner portfolio needs an extra phase on 64 of 61,938 reachable changes, while the stage portfolio ties every goal | `schema-census/`, `schema-path-analysis/` |
| What changes with heterogeneous release orders? | 394,560 finite contexts and 122,120 reachable tasks; individual priority families have gaps, while their full union and the exact event schedule tie all reachable tasks; production coverage is explicit per catalog | `heterogeneous-schema/` |
| Does the application evidence extend beyond conjunctive threshold dependencies? | 56 non-min-closed contexts, 8,595 forward goals and 22 forward obstructions; four exact methods agree; both reader choices execute in separate three-owner deployments | `alternate-readers/` |
| Are complete responses and journal initialization stable? | Both modes complete 22 requests and 42 effects, reject 50 input/identity/journal cases, reconstruct 182 audit rows and retain zero guards | `session-reliability/` |
| How does factored planning grow with owner count and density? | Ten conditions from 8 to 1,024 owners and up to 4,096 factors; five fresh workers per condition; full witnesses and preparation-through-serialization costs retained | `factored-scale/` |
| Does the factored runtime execute actual shared-owner dataflows? | Nine cohorts with up to 32 separate owner processes on one host; 185 logical requests, 4,884 durable per-hop effects and 605 installations | `factored-runtime/` |
| Are admission identity, request binding and follow-on jobs correct? | Normal and optimized controls for reused readable identities, exact pending retries, successive rollouts, numeric domains and concurrent completion binding | `factored-runtime-review/` |
| Can invalid input create permanently pending work? | Both APIs reject unencodable strings before binding; 36 actual program controls, 324 rejected inputs, 288 valid requests, 640 effects, 36 owner restarts and no remaining guard | `utf8-inputs/` |
| What does a protection-phase boundary cost? | 19 paired goals, 38 executions, 129 installations per route; 129 versus 39 phases and 3,234 versus 1,386 owner RPCs | `phase-granularity/` |

Planning scale and physical execution use different inventories. The 1,024-owner
conditions are complete planner inputs with checked local contracts and paths.
The largest executed dataflows have 32 owner processes on one host. Owner counts,
factor counts, logical request counts and per-hop effects are reported separately.
A cycle uses a finite declared route, with distinct hop identities when a request
revisits one physical owner.

The schema census retains every graph and ordered compatible goal, including
no-ops and unreachable cases. Both migrations in each matrix class remain
identified as separate wire mechanisms. These registered graph instances do
not estimate deployment prevalence. Each actual wire and parser outcome remains
available in the source probes.

The runtime review uses the actual Endpoint, SQLite and ProtoJSON implementations
in process; its missing-response control is a unit-test injection after an actual
effect commit. The physical-runtime campaign separately records real owner and
coordinator processes, TCP relay events, `SIGKILL`, durable reopen operations and
their independent replays.

## Retained comparisons and supporting studies

| Study | Evidence | Location under `results/` |
| --- | --- | --- |
| Difference-hull recognition and fallback | 17,710 queries over 785 contexts, including 160 recognized contexts; zero independent status/cost discrepancies | `structured-planning/` |
| Complete fixed-path comparison | 46,080 relation/graph queries, including 20,654 nontrivial reachable tasks and 48 phase gaps | `goal-baselines/` |
| Published version constraints | All 529 primary source/target pairs and 18 selected larger goals; fixed-path segmentation and exact methods tie on all 214 nontrivial reachable tasks | `goal-policy/`, `goal-baselines/` |
| Original three-service pipeline | 1,296 catalog queries; individual priorities have 8–24 phase gaps, while the best six-path portfolio ties all 428 nontrivial reachable goals | `application-planning/` |
| Transformed pipeline traffic | 18 fixed and migrating trials at concurrency 1, 4 and 16; 1,728 completed requests and 5,184 durable effects, plus separate failure controls | `application-rollout/` |
| General coordinator recovery | 24 methods per Python mode, including six coordinator and six owner process kills per mode, with durable observations | `goal-recovery/` |
| Earlier same-goal planning cost | 105 independently budgeted workers comparing the difference-hull route, complete frontiers and strong controls; preparation and every registered query included | `structured-planning/timing-summary.json` |
| Static frontier preparation reuse | 16 contexts, 32 supplied batches and three repetitions; 14 contexts complete both routes | `direct-optimization/` |

These cohorts retain their original inputs and observations. The
[difference-hull results](docs/STRUCTURED-PLANNING-RESULTS.md) describe that
narrower recognizer; the [factored theorem](docs/FACTORED-PLANNING.md) and
[schema census](docs/SCHEMA-CONTRACTS.md) cover the new max-closed route. The
original transformed pipeline remains a separate workload with its own
[application study](docs/APPLICATION-STUDY.md).

For a successful nonempty rollout with `n` owners, `k` phases and `W`
installations, the executor's fault-free owner RPC count is
`2W + 4nk + 4n`. The paired phase study holds every installation fixed to isolate
the cost of admission and retirement. Timing workers, process executions and
database checkpoints remain separate counting units.

## Input and execution contract

Positive compatibility obligations, complete physical catalogs and permitted
local transitions define the planning problem. General frontiers have explicit
language and work limits. The factored route instead checks small local
relations and guard corners under its own resource budgets; it does not apply
the general route's global-corner cap to the full deployment. An exhausted
budget returns refusal, not a partial optimum or an unreachable verdict.

Owners serialize guarded changes and persist support together with all live
obligations. Execution assumes trusted registered programs, guarded mutations,
durable storage and one active writer per identity. An unresolved request keeps
its guards; no timeout releases protection. Inputs must fit every retained
emitter's domain, and exact retries preserve their durable admission and effect
identity. Matching versioned collections establish a common target state during
the observation interval.

The files under `results/` retain raw observations, executed source snapshots and
independent checking records. [literature.md](literature.md) links the
claim-level reference audit and source-reading records.


## Licenses

Code and documentation are under the MIT License (`LICENSE`). Third-party
sources consulted or transcribed (Android API records, scholarly works) keep
their own terms; see `THIRD-PARTY-NOTICES.md` and `data/SOURCE-NOTES.md`.
