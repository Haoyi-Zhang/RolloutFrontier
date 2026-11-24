# Executable ProtoJSON contracts and complete topology census

This study connects the planner's capability predicates to executable schema
changes. It first runs the Protocol Buffers JSON serializer and parser on four
migrations, then uses the observed contracts in every nonempty directed simple
graph on three labelled owners. Each graph retains every ordered pair of
compatible configurations, including unchanged goals, goals requiring a
backward installation, and ties with the comparison algorithms.

The measured directory is `results/schema-census/`. Its 252 contexts contain
186,174 planning queries. The four schema mechanisms produce two distinct
compatibility matrices; families sharing a matrix are reported separately as
application mechanisms, not counted as independent mathematical cases.

## Schema mechanisms

All program variants are concrete protobuf descriptors. Each variant uses a
separate descriptor pool and its own generated message class. A program rank
specifies the permitted installation sequence.

| Family | Installation sequence | Actual wire behavior |
| --- | --- | --- |
| Enum alias | legacy → accepting → emitting → current | Add `ENABLED` as an alias of `ACTIVE`; move the new name first to change serialization; remove the old alias after senders change. |
| Field key | legacy → accepting → emitting → current | Accept both proto field `count` and JSON name `quantity`; keep emitting the old proto spelling during reader preparation; then emit and finally retain only `quantity`. |
| Field addition | legacy → accepting → emitting | Add a string field to the reader before the producer starts emitting it; the legacy parser rejects the new field. |
| Integer widening | legacy → accepting → emitting | Change the reader from `int32` to `int64`; keep the producer within the `int32` range until the final program enables the wider domain. |

The field-key sequence composes the documented parser acceptance of both field
spellings with the serializer option to preserve proto names. The integer
producer restriction is an explicit application policy enforced by
`encode_wire`; changing its descriptor alone does not enable wider values.
The accepting field-addition program similarly omits the new field until
producer activation.

