# Availability frontiers: model, arguments, and finite exactness

These arguments concern a finite abstract API-contract model. They are not a proof
that real APIs satisfy their declarations, a mechanization, or a new general theory
of coordination avoidance. Predicate reservation, warranties, and local treaties
already establish the broader local-to-global preservation pattern. The contribution
here is narrower: characterize every independently enforceable positive product in a
bounded rollout domain, choose an exact finite availability optimum, and connect that
choice to durable acquisition and retirement.

## 1. State and trust boundary

There are at most six endpoint owners and six origins. Each identity has one writer;
there is no concurrent failover for the same origin. Endpoint `i` has authoritative
installed support `S_i`, a finite set of positive contract atoms. Only the serialized
installation operation changes `S_i`. An atom denotes a declared behavioral
obligation, not merely a method spelling. The prototype trusts these declarations and
does not infer semantic equivalence.

A workload manifest has `1..8` complete alternatives. Alternative `j` maps every
selected endpoint `i` in a common nonempty placement `P` to a closed conjunction
`R_ji`. Its compatibility predicate is

    F(S) = OR_j AND_(i in P) [R_ji subseteq S_i].

The disjunction is outside the endpoint conjunction: one alternative must explain
the whole placement. Positive dependency closure is the least fixed point reached by
repeatedly adding declared dependencies; cycles are harmless because each distinct
atom is inserted once. Inputs that exceed the explicit encoding bounds fail closed.

Messages may be delayed, duplicated, lost, or reordered, and partitions may be
permanent. Stable SQLite storage and single-writer identities are premises. Disk
loss, Byzantine messages, external unguarded platform mutation, application-state
migration, and actual Android execution are outside the model.

## 2. Positive local guards and accepted candidate profiles

A local guard `G_i={g_i1,...,g_ik}` is a nonempty antichain of positive conjunctions.
It accepts support profile `s_i` when some `g` in `G_i` is a subset of `s_i`. Let

    A_i(G_i) = { d in D_i : exists g in G_i, g subseteq d },

where `D_i` is the supplied finite candidate-profile domain for endpoint `i`. Every
admissible guard must accept the current projected support. A guard family
`G=(G_i)` therefore admits the Cartesian product `x_i A_i(G_i)` if owners make
future choices independently.

The finite objective is deliberately combinatorial. Each candidate profile can have
a bounded nonnegative integer weight `w_i(d)`; define local mass

    m_i(G_i) = sum_{d in A_i(G_i)} w_i(d)

and product mass `M(G)=product_i m_i(G_i)`. Uniform weights count accepted profile
combinations. These weights are not probabilities, observed frequencies, or a fleet
model.

## 3. Product safety and the availability frontier

**Theorem 1 (independent-choice product).** After the guards are acquired, if each
owner independently chooses any profile accepted by its local guard, the set of
possible joint profiles is exactly `x_i A_i(G_i)`.

*Argument.* Every execution chooses one accepted local profile at each owner, hence
lies in the product. Conversely, independence places no cross-owner restriction on
combining accepted choices, so every product member is possible in the abstract
model.

**Theorem 2 (product criterion).** A guard family preserves workload compatibility
against all independently permitted choices if and only if

    x_i A_i(G_i) subseteq F.

*Argument.* Sufficiency follows by Theorem 1: every possible joint profile belongs to
`F`. For necessity, a product member outside `F` is itself an independently permitted
joint choice and is a concrete incompatible corner. This finite-domain statement alone does not establish safety on supports outside
`D_i`. The production checker therefore uses the stronger powerset corner criterion:
every combination of minimal guard terms must satisfy one common whole alternative.
If all such corners are safe, every larger support satisfying the guards is safe
by positive monotonicity. Conversely, in the unrestricted powerset domain a minimal
corner is itself an admissible support vector. Thus the corner criterion is
necessary and sufficient there; on a physically restricted domain it remains
sufficient but need not be necessary.

For two endpoints with singleton profile names, the criterion is exactly the
all-edges condition for a complete bipartite subgraph containing the current edge.
For more endpoints it is the corresponding complete multipartite subrelation problem.
These are classical maximal-product objects: maximal bicliques in the binary case,
formal concepts under a closure view, and closed n-sets for higher arity. The term
"availability frontier" names their rollout interpretation, not a new combinatorial
object. Maximum edge biclique is NP-complete (Peeters, 2003), so the weighted seeded
special case already excludes a general polynomial exact algorithm unless P=NP.

