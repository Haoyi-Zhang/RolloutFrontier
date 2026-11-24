# Alternative compatible readers

An emitter can send its complete record to either of two prepared readers.
Adding a populated ProtoJSON field gives the measured condition
`emitter_active => reader_b_prepared or reader_c_prepared`. Preparation retains
support for old records. The Boolean relation contains `110` and `101` but
excludes their minimum `100`; it is closed under componentwise maximum.

The [ProtoJSON specification](https://protobuf.dev/programming-guides/json/)
describes the underlying serialization constraint: an old parser can reject
newly added fields, and unknown fields are rejected by default. The retained
observations include actual serialized descriptors, wires, parser outcomes,
and semantic values.

## Complete planning inventory

Each of three owners prepares one parser and activates one emitter, in either
local order. All seven nonempty producer subsets and all eight combinations of
local event orders give 56 contexts. Every context is max-closed and has a
retained non-min-closure witness.

The study queries every compatible ordered source/target pair. The forward
pairs provide the main reachability and optimization denominator:

| Forward outcome | Pairs |
| --- | ---: |
| No operation | 1,205 |
| One phase | 5,822 |
| Two phases | 1,501 |
| Three phases | 45 |
| Unreachable | 22 |
| **All forward pairs** | **8,595** |

Another 18,142 pairs move backward or are incomparable on the directed chains,
giving 26,737 ordered compatible pairs in total. The production planner, literal
safe-rectangle graph, OR event fixed point, and best selected-reader event graph
agree on all pairs. Full initial-to-final migrations require two phases in
52 contexts and three phases in three contexts; one context is unreachable.

The codec observations are shared across the planning contexts: ten matrix
wire records, twenty matrix parser calls, two additional parser calls witnessing
preparation, and thirteen emitter calls including event witnesses. Query counts
and codec invocation counts describe different operations.

## Why the event comparison is exact

A pending event has phase at least one and no earlier than its local predecessor.
An emitter activating the new field additionally satisfies

`t(emit) >= 1 + min(t(prepare_b), t(prepare_c))`.

A preparation already complete at the source has time zero; one outside the
target has time infinity. A whole phase rectangle includes the emitter-first
interleaving, so at least one reader must already be prepared at its source.
Monotone relaxation yields the earliest feasible event phases. With `N` pending
events, values above `N` can be represented by infinity: a reachable target
always has a serial schedule of at most `N` nonempty phases. The second event
comparison enumerates candidate readers and solves each resulting weighted
event graph. Both are exact for the measured event construction.

The full proof appears in the supplement's **Alternative Compatible Readers**
section, sourced by `paper/alternate-readers-supplement.tex`. The general
greatest-endpoint argument is in [FACTORED-PLANNING.md](FACTORED-PLANNING.md).

Whole-record choice extends to several fields on directed chains. For emitted
field set `E` and monotonically growing reader sets `P_b`, `P_c`, compatibility
is `(E subset P_b) or (E subset P_c)`. Given two compatible placements, their
maximum uses one placement's emitter rank. Its witnessing reader retains all
of that emitted set at its equal or greater rank in the maximum. This proves
max-closure. Independent choices for individual fields describe another
contract: `E={f,g}`, `P_b={f}`, `P_c={g}` has no reader for the whole record.
The measured census and implemented event comparisons use the single-field
construction above.

## Fixed choices on actual owner processes

Two fresh deployments execute the two reader choices. Each deployment retains
three original physical owner identities and the complete existing
`field-addition` catalog. That catalog's alternative-reader relation contains
26 of 27 placements, excluding only `(2,0,0)`. It supplies an executable
non-min-closure witness through `(2,2,0)` and `(2,0,2)`.

The producer and selected reader begin at rank two; the unused reader begins
at rank zero. A session fixes its two-owner transport view, workflow, codecs,
and journal. After the source commits its actual effect, the caller stops with
the request pending. Regressing the selected reader to its old program is
blocked, while the unused reader can prepare its parser. Reopening the pending
journal with a different reader is rejected. The selected owner is killed with
`SIGKILL` and restarted; the original session retries the same request,
deduplicates the source effect, and completes its selected-reader effect.

After the application guards drain, a new global plan performs the unused
reader's remaining update. Its installation is checked against the common
interval of all three original owners' compiled phase guards. The two
deployments retain two logical requests, four durable per-hop effects, two owner
restarts, two blocked regressions, two unselected-reader preparations, two
rejected pending route changes, and two final rollout installations. No pending
request or physical guard remains. The first unused-reader update is a direct
guard control; the final update belongs to the global rollout plan.

## Check or reproduce

Run from `artifact/`. Physical execution and its checker require the package in
`requirements-application.txt`; planning saved-data checking uses the standard
library.

```sh
python -B -m tests.alternate_reader_check --results results/alternate-readers/planning --corruption-controls
python -O -B -m tests.alternate_reader_check --results results/alternate-readers/planning --corruption-controls
python -B -m tests.alternate_reader_runtime_check --results results/alternate-readers/execution --corruption-controls
python -O -B -m tests.alternate_reader_runtime_check --results results/alternate-readers/execution --corruption-controls
```

For fresh observations, choose output directories that do not yet exist:

```sh
python -B -m tests.alternate_reader_study --out /tmp/alternate-reader-planning
python -B -m tests.alternate_reader_check --results /tmp/alternate-reader-planning --corruption-controls
python -B -m tests.alternate_reader_runtime --out /tmp/alternate-reader-execution
python -B -m tests.alternate_reader_runtime_check --results /tmp/alternate-reader-execution --corruption-controls
```

The independent checkers import no production planner, owner, transport,
session, or codec helper. Planning replay reconstructs all finite models and
checks every complete guard and installation witness. Physical replay executes
saved protobuf descriptors, reconstructs original-owner SQLite audits, and
correlates RPC replies with those audits. Thirteen planning corruption controls
and nine physical-evidence corruption controls are rejected in both interpreter
modes. Normal and optimized modes produce identical retained checker reports.