The [official ProtoJSON guide](https://protobuf.dev/programming-guides/json/)
documents field-name handling, enum aliases, unknown-field behavior, numeric
representations, and compatible schema changes. `src/schema_contracts.py`
implements the exact variants exercised here. The complete dependency and
platform metadata are retained in `environment.json`.

## Raw observations

`probes.json` records 74 actual emitted wire strings and all 262 corresponding
parser invocations. There are 49 parser rejections. Every successful parse is
checked against the producer's semantic input, so acceptance alone does not
establish a contract when a value is lost or changed. The file includes each
serialized protobuf descriptor, wire string, decoded value, and parser error.

The fixed payload corpus covers zero, signed `int32` boundaries, signed `int64`
boundaries for the widened producer, values outside the `int32` range, and
Unicode keys. Enum payloads use the nonzero aliased value. Field-addition
payloads distinguish absence of the new field from its emitted string value.
A consumer accepts a registered wire class only when it preserves every
registered payload in that class. These probes establish the recorded finite
contracts; the documentation supplies the language-level rationale for the
schema changes.

Each program profile records its producer class and accepted consumer classes.
For a directed communication edge `u → v`, the factor is

```
OR over classes c: emit(c) at u AND accept(c) at v.
```

The enum-alias and field-key matrices, with sender ranks as rows and receiver
ranks as columns, are:

| Sender rank | Receiver 0 | Receiver 1 | Receiver 2 | Receiver 3 |
| --- | ---: | ---: | ---: | ---: |
| 0 | 1 | 1 | 1 | 0 |
| 1 | 1 | 1 | 1 | 0 |
| 2 | 0 | 1 | 1 | 1 |
| 3 | 0 | 1 | 1 | 1 |

The field-addition and integer-widening matrices are:

| Sender rank | Receiver 0 | Receiver 1 | Receiver 2 |
| --- | ---: | ---: | ---: |
| 0 | 1 | 1 | 1 |
| 1 | 1 | 1 | 1 |
| 2 | 0 | 1 | 1 |

Both matrices are closed under componentwise maximum. The recognition records
enumerate each local factor relation, check every required join, and retain
the maximal contiguous safe prefix for each local axis. Recognition never
constructs the global product of owner catalogs.

## Complete graph and goal inventory

The six possible directed edges are ordered as `(0,1)`, `(0,2)`, `(1,0)`,
`(1,2)`, `(2,0)`, `(2,1)`. Graph masks 1 through 63 select every nonempty subset.
These are registered topology instances, not a sample of deployed services.
An isolated owner has an explicit unconstrained unary factor. Its installation
chain remains part of the goal and cost.

For each graph and family, the producer enumerates all compatible physical
configurations and queries every ordered source/target pair. Consecutive
program ranks are the only permitted installations. A goal behind its source
on any owner therefore remains in the inventory with an unreachable answer.

| Family | Contexts | Queries | Unchanged goals | Reachable changes | Unreachable goals |
| --- | ---: | ---: | ---: | ---: | ---: |
| Enum alias | 63 | 69,072 | 2,040 | 23,238 | 43,794 |
| Field key | 63 | 69,072 | 2,040 | 23,238 | 43,794 |
| Field addition | 63 | 24,015 | 1,221 | 7,731 | 15,063 |
| Integer widening | 63 | 24,015 | 1,221 | 7,731 | 15,063 |
| Total | 252 | 186,174 | 6,522 | 61,938 | 117,714 |

Each returned phase retains its initial and final physical profiles, local
paths, positive guard, installation steps, and factor-corner checks. Catalogs,
transitions, factors, and recognition certificates are stored once per
context; no per-query safety witness is replaced by an aggregate count.

## Comparison algorithms and findings

The exact planner is compared with a literal phase graph that enumerates all
compatible configurations and all safe monotone rectangles. Breadth-first
search of that graph supplies an independent minimum-phase answer. Every
monotone chain route between a fixed pair has the same installation count.

The fixed-priority comparison retains all six permutations of owner priority.
For each priority, breadth-first search selects its deterministic shortest
installation path. A separate dynamic program partitions that full path into
the fewest safe guard phases. The portfolio result is the minimum over all
six optimally partitioned paths. Thus a portfolio gap cannot be attributed to
one unfavorable owner order or to a greedy partition of the chosen path.
Every individual path, priority, partition cost, and cut index is present in
the compressed query records.

| Family | Exact phases over reachable changes | Owner-priority six-path phases | Goals with an owner-priority gap | Full migrations with a gap |
| --- | ---: | ---: | ---: | ---: |
| Enum alias | 39,066 | 39,096 | 30 / 23,238 | 8 / 63 |
| Field key | 39,066 | 39,096 | 30 / 23,238 | 8 / 63 |
| Field addition | 10,338 | 10,340 | 2 / 7,731 | 2 / 63 |
| Integer widening | 10,338 | 10,340 | 2 / 7,731 | 2 / 63 |

The full-migration denominator selects the all-legacy source and the final
program target in each of the 63 graphs. All of these goals are reachable.
Every strict fixed-owner gap is one phase. The table retains all reachable
changes and all complete legacy-to-final migrations.

A stage-priority control uses the same ranks and permitted transitions. At
each step it selects an enabled target-directed installation at the owner with
the least current rank, using a fixed owner order to break ties. Its path is
then optimally partitioned. Taking the best of all six tie orders matches the
exact optimum on all 61,938 reachable application changes. A single fixed
stage order has 277 extra-phase goals in each rename family and none in either
extension family; the six-order portfolio removes all of those gaps. The
existing six owner-priority paths combined with one fixed stage-priority path
also match throughout. These stronger controls establish that the application
census has no observed phase advantage over the best stage-priority portfolio.

All 252 complete legacy-to-final migrations are already phase-optimal under
one fixed stage order. For any nonempty graph with these homogeneous contracts,
all-reader preparation followed by producer activation gives three phases for
the rename mechanisms and two for the extension mechanisms; a single edge
supplies the matching lower bound. The [stage analysis](stage-baseline-analysis.md)
derives this property and separates it from the generic maximum-closure theorem.

The directed cycle `0 → 1 → 2 → 0` provides a concrete gap for every family.
The four-stage migrations use `000 → 111 → 222 → 333`, requiring three phases
and nine installations. Each of the six owner-priority paths needs four phases
even after its best partition. The three-stage migrations use
`000 → 111 → 222`, requiring two phases and six installations, while each
owner-priority path needs three phases. Stage-priority paths attain the joint
optimum on the same goals. The two four-stage cycle instances are
also run through the original production `GoalPlanner` with their exact
eight-branch global formula. Its returned three-phase plans are retained in
`frontier-cycle-controls.json` and checked independently.

The 63 labelled graphs form 15 graph isomorphism classes. For each rename
mechanism, the fixed-owner portfolio's 30 gaps occur on two motifs: 12 among
600 reachable changes on the two directed three-cycles, and 18 among 1,596
changes on the six cycles with one reverse edge. Every other labelled graph
ties. For each extension mechanism, its two gaps occur among the 222 changes
on the two directed three-cycles. The complete motif table and graph/source/
target equivalence classes are in
[the path-analysis records](../results/schema-path-analysis/README.md).

## Independent verification

`tests/check_schema_contracts.py` uses only the Python standard library. It
does not import the codec, protobuf runtime, producer, or either planner. It
decodes the retained protobuf descriptor wire format, reconstructs expected
JSON representations, checks all recorded parser outcomes, and derives the
capability profiles. It reconstructs every graph, every ordered goal, all
factor recognition certificates, and the literal minimum-phase oracle.

The checker also reconstructs each priority path independently with a
target-bounded lexicographic ready-step rule. It verifies the stored partition
costs and cut witnesses, all literal phase products, positive guard corners,
physical installation steps, ranked search traces, and final goals. Source
identity checks bind both the current implementation and its retained
measurement snapshot. Missing or extra query rows fail verification.

Eight mutation controls exercise failures in parser values, factor relations,
the context inventory, phase costs, ranked search traces, guard coverage,
priority paths, and partition boundaries. The checks are repeated under
ordinary Python and `python -O`, so correctness does not depend on assertions
that an optimized interpreter can remove. The resulting summaries are
`checked.json` and `checked-optimized.json`.

The additional `tests/analyze_schema_paths.py` reconstructs both portfolios,
the complete literal phase graph, and all topology/query orbits without
importing a production planner, codec, producer or earlier checker. Its normal
and optimized outputs agree, and six derived-record corruption controls are
rejected. It also checks the existing 7,835-query finite factor corpus: the
stage portfolio needs an extra phase on two of 2,104 reachable changes, while
the fixed-owner and combined portfolios tie all of them. In the ordered
relation `x0 <= x1` on ranks 0, 1 and 2, every stage-priority path from `00` to `22`
uses three phases, whereas `00 -> 02 -> 22` uses two. The mirror relation gives
the other case. These are finite compatibility controls, separate from the
executed application programs.

## Reproduction

Run from the artifact directory with the recorded protobuf dependency installed:

```bash
python -B -m unittest tests.test_schema_contracts
python -O -B -m unittest tests.test_schema_contracts
python -B -m tests.schema_contract_study --out results/schema-census-recomputed
python -B -m tests.check_schema_contracts --results results/schema-census-recomputed --corruption-controls
python -O -B -m tests.check_schema_contracts --results results/schema-census-recomputed --corruption-controls
```

The producer requires an empty output directory. The two check commands do
not need protobuf. They verify the complete retained results rather than
rerunning the planner. The census measures planning correctness and phase
cost, not execution time, network latency, or deployment prevalence. Actual
process and request execution is recorded separately by the distributed
runtime experiments.

Verify the added path comparison against the existing records:

```sh
python -B -m tests.analyze_schema_paths --census results/schema-census --check results/schema-path-analysis --corruption-controls
python -O -B -m tests.analyze_schema_paths --census results/schema-census --check results/schema-path-analysis --corruption-controls
```
