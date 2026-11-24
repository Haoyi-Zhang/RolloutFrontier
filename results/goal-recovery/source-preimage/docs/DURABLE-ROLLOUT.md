# Durable execution of a goal plan

The goal planner chooses a finite path to a specified configuration. The
`RolloutCoordinator` in `src/rollout.py` executes that path through the existing
durable admission protocol. The planner minimizes the number of safe phases,
then the number of installation steps. The executor checks feasibility again,
records phase roles before relying on them, and resumes a partially executed
job after a process restart.

This component owns configuration-update authority. It does not own or drain
arbitrary application work. `DrainingClient` remains the separate interface for
the explicitly owned SQLite effect described in the paper. Its leases must not
be attached to the coordinator's private origins. The two interfaces are not
silently combined into an external-side-effect guarantee.

## The interrupted handoff that motivates the journal

In the previous policy case, the handoff was a test script: acquire a second
guard, retire the first guard, and install the remaining target. Each `Client`
already recovered its own admission correctly. The roles of the two clients,
the rollout goal and the intended next action existed only in Python memory.

A retained control executes the original revision-2 sources and sends SIGKILL
after the second phase commits but before the first phase retires. On reopening
both clients, their generic `recover()` methods correctly preserve both valid
committed admissions. The old guard still blocks the final target. This is a
missing rollout-recovery workflow; retaining the two guards is safe core
protocol behavior and is not reported as a safety violation.

The new job journal supplies the missing decision: which phase is old, which
phase is next, which certificate belongs to each, and which directed update is
next. Recovery uses that recorded decision rather than choosing an arbitrary
committed admission to discard.

## Input and execution contract

The executor accepts a completed `rollout-goal-plan-v1` plan. It independently
checks all of the following before sending an admission request:

- the normalized manifest branches and full-support initial/target profiles;
- catalog membership and the explicit directed local transition relation;
- every phase source, target, positive guard, local path and installation step;
- each phase guard's universal safety using the independent checker;
- source/target continuity between phases, termination at the requested target,
  and the phase/write/handoff counts reported by the supplied plan.

It verifies a feasible execution, not the search's minimality. The goal planner
and its independent all-product oracle establish the planning result. A
resource refusal and an unreachable goal are not executable plans. A goal that
already equals the initial configuration needs zero phases and sends no prepare
requests. Execution is bounded to 4,096 phases and 4,096 installation steps.

These execution limits cover every completed plan returned by the current goal
planner. Let `M` be the number of distinct full-support placements in the fixed
Cartesian catalog; the planner requires `M <= 4096`. A lexicographically optimal
plan cannot revisit a full placement after one or more installations. If it
did, retain the prefix ending at its first occurrence and the suffix beginning
at its later occurrence. Both bounding guards accept that placement, so they
can hand off there; removing the intervening cycle needs no additional phase
and strictly reduces installations. Empty phase fragments can be omitted. The
catalog is fixed and already contains every phase source, so this splice does
not introduce a new guard term or an undeclared local transition. A frontier
guard that dominates a retained guard accepts all of its remaining catalog
paths as well. Thus the shorter execution is represented by the same planning
problem, contradicting either the minimum phase count or the minimum write count
at that phase count. Shared configurations at a handoff are not additional
installations. The sequence consisting of the initial placement and each
post-installation placement therefore contains at most `M` distinct entries:
installations are at most `M - 1 <= 4095`. Every nonempty phase contains at least
one installation, so its phase count has the same upper bound. The zero-phase
case covers an initial placement already equal to the target.

The separate 250,000 phase-candidate budget limits search work, including
parallel guard/destination candidates; it is not a bound on steps in a returned
plan. Exhausting that budget produces an explicit planning refusal. Handwritten
feasible plans can contain redundant cycles and are still subject to the
executor's independent phase and step limits. Fitting these limits establishes
the planner/executor size contract; runtime progress also requires the
communication, storage, authority and counter premises stated below.

Both origin identities must be otherwise unused. The default pair is `(0,1)`;
the identities alternate across phases and can be reused after the prior phase
has completely retired. A manifest identifier derived from the job's input hash
and phase number binds each admission to exactly one recorded phase. The
executor refuses an origin containing another job's admission before sending
cleanup requests. As with `Client`, the previous writer must stop before another
writer opens the same durable identity. This is not leader election.

## Persistent state machine

The SQLite job row retains the complete plan, input digest, manifest identifier,
network configuration, origin pair, phase/step indices, phase certificates and
execution counters. It uses `synchronous=FULL` and `journal_mode=DELETE`, matching
the underlying origin and owner stores.

