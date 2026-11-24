# Catalog-covered batch-selection study

## Question and scope

Does choosing a safe static product for an explicitly supplied proposal batch
improve installed changes on that batch, and how does the choice transfer when
the next batch differs? This is a new generated evaluation, separate from the
retained 1,440-case holdout. It is not a field workload, deployment prevalence
estimate, or independent implementation of the protocol.

The plan below is fixed before the first study execution. The runner records this
file's SHA-256, its own bytes, and executed module hashes before execution and
requires unchanged source hashes afterward. Complete context-level observations
are retained, including any refused contexts. No design parameter or selection
policy is tuned after observing these outcomes.

## Fixed design

- Six relation families: diagonal, cycle, staircase, planted, sparse and
  capped-random, using the existing public generator definitions.
- Eighty context seeds per family: 6000 through 6079, disjoint from the earlier
  1000 through 1239 holdout and 3000 through 3002 dense stress seeds.
- Two owners and four singleton profiles per owner. Current support is a
  seed-selected allowed cell. All proposed profiles are present in the catalog.
- A 48-proposal supplied training batch. With probability 0.85, a proposal targets
  a seed-selected owner; its profile is drawn uniformly from the four profiles.
- Three 48-proposal evaluation regimes for each context: the supplied batch
  itself; an independently drawn batch with the same owner-demand probability;
  and an independently drawn batch whose favored owner is reversed.
- The three retained choices are maximum product mass, greedy envelope, and the
  optional batch selector. Choices are frozen before seeing the two new batches.
- A literal hindsight reference enumerates *all* seeded safe rectangles and finds
  the greatest installed-change count for each evaluation batch. It receives that
  batch and is not a forecast or a runtime policy.

This yields 480 planning contexts, 1,440 evaluation schedules, and 69,120 proposals
per policy when all contexts complete. A refusal stays in the context rows and
summary rather than disappearing from the denominator.

## Independent calculations and execution checks

The literal oracle enumerates row and column subsets directly, tests every cell
against the relation, and removes dominated rectangles. It does not import
planner/checker helpers or the batch forecaster. It checks the entire returned
acceptance frontier and the mass optimum. Its sequential replay counts installed,
blocked and unchanged proposals and verifies compatibility after every event.

Each of the three policy choices is also installed into actual in-memory Endpoint
objects, then replayed through their guarded `install` transition. The literal
counts, per-event outcomes and final states must agree. This is an implementation
conformance check; it adds no network or crash coverage.

On the supplied batch, the chosen product must equal the best literal seeded safe
rectangle in installed count. On unseen batches, report wins, ties, losses and
regret against hindsight, without assuming a positive transfer guarantee.

## Reporting

Report all per-context policy and regime counts, paired differences, all refusal
reasons, guard changes relative to maximum mass, frontier sizes, and total
installed/blocked/no-op proposals. Regime totals are descriptive for these fixed
generators; no population confidence interval is claimed. Runtime is retained for
reproduction bookkeeping only, not used as a performance comparison.
