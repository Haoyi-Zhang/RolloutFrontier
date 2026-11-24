# Policy boundaries and coordinated phase handoff

The crossed policy domain and the directed handoff below have separate
observations and denominators. The design and transcribed policy facts are in
[POLICY-BOUNDARY-DESIGN.md](../../docs/POLICY-BOUNDARY-DESIGN.md) and
[kubernetes-policy-boundaries.json](../../data/kubernetes-policy-boundaries.json).
The [role-slice cohort](../kubernetes-skew/README.md) checks its own registered
36-vector domain.

## Numerical-policy boundaries

The two server catalogs contain minors 35, 36 and 37; the kubelet catalog
contains minors 33 through 37. The seven-alternative positive encoding checks
all **45 version vectors**, including server pairs two minors apart and
clients four minors behind. **23 vectors are compatible**. Synthesis completes
under its default bounds for all 23 compatible seeds, with **44
frontier members** and no refusal or literal-oracle mismatch.

Removing one arithmetic constraint at a time exposes an independent witness:

| Rule omitted | Witness `(server0,server1,client)` | Newly admitted incompatible vectors |
| --- | --- | ---: |
| Server gap at most one | `(35,37,35)` | 4 |
| Client not newer than either server | `(36,36,37)` | 9 |
| Client at most three minors behind | `(37,37,33)` | 3 |

Each witness satisfies the two remaining constraints. Its adjacent compatible
vector is retained as a positive boundary. Marginal-only admission allows
22 incompatible vectors in the same domain. These rule-deletion calculations
test which constraints the domain exercises; they do not modify production
protocol code.

Three actual loopback TCP/SQLite lifecycles offer **36 proposals**, including
the three independently invalid boundary probes. Each invalid probe is blocked.
Every event agrees with literal guard replay; every resulting vector satisfies
all numerical rules. Owner/origin reopen, continued use, retirement and delayed
prepare checks pass. The **12 final boundary databases** are retained and read
independently by the saved-data checker.

## Goal-directed handoff

The separate upgrade path is
`(36,36,36) -> (37,36,36) -> (37,37,36) -> (37,37,37)`.
No current-preserving static safe product can admit all three target steps:
admitting the initial server versions and the final client version would also
admit the invalid vector `(36,36,37)`. Direct product enumeration finds a maximum
of **two of three target steps**. The maximum-mass first phase executes those
two server updates and blocks the client update.

At `(37,37,36)`, the batch selector sees only the remaining client target. The
selected second guard forecasts one installation, while maximum mass forecasts
zero. Origin 1 acquires the second guard under the same manifest predicate and
identifier while origin 0 still owns the first guard. A repeated client proposal
is blocked by the old hold `0:1`. After origin 0 retires, the proposal installs
and all **three target steps** are complete. Reopening owner 1 and both origins
keeps the old token unauthorized and the new token authorized. Final retirement
and a delayed old prepare preserve closure.

The two origins are distinct identities; this is a coordinated phase handoff,
not concurrent failover or automatic replanning during a partition. Target
completion is separate from installation count: the experiment issues **five
installation requests**, with three installations and two blocks, to complete
three unique target steps. Its **15 database images** cover both guards held,
the old phase retired, and both phases closed. These counts are separate from
the 45-vector domain and 36 boundary proposals above.

## Retained evidence and validation

- `results.json`: all version rows, complete plans, rule-deletion controls,
  boundary events, handoff events, certificates, logical RPC traces and snapshot
  inventories.
- `registration.json`, `execution.json`, `source-preimage/`: the fixed design,
  environment, the declared source identities and exact source bytes. Bytes were
  checked before and after execution.
- `databases/`: twelve boundary databases and fifteen handoff databases. The
  checker opens their actual rows read-only and derives expected state from the
  recorded input sequence and numerical policy.
- `check-normal.json`, `check-optimized.json`: identical passing saved-data
  checks in ordinary Python and with `-O`.
- `check-corruptions.json`: all six falsification controls rejected, including
  a rehashed database with a lowered closed floor and another with the old
  overlap guard removed. The reported states were changed alongside the database
  in those controls, so snapshot equality alone would not detect them.
- `stdout.log`, `stderr.log`: the execution output; no timing inference is made
  from this correctness study.

Recheck the retained cohort from `artifact/`:

```sh
python -B -m tests.check_policy_boundaries
python -O -B -m tests.check_policy_boundaries
python -B -m tests.check_policy_boundaries --corruption-controls
```

For a new execution, use a fresh output path and the full commands in the design
document. Only the three explicit synthesis resource limits are recorded as
refusals; logical or schema failures fail the run.

The official source supplies numerical constraints, not measured incident
frequency. These programs execute declared support through the prototype; they
do not run Kubernetes binaries, perform node draining, or certify all cluster
upgrade requirements. The crossed domain overlaps part of the kubelet role
slice and is reported as a separate cohort.