| Durable stage | Required authority | Action and successful successor |
| --- | --- | --- |
| `acquire` | Previous phase remains committed, if any | Admit the planned next guard; persist its certificate; enter `release-old`, or `install` for the first phase. |
| `release-old` | New phase is committed at every owner | Retire only the recorded old certificate. Enter `install` after every old close is confirmed. |
| `install` | Current phase remains committed | Read only the selected owner; reconcile or compare-and-install its next directed step; record one completed plan step. |
| `install`, all steps complete | Current phase remains committed | Check the planned phase endpoint, then enter the next `acquire` stage or `release-final`. |
| `release-final` | Final phase certificate, unless its retirement already completed | Check the target and finish retirement. Persist `complete`. |
| `complete` | No remaining admission owned by the job | Confirm a common target observation and report completion without repeating installations. |

An admission can commit before the job records its certificate. After a crash,
the unchanged phase-specific manifest lets the underlying client return that
same committed certificate. Conversely, a close can finish before the job
records retirement. If the exact recorded old certificate is absent from its
authoritative origin journal, the executor treats its release as complete. It
does not delete or infer ownership of any different certificate.

An owner unavailable for the current action, or a failed release, produces an
explicit `pending` result.
The caller may restore communication or reopen a failed database object and
retry. The executor does not reclaim authority after a timeout. A job-database
error has an uncertain outcome: the live object becomes unusable until reopened,
at which point the actual durable row determines the next action.

## Atomic directed installations

A goal may allow `A -> B` but not `C -> B`. Reading `A` and later sending an
unconditional installation of `B` would overwrite a concurrent change to `C`.
That would invalidate the planned directed edge even if the phase guard still
accepted both configurations.

`Endpoint.install_if_current(expected_generation, expected_support, support)`
compares both fields at the endpoint's serialization point. A mismatch returns
`stale` and the authoritative profile without changing the durable state. A
match passes through the original installation path, including every active
guard, generation exhaustion and persist-before-acknowledgement behavior. The
new operation rejects boolean/float generation aliases and noncanonical
expected support lists. Ordinary `install` semantics are unchanged.

Before executing a step, the coordinator derives that owner's expected full
support from the recorded plan prefix and reads only that owner, using the
current phase's origin. A different local source returns `deviation` and retains
the current guard. A concurrent change between the read and the conditional
write returns `pending` with `owner-profile-changed`; the next call rereads that
owner. Thus an observed or raced local deviation is not overwritten by assuming
an old read is still authoritative.

The other owners' persisted guards already protect the whole safe phase product.
The current step therefore needs communication only with its selected owner;
another owner can be unreachable while this step completes. The implementation
keeps the plan's fixed serial step order. If the selected owner itself is
unreachable, the job stays at that step rather than skipping ahead to another
owner. Full placement collects remain before phase admission and at each phase
endpoint. A guard-respecting external change at another owner may be discovered
only when that owner is next selected or at the boundary. Until then, local
steps can proceed safely within the held product; detection of every unrelated
change before every installation is not the execution contract.

If the next planned target is already present, the executor records
`already-target`. That may follow a committed installation whose response was
lost, or an external writer making the same transition. It increments
`reconciled_steps`, not `acknowledged_installs`. The latter counts successfully
acknowledged installations that the job durably recorded. Neither counter alone
is a claim about every physical write by all actors; retained RPC events and
owner generations provide that separate evidence.

## Observing a common target configuration

A sequential read of several owners is not a snapshot. For example, a collector
could read owner 0 at `A`, then external updates could change the actual vector
from `(A,B')` to `(A',B')` and then `(A',B)`, after which the collector reads owner
1 at `B`. The assembled `(A,B)` never existed. A retained RPC-interleaving control
reproduces this false-completion result in an intermediate single-collect
implementation and checks its rejection after the following correction.

Completion uses two full collects of authoritative owner profiles. Every owner's
generation and support must be identical in both collects. Because generations
increase on every changed installation and never wrap, each owner was unchanged
between its first and second read. Those intervals share the interval between
the end of the first collect and the beginning of the second. The agreed vector
therefore existed jointly during that common interval. Comparing generations
also detects an external change away from and back to the same support.

The returned `target_observation` retains both profile maps. A mismatch returns
`pending` with `target-snapshot-changed`; a stable non-target vector returns
`deviation`. No completion is reported from a torn vector, and repeated churn
does not produce a completion guarantee. The same double collect is used before
final retirement and when reporting completion after it.

## Safety and recovery argument

During the first acquisition, no configuration change is executed by the job
until its guard is committed. During later acquisition, the previous complete
guard remains in force. The next origin commits only after all owners have
persisted their local guard. The job records that new authority before retiring
any part of the old one. Partial retirement therefore leaves every owner under
the new safe guard, sometimes with the stricter old/new intersection as well.

