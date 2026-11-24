# Schema contract census

This directory contains actual ProtoJSON observations and the complete
three-owner graph/goal census used in the schema-contract study. See
`../../docs/SCHEMA-CONTRACTS.md` for the experimental definition, findings,
comparison algorithms, and reproduction commands.

| File | Contents |
| --- | --- |
| `probes.json` | Four concrete schema migrations; descriptors, 74 emitted wires, all 262 parser calls, decoded values, errors, and derived profiles. |
| `contexts.json` | All 63 nonempty directed graphs for each family, with complete physical catalogs, local installation edges, and compatibility factors. |
| `recognition/` | One factorwise max-closure and safe-axis certificate per context. |
| `enum-alias.jsonl.gz` | All 69,072 ordered compatible source/target queries for enum alias migration. |
| `field-key.jsonl.gz` | All 69,072 ordered compatible source/target queries for field-key migration. |
| `field-addition.jsonl.gz` | All 24,015 ordered compatible source/target queries for field addition. |
| `integer-widening.jsonl.gz` | All 24,015 ordered compatible source/target queries for integer widening. |
| `frontier-cycle-controls.json` | Original production `GoalPlanner` plans for the two four-stage directed-cycle instances. |
| `inventory.json` | Exact query/context totals and all six owner-priority orders. |
| `environment.json`, `sources/` | Runtime metadata and exact producer input sources retained at collection. |
| `checked.json` | Complete independent standard-library audit, including mutation controls. |
| `checked-optimized.json` | The same audit under optimized Python. |
| `summary.json` | Compact checked denominators, per-family phase totals, and the complete inventory of full-migration gaps. |

Each JSONL query row contains `context`, `source`, `target`, `answer`, and
`routes`. Source and target are program ranks. `answer` preserves the actual
returned phase guards, physical local paths, installation steps, search
iterates, and costs. `routes` retains every priority path together with its
minimum partition cost and boundary indices. Shared catalogs and factors are
stored once in `contexts.json`; the context identifier joins them to each
query. All ties, unchanged goals, and unreachable goals remain in the files.

To verify the retained directory from the artifact root:

```bash
python -B -m tests.check_schema_contracts --results results/schema-census --corruption-controls
python -O -B -m tests.check_schema_contracts --results results/schema-census --corruption-controls
```

These commands require only the Python standard library. They verify all
186,174 records, not a sample. The producer's registered graph corpus is an
exhaustive finite planning experiment; its graph counts do not estimate
deployment prevalence.
