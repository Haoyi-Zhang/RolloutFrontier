# Phase granularity under one durable executor

This study isolates the communication cost of phase boundaries. Its design is
fixed before the paired executions, using the existing goal-policy plans.
It is an execution ablation, not an alternative planner or a latency benchmark.

The inventory is the 19 fault-free cases in the retained policy execution
design: the three-owner two-minor upgrade and all 18 already-selected four-,
five- and six-owner goals. Every case has two executions in fresh databases:

1. The retained minimum-phase plan.
2. The identical ordered installations, split into one installation per phase.
   Each split phase retains the original enclosing phase's guard. Thus initial
   state, target, installation order, support payloads and admissible local
   language are fixed; only admission/retirement granularity changes.

Both executions use the unchanged RolloutCoordinator and ProcessNetwork. Every
owner runs in a separate OS process with its own SQLite file; the coordinator
runs in the study process, on the same host. TCP carries every owner request.
The two origins and the rollout journal have separate SQLite state. No faults,
external mutations, retries or no-op plans are introduced in this cohort.

For n owners, P nonempty phases and W installations, the predicted operation
counts are W+n(2P+4) reads, nP prepares, nP closes and W conditional installs:
2W+4nP+4n owner RPCs. The paired difference is therefore 4n(W-P).
This is an exact count for this executor's successful path. It is not a claim
about network latency, deployment downtime or a generic lower bound on RPCs.
The policy tasks have fixed W, so minimizing P minimizes this count within
the executor. For general directed catalogs, the two objectives can differ.

Each action records owner/origin/job state and its trace position. SQLite
backups are retained initially, after every phase admission and at completion.
The saved-data checker imports no planner, controller or coordinator: it reuses
the separate numerical-policy and owner-transition checker, validates the full
pairing and flattened path, reconstructs every owner RPC, checks every action's
authority/state, and compares retained SQLite bytes with reconstructed states.
All 38 completions must carry equal, full versioned target collections backed
by their final 2n read RPCs. Process identities and successful worker readiness
are retained. Interpreter optimization is used for saved-data checking, not
reported as a second independent execution cohort.

Commands from artifact/:

```sh
python -B -m tests.phase_granularity_study --out /new/output
python -B -m tests.check_phase_granularity --results /new/output
python -O -B -m tests.check_phase_granularity --results /new/output
```

Timing fields in transport traces are raw observations; no speedup is derived
from them. The independent fault-recovery cohort remains the source for crash,
partition and acknowledgement-loss claims.