Before every directed installation, the current origin still has its committed
certificate. Its private identity is not concurrently retired by another actor.
Each owner checks its local active guards at the same serialization point as the
conditional installation. Consequently every configuration update executed by
the job remains inside a safe phase product. This argument also allows other
guard-respecting updates for configuration safety; completion, the chosen path
and its optimal cost additionally require the planner's no-interference premise.

The order is durable across each relevant cut: before recording a new phase,
after recording it, during old release, after a local installation but before
recording the step, and after final release but before recording completion.
On recovery, the phase-specific admission identity and recorded phase roles make
the next action idempotent. Closed floors still reject delayed old prepares.
No atomic transaction across the job, origin and owner databases is assumed.

Completion is conditional on a valid finite plan, sufficient sequence and
generation headroom, eventual communication and healthy storage, and no
interfering configuration updates that make the fixed path inapplicable.
Partitions may leave the job pending while its guards continue to protect the
configuration. The final target is an observed completion condition, not a
promise that unrelated future updates will preserve that configuration forever.

## API

From `artifact/`, after producing a goal plan:

```python
from pathlib import Path
from src.rollout import RolloutCoordinator

job = RolloutCoordinator(network, Path("rollout.sqlite"),
                         manifest="declared-upgrade", plan=plan)
result = await job.run()       # complete, pending, or deviation
job.disconnect()

# After the old process has stopped, no in-memory phase or certificate is needed.
job = RolloutCoordinator(network, Path("rollout.sqlite"))
result = await job.run()
job.disconnect()
```

`advance()` performs one phase action and returns `progress` when another action
is possible. `run()` repeats those actions until completion or a known pending
or deviation condition. The optional synchronous `observer` receives detached
event dictionaries for instrumentation; it is not part of the authority path.
The network's lifetime remains the caller's responsibility.

## Executed fault controls

`tests/rollout_recovery.py` covers canonical conditional-write inputs, stale
profiles, plan corruption, four-phase origin reuse, zero-phase goals, lost
acquisition/retirement/installation messages, an external write between the read
and conditional installation, source deviation, already-target accounting,
foreign authority, actual SQLite transaction abort, postcommit job uncertainty,
durable role corruption and delayed old prepares.
The target controls additionally cover a torn multi-owner collect and an ABA
update whose final support is unchanged but whose generation has advanced.

Three local-progress controls distinguish step execution from phase boundaries.
A TCP proxy cuts the coordinator's route to an owner while the owner's original
server remains alive and answers a separate inspection probe. When that owner
is unrelated to the current step, the selected-owner installations proceed and
the phase endpoint waits. Cutting the selected owner's route leaves that step
pending without skipping to a later owner. A separate external write to an
unselected owner remains safe under its guard and is reported as a deviation
at the phase boundary. These controls retain the observed RPCs and the guarded
owner state; a partition does not imply eventual rollout completion.

Six real coordinator SIGKILL cuts keep the owner processes alive. In each case,
one owner is then separately SIGKILLed and reopened before the coordinator is
recreated solely from its job database. The cuts cover first admission, an
installed-but-unrecorded step, next admission before/after its job record, old
retirement and final retirement. SQLite snapshots before and after recovery and
the distinct coordinator/owner kill counts are retained. These are independent
processes on one host; they do not model physical power failure or WAN timing.

`tests/rollout_locality_study.py` executes both the retained global-preread
runtime and the current runtime against the same previously recorded goal.
For three owners, three phases and six installations, the retained traces show
48 read RPCs before the change and 36 after it. Both executions send nine
prepares, nine closes and six conditional installations. In the paired TCP
partition control, the old runtime completes zero local steps while the
unrelated owner is unreachable; the revised runtime completes its two local
steps and then waits at the phase boundary. Both finish after the route heals.
The exact runtime bytes, input plan and request/reply traces are retained in
`results/goal-recovery/locality-comparison/`.

For a nonempty, fault-free execution with `N` owners, `P` phases and `W`
installations, the lifecycle performs `W` local reads plus `N * (2P + 4)`
boundary reads: one full collect before each acquisition, one at each phase
endpoint, and two double collects around final retirement. The previous
per-step full collect used `N * (W + 2P + 4)` reads. These formulas describe
logical read requests in this implementation; retries and repeated completion
checks add requests. Fewer phase admissions and fewer reads are distinct
counts, and neither alone is a measured latency improvement.

Run both Python modes with new output directories:

```sh
python -B -m tests.rollout_recovery --out /tmp/rollout-recovery-normal
python -O -B -m tests.rollout_recovery --out /tmp/rollout-recovery-optimized
python -B -m tests.rollout_locality_study --out /tmp/rollout-locality-comparison
```
