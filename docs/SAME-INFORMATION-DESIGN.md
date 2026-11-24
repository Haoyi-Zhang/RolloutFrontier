# Same-information batch choice study

## Question and registered comparison

Does complete static-frontier selection add value beyond a greedy planner that
sees the same ordered proposal batch and optimizes the same installed-change
count? This study supplements the earlier comparison with demand-oblivious mass
and fixed-order greedy selection. It does not replace that retained cohort.

The design is fixed before the first complete run. No parameter, tie rule,
generator or seed is selected after viewing the study totals. Every declared
condition and refusal remains in the output. The source inventory is captured
before execution and checked again afterward.

## Policies

All policies receive the relation, current state and candidate catalog. The two
batch-aware policies also receive exactly the same ordered training proposals.

1. **Mass:** the existing maximum-mass frontier choice, using uniform weights.
2. **Batch-aware greedy:** start with the current singleton at each owner. At
   every step, consider adding one absent catalog profile at one owner. Discard
   additions whose Cartesian product is unsafe. Replay the complete supplied
   batch under every remaining trial. Select the trial with the greatest
   installed count; break ties by greater product mass, then smaller owner and
   profile index. Continue through zero-gain additions until none is safe. The
   resulting product is static and maximal on this singleton-profile domain.
3. **Exact batch:** the existing selector evaluates the complete canonical
   frontier and maximizes the supplied-batch installed count.

The new greedy control is an explicitly implemented baseline, not a claimed
reimplementation of Homeostasis or another published system. Its corner test
and training replay are literal relation operations, independent of the planner.
Both batch-aware policies see sequence order, not only target frequencies.

## Fixed population and schedules

- Six existing relation families: diagonal, cycle, staircase, planted, sparse
  and capped-random.
- Forty new seeds, 7000 through 7039, in each family: 240 structural contexts.
- Two owners and four singleton profiles per owner; every proposed profile is
  catalog covered.
- Three preferred-owner probabilities: 0.50, 0.70 and 0.90. Each structural
  context is reused at each probability, giving 720 planning conditions.
- Forty-eight proposals per batch, with a uniform target among the four
  profiles after choosing the owner. The preferred owner is the seed parity.
- Three evaluations per condition: the supplied batch; an independent batch
  with the same owner distribution; and an independent batch with the preferred
  owner swapped. At probability 0.50 the swapped regime has the same distribution
  and serves as an additional independent batch, not a distribution shift.
- A deterministic seed formula fixes each batch before planning. Both policies
  remain frozen before either unseen batch is exposed.

There are 2,160 planned evaluation schedules and 103,680 proposals per policy,
or 311,040 per-event policy observations if every condition completes. The three
probabilities and three regimes share structural contexts; they are not
independent field samples. No population confidence interval or deployment
prevalence claim is planned.

## Mechanism control

A separate fixed relation contains (0,0), (0,1), (0,2), (0,3), (1,0) and (2,0).
Starting from (0,0), owner A proposes 1,2 ten times, then owner B proposes 1,0.
Each single A expansion installs once, whereas the B=1 expansion installs twice.
The greedy planner therefore chooses B flexibility and cannot subsequently add
A=1 or A=2. The A-flexible product installs all twenty A changes. This control
isolates complementarity between two local extensions; it is not included in the
generated-study aggregates.

## Checks and reporting

A literal subset oracle enumerates every anchored safe rectangle. All policies
must remain safe, exact batch must equal its supplied-batch optimum, and the
greedy result must be maximal. Every schedule is also executed through the actual
in-memory Endpoint installation interface, with statuses, counts and final
states compared to a separate replay. This execution adds no TCP/fault coverage.

Retain complete inputs, guards, greedy expansion traces, training forecasts,
per-event observations, all context rows and summaries by probability and regime.
Report paired exact-minus-greedy wins/ties/losses, installed counts and regret
against the all-product hindsight reference. The unseen hindsight reference sees
the evaluation batch and is not an implementable forecast. Greedy trial counts
and frontier sizes are descriptive work counts, not equal-cost timing results.
