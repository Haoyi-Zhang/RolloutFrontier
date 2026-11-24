# Heterogeneous field-addition release chains

This result directory contains executable ProtoJSON channel measurements,
complete finite release-order inventories, and production planner witnesses.
Every release prepares one incoming field in an actual reader descriptor or
activates one outgoing nonempty field in the emitted JSON. Each emission uses
the channel's complete producer descriptor; activation changes the wire payload.

## Inventory and coverage

| Domain | Release events per owner | Contexts | Reachable | Dependency deadlock | Production planner results |
|---|---:|---:|---:|---:|---:|
| `two_owner` | 4 / 4 | 576 | 244 | 332 | All 576 |
| `three_owner` | 4 / 6 / 2 | 34,560 | 10,980 | 23,580 | All 34,560 |
| `three_owner_complete` | 4 / 4 / 4 | 13,824 | 5,316 | 8,508 | All 13,824 |
| `three_owner_complete_extra` | 5 / 5 / 4 | 345,600 | 105,580 | 240,020 | 20 controls |

The first three rows are the declared small finite construction domains. The
fourth row is a discovery extension: a bidirectional triangle plus one extra
A→B field. All 394,560 labelled release-order contexts are retained. There is
one query per context, from the all-legacy state to the fully prepared and
emitting state. There are 122,120 reachable queries and 272,440 dependency
deadlocks. These are finite construction counts, with no deployment-frequency
sampling claim.

The 48,980 retained production results comprise every context in the first
three domains and twenty controls in the discovery domain. The latter consist
of sixteen evenly spaced IDs fixed by the inventory size plus four additional
first-outcome contexts. Twelve of those controls are planned migrations and
eight are dependency deadlocks.

All fixed owner tie orders are evaluated for owner priority, minimum-current-
rank priority, prepare-first owner priority, and prepare-first rank priority.
Every resulting path receives its exact minimum-phase partition. The union of
the four families matches the optimum on every one of the 122,120 reachable
queries. Individual-family gaps and all ties are retained in the CSV files.

The exact application baseline is a weighted release-event DAG: local chain
edges have weight zero; reader-preparation-to-emitter-activation edges have
weight one. A directed cycle proves a release dependency deadlock. Otherwise,
one plus the greatest directed-path weight is the minimum phase count.

## Measured channel records

`channel-observations.json` records eight directed channel inventories,
twenty reader-descriptor configurations, and one hundred emitted-wire records.
Those records contain eleven distinct serialized descriptors and fifty-five
distinct wire strings because different channels reuse base and single-field
configurations. The complete subset matrices execute 280 parser calls: 180
preserve the semantic record and 100 reject the unknown field. Fourteen adjacent
subset changes also have emitter-change and reader-before/after witnesses,
executing another 28 parser calls.

Each descriptor is retained as serialized bytes. Each wire record identifies
its emitted field subset and sample, and each parse record identifies its reader
subset and wire. A reader preparation changes an actual accepted-field set.
An emitter activation adds exactly one nonempty JSON field while preserving
the preceding fields.

## Files

- `metadata.json` defines the domains, single-query rule, baseline rules,
  production coverage, and complete source inventory.
- `channel-observations.json` and `probe-summary.json` retain the shared
  descriptor, wire, parser, and event-effect evidence.
- Each domain's `contexts.csv.gz` lists every labelled local event permutation,
  exact outcome, every per-priority baseline cost, and each portfolio minimum.
- Each domain's `production.jsonl.gz` retains the declared production results.
  A compact witness preserves rank endpoints, guards, local paths, installations,
  factor-corner checks, costs, and the complete rank-iterate trace. The physical
  support catalog is reconstructed from the measured channels and event order.
- Each domain's `summary.json` gives all denominators, ties, gaps, cost vectors,
  and production coverage. `elapsed_seconds` covers the full generation task,
  including enumeration, witness construction, and output.
- `first_*.json` retains the first occurrence of every observed outcome label.
  There are twenty-five labelled records covering sixteen distinct contexts.
  Each retains its complete finite phase graph; unreachable examples also
  identify an actual cycle of release dependencies.
- `sources/` captures all six source files from the start of this complete
  generation run. The checker verifies exact byte equality with the project
  sources.
- `checked.json` and `checked-optimized.json` contain the independent checks in
  normal and optimized Python execution.

The checker imports only the Python standard library. It reconstructs each
event order and threshold contract, solves the weighted constraints by repeated
relaxation, and computes fixed-path phase costs with a serial-event recurrence.
These differ from the producer's topological longest-path baseline and interval
dynamic program. It checks every production guard corner and installation,
all finite representative phase graphs, and six deliberately corrupted records.

## Reproduction

Run from the artifact root with the project's protobuf dependency available.
The producer requires an empty destination.

```bash
python -B -m tests.check_heterogeneous_schema results/heterogeneous-schema --corruption-controls
python -O -B -m tests.check_heterogeneous_schema results/heterogeneous-schema --corruption-controls
python -B -m tests.heterogeneous_schema_study /tmp/rollout-release-orders
python -B -m tests.check_heterogeneous_schema /tmp/rollout-release-orders --corruption-controls
```