A safe accepted-set vector `A=(A_i)` dominates another vector `B` when every `A_i`
contains `B_i` and at least one containment is strict. The **availability frontier**
is the set of safe vectors not dominated by another safe vector. It preserves
tradeoffs that a single scalar objective would hide.

## 4. Bounded exact synthesis

The implemented exact language draws each local guard term from the projected
current profile, supplied candidate profiles, or branch-local requirements. It
canonicalizes terms to an antichain, requires the current profile to be accepted,
and enforces the public limits: at most ten library terms per endpoint, eight guard
terms, 4,096 checked corners, 250,000 joint search states, and 4,096 returned frontier
plans. The routine raises on exhaustion; it never labels a truncated search exact.
The 96-atom bound applies to a branch-local requirement, not to a profile-derived
guard term. Profiles and guard terms use the 12,000-atom support encoding bound;
projection onto eight branch-local requirements retains at most 768 relevant atoms.
The producer, independent checker, and durable hold/certificate encodings use this
same distinction.

**Theorem 3 (finite exactness).** If the bounded enumeration terminates, it returns
all nondominated accepted-profile vectors expressible in the declared positive guard
language and selects, **from that frontier**, the score-optimal guard under the ordered
objective

1. maximize weighted product mass;
2. maximize the sum of local masses;
3. minimize the total number of guard terms; and
4. choose the lexicographically first canonical box.

*Argument.* For each endpoint, subset enumeration covers every nonempty subset of
the finite term library. Antichain canonicalization preserves its accepted supports,
so deduplication removes representations, not behaviors. A depth-first traversal
therefore reaches every expressible guard family unless a declared bound excludes it.
It may prune an unsafe prefix: such a prefix already contains a product corner outside
`F`, and extending the prefix only adds coordinates, so no extension can become safe.
It may also prune a prefix whose guard-corner product exceeds 4,096, which is outside
the declared exact language. The 250,000 limit counts visited prefix states, not the
raw product of local-choice counts. At every complete retained family, Theorem 2 is
checked. Pairwise accepted-set dominance removes exactly the dominated vectors. The
objective is then evaluated only over the surviving frontier, and the total score
order selects one deterministic optimum. Bounds are checked before a result is
returned.

The exact checker in `src/checker.py` imports no planner routine. It independently
reconstructs libraries, guards, candidate masks, bounded prefix search, safe complete
combinations, the nondominated frontier, every reported metadata field, and the full
tie-break order. A retained high-pruning case has 260,876 raw local combinations but
only 37 visited prefix states; producer and checker agree under the same state-bound
semantics. Eight mutations of the selected plan, frontier, counters, certificate, or
objective are rejected. The direct relation oracle represents each singleton-profile
relation as allowed tuples and enumerates all seed-containing coordinate subsets. It
exhausts the declared edge-encoded 3×3 domain, checks 480 deterministic sparse 4×4/5×5 instances,
and separately checks 192 seeded 3×3×3 instances. The larger and ternary instances
are samples, not an exhaustive higher-dimensional proof.

The worst-case search is exponential. Exactness is therefore a bounded-domain
property, not a polynomial-time claim. The greedy planner remains useful as a cheap
baseline but is not an approximation algorithm with a stated ratio. A retained
relation has one row connected to seven columns and a second row connected only to
the first column. Starting at their shared cell, the greedy order expands the second
row and accepts product mass 2; the exact frontier keeps one row and seven columns,
accepting 7. In a weighted three-edge relation, uniform mass is 2 while supplied
weights select a different frontier member with product mass 80.

A separate zero-weight regression is logically necessary. With one endpoint,
profiles `a` and `b`, current profile `a`, and weights `[1,0]`, accepting only `a`
and accepting both profiles have the same weighted mass and local mass. The former
is dominated by the latter. An objective evaluated over all safe plans could
therefore choose the dominated singleton by its later tie rules. The repaired
implementation and independent checker first compute the complete frontier and then
select only among frontier members; both return `{a,b}`. This regression is retained
in `results/frontier.json` and documented in `REPAIRS.md`.

