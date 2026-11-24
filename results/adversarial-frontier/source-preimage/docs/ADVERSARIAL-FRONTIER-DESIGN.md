# Weighted frontier and premise controls

This fixed logical campaign complements the complete smaller-domain checks in
`tests/static_batch_optimality.py`. It targets interactions among nonuniform and
zero weights, duplicate projections, sparse catalogs, three owners and full-support
changes. It is a conformance study, not a performance or generalization experiment.

## Fixed inputs

The generator uses one master seed, **8317401**, and context indices 0–239. The
first 120 contexts have two owners; the remaining 120 have three. Each owner has
three named base atoms, so its abstract support universe contains all eight subsets.
Context `k` has `1 + k mod 5` alternatives. Local requirements are selected from
those eight supports. The initial placement is chosen from the manifest's compatible
full support vectors before any irrelevant atoms are attached.

Each owner receives zero through eight raw candidate profiles, sampled with
replacement. Some receive additional irrelevant atoms, so different full profiles
can have the same relevant projection. Every raw profile receives a weight drawn
from `(0, 0, 1, 2, 13, 10^9)`. The repeated zero increases the number of zero-weight
entries; it does not give those entries a special acceptance rule. An absent
current projection remains a zero-weight anchor under the existing planner.

There are 31 proposals per context. Each projected target is drawn from the
anchored catalog. Irrelevant atoms vary between some targets so the replay must
count changes in complete supports, including changes with identical projections.
These 240 contexts are a fixed generated sample, not 240 independently collected
deployments and not an exhaustive enumeration of all three-atom manifests.

## Independent reference and recorded comparisons

The reference enumerates local antichains from the declared library and every
product in the tested language. It checks each product against all accepted
**full abstract support vectors**, without invoking the producer's corner,
dominance, scoring or forecast helpers. Raw candidate weights are summed directly;
only acceptance labels are deduplicated. Dominance and the minimum-term lexical
representative are then computed independently.

For each context the campaign checks the complete frontier, the selected weighted
score and tie result, and the installed-change optimum over **all** legal products
for the covered 31-proposal batch. It also reruns producer and checker at the exact
number of visited prefixes, then at one fewer prefix. The exact budget must accept
the same result, and the smaller budget must refuse. This campaign does not reach
the eight-option or 4,096-corner language caps; the existing dedicated boundary
controls cover those limits.

The output retains all 240 inputs, proposal sequences, per-context counts, selected
boxes, returned frontiers and forecasts. Product totals count products before the
acceptance-vector quotient; frontier totals count canonical returned members.
Proposal totals are 240 × 31 for this logical campaign and are not added to the
separate batch-generalization or network-study denominators.

## Two discriminating controls

**Generation headroom.** A known two-owner relation has two frontier members.
One permits six supplied changes at owner zero and the other four at owner one.
The forecasting rule selects the six-change member. The control seeds valid
in-memory initial generations with only one and four increments remaining,
respectively, before acquiring guards. Actual `Endpoint.install` transitions then
give one installation for the selected member and four for the alternative.
Compatibility remains true after every proposal. This removes the theorem's
explicit generation-headroom premise and demonstrates a progress discrepancy;
it is not a counterexample under that premise. It does not execute 2^63 prior
updates or claim a persistent recovery experiment.

**Term-count tie.** With the single-owner manifest `(a and b) or z`, current and
sole candidate `{a,b,z}`, the canonical tie rule selects the one-term guard `{a,b}`
before the one-term guard `{z}`. Both have the same catalog acceptance. The former
has two atoms and the latter one. Thus the implemented tie rule minimizes term
count followed by lexical order, rather than atom count or serialized size.

## Execution and provenance

Run from the artifact root into a new directory:

```sh
python -B -m tests.adversarial_frontier --out /tmp/rollout-adversarial-normal
python -O -B -m tests.adversarial_frontier --out /tmp/rollout-adversarial-optimized
```

Every check uses an explicit exception and remains active under optimized Python.
The driver captures source bytes before importing production code, verifies that
they remain unchanged through execution, and writes exact source preimages with
the result. The two `summary.json` files should be byte-identical in the same
Python environment. A nonempty destination is rejected. Retained publication
results are generated only after the reviewed implementation is frozen.
