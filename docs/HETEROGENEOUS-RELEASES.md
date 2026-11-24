# Heterogeneous release orders

Local release ranks need not name the same action at different services. This
study gives every directed field one reader-preparation event at its receiver
and one activation event at its emitter, then exhausts the local event orders.
Each query goes from no events completed to every event completed. There are no
padding releases: preparation changes an actual reader descriptor, and
activation adds one nonempty field to the actual emitted wire.

## Programs and measured contracts

`src/heterogeneous_contracts.py` executes eight channel catalogs using 20
Protobuf reader-descriptor configurations. The emitters use complete descriptors and omit
inactive default-valued fields; they do not add a descriptor on activation.
The application identifies an absent field with its proto3 empty-string value.
The five payloads contain ASCII, Greek, Chinese, escaped characters and
supplementary Unicode characters.

The retained 100 emitted-wire records are parsed 280 times: 180 results preserve the full
semantic value and 100 fail on an unprepared field. Fourteen field/subset
witnesses add 28 before/after parser calls. These observations give the exact
finite rule `emitted fields ⊆ prepared fields`. Distinct uses of a channel
catalog reuse its measured contract; repeated event contexts are not counted
as additional parser measurements.

## Complete inventories and baseline outcomes

| Catalog | Local event counts | All contexts | Reachable | No path | Owner+stage gaps | Preparation-priority gaps |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Two services, two fields each direction | 4, 4 | 576 | 244 | 332 | 16 | 0 |
| Bidirectional path with a third service | 4, 6, 2 | 34,560 | 10,980 | 23,580 | 1,760 | 0 |
| Bidirectional triangle | 4, 4, 4 | 13,824 | 5,316 | 8,508 | 594 | 2 |
| Triangle with one additional field | 5, 5, 4 | 345,600 | 105,580 | 240,020 | 19,578 | 52 |

Each portfolio includes all owner permutations: two for the first catalog and
six for each three-owner catalog. Owner priority selects the first enabled
owner; stage priority selects minimum current rank before its owner tie order.
Preparation priority selects an enabled reader preparation before an emission;
its rank-aware variant then compares current ranks. Every resulting path gets
its exact minimum-phase partition. All four families' combined portfolio ties
all 122,120 reachable tasks. The complete per-priority costs, ties, gaps and
deadlocks remain in the compressed context tables.

Every one of the first three catalogs' 48,960 contexts has a captured
RolloutFrontier result. The additional-field catalog is a discovery extension with a
complete event-algorithm census and 20 separate planner checks: 16 evenly
spaced context identifiers plus the first witness of each outcome class. The
checked planner denominator and each selection reason are in
`results/heterogeneous-schema/summary.json` and the per-catalog records.
The full finite census covers 394,560 contexts; the captured RolloutFrontier
results cover 48,980 of those contexts.

## A specialized exact schedule

For these precedence contracts, connect consecutive local events with weight
zero and each preparation to its emission with weight one. A migration is
reachable exactly when this event graph is acyclic. For a nonempty acyclic
graph, one plus the longest path weight is the minimum phase count. Assigning
events their longest-path labels attains that bound: local order is preserved
and each reader is prepared before its field is emitted in a later phase.

The construction also applies to conjunctions of cross-owner threshold
implications. For example, the homogeneous renaming relation is the conjunction
`sender >= 2 ⇒ receiver >= 1` and `receiver >= 3 ⇒ sender >= 2`. The event
schedule is therefore credited as an exact specialized baseline, including
these precedence-style contracts. The general max-closed route additionally
accepts relations with disjunctions or without minimum closure; no measured
speed advantage over this specialized event schedule is asserted.

The independent checker uses weighted-constraint relaxation and a serial
event-phase recurrence, distinct from the producer's topological event
algorithm and path-interval dynamic program. It rechecks every context and
every captured RolloutFrontier guard and step. Retained outcome witnesses also
receive literal catalog-cell and safe-rectangle enumeration with breadth-first
search. Six corruption controls change a measured relation cell, wire value,
phase cost, positive guard, local installation or event inventory.

## Reproduction

```sh
python -B -m tests.check_heterogeneous_schema results/heterogeneous-schema --corruption-controls
python -O -B -m tests.check_heterogeneous_schema results/heterogeneous-schema --corruption-controls
python -B -m tests.heterogeneous_schema_study /tmp/rollout-release-orders
```

The study concerns actual ProtoJSON channel behavior and finite planner inputs.
It is separate from the multi-process rollout campaign and supplies neither
deployment frequencies nor additional performance samples. Full domain
inventories are fixed by their field sets and all local permutations.