## 5. Durable acquisition and the lifetime invariant

An advertisement is a planning hint, not authority. For origin `o` and sequence `q`,
each selected owner durably records one hold for a specific manifest and local guard.
The origin may commit admission only after it has durable receipts from every owner.
Installation is serialized with hold checking and may proceed only when the new
support satisfies every live local guard. Use is authorized only by a committed,
nonretired origin record whose endpoint holds still exist.

**Invariant 4 (live guards).** For every live hold at owner `i`, installed support
`S_i` satisfies that hold's local guard.

The invariant holds after acquisition because prepare checks current support before
persisting the hold. The only support-changing transition checks all holds before
installation. Replay and duplicate prepares do not weaken a stored hold, while close
removes obligations only after the origin has stopped authorizing use.

**Theorem 5 (admission lifetime safety).** Under the single-writer, durable-storage,
and guarded-installation premises, every use authorized by a committed, nonretired
admission satisfies one complete workload alternative.

*Argument.* Invariant 4 places each selected endpoint in the accepted set of its
acquired guard. Theorem 2 makes the resulting product a subset of `F`. Crashes and
partitions can delay transitions but do not create a transition that bypasses the
owner's durable hold check.

This is exactly-once logical authorization neither for application effects nor for
physical platform writes. Application state transfer and routing handover are not
implemented.

## 6. Retirement, replay, and bounded metadata

Each origin has a fixed `K`-slot sequence window (`1..64`, normally 8) and a durable
closed floor at every owner. Floors and slot keys are indexed by origin, so closing
origin `o` cannot retire a live hold for origin `o'`. Reusing a live sequence with
different content is rejected. The origin marks the attempt nonauthorizing and persists retirement before sending
owner closes; recovery retries those closes. An owner rejects prepares at or below the
matching origin's closed floor, so a delayed prepare cannot resurrect a retired hold.
Duplicates are idempotent. A directed two-origin test retains both holds across an
owner reopen, loses one origin's close, then advances the two floors independently.

A permanent partition may leave a conservative hold indefinitely. Metadata remains
bounded because the origin admits at most `K` unresolved sequences and then applies
backpressure; boundedness is obtained by refusing new work, not by silently dropping
protection. After every retained event is delivered, deterministic merge keeps the
highest non-equivocating advertisement per owner and catalog replicas converge.
Catalog convergence does not assert that installed platforms become identical.

## 7. Rejection evidence

For a frozen observation vector, each complete alternative contributes the set of its
currently false atoms. If some alternative has no false atom, the workload is
compatible. Otherwise a rejection obstruction is a hitting set intersecting every
false-atom set. The implementation's mask dynamic program stores, for each reached
branch mask, the smallest chosen atom tuple and uses lexical order to break ties.
The implementation expands coverage masks in increasing integer order. Each
accepted transition adds a new bit, so all incoming states are finalized before
a mask is expanded. Its added atom cannot already belong to a tuple for the
source mask. Cardinality and sorted lexical order are preserved under adding
the same absent atom. Every minimum-cardinality cover has no redundant atom,
and therefore admits a path whose coverage strictly increases at each step.
Induction over masks establishes the best tuple at each state; the full mask
is therefore a minimum-cardinality obstruction. Deleting any returned atom
is independently checked to uncover at least one alternative.

This witness explains why the frozen vector fails. It is not proof that a delayed or
partitioned owner currently lacks an atom. A timeout means “not justified,” not
“incompatible.” A rejected exact frontier plan additionally carries an unsafe corner,
which is a direct product member outside `F`.

## 8. Finite protocol exploration

`tests/modelcheck.py` is a separate transition system, not a wrapper around the
controller. Its state contains one origin phase, two durable owner records, two
support bits, owner liveness, prepare/close acknowledgement masks, and the relevant
message possibilities. It exactly explores one attempt, two owners, one positive
atom, and one nonwrapping sequence under request/reply loss, replay, arbitrary
reordering, origin crash/recovery, owner crash/restart, support changes, commit,
retirement, and close.

