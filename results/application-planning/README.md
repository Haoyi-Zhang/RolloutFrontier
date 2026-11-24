# Complete pipeline path comparisons

This study reuses the three-service pipeline's actual contracts and every
ordered pair of its 36 compatible configurations: 1,296 queries. All six
fixed-owner priority paths and their optimal phase partitions are retained.
Each order has 8–24 phase gaps among 428 nontrivial reachable goals; the best
of all six paths ties the exact result on every reachable change.

`plans.jsonl.gz` stores every result. `inputs.json` binds the source corpus;
`recognition.json` records the exact difference-hull rejection and complete
planner fallback. `checked.json` and `checked-optimized.json` contain matching
independent summaries. See `../../docs/APPLICATION-STUDY.md` for definitions
and fresh-run commands.
