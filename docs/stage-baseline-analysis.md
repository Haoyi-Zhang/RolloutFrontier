# Stage-aware paths and exact phase planning

A fixed owner-priority path repeatedly takes the first enabled installation in
a fixed owner order. A stage-priority path instead selects an enabled,
unfinished owner with the smallest current physical rank, breaking ties by
that same order. Both remain within the source-to-target rank box. Each full
path is partitioned by the same exact dynamic program: an interval is one
phase exactly when its Cartesian rectangle is compatible. A portfolio takes
the minimum partition cost across the specified paths.

These comparisons separate path choice from phase partitioning. They also
represent a practical alternative for the measured schema migrations: prepare
readers before enabling producers, then remove old parsing support when a
rename requires that final stage.

## Full homogeneous migrations

Let every owner run the same family's physical chain and migrate from its
legacy rank to its final rank. At least one dependency must join two distinct
owners. Isolated owners may also occur.

For enum and field-key renaming, the synchronized rectangles `[0,1]^n`,
`[1,2]^n` and `[2,3]^n` are compatible. At each stage every remaining owner can
advance, so minimum current rank visits all owners in that stage before moving
to the next. Its path therefore admits a three-phase partition.

Three phases are also necessary. On any dependency edge, a first rectangle
starting at `(0,0)` cannot advance the sender past rank 1: the receiver might
still use the legacy parser. A final rectangle ending at `(3,3)` must begin
with its sender at rank 2 or later: the receiver might already have removed
the old parser. A two-phase plan would require its shared sender rank to be
both at most 1 and at least 2.

For field addition and integer widening, the rectangles `[0,1]^n` and
`[1,2]^n` are compatible. The missing corner `(2,0)` on any edge rules out
one phase. Thus a stage-priority path is phase optimal with two phases. An
edgeless deployment instead needs one phase; it is outside the nonempty-graph
inventory in the schema census.

These are model-level proofs for arbitrary graph size, not frequency estimates
for deployed topologies. They show why a complete legacy-to-final migration
cannot establish an advantage over informed staging in these two matrices.
The complete corpus comparison should retain the stage-aware ties alongside
the fixed-owner-priority gaps.

## Why cyclic fixed priorities can add a phase

In a directed rename cycle, every owner is both sender and receiver. A
three-phase complete migration must pass through `1^n` and then `2^n`.
The first endpoint is at most `1^n`. Reaching every producer's rank 2 during
the next phase requires each receiver already to have left rank 0, forcing
the first endpoint to equal `1^n`. The final phase requires every sender to
be at least rank 2, while a rectangle from `1^n` cannot yet include rank 3;
the second endpoint is therefore `2^n`.

A serial path that misses either vector cannot have a three-phase partition.
For the three-owner cycle, fixed priorities advance an enabled service beyond
one of these handoffs before the other services have reached it. Stage-aware
paths preserve these handoffs. This explains the observed gap without treating
the six fixed priorities as an exhaustive set of informed planning methods.

## Reachability and phase optimality are separate

On a max-closed chain instance, suppose target `h` is reachable from source
`s`. Every compatible intermediate `z` with `s ≤ z ≤ h` can still reach `h`.
The greatest-endpoint operator is monotone, so its iterates from `z` dominate
the corresponding iterates from `s`. A target-bounded rule that keeps taking
enabled forward steps therefore reaches `h`; ranks increase and there are
only finitely many steps. The rule need not preserve an optimal phase handoff.

The retained ternary relation `a ≤ b` illustrates the distinction. From
`(0,0)` to `(2,2)`, either stage-priority tie order follows
`00 → 01 → 11 → 12 → 22`. A two-phase handoff would have to be `(0,2)`,
which the path misses. Its best partition is `00 → 01 → 12 → 22`, with
three phases. An exact plan uses `00 → 02 → 22`, with two phases and the
same four installations.
The literal phase checker determines the path partition; this example is a
finite logical control, not an application measurement.

## A combined-portfolio counterexample

Take `a ∈ {0,…,4}`, `b ∈ {0,…,6}`, and require all four implications:

| Trigger | Required companion rank |
| --- | --- |
| `a ≥ 3` | `b ≥ 1` |
| `a ≥ 4` | `b ≥ 4` |
| `b ≥ 5` | `a ≥ 1` |
| `b ≥ 6` | `a ≥ 2` |

Each implication preserves componentwise maximum, so their conjunction is
max-closed. The relation has 27 compatible cells out of 35. It can be encoded
with five positive alternatives and five and seven physical profiles, within
the unchanged factor planner's existing input bounds.

From `(0,0)` to `(4,6)`, any first-phase endpoint is at most `(2,4)`.
Any final-phase source is at least `(2,4)`, because the target includes `a=4`
and `b=6`. Hence `(2,4)` is the unique handoff for a two-phase plan. Both
rectangles around it are safe, giving the exact cost of two phases and ten
installations.

All fixed-owner and stage-priority tie orders miss that handoff:

| Path rule | Transition that prevents visiting `(2,4)` | A valid three-phase partition |
| --- | --- | --- |
| Fixed priority `a,b` | `(2,1) → (3,1)` | `00 → 21 → 34 → 46` |
| Fixed priority `b,a` | `(1,4) → (1,5)` | `00 → 14 → 25 → 46` |
| Stage priority `a,b` | `(2,2) → (3,2)` | `00 → 11 → 34 → 46` |
| Stage priority `b,a` | `(2,2) → (2,3) → (3,3)` | `00 → 01 → 34 → 46` |

Forward installation chains prevent any return to the missing handoff. Every
listed partition is compatible, while two phases are impossible for these
paths. The best combined portfolio therefore needs three phases. The exact
planner constructs `00 → 24 → 46` in two phases.

The example establishes that these elementary path portfolios do not replace
the greatest-endpoint result. Its purpose is a mathematical separation; it
does not estimate the occurrence or cost of such thresholds in production.