For the guarded model, 296 states and 1,388 transitions are reachable. No committed
state violates compatibility, and no transition changes an owner's sequence from
closed back to held. Every committed or retiring state has some path to complete
cleanup. The last fact is existential reachability, not a fairness or eventual-
delivery theorem. Two negative controls keep the abstraction discriminating:
unguarded installation reaches 12 violating states, and unsafe timeout reclamation
reaches 32; each has a shortest five-step counterexample.

This model checker establishes exhaustive behavior only for that finite abstraction.
It does not cover multiple attempts, wrapping counters, arbitrary manifests, all
network payloads, or the full SQLite/TCP implementation.

## 9. Evidence boundary and falsifiers

The retained edge-encoded frontier evidence exhausts 510 nonempty 3×3 relations
with at most eight allowed cells and
2,295 seeded instances, independently enumerating 9,369 safe boxes and 3,222 frontier
members. The full nine-cell relation is nevertheless representable by one
empty-requirement alternative. `tests/positive_oracle.py` checks all nine current
cells of that encoding against direct support-vector enumeration. Projection
combines three candidate profiles into one weight-three profile per owner, giving
product mass nine and a single unrestricted guard product. Together these checks
cover all 511 nonempty 3×3 relations and 2,304 current cells, without relabeling the
retained edge-encoded counts. A post-development generated holdout adds 1,440 cases and 69,120 fixed
proposals from six relation generators and seed range 1000--1239. Exact frontiers
match direct subset enumeration in every holdout case; exact beats greedy on 206
proposal schedules, loses on 156, and ties on 1,078. A centralized same-order reference
installs more in 978 cases. The holdout tests sensitivity to relation shape without
turning generated evidence into an external-validity claim. Larger direct oracles check 480 deterministic 4×4/5×5 seeded instances
(1,426 safe boxes and 627 frontier members) and 192 deterministic 3×3×3 seeded
instances (398 safe boxes and 233 frontier members). Other finite evidence covers
65,536 four-atom obstruction inputs, 24,990 legacy relation/product instances, the
296-state protocol abstraction, and a 445-state endpoint graph.

Network experiments exercise five loopback listeners; a separate test runs five
independent owner processes with separate SQLite files and three SIGKILL events. A
structurally separate trace replayer reconstructs 40,992 request/reply exchanges.
These are bounded same-host tests, not a proof of all executions, a power-loss test,
or a multi-machine deployment.

The claims are falsified by any of the following within the premises: a live guarded
placement outside `F`; an accepted unsafe product corner; a returned frontier that
omits an expressible nondominated vector; a selected plan outside the frontier or
below the stated frontier objective; a retired sequence resurrected by replay; a
claimed-minimum obstruction with a smaller hitting set; or acknowledged state lost at
a tested process-recovery cut.

## Static-mass objective versus scheduled progress

Let the two-owner singleton relation be `{(0,0),(0,1),(0,2),(1,0)}`, with seed
`(0,0)` and unit weights. The two maximal products have masses three and two.
The mass-three product fixes owner zero at 0; the mass-two product fixes owner
one at 0 and permits owner zero to choose 0 or 1. Hold owner one at 0 and propose
1,0 at owner zero, repeated T times. The maximum-mass product installs zero
changes (blocked ones followed by no-ops); the alternate safe product installs
2T. For every integer T>=1 both products remain safe. Consequently no positive
worst-case ratio of scheduled successful installations follows from the frozen
maximum-mass objective. This is not a lower bound for all online strategies.
The executable T=100 case is retained in `results/journal-analysis.json`.

## Generalized complexity, not fixed-cap hardness

The unbounded two-coordinate weighted seeded problem contains maximum edge
biclique: add universal zero-weight seed vertices and give original vertices unit
weight. A seed-containing safe product has exactly the mass of the corresponding
original biclique. Singleton profile names and one alternative per allowed edge
express the construction when sizes are not capped. For an explicit binary relation,
a guessed pair of coordinate subsets can be checked in polynomial time. The
threshold problem is NP-complete in this generalized formulation. This is not
an NP-completeness claim for fixed constants such as eight branches or ten local
library terms. Language caps restrict the exact domain; computational caps cause
refusal and no truncated optimum.
