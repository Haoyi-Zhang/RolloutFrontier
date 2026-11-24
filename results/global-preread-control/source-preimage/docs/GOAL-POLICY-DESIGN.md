# Goal completion and minimum protected phases

Design identifier: `kubernetes-goal-phases-v1`. The domain, task-generation rule,
transition relation, comparators, bounds and original three execution cases
below were fixed in `data/goal-policy.json` before the first study run. A
subsequent review amendment extended execution to every already-fixed scaling
goal, as recorded below. No goal or favorable subset was selected after
observing planner outcomes.

## Question and real policy boundary

The study asks how many independently safe guard phases are needed to reach an
explicit version target. Installation count is retained as a secondary cost;
repeated rollback cannot increase target completion in this task. A phase may
contain several single-owner installations. Changing phases requires a durable
admission and handoff, so phase count measures coordination boundaries, not wall
time or message latency.

The official Kubernetes version-skew policy requires HA API servers to differ
by at most one minor version, and each kubelet to be no newer than any contacted
server and no more than three minors older in the selected version domain.
The policy also forbids skipping API-server minor versions. The kubeadm upgrade
workflow likewise disallows minor-version skipping and already upgrades control
planes before workers. We therefore permit only single-owner `v -> v+1` steps.
This is a declared numerical transition model; actual kubeadm execution has
additional requirements, including sequential control-plane work, draining,
available capacity and webhook compatibility.

Sources, both read at body depth on 18 November 2026:

- https://kubernetes.io/releases/version-skew-policy/
- https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/

## Registered domains and tasks

The primary domain has two API servers at minors 35, 36 or 37 and one kubelet at
minors 33 through 37. Every ordered pair of compatible placements is a task.
Equal pairs are zero-installation, zero-phase tasks. Direction-infeasible pairs
remain in the output and are classified separately from resource refusals.

Three additional domains have two servers and respectively two, three or four
kubelets, with minors 35 through 37 at every owner. The six task templates in
the fixture cover one- and two-minor targets, server-ahead targets, client catch
up and client-only work. These domains increase owners and active constraints;
they do not inflate payloads with irrelevant atoms. Task templates share a
policy structure and are not independent production samples.

Each version profile contains its exact role/version identity and positive
membership declarations for safe server windows and client intervals. The
manifest is the disjunction of maximal compatible interval products. All
versions retain distinct full profiles even when their manifest projections
coincide, so local `+1` transitions cannot be collapsed into version jumps.
The numeric oracle verifies the encoding on every catalog placement. The
encoding and all profiles are retained with each domain.

## Comparators and independent optimum

1. **One static product.** A target is reachable with one safe product precisely
   when the local paths from start to target fit in a safe product. It performs
   no phase handoffs. Equal placements require no admission.
2. **Automatic phase planner.** The delivered planner minimizes the pair
   `(number of phases, number of installations)` lexicographically. It can reuse
   complete frontiers and phase edges across queries in the same domain. Cache
   use, newly expanded work and cumulative work are recorded separately.
3. **Coordinate every proposal.** A shortest path in the graph of globally
   compatible placements uses one globally checked step per installation. It
   is a coordination-count reference, not a timing or complete-system baseline.
   Each task retains this reference route and its number of global checks, as
   well as the static-product outcome, separately from the automatic plan.

The independent oracle uses integer versions only. A one-phase move from `s`
to `t` requires nondecreasing coordinates and all points in the interval hull
`product([s_i, t_i])` to satisfy the policy. The hull includes every intermediate
version because local transitions advance by one minor. Enumerating these edges
over compatible placements and searching the resulting graph gives the minimum
phase count without importing the planner, guard synthesizer or controller.
The one-step global graph independently gives reachability and installation
cost. Returned guards are checked literally on all positive corners and every
declared local path. Matching the numeric lower bound with a valid returned
guard plan establishes the attainable optimum for these instances.

## Refusals, evidence and execution

The configured placement, phase-edge and synthesis bounds are recorded in the
fixture. A budget exception is retained as a refusal, never classified as an
unreachable target or silently omitted. Deliberately insufficient placement
and phase-edge bounds are separate negative controls. Default-bound refusal
remains an experimental outcome even if a larger bound later solves the task.

All task inputs, plans, status and counts are retained in deterministic JSONL
records. A study-level manifest binds those records, the frozen design, data and
tested source. The data checker reconstructs the complete registered task set,
integer policy, legal transition paths, optimum and guard semantics. It also
checks selected durable executions from their event records and SQLite states,
including support versions, live guards and origin authorization.

The three registered execution cases cover a two-minor normal run, an unavailable
next-phase acquisition and loss of an old-phase close reply followed by reopen.
On 19 November 2026, after the initial three-case cohort had completed, review
identified that the 4-, 5- and 6-owner planning extension lacked runtime evidence.
The execution amendment therefore adds normal execution of all six existing
goal templates in every scaling domain: eighteen additional cases, with no new
planning tasks or changed targets. The final cohort executes all twenty-one
cases and preserves this amendment history rather than describing the added
runtime coverage as registered before the initial run.
Deep process-cut coverage belongs to the separate protocol suite. Snapshots are
taken at explicit boundaries; installation requests, completed distinct target
coordinates, phase admissions and handoffs have separate counters. Every case
is driven from an automatically generated plan rather than a hand-written phase
sequence. No timing comparison is inferred from these semantic executions.

Saved-data corruption controls remove a task, alter an optimum, insert a skipped
minor transition, alter full-profile identity, weaken a guard and modify a
durable state while recomputing its byte hash. Each must be rejected for the
affected semantic reason. No data checker imports planner or runtime code.

## Claim limits

These finite workloads measure target reachability and exact coordination-phase
cost under a public numerical policy. They do not establish incident frequency,
deployed cluster performance or a better real kubeadm upgrade sequence. A safe
Cartesian phase describes permitted support changes; it does not model the
temporary unavailability of an endpoint while installing a binary. The new
question is the minimum protected-phase decomposition and its durable execution,
not the already-established idea of renegotiating local treaties. Finite-graph
shortest-path search is an existing tool: the relevant result is preservation of
directed phase reachability and cost by the complete bounded frontier. In these
monotone `+1` policy tasks, every successful route has the same installation
count. General tests with alternative directed routes, rather than this policy
cohort, must establish the secondary installation objective.
