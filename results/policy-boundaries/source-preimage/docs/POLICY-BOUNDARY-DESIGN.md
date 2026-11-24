# Kubernetes policy boundary study

## Question and fixed scope

This follow-up checks whether the declared-policy bridge distinguishes each of
three coupled constraints: the one-minor HA API-server gap, a kubelet newer than
a contacted server, and a kubelet more than three minors behind a contacted
server. The earlier two-server-version slice remains unchanged. Its catalog
does not cross the HA gap or the three-minor boundary.

The source is the official Kubernetes version-skew policy, checked on
18 November 2026, under **kube-apiserver** and **kubelet**:
https://kubernetes.io/releases/version-skew-policy/ . The fixture transcribes
numerical policy facts. It does not describe observed incidents or execute
Kubernetes binaries. All client versions in this study exceed 1.25, so the
three-minor rule applies throughout the selected domain.

A feasibility pilot established that the seven-alternative encoding completes
under the existing default bounds. The final study keeps every vector and every
compatible seed below, including any refusal. The driver records this design,
fixture, checker and executed source hashes before execution, retains their
exact bytes, and checks unchanged hashes afterward.

## Domain and independent constraints

Each of two API servers may have minor version 35, 36 or 37. The kubelet may
have minor version 33, 34, 35, 36 or 37. All 45 version vectors are examined.
For server minors `a,b` and client minor `c`, the arithmetic reference checks:

1. `abs(a-b) <= 1`;
2. `c <= min(a,b)`;
3. `max(a,b) - c <= 3`.

For the positive encoding, each server declares the client versions it supports
and membership in the windows `[35,36]` and `[36,37]`. A branch requires both
servers to name the same window and support the branch's client version.
There are seven branches: one for client 33 in the first window, two each for
clients 34 and 35, and one each for clients 36 and 37 in the second window.
Thus the HA rule is a checked relationship rather than a property that holds
for every server pair in the catalog. Server libraries contain at most the
seven branch requirements and three supplied profiles, fitting the ten-item
default bound. The study does not raise any synthesis bound.

For every compatible seed, direct subset enumeration finds all anchored safe
version products and their nondominated frontier. The synthesized frontier,
its selected mass and each positive guard are checked. Completion and refusal
counts use all compatible seeds as the denominator.
Only the explicit local-library, search-state and frontier-result resource
limits count as refusals; malformed input and logical mismatches fail the run.

## Rule-deletion controls

The arithmetic reference is evaluated after removing each rule in turn. All
newly admitted incompatible vectors are retained. These are domain controls,
not modified production implementations. Each rule has an explicitly registered
witness that violates only that rule:

| Removed rule | Incompatible witness | Adjacent compatible vector |
| --- | --- | --- |
| HA gap | `(35,37,35)` | `(36,37,35)` |
| Client not newer | `(36,36,37)` | `(36,36,36)` |
| Client at most three minors older | `(37,37,33)` | `(37,37,34)` |

The full encoding must reject every witness and accept its adjacent compatible
vector. The positive boundary is respectively a one-minor server gap, equal
client/server minors, and a three-minor client lag. Local version marginals are
also computed from compatible vectors; their Cartesian product supplies a
separate check of the correlation discarded by marginal-only admission.

## Actual guarded boundary transitions

One owned loopback TCP/SQLite lifecycle starts at each registered compatible
vector. It acquires the maximum-mass guard selected for that seed, first proposes
the corresponding incompatible witness at its single changed owner, then offers
every catalog version once at each owner. The initial incompatible proposal must
be blocked. Every later outcome is compared to a separate literal guard replay
and every resulting version vector is checked arithmetically.

There are 12 proposals per lifecycle: one negative boundary proposal plus
three versions at each API server and five client versions. Three lifecycles
therefore offer 36 proposals if all their synthesis calls complete. Each run
reopens owner 1 and the origin, checks continued authorization, retires its
admission and rejects a delayed prepare. Final owner and origin SQLite files
and logical RPC traces are retained. A separate data-only checker reads the
actual database rows and reconstructs the event counts. No timing comparison
or production deployment claim is made.

## Goal-directed phase handoff

A separate case distinguishes completed upgrade targets from installation count.
It starts at `(36,36,36)` and offers server 0, server 1 and the kubelet an upgrade
to minor 37, in that order. The target is `(37,37,37)`. A current-preserving safe
static product cannot admit client 37 while also admitting both initial server
versions: it would contain the invalid vector `(36,36,37)`. Direct product
enumeration therefore checks a maximum of two installed target steps under a
single static product. The maximum-mass first phase executes the same path and
must finish at `(37,37,36)`.

At that state, the optional batch selector receives only the remaining client
upgrade, using the same manifest predicate and catalog. Two distinct existing
origin identities implement the handoff: origin 0 owns the first phase and
origin 1 acquires the selected second-phase guard under the same manifest
identifier. This uses the existing multiple-origin interface; it is not
same-identity failover. While both guards are held, client 37 must still be
blocked by the old guard. After origin 0 retires, repeating that target proposal
must install and reach the target. Owner 1 and both origin objects then reopen;
the old token remains unauthorized, the new token remains authorized, final
retirement releases the new guards, and a delayed old prepare remains closed.

This handoff requires communication and admission coordination. No whole-rollout
completion guarantee under a partition is inferred from independent execution
within each static phase. The three target steps are the goal denominator.
The five actual installation requests include the first blocked target, an
additional both-guards probe, and the successful retry. Their outcomes and
the three completed targets are reported separately from the 45-vector domain
and 36 boundary proposals above.

Five owner/origin SQLite files are snapshotted with SQLite's backup interface
at each of three quiescent checkpoints: both phases held, old phase retired,
and both phases closed. These 15 handoff images are separate from the 12 final
boundary images. The data-only checker reconstructs all holds, floors,
generations, origin attempts and target states at those checkpoints.

## Reproduction

From `artifact/`, after the implementation sources are fixed:

```sh
python -B -m tests.kubernetes_policy_boundaries --out /tmp/policy-boundaries-new
python -B -m tests.check_policy_boundaries --directory /tmp/policy-boundaries-new
python -B -m tests.check_policy_boundaries --directory /tmp/policy-boundaries-new --corruption-controls
```

The output path must be new and outside the artifact. Existing evidence is not
replaced. The checker imports neither the experiment driver nor production
modules; it validates the declared domain, positive encoding, literal frontiers,
rule-deletion controls, installed/blocked/no-op transitions and stored states.
Six corruption controls change a policy cell, delete a frontier member, falsify
a boundary event, lower a stored closed floor, misstate the handoff overlap, and
delete the old live guard from an overlap database. Database controls update
both the checksum and reported state. Each modified copy must be rejected.
