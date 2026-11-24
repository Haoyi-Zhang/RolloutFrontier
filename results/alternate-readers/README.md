# Alternative-reader evidence

The two subdirectories retain complete planning and physical-execution
observations for choosing one compatible reader for a complete ProtoJSON record.
The contract, proofs, execution scope, and reproduction instructions are in
[ALTERNATE-READERS.md](../../docs/ALTERNATE-READERS.md).

## Planning

`planning/` contains 56 contexts and all 26,737 compatible ordered endpoint
pairs. The 8,595 forward pairs comprise 1,205 no-ops, 5,822 one-phase changes,
1,501 two-phase changes, 45 three-phase changes, and 22 unreachable targets.
The remaining 18,142 pairs go backward or are incomparable on the directed
chains. Every context is max-closed and has an explicit non-min-closure witness.

The production planner, literal safe-rectangle graph, polynomial OR event
relaxation, and best selected-reader event graph agree throughout. The shared
codec measurement comprises ten matrix wire records, twenty matrix parser
calls, two preparation-witness parser calls, and thirteen emitter calls.

| File | Content |
| --- | --- |
| `actual-channel-probe.json` | Descriptors, actual wire records, parser outputs, and event witnesses |
| `contexts.json` | Complete local catalogs, event orders, positive factors, relations, closure witnesses, and recognition certificates |
| `plans.jsonl.gz` | Every full plan or unreachable result and both exact event comparisons |
| `queries.csv` | One row per query, including the forward-pair indicator |
| `summary.json` | Reconstructible complete counts and per-context outcomes |
| `metadata.json`, `sources/` | Used source files and their before/after binding |
| `check-normal.json`, `check-optimized.json` | Actual independent-checker outputs, including 13 rejected corruptions |

## Physical execution

`execution/selected-b/` and `execution/selected-c/` are fresh three-owner
deployments with fixed selected-reader sessions. They contain original physical
registries, full codec probes, owner SQLite databases, transport and process
events, session journals, the final global plan and its coordinator journal.

Across the two deployments there are two logical requests, four durable effects,
two actual owner kills and restarts, two blocked selected-program regressions,
two unused-reader preparations, two rejected pending route changes, and two
follow-on rollout installations. The independent checker verifies all three
original owner identities and the common phase-guard interval for each final
installation. Both sessions and rollouts finish without pending work or guards.
The runtime uses the complete existing three-program endpoint catalog. The
planning census separately varies the parser-preparation and emitter-activation
orders in its executable codec construction.

## Saved-data commands

Run from `artifact/`; add `-O` after `python` to check optimized mode.

```sh
python -B -m tests.alternate_reader_check --results results/alternate-readers/planning --corruption-controls
python -B -m tests.alternate_reader_runtime_check --results results/alternate-readers/execution --corruption-controls
```

Fresh producers use `--out` and a new directory:

```sh
python -B -m tests.alternate_reader_study --out /tmp/alternate-reader-planning
python -B -m tests.alternate_reader_runtime --out /tmp/alternate-reader-execution
```

These observations establish the measured branching contract, exact planning
agreement, and execution of both fixed reader choices. Whole-record choice is
also max-closed for larger emitted field sets on monotone reader chains, as
proved in the supplement. The present codec and event census remains the
single-field construction recorded here.
