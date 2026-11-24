# Weighted-frontier and premise controls

The normal and optimized executions produce identical result summaries for
240 registered contexts. They cover 21,228 products, 2,120 safe products,
260 frontier members and 240 covered-batch optimum comparisons, with zero
mismatches. The output also records exact budget acceptance, one-less refusal,
zero weights, generation headroom and term-count tie controls.

`execution.json` records both commands, exit codes and the summary identity.
Complete outputs and six declared source inputs are retained. The registered
finite campaign checks the weighted acceptance and static selection mechanisms;
its design is in [ADVERSARIAL-FRONTIER-DESIGN.md](../../docs/ADVERSARIAL-FRONTIER-DESIGN.md).

Run from `artifact/` with fresh output directories:

```sh
python -B -m tests.adversarial_frontier --out /tmp/adversarial-normal
python -O -B -m tests.adversarial_frontier --out /tmp/adversarial-optimized
```
