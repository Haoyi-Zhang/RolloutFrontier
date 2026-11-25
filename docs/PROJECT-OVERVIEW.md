# RolloutFrontier: project overview

**Joint Safe-Region and Path Planning for Durable API Rollouts**

RolloutFrontier plans a change from a complete physical source configuration to
a requested target while preserving compatibility between independently
changing services. It minimizes protection phases first and installations
second. Complete acceptance frontiers handle general directed catalogs. For
directed chains whose local compatibility factors are closed under
componentwise maximum, a greatest-endpoint theorem gives the optimum without
enumerating the global catalog.

The executor combines durable owner guards, conditional installations,
recoverable phase handoffs and coherent target observations. Actual ProtoJSON
handlers exercise enum aliases, JSON field names, added fields and integer
widths. Durable application sessions bind inputs, admissions and effects across
retries and retain the required codecs while a request is unresolved. A birth
identity is persisted before admission and bound to the workflow, registry and
codecs, so a separately created journal with the same label cannot adopt a
pending session's authority.

The project contains the implementation, complete recorded evidence, independent
checkers, manuscript sources and publication figures.

## Read the research

The `paper/` links below refer to the full submission package, where this
repository is the `artifact/` directory; they are not part of this repository.

| File | Content |
| --- | --- |
| [paper/main.pdf](../../paper/main.pdf) | Main article |
| [paper/supplement.pdf](../../paper/supplement.pdf) | Complete arguments, comparison methods and experimental details |
| [paper/figure_atlas.pdf](../../paper/figure_atlas.pdf) | Figures in color and grayscale at their actual printed sizes |
| [paper/README.md](../../paper/README.md) | Manuscript build and figure-generation instructions |
| [artifact/docs/README.md](README.md) | Implementation, experiment and evidence guides |

## Choose an entry point

| Task | Start here |
| --- | --- |
| Understand the two exact planning routes | [General goal planning](GOAL-PLANNING-DESIGN.md) and [factored planning](FACTORED-PLANNING.md) |
| Inspect actual schema contracts and the strongest small-graph comparisons | [Schema-contract census](SCHEMA-CONTRACTS.md) |
| Compare stage-aware paths and inspect their generality | [Complete path analysis](../results/schema-path-analysis/README.md) and [combined-priority counterexample](../results/priority-counterexample/README.md) |
| Inspect different local release orders and preparation-aware comparisons | [Heterogeneous releases](HETEROGENEOUS-RELEASES.md) |
| Inspect preparation-inclusive planning scale | [Factored scale](FACTORED-SCALE.md) |
| Inspect physical handler execution and recovery | [Factored runtime](factored-runtime.md) |
| Inspect input rejection and request-journal consistency | [Input validation](INPUT-VALIDATION.md) and [session reliability](SESSION-RELIABILITY.md) |
| Inspect a choice between compatible readers | [Alternative readers](ALTERNATE-READERS.md) |
| Check file-path portability and interruption cleanup | [Delivery controls](DELIVERY-PORTABILITY.md) |
| Check saved evidence or run fresh experiments | [Reproduction guide](REPRODUCTION.md) |
| Locate a figure's generator and data | [Figure map](../../paper/figures/README.md) and [statistical inputs](../figures/STATISTICAL-PLOTS.md) |
| Review the publication graphics | [Figure review](FIGURE-REVIEW.md) |

The complete schema study retains 186,174 queries over all 63 nonempty directed
three-owner graphs for each of four migrations. The mechanisms induce two
distinct compatibility matrices. Every fixed owner-priority path and its best
phase partition remain in the evidence, including ties and unreachable goals.
The strongest tested six-path stage-priority portfolio matches all 61,938
reachable changes. The six fixed owner-priority paths need an extra phase on
64 changes; one fixed stage-priority path does so on 554. A separate declared
max-closed relation shows the distinction between these tested portfolios and
an exact guarantee: all four fixed-owner and stage-priority paths need three
phases, while the certified plan needs two, with ten installations in every
case. The application ties and the finite counterexample are both retained.

The heterogeneous field-event study exhausts 394,560 local release-order
contexts and retains RolloutFrontier results for 48,980 of them. Preparations
and activations change actual Protobuf descriptors and emitted fields. Some
individual priority portfolios miss the optimum; the union of all four
priority families and a specialized exact event schedule match all 122,120
reachable migrations. Every unreachable target and every comparison outcome
remains in the complete finite inventory.

The alternative-reader study adds an executable relation that is max-closed but
not min-closed. Its 56 contexts cover 8,595 forward goals, including 22 forward
obstructions. The production planner, literal phase graph, polynomial OR-event
relaxation and reader-choice graph oracle agree on all goals. Two separate
three-owner deployments execute the two reader choices with durable request
recovery, a fixed recipient, and a final guarded global update.

The scale study measures planning for 8 through 1,024 owners, with as many as
4,096 overlapping factors. The physical execution study separately runs up to
32 owner processes, each with its own endpoint and SQLite database, on one host.
The campaign uses birth-bound sessions and validates inputs before durable
request binding. Its nine cohorts complete
185 logical requests, 4,884 durable per-hop effects, 605 installations and 8,811
dataflow input parses. Separate identity and cancellation controls run six
groups in each Python mode, retaining 24 actual owner databases across both
modes. Earlier runtime observations, their source snapshots and timing records
remain intact in [retained-runtime](../results/retained-runtime/README.md).
The larger planning count describes the input model; the
process count describes the executed deployment. Both retain their own
inventories and measurement definitions.

Input controls execute every schema and pipeline program in normal and
optimized Python: 36 controls reject 324 invalid inputs, then complete 288
corrected requests with 640 effects and no remaining guards. Two historical
encoding-failure captures retain their pending requests, failed replies and
held obligations separately. The application captures preceding the UTF-8
validation change are preserved in
[retained-input-validation](../results/retained-input-validation/README.md).
The subsequent captures preceding the completion and journal repairs are preserved
in [retained-session-reliability](../results/retained-session-reliability/README.md).
Fresh controls in both Python modes complete 22 requests and 42 owner effects,
reject 50 input, identity or journal cases, and reconstruct 182 owner audit rows.

## Check the delivered records

From the repository root, install the application dependency and run the
read-only verifier into a fresh output directory (see the top-level README for
the `make` targets):

```sh
make install
make verify OUT=/tmp/rollout-check
```

The factored execution checker uses the recorded protobuf descriptors. Planning,
census, scale and follow-on record checks use the standard library; session
identity reconstruction also uses protobuf to check recorded effects. The
complete verifier registers 32 tasks, yielding 64 checks with `--mode both`.
Its output reports the actual outcome of that invocation. Saved-data
verification does not rerun research workloads, process failures or measurements.
A separate bounded check executes temporary SQLite and subprocess fixtures for
path handling and verifier interruption cleanup.
The reproduction guide supplies separate commands for those tasks.

Run focused planning and schema regressions from the artifact directory:

```sh
python -B -m tests.factored_planning_regression
python -B -m unittest tests.goal_planner_regression tests.test_schema_contracts -v
python -B reproduce.py --out /tmp/rollout-semantic-fresh \
  --check-reference results/reproduction-baseline-2026-11-21
```

## Build the paper and figure atlas

In the full submission package, from its root (the parent of `artifact/`):

```sh
sh paper/build.sh
```

The build regenerates statistical plots from retained observations and
rebuilds the figure atlas from the compiled documents. Fresh
experiment commands require new output directories; timing campaigns should run
while other experiments and document builds are idle.
