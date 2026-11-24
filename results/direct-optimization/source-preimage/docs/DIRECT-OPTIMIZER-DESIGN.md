# Direct optimization and repeated frontier queries

## Question fixed before the study

For one supplied batch, a complete frontier is not necessary: optimize its
installation objective directly over the same legal guard language. Does keeping
the complete frontier help when the same manifest, anchored initial placement
and candidate catalog serve multiple independent planning queries?

Both algorithms receive the same exact batch. Direct branch-and-bound may cache
its local guard language across queries, just as frontier selection caches the
frontier. Queries are counterfactual plans from the same initial state, not
sequential live admissions. A change to that state or catalog invalidates the
cache. The outcome is installed changes, including reversals, not final rollout
goal completion. The separate goal-planning study measures that task.

## Algorithms and assurance

For a fixed product, installation counts sum over the owners' proposal
subsequences. The direct optimizer orders local guards by those counts and uses
the sum of the maximum counts at unassigned owners as an upper bound. Safety and
corner-budget pruning use the original bounded language. A subtree whose bound
cannot strictly improve the incumbent may be discarded; ties use deterministic
first-encounter order. Search-budget exhaustion raises without a partial optimum.
This is a direct exact optimization baseline, not a reimplementation of a
published treaty system and not a new claim about branch-and-bound itself.

The frontier route builds the complete frontier, checks it through the independent
checker, and scores cached members using local subsequence counts. Each returned
guard from either route receives the same independent safety check. The direct
baseline guarantees its optimum by completed search; the frontier additionally
supplies independently checked completeness for every alternative it caches.
Prepared Python handles are immutable and factory-only: ordinary construction
and `dataclasses.replace` cannot remove checked members while retaining the
exact-result promise. They are trusted-process caches, not an untrusted
serialization or a defense against hostile Python reflection.
The common small-domain oracle compares direct results with all literal seeded
rectangles on all 511 nonempty 3-by-3 relations and three batches per relation.

## Structural scale

The registered grid uses owner counts 2, 3, 4 and 6 and alternative counts 2, 3,
4 and 6, giving 16 contexts. Alternative j requires capability j at every owner.
Each owner has the full-support current profile, all singleton capabilities,
and lexicographically rotated two-capability profiles up to eight distinct
candidates. For two capabilities only three nonempty profiles exist. Every
declared atom occurs in a branch and in a singleton candidate, so this grid
changes semantic constraint size rather than appending irrelevant atoms.

Owner identity rotates which pair profiles are included. There is no random
relation filtering. For each context, generate 32 independent 96-proposal
batches from seeds 91000 through 91031; each proposal chooses an owner and one
of its candidate profiles uniformly. These are controlled planning workloads,
not observations sampled from deployments.

## Measurements and denominators

Run three repetitions, preserving every raw timing row. Report prefix query
counts 1, 4, 16 and 32. Record local-language preparation, frontier construction,
independent completeness checking/compilation, and each query separately, with
wall and process CPU nanoseconds. Direct reuse pays one local-language
preparation plus direct queries. Frontier reuse pays preparation, full frontier
construction and checking/compilation, then frontier queries. The construction
currently performs its own internal language preparation; that actual cost is
included and reported separately rather than hidden in an amortized total.

Rotate whether direct or frontier selection runs first at each query. Use the
same process, one pinned logical CPU, fixed input records and standard explicit
250,000-state/4,096-corner bounds. Record the host and Python version. Repeated
times describe this local run; no significance or fleet performance claim is
made. Retain construction refusals, query refusals and any wall-time limit as
distinct outcomes. If a frontier cannot be constructed, do not claim a finite
break-even point or silently drop the context.

Each route has an independent cumulative 30-second wall budget covering timed
planning calls. The common local-language preparation is charged once to both.
Frontier construction and independent checking consume only the frontier
route's remaining budget; each direct query consumes only the direct route's
remaining budget. A signal interrupts an exhausted pure-Python planning call
without exposing a partial result. A separate 90-second worker safety limit
protects the experiment runner; JSON output I/O is outside timed calls. Completed
prefixes remain reportable even if a later query or the worker does not finish.
Both caches occupy the same process, so heap and cache effects are shared; these
are paired local implementation measurements, not isolated deployment timings.

### Amendment after the first measurement attempt

The first attempt imposed one 120-second worker limit. At the six-owner,
three-alternative context, frontier preparation did not finish before that
limit and the direct route did not run. The attempt was interrupted and retained as development
evidence. That arrangement could not compare the routes' ability to finish.
The final run uses the equal, independent route budgets above. The grid,
catalogs, 32 seeds, 96 proposals, three repetitions, language bounds and prefix
counts are unchanged. This budget amendment was made after observing the first
attempt and is not described as an untouched preregistered design.

The independent saved-data checker reconstructs all registered contexts and
proposal streams, checks source hashes, rechecks each retained frontier's
completeness when preparation completed, replays each output guard literally, compares optimum values when
both methods complete, and recomputes all cumulative and aggregate rows.
If a producer emits a frontier but independent preparation times out, the raw
candidate plan is retained as unfinished evidence. The saved-data checker does
not restart that unfinished completeness search without its time budget; it
checks those direct-only outputs for safety and literal counts. Independent
large-context optimality is not claimed for these unmatched outputs. This
verification boundary was clarified after the first equal-budget run revealed
that the expensive stage was independent checking rather than construction.
Timing values are retained observations; the checker verifies their structure
and aggregation, not the accuracy of a host clock.
